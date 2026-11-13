# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Observable building-renovation accounting with independent expected answers."""

from dataclasses import replace

import pytest
from epsm_core import Building, Footprint
from epsm_data import (
    ConstructionOperation,
    EnvironmentalFactor,
    RenovationMeasure,
    reference_construction_set,
)
from epsm_data.domain import BuildingElement as Role

from epsm_lca import (
    AnnualEnergy,
    AssessmentSettings,
    FactorTrajectory,
    RenovationResult,
    assess_renovation,
)


@pytest.fixture
def case():
    reference = Building(preset="illustrative-reference")
    baseline = Building.from_footprint(
        Footprint.rectangle(5, 5),
        storeys=1,
        storey_height_m=2.5,
        construction_set=reference_construction_set(),
        facade=reference.facade,
    )
    window = replace(
        baseline.construction_set.elements[Role.WINDOW],
        name="Teaching replacement windows",
        u_value=1.0,
    )
    windows = RenovationMeasure(
        "windows",
        "envelope",
        "Replace windows",
        "Teaching example",
        "window",
        operations=(
            ConstructionOperation("replace_element", Role.WINDOW, element=window),
        ),
    )
    component = baseline.construction_set.elements[Role.EXT_WALL].components[0]
    slot = component.layers[0]
    layer = replace(
        slot.layer,
        name="Extra insulation",
        thickness=0.1,
        materials=tuple(replace(p, thickness=0.1) for p in slot.layer.materials),
    )
    addition = replace(
        component,
        name="Extra insulation",
        layers=(replace(slot, layer=layer, position=0),),
    )
    insulation = RenovationMeasure(
        "insulation",
        "envelope",
        "Insulate walls",
        "Teaching example",
        "wall",
        operations=(
            ConstructionOperation(
                "add_component", Role.EXT_WALL, component=addition, position=0
            ),
        ),
    )
    one = baseline.renovate(windows)
    two = one.renovate(insulation)
    factors = {}
    for flow in two.material_flows:
        for row in (*flow.installed, *flow.removed):
            unit = "m2" if row.kind == "window" else "kg"
            values = (
                {"A1A3": 18, "A4": 1, "A5": 1}
                if unit == "m2"
                else {
                    "A1A3": 1.6,
                    "A4": 0.2,
                    "A5": 0.2,
                }
            )
            values.update({module: 0.5 for module in ("C1", "C2", "C3", "C4")})
            factors[row.material_id] = {
                module: EnvironmentalFactor(
                    value, unit, module, "Synthetic teaching factor"
                )
                for module, value in values.items()
            }
    settings = AssessmentSettings(
        period_years=30,
        material_factors=factors,
        carrier_factors={
            "electricity": EnvironmentalFactor(0.1, "kWh", "B6", "Teaching")
        },
    )
    energy = {
        i: AnnualEnergy.for_building(
            b,
            delivered_by_carrier={"electricity": kwh},
            source="Assumed annual teaching values",
        )
        for i, (b, kwh) in enumerate(((baseline, 10000), (one, 9000), (two, 8000)))
    }
    return baseline, windows, insulation, one, two, settings, energy


def test_every_step_has_its_own_material_and_energy_answer(case):
    baseline, _, _, one, two, settings, energy = case
    original = baseline.snapshot().sha256
    report = assess_renovation(two, settings, energy=energy)
    assert report.complete
    assert report.baseline.total_kgco2e == pytest.approx(30000)
    assert [s.material_kgco2e for s in report.stages] == pytest.approx([220, 280])
    assert [s.material_so_far_kgco2e for s in report.stages] == pytest.approx(
        [220, 500]
    )
    assert [s.total_kgco2e for s in report.stages] == pytest.approx([27220, 24500])
    assert [s.savings_kgco2e for s in report.stages] == pytest.approx([2780, 5500])
    assert baseline.snapshot().sha256 == original and not baseline.stages
    assert report.stages[0].state_id == one.snapshot().sha256
    assert report.stages[1].stage_id == two.stages[-1].stage_id
    assert len(report.table()) == 3


