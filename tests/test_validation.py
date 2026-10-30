# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Scientific input and old-result validation, independent of building fixtures."""

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace as NS

import pytest
from epsm_data import EnvironmentalFactor as F

from epsm_lca import AnnualEnergy, AssessmentSettings, LCAResult, assess


@pytest.mark.parametrize(
    "flow", [{}, None, {"installed": []}, {"installed": None, "removed": []}]
)
def test_unknown_flows_are_not_empty_work(flow):
    with pytest.raises(ValueError, match="explicit"):
        assess((), (flow,), None, AssessmentSettings(30, include_energy=False))


@pytest.mark.parametrize("value", [True, "30", 0, -1, float("inf"), float("nan")])
def test_invalid_periods_fail_clearly(value):
    with pytest.raises(ValueError):
        AssessmentSettings(value)


@pytest.mark.parametrize("value", [True, -1, "100", float("nan"), float("inf")])
def test_invalid_annual_amounts_fail_clearly(value):
    with pytest.raises(ValueError):
        AnnualEnergy("state", {"electricity": value}, "Test")


def test_settings_freeze_input_factor_mappings_and_keep_replace_deepcopy():
    factors = {"wood": {"A1A3": F(2, "kg", "A1A3", "Test")}}
    settings = AssessmentSettings(30, material_factors=factors)
    factors["wood"].clear()
    assert settings.material_factors["wood"]["A1A3"].value == 2
    with pytest.raises(TypeError):
        settings.material_factors["wood"]["A1A3"] = F(3, "kg", "A1A3", "Test")
    assert deepcopy(settings) == settings
    assert replace(settings, period_years=60).period_years == 60


@pytest.mark.parametrize(
    "material,energy,total,requirements",
    [
        (None, None, None, ()),
        (1, 2, float("nan"), ()),
        (1, 2, 999, ()),
        (1, 2, 3, ("Missing",)),
    ],
)
def test_complete_saved_results_cannot_claim_invalid_totals(
    material, energy, total, requirements
):
    with pytest.raises(ValueError):
        LCAResult.from_dict(
            dict(
                status="complete",
                material_gwp_kgco2e=material,
                operational_gwp_kgco2e=energy,
                total_gwp_kgco2e=total,
                requirements=requirements,
            )
        )


def test_valid_older_results_remain_readable_without_invented_context():
    result = LCAResult.from_dict(
        dict(
            status="complete",
            material_gwp_kgco2e=1,
            operational_gwp_kgco2e=2,
            total_gwp_kgco2e=3,
        )
    )
    assert (
        result.complete
        and result.context_status == "unrecorded"
        and result.assessment is None
    )
    with pytest.raises(ValueError, match="Unsupported"):
        LCAResult.from_dict({**result.to_dict(), "format": "future"})


def test_format_one_settings_held_by_saved_buildings_still_load():
    saved = AssessmentSettings(30).to_dict()
    for name in (
        "reference_area_m2",
        "reference_area_basis",
        "include_replacements",
        "service_lives",
    ):
        del saved[name]
    old = {**saved, "format": "epsm-lca-settings/1"}
    assert AssessmentSettings.from_dict(old) == AssessmentSettings(30)
    unversioned = dict(
        period_years=30,
        energy_boundary="space_heating_and_fans",
        baseline="retained",
        material_modules=("A1A3",),
    )
    assert AssessmentSettings.from_dict(unversioned).include_energy is True
    with pytest.raises(ValueError, match="lack recorded"):
        AssessmentSettings.from_dict({"period_years": 30})
    with pytest.raises(ValueError, match="Unsupported"):
        AssessmentSettings.from_dict({**saved, "format": "epsm-lca-settings/9"})


def test_reference_area_requires_a_basis():
    with pytest.raises(ValueError, match="together"):
        AssessmentSettings(30, reference_area_m2=100.0)
    with pytest.raises(ValueError, match="positive"):
        AssessmentSettings(30, reference_area_m2=0.0, reference_area_basis="Atemp")
    settings = AssessmentSettings(
        30, reference_area_m2=100, reference_area_basis="Atemp"
    )
    assert AssessmentSettings.from_dict(settings.to_dict()) == settings


@pytest.mark.parametrize(
    "basis,amount,expected",
    [("kg", 10, 20), ("m2", 2, 4), ("m3", 0.02, 0.04), ("item", 3, 6)],
)
def test_all_quantity_units(basis, amount, expected):
    field = {"kg": "mass_kg", "m2": "area_m2", "m3": "volume_m3", "item": "count"}[
        basis
    ]
    row = NS(material_id="test", occurrence_id="test", **{field: amount})
    settings = AssessmentSettings(
        30,
        baseline="include",
        material_modules=("A1A3",),
        include_energy=False,
        material_factors={"test": {"A1A3": F(2, basis, "A1A3", "Test")}},
    )
    result = assess((row,), (), None, settings)
    assert result.complete and result.total_gwp_kgco2e == pytest.approx(expected)


def test_contribution_quantity_and_factor_must_agree_with_saved_impact():
    contribution = dict(
        module="A1A3", quantity=2, factor_value=10, gwp_kgco2e=20, source="Test"
    )
    result = LCAResult("complete", 20, 0, 20, contributions=(contribution,))
    assert result.complete
    for changes in (
        {"quantity": -2},
        {"quantity": 3},
        {"factor_value": float("nan")},
        {"source": ""},
    ):
        with pytest.raises(ValueError):
            LCAResult(
                "complete", 20, 0, 20, contributions=({**contribution, **changes},)
            )


@pytest.mark.parametrize(
    "changes",
    [
        {"baseline": []},
        {"material_modules": None},
        {"material_modules": ("A5", "A5.1")},
        {"include_energy": "no"},
        {"energy_boundary": 123},
        {"material_factors": None},
    ],
)
def test_invalid_choices_fail_with_actionable_errors(changes):
    with pytest.raises(ValueError):
        AssessmentSettings(30, **changes)
