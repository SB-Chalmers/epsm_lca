# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Use the installed Data catalogue's real Boverket values and quantity bases."""

from dataclasses import replace

import pytest
from epsm_core import Building
from epsm_data import Catalogue, ConstructionOperation
from epsm_data.domain import BuildingElement as Role

from epsm_lca import AssessmentSettings, assess_renovation


def test_boverket_window_factors_use_explicit_area_conversion_and_source():
    catalogue = Catalogue.load()
    baseline = Building(
        preset="illustrative-reference",
        construction_set=catalogue.for_year(
            "multi_family", 1960, state="existing"
        ).construction_set,
    )
    window = baseline.construction_set.elements[Role.WINDOW]
    renovated = baseline.renovate(
        ConstructionOperation("replace_element", Role.WINDOW, element=window)
    )
    config = AssessmentSettings.from_building(
        renovated,
        period_years=30,
        catalogue=catalogue,
        include_energy=False,
        material_modules=("A1A3", "A4", "A5.1"),
    )
    rows = [row for row in renovated.quantities() if row.kind == "window"]
    assert rows and all(row.mass_kg is None for row in rows)
    factor = config.material_factors[rows[0].material_id]["A1A3"]
    assert factor.unit == "m2" and factor.value == pytest.approx(95.5)
    assert (
        "02.07.000" in factor.source
        and "38.2" in factor.source
        and "Conservative" in factor.source
    )
    report = assess_renovation(renovated, config)
    assert report.complete
    assert report.stages[0].material_kgco2e == pytest.approx(
        sum(row.area_m2 for row in rows) * 97.55898
    )
    assert all(row["mass_kg"] is None for row in report.stages[0].removed_quantities)
    typical = AssessmentSettings.from_building(
        renovated, period_years=30, catalogue=catalogue, production="typical"
    )
    assert typical.material_factors[rows[0].material_id]["A1A3"].value == pytest.approx(
        76.4
    )


def test_default_boverket_assessment_keeps_missing_disposal_factors_visible():
    catalogue = Catalogue.load()
    baseline = Building(
        preset="illustrative-reference",
        construction_set=catalogue.for_year(
            "multi_family", 1960, state="existing"
        ).construction_set,
    )
    window = baseline.construction_set.elements[Role.WINDOW]
    renovated = baseline.renovate(
        ConstructionOperation("replace_element", Role.WINDOW, element=window)
    )
    settings = AssessmentSettings.from_building(
        renovated, period_years=30, catalogue=catalogue, include_energy=False
    )
    report = assess_renovation(renovated, settings)
    assert not report.complete
    assert report.stages[0].removed_quantities
    assert any("C4" in r for r in report.stages[0].requirements)
    assert "A5.1" in settings.material_modules and "A5" not in settings.material_modules
    with pytest.raises(ValueError, match="not both"):
        replace(settings, material_modules=("A5", "A5.1"))


def test_material_embodied_values_work_without_catalogue_loading():
    catalogue = Catalogue.load()
    baseline = Building(
        preset="illustrative-reference",
        construction_set=catalogue.for_year(
            "multi_family", 1960, state="existing"
        ).construction_set,
    )
    settings = AssessmentSettings.from_building(baseline, period_years=30)
    material = next(
        row.material
        for row in baseline.quantities()
        if row.material is not None and row.material.embodied_carbon is not None
    )
    identity = material.json_id or str(material.uuid)
    assert (
        settings.material_factors[identity]["A1A3"].value
        == material.embodied_carbon.A1_A3_conservative
    )
    assert "Boverket" in settings.material_factors[identity]["A4"].source