def test_bundled_and_staged_work_have_equal_final_answers(case):
    baseline, windows, insulation, _, two, settings, energy = case
    bundled = baseline.renovate(windows, insulation)
    supplied = {
        0: energy[0],
        1: AnnualEnergy.for_building(
            bundled,
            delivered_by_carrier={"electricity": 8000},
            source="Teaching",
        ),
    }
    single = assess_renovation(bundled, settings, energy=supplied)
    staged = assess_renovation(two, settings, energy=energy)
    assert len(single.stages) == 1
    assert single.stages[0].material_kgco2e == pytest.approx(500)
    assert single.stages[-1].total_kgco2e == pytest.approx(
        staged.stages[-1].total_kgco2e
    )


def test_materials_only_and_missing_stage_energy_keep_useful_results(case):
    _, _, _, _, two, settings, energy = case
    materials = assess_renovation(two, replace(settings, include_energy=False))
    assert materials.complete
    assert materials.stages[-1].total_kgco2e == pytest.approx(500)
    assert materials.stages[-1].energy_kgco2e is None
    partial = assess_renovation(two, settings, energy={0: energy[0], 2: energy[2]})
    assert not partial.complete
    assert partial.stages[0].total_kgco2e is None
    assert partial.stages[0].material_kgco2e == pytest.approx(220)
    assert partial.stages[1].complete
    assert partial.stages[1].savings_kgco2e == pytest.approx(5500)


def test_removed_quantities_survive_missing_removal_factors(case):
    _, _, _, _, two, settings, _ = case
    factors = {
        identity: {
            module: factor
            for module, factor in values.items()
            if module.startswith("A")
        }
        for identity, values in settings.material_factors.items()
    }
    report = assess_renovation(
        two, replace(settings, include_energy=False, material_factors=factors)
    )
    assert not report.complete
    removed = report.quantities(step=1, action="removed", by_material=True)
    assert sum(row["area_m2"] for row in removed) == pytest.approx(10)
    assert all(row["mass_kg"] is None for row in removed)
    assert report.quantities(step=2, action="removed") == []
    added = report.quantities(step=2, action="added", by_material=True)
    assert sum(row["mass_kg"] for row in added) == pytest.approx(140)
    inspected = report.stages[0].removed_quantities
    inspected[0]["area_m2"] = 999
    assert report.stages[0].removed_quantities[0]["area_m2"] != 999


def test_arbitrary_steps_and_repeat_replacement_count_removed_materials(case):
    baseline, windows, insulation, _, _, settings, _ = case
    final = baseline
    for _ in range(4):
        final = final.renovate(windows)
    final = final.renovate(insulation)
    report = assess_renovation(final, replace(settings, include_energy=False))
    assert len(report.stages) == 5
    assert report.stages[-1].material_so_far_kgco2e == pytest.approx(1160)
    assert sum(
        row["area_m2"] for row in report.quantities(action="removed")
    ) == pytest.approx(40)


def test_unknown_baseline_energy_does_not_prevent_known_later_totals(case):
    _, _, _, _, two, settings, energy = case
    report = assess_renovation(two, settings, energy={1: energy[1], 2: energy[2]})
    assert not report.baseline.complete and not report.complete
    assert report.stages[-1].total_kgco2e == pytest.approx(24500)
    assert report.stages[-1].savings_kgco2e is None


def test_saved_report_roundtrips_without_mutable_inputs(case, tmp_path):
    baseline, _, _, _, two, settings, energy = case
    report = assess_renovation(two, settings, energy=energy)
    saved = report.to_dict()
    restored = RenovationResult.from_dict(saved)
    assert restored == report
    saved["settings"]["period_years"] = 60
    saved["stages"][0]["removed_quantities"][0]["area_m2"] = -100
    baseline.identifier = "changed after assessment"
    assert restored == report and report.settings.period_years == 30
    path = tmp_path / "report.json"
    assert report.save(path) == path
    assert RenovationResult.load(path) == report
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        report.save(path)
    assert path.read_bytes() == before
    report.save(path, overwrite=True)
    assert not tuple(tmp_path.glob(".epsm-lca-*"))


@pytest.mark.parametrize(
    "change", ["total", "savings", "quantities", "period", "format"]
)
def test_tampered_reports_are_rejected(case, change):
    _, _, _, _, two, settings, energy = case
    saved = assess_renovation(two, settings, energy=energy).to_dict()
    if change == "total":
        saved["stages"][0]["total_kgco2e"] = 1
    elif change == "savings":
        saved["stages"][0]["savings_kgco2e"] = 999
    elif change == "quantities":
        saved["stages"][0]["removed_quantities"][0]["area_m2"] = 999
    elif change == "period":
        saved["settings"]["period_years"] = 60
    else:
        saved["format"] = "future"
    with pytest.raises(ValueError):
        RenovationResult.from_dict(saved)


def test_unrecorded_physical_edits_remain_incomplete(case):
    _, _, _, one, _, settings, _ = case
    one.construction_set = reference_construction_set()
    assert one.material_history_requirements
    report = assess_renovation(one, replace(settings, include_energy=False))
    assert not report.stages[0].complete
    assert any("history" in r.lower() for r in report.stages[0].requirements)


def test_energy_must_describe_the_correct_step_and_uses(case):
    baseline, _, _, _, two, settings, energy = case
    with pytest.raises(ValueError, match="different building"):
        assess_renovation(two, settings, energy={1: energy[0]})
    wrong = AnnualEnergy.for_building(
        baseline,
        delivered_by_carrier={"electricity": 1},
        source="Test",
        boundary="whole_building",
    )
    with pytest.raises(ValueError, match="different uses"):
        assess_renovation(two, settings, energy={0: wrong})
    with pytest.raises(ValueError, match="Energy step"):
        assess_renovation(two, settings, energy={99: energy[0]})


def test_logging_has_shared_fields_and_no_large_records(case, caplog, tmp_path):
    _, _, _, _, two, settings, energy = case
    with caplog.at_level("DEBUG", logger="epsm_lca"):
        report = assess_renovation(two, settings, energy=energy)
        path = report.save(tmp_path / "report.json")
        RenovationResult.load(path)
    events = [record.epsm_event for record in caplog.records]
    assert events.count("lca.renovation.started") == 1
    assert events.count("lca.renovation.completed") == 1
    assert events.count("lca.step.completed") == 3
    assert "lca.report.saved" in events and "lca.report.loaded" in events
    for record in caplog.records:
        assert isinstance(record.epsm_context, dict) and isinstance(
            record.epsm_details, dict
        )
        assert "contributions" not in record.epsm_details
        assert not record.exc_info


def test_include_original_materials_once(case):
    baseline, _, _, _, two, settings, _ = case
    factors = {
        identity: dict(values) for identity, values in settings.material_factors.items()
    }
    for row in baseline.quantities():
        unit = (
            "kg"
            if row.mass_kg is not None
            else "item"
            if row.count is not None
            else "m2"
        )
        factors.setdefault(row.material_id, {}).update(
            {
                m: EnvironmentalFactor(1, unit, m, "Teaching original material")
                for m in ("A1A3", "A4", "A5")
            }
        )
    config = replace(
        settings, baseline="include", include_energy=False, material_factors=factors
    )
    report = assess_renovation(two, config)
    assert report.complete and report.baseline.material_kgco2e > 0
    assert report.stages[-1].material_so_far_kgco2e == pytest.approx(
        report.baseline.material_kgco2e + sum(s.material_kgco2e for s in report.stages)
    )


def test_plot_keeps_style_and_existing_axes(case, tmp_path):
    matplotlib = pytest.importorskip(
        "matplotlib", reason="Install the plot extra for rendering checks"
    )
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _, _, _, _, two, settings, energy = case
    report = assess_renovation(two, settings, energy=energy)
    fig, ax = plt.subplots()
    (original_line,) = ax.plot([0, 1], [1, 2])
    style = matplotlib.rcParams.copy()
    assert report.plot(ax=ax) is fig
    assert original_line in ax.lines
    assert matplotlib.rcParams == style
    assert "kg CO₂e" in ax.get_ylabel()
    fig.savefig(tmp_path / "plot.svg")
    plt.close(fig)


def test_rejected_file_publication_preserves_existing_evidence(
    case, tmp_path, monkeypatch
):
    from epsm_lca import io

    _, _, _, _, two, settings, energy = case
    report = assess_renovation(two, settings, energy=energy)
    path = tmp_path / "evidence.json"
    path.write_text("Earlier evidence")

    def reject(*args):
        raise OSError("Publication unavailable")

    monkeypatch.setattr(io.os, "replace", reject)
    with pytest.raises(OSError, match="unavailable"):
        report.save(path, overwrite=True)
    assert path.read_text() == "Earlier evidence"
    assert not tuple(tmp_path.glob(".epsm-lca-*"))


@pytest.mark.parametrize(
    "payload", ['{"format": "future"}', '{"a": 1, "a": 2}', '{"value": NaN}', "[]"]
)
def test_bad_report_files_fail_clearly(tmp_path, payload):
    path = tmp_path / "bad.json"
    path.write_text(payload)
    with pytest.raises(ValueError, match="Invalid renovation report"):
        RenovationResult.load(path)


def test_stage_overflow_keeps_quantities_and_finite_evidence(case):
    _, _, _, _, two, settings, _ = case
    factors = {
        identity: {m: replace(factor, value=1e308) for m, factor in values.items()}
        for identity, values in settings.material_factors.items()
    }
    report = assess_renovation(
        two, replace(settings, include_energy=False, material_factors=factors)
    )
    assert not report.complete
    assert report.stages[0].total_kgco2e is None
    assert report.stages[0].removed_quantities
    assert any("finite" in r for r in report.stages[0].requirements)
    import json

    json.dumps(report.to_dict(), allow_nan=False)


def test_representation_uses_saved_summaries_without_recalculating_or_io(
    case, monkeypatch
):
    _, _, _, _, two, settings, energy = case
    report = assess_renovation(two, settings, energy=energy)
    objects = (report, report.baseline, *report.stages, settings, energy[0])

    def forbidden(*args, **kwargs):
        pytest.fail("Printing must not read files or calculate building quantities")

    monkeypatch.setattr(Building, "quantities", forbidden)
    monkeypatch.setattr("pathlib.Path.open", forbidden)
    for obj in objects:
        for render in (repr, str):
            value = render(obj)
            assert len(value) <= 160 and "\n" not in value


def test_missing_energy_plot_uses_a_gap_and_label(case):
    matplotlib = pytest.importorskip("matplotlib", reason="Install plot extra")
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _, _, _, _, two, settings, energy = case
    report = assess_renovation(two, settings, energy={0: energy[0], 2: energy[2]})
    figure = report.plot()
    ax = figure.axes[0]
    assert any(text.get_text() == "Missing" for text in ax.texts)
    assert any(text.get_text() == "Total incomplete" for text in ax.texts)
    plt.close(figure)


def test_carbon_payback_and_per_area_results_are_checkable_by_hand(case):
    _, _, _, _, two, settings, energy = case
    area = replace(settings, reference_area_m2=25.0, reference_area_basis="Atemp")
    rows = assess_renovation(two, area, energy=energy).table()
    # Baseline uses 10,000 kWh x 0.1 kg/kWh; steps save 100 and 200 kg a year.
    assert [r["renovation_kgco2e"] for r in rows] == pytest.approx([0, 220, 500])
    assert rows[0]["carbon_payback_years"] is None
    assert [r["carbon_payback_years"] for r in rows[1:]] == pytest.approx([2.2, 2.5])
    assert rows[2]["total_kgco2e_per_m2"] == pytest.approx(24500 / 25)
    assert rows[2]["total_kgco2e_per_m2_year"] == pytest.approx(24500 / 25 / 30)
    report = assess_renovation(two, area, energy=energy)
    assert report.summary()["final_carbon_payback_years"] == pytest.approx(2.5)
    assert RenovationResult.from_dict(report.to_dict()) == report


def test_indicators_stay_unknown_without_energy_area_or_savings(case):
    _, _, _, _, two, settings, energy = case
    materials = assess_renovation(two, replace(settings, include_energy=False))
    row = materials.table()[-1]
    assert row["carbon_payback_years"] is None
    assert row["total_kgco2e_per_m2"] is None
    worse = {
        **energy,
        2: AnnualEnergy.for_building(
            two, delivered_by_carrier={"electricity": 12000}, source="Teaching"
        ),
    }
    row = assess_renovation(two, settings, energy=worse).table()[-1]
    assert row["annual_energy_saving_kgco2e"] == pytest.approx(-200)
    assert row["carbon_payback_years"] is None


def test_older_report_formats_are_rejected(case):
    _, _, _, _, two, settings, energy = case
    saved = assess_renovation(two, settings, energy=energy).to_dict()
    with pytest.raises(ValueError, match="Unsupported renovation report"):
        RenovationResult.from_dict({**saved, "format": "epsm-lca-renovation/1"})


def test_settings_from_building_use_core_conditioned_floor_area(case):
    _, _, _, _, two, _, _ = case
    settings = AssessmentSettings.from_building(two, period_years=30)
    assert settings.reference_area_m2 == pytest.approx(25)
    assert settings.reference_area_basis == "conditioned floor area (epsm_core)"
    chosen = AssessmentSettings.from_building(
        two, period_years=30, reference_area_m2=20, reference_area_basis="Atemp"
    )
    assert chosen.reference_area_m2 == 20


def test_carbon_payback_follows_a_yearly_factor_trajectory(case):
    _, _, _, _, two, settings, energy = case
    # Step 1 saves 1,000 kWh a year: 100 kg in years 1-2, then 10 kg a year.
    falling = FactorTrajectory.from_values([0.1, 0.1] + [0.01] * 28, "kgCO2e/kWh", "s")
    rows = assess_renovation(
        two, replace(settings, carrier_factors={"electricity": falling}), energy=energy
    ).table()
    assert rows[1]["carbon_payback_years"] == pytest.approx(4.0)  # 100+100+10+10
    tiny = FactorTrajectory.from_values([1e-4] * 30, "kgCO2e/kWh", "s")
    rows = assess_renovation(
        two, replace(settings, carrier_factors={"electricity": tiny}), energy=energy
    ).table()
    assert rows[1]["carbon_payback_years"] is None  # not repaid within 30 years


def _core_records_installing_measures():
    from dataclasses import fields

    from epsm_core.building import RenovationStage

    return any(f.name == "installed_by" for f in fields(RenovationStage))


needs_installing_measures = pytest.mark.skipif(
    not _core_records_installing_measures(),
    reason="this epsm_core does not record installing measures",
)


@needs_installing_measures
def test_replacements_repeat_installation_and_removal_within_the_period(case):
    from epsm_lca import ServiceLife

    _, _, _, _, two, settings, energy = case
    lives = {
        "windows": ServiceLife(20, "Teaching assumption"),
        "insulation": ServiceLife(50, "Teaching assumption"),
    }
    counted = replace(settings, include_replacements=True, service_lives=lives)
    report = assess_renovation(two, counted, energy=energy)
    assert report.complete
    # 10 m2 of windows are replaced once in 30 years: (18+1+1 + 4x0.5) x 10.
    assert [s.replacement_kgco2e for s in report.stages] == pytest.approx([220, 220])
    assert report.baseline.replacement_kgco2e == 0
    assert [s.total_kgco2e for s in report.stages] == pytest.approx([27440, 24720])
    b4 = [c for c in report.stages[0].contributions if c["module"] == "B4"]
    assert {c["year"] for c in b4} == {20.0}
    assert {c["replaced_module"] for c in b4} == {
        "A1A3",
        "A4",
        "A5",
        "C1",
        "C2",
        "C3",
        "C4",
    }
    assert RenovationResult.from_dict(report.to_dict()) == report
    off = assess_renovation(two, settings, energy=energy)
    assert off.stages[0].replacement_kgco2e is None
    assert off.stages[0].total_kgco2e == pytest.approx(27220)


@needs_installing_measures
def test_replacements_need_service_lives_and_skip_removed_work(case):
    from epsm_lca import ServiceLife

    baseline, windows, insulation, _, _, settings, _ = case
    unknown = replace(settings, include_replacements=True, include_energy=False)
    report = assess_renovation(baseline.renovate(windows), unknown)
    assert not report.complete
    assert "windows: service life is missing" in report.stages[0].requirements
    twice = baseline.renovate(windows).renovate(windows)
    lives = {"windows": ServiceLife(20, "Teaching assumption")}
    report = assess_renovation(twice, replace(unknown, service_lives=lives))
    # Only the second set of windows survives; the first is not replaced again.
    assert [s.replacement_kgco2e for s in report.stages] == pytest.approx([220, 220])


def test_coverage_counts_factored_occurrences_and_known_mass(case):
    _, _, _, _, two, settings, energy = case
    report = assess_renovation(two, settings, energy=energy)
    coverage = report.coverage()
    assert [c["step"] for c in coverage] == [0, 1, 2]
    assert [c["status"] for c in coverage] == ["complete"] * 3
    windows = {m["module"]: m for m in coverage[1]["modules"]}
    assert windows["A1A3"]["action"] == "added" and windows["C4"]["action"] == "removed"
    # Windows are declared per m2, so their mass is unknown and never pretended.
    assert windows["A1A3"]["covered_occurrences"] == windows["A1A3"]["occurrences"] == 4
    assert windows["A1A3"]["occurrence_share"] == 1.0
    assert windows["A1A3"]["mass_share"] is None
    assert windows["A1A3"]["mass_unknown_occurrences"] == 4
    insulation = {m["module"]: m for m in coverage[2]["modules"]}
    assert insulation["A4"]["mass_kg"] == pytest.approx(140)
    assert insulation["A4"]["covered_mass_kg"] == pytest.approx(140)
    assert insulation["A4"]["mass_share"] == 1.0
    assert (
        insulation["C1"]["occurrences"] == 0 and insulation["C1"]["mass_share"] is None
    )
    sources = coverage[2]["sources"]
    assert sources["material"]["total_kgco2e"] == pytest.approx(280)
    assert sources["material"]["share_by_source_kind"] == {"other": 1.0}
    assert sources["energy"]["by_source_kind"] == {"other": pytest.approx(24000)}
    assert "replacement" not in sources


def test_coverage_shows_the_missing_module_of_an_incomplete_step(case):
    _, _, _, _, two, settings, energy = case
    factors = {
        identity: {
            m: f
            for m, f in modules.items()
            if (identity, m) != ("reference.insulation", "A4")
        }
        for identity, modules in settings.material_factors.items()
    }
    report = assess_renovation(
        two, replace(settings, material_factors=factors), energy=energy
    )
    step = report.coverage()[2]
    assert step["status"] == "incomplete"
    modules = {m["module"]: m for m in step["modules"]}
    assert modules["A1A3"]["covered_occurrences"] == 4
    assert modules["A4"]["covered_occurrences"] == 0
    assert modules["A4"]["mass_share"] == 0.0
    # No ranking over partial contributions: step 2 is left out.
    assert {r["step"] for r in report.sensitivity()} == {1}
    assert {r["step"] for r in report.sensitivity(target="total")} == {0, 1}


def test_sensitivity_swings_follow_each_drivers_linear_impact(case):
    _, _, _, _, two, settings, energy = case
    report = assess_renovation(two, settings, energy=energy)
    rows = [r for r in report.sensitivity() if r["step"] == 2]
    assert [(r["driver_kind"], r["driver"]) for r in rows] == [
        ("carrier", "electricity"),
        ("material", "reference.insulation"),
        ("material", "Teaching replacement windows"),
        ("material", "reference.WINDOW"),
    ]
    # Baseline electricity 30,000 minus step 2's 24,000; materials cost carbon.
    assert [r["impact_kgco2e"] for r in rows] == pytest.approx([6000, -280, -200, -20])
    assert sum(r["impact_kgco2e"] for r in rows) == pytest.approx(5500)
    assert rows[0]["share"] == pytest.approx(6000 / 5500)
    assert rows[0]["swing_kgco2e"] == pytest.approx(1500)
    assert (rows[0]["low_kgco2e"], rows[0]["high_kgco2e"]) == pytest.approx(
        (4000, 7000)
    )
    assert rows[1]["swing_kgco2e"] == pytest.approx(70)
    assert rows[0]["source_kinds"] == ("other",)
    assert all(r["target"] == "savings" for r in rows)
    totals = [
        r for r in report.sensitivity(target="total", fraction=0.1) if r["step"] == 2
    ]
    assert sum(r["impact_kgco2e"] for r in totals) == pytest.approx(24500)
    assert totals[0]["swing_kgco2e"] == pytest.approx(2400)
    with pytest.raises(ValueError, match="fraction"):
        report.sensitivity(fraction=0)
    with pytest.raises(ValueError, match="target"):
        report.sensitivity(target="payback")


@pytest.mark.parametrize(
    "source,kind",
    [
        ("EPD-IES-0005222:003 | GWP-GHG; EN 15804 | https://example.org", "epd"),
        ("ref-7 | GWP-GHG | https://example.org", "reference"),
        ("EPD-1 | GWP-GHG | https://example.org | proxy for: sand 0/2", "proxy"),
        ("Boverket 1234; version 2024; GWP-GHG AR4; A1-A3 Conservative", "boverket"),
        ("Synthetic teaching factor", "other"),
    ],
)
def test_source_kinds_come_from_how_the_source_is_written(source, kind):
    from epsm_lca.coverage import source_kind

    assert source_kind(source) == kind
