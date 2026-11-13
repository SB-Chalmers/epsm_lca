"""Catalogue renovations: unit-rate costs per stage and carbon of installed products."""

import pytest
from epsm_core import Building, Footprint, GeometrySpec
from epsm_core.measures import apply_candidates
from epsm_data import Catalogue, ConstructionOperation, RenovationCatalogue
from epsm_data.domain.enums import BuildingElement as Role

from epsm_lca import (
    AssessmentSettings,
    CostSettings,
    assess_renovation,
    assess_renovation_cost,
)

RATE = {"currency": "SEK", "price_year": 2026}


@pytest.fixture(scope="module")
def library():
    return Catalogue.load()


def overlay():
    return {
        "insulate_wall": RATE
        | {
            "items": [
                {"category": "material", "rate": 700.0, "driver": "element_area_m2"},
                {
                    "category": "labour",
                    "rate": 400.0,
                    "driver": "element_area_m2",
                    "labour_hours": 1.5,
                },
                {"category": "overhead", "rate": 100.0, "driver": "building"},
            ]
        },
        "upgrade_ventilation": RATE
        | {
            "items": [
                {
                    "category": "material",
                    "rate": 300.0,
                    "driver": "supply_terminal_count",
                }
            ],
            "coverage": "partial",
            "missing_scope": ["air handling units"],
        },
    }


def building(library):
    result = Building(
        preset="illustrative-reference",
        construction_set=library.get("mf_se02", state="existing").construction_set,
        geometry=GeometrySpec.from_footprint(
            Footprint.rectangle(20, 12), storeys=3, storey_height_m=2.8
        ),
    )
    result.hvac = result.hvac.with_changes(
        airflow=result.hvac.airflow.model_dump()
        | {
            "topology": "S",
            "mechanical_vent_l_s_m2": 0.0,
            "natural_exchange_ach": 0.5,
            "sensible_recovery_effectiveness": 0.0,
        }
    )
    return result


def test_stage_cost_is_rate_times_geometric_driver(library):
    renovations = RenovationCatalogue.load(library, costs=overlay())
    child = apply_candidates(
        building(library), renovations.get("insulate_wall.stone_wool_200")
    )
    area = dict(child.stages[0].quantities[0].drivers)["element_area_m2"]
    stage = assess_renovation_cost(
        child, CostSettings.from_catalogue(renovations)
    ).stages[0]
    assert stage.status == "complete"
    assert stage.total == pytest.approx(1100 * area + 100)
    assert stage.by_category["labour"] == pytest.approx(400 * area)
    assert stage.labour_hours == pytest.approx(1.5 * area)


def test_partial_scope_missing_estimates_and_raw_operations_keep_totals_open(library):
    renovations = RenovationCatalogue.load(library, costs=overlay())
    base = building(library)
    child = apply_candidates(
        base,
        renovations.get("upgrade_ventilation.ftx_080"),
        renovations.get("replace_window.u_0_90"),
    )
    wall = next(e for e in child.elements if e.role == Role.EXT_WALL)
    child = child.renovate(
        ConstructionOperation(
            "replace_element", Role.EXT_WALL, element=wall.construction
        )
    )
    result = assess_renovation_cost(child, CostSettings.from_catalogue(renovations))
    first, second = result.stages
    terminals = dict(child.stages[0].quantities[0].drivers)["supply_terminal_count"]
    assert first.priced_subtotal == pytest.approx(300 * terminals)
    assert first.total is None and result.total is None
    assert any("unpriced scope: air handling units" in r for r in first.requirements)
    assert any(
        "no cost estimate for replace_window.u_0_90" in r for r in first.requirements
    )
    assert any("not a catalogue measure" in r for r in second.requirements)
    assert "seal_envelope.renovated_joints" in child.stages[0].measure_ids
    assert not any(
        "seal_envelope" in r for r in first.requirements
    )  # priced with its host
    with pytest.raises(ValueError, match="convert prices"):
        CostSettings(
            dict(CostSettings.from_catalogue(renovations).estimates), currency="EUR"
        )


def test_installed_products_are_assessed_from_boverket_by_mass(library):
    renovations = RenovationCatalogue.load(library)
    child = apply_candidates(
        building(library), renovations.get("upgrade_ventilation.ftx_080")
    )
    settings = AssessmentSettings.from_building(
        child,
        period_years=50,
        catalogue=library,
        renovations=renovations,
        material_modules=("A1A3",),
        include_energy=False,
    )
    stage = assess_renovation(child, settings).stages[0]
    assert stage.status == "complete"
    mass = sum(i.mass_kg for i in child.installations)
    factor = settings.material_factors["duct.galvanised_steel_d160"]["A1A3"].value
    assert stage.material_kgco2e == pytest.approx(mass * factor)
    without = AssessmentSettings.from_building(
        child,
        period_years=50,
        catalogue=library,
        material_modules=("A1A3",),
        include_energy=False,
    )
    assert assess_renovation(child, without).stages[0].status == "incomplete"


def test_pv_and_dhw_carbon_use_area_records_and_direct_factors(library):
    renovations = RenovationCatalogue.load(library)
    base = building(library)
    pv = apply_candidates(base, renovations.get("install_pv.roof_south_15"))
    settings = AssessmentSettings.from_building(
        pv,
        period_years=50,
        catalogue=library,
        renovations=renovations,
        material_modules=("A1A3",),
        include_energy=False,
    )
    module = settings.material_factors["pv.module_mono_si"]["A1A3"]
    bos = settings.material_factors["pv.balance_of_system"]["A1A3"]
    assert (module.unit, module.value, bos.unit, bos.value) == (
        "m2",
        119.0,
        "item",
        460.0,
    )
    kwp = dict(pv.stages[0].quantities[0].drivers)["pv_capacity_kwp"]
    stage = assess_renovation(pv, settings).stages[0]
    assert stage.material_kgco2e == pytest.approx(
        kwp * (1000 / 209 * 119 + 460), rel=1e-3
    )
    cost = assess_renovation_cost(pv, CostSettings.from_catalogue(renovations)).stages[
        0
    ]
    assert cost.total == pytest.approx(12100 * kwp)

    dhw = apply_candidates(base, renovations.get("reduce_dhw.low_flow_fittings"))
    settings = AssessmentSettings.from_building(
        dhw,
        period_years=50,
        catalogue=library,
        renovations=renovations,
        material_modules=("A1A3",),
        include_energy=False,
    )
    area = base.effective_load_reference_area_m2
    assert assess_renovation(dhw, settings).stages[0].material_kgco2e == pytest.approx(
        0.2 * area
    )
    assert assess_renovation_cost(dhw, CostSettings.from_catalogue(renovations)).stages[
        0
    ].total == (pytest.approx(90 * area))


def test_simple_cost_payback_divides_investment_by_operating_saving():
    from types import MappingProxyType

    from epsm_lca import OperatingCost, RenovationCostResult, StageCost

    def stage(step, total):
        return StageCost(
            step,
            f"s{step}",
            (),
            "SEK",
            (),
            MappingProxyType({}),
            MappingProxyType({}),
            0.0,
            total or 0.0,
            total,
            (2026,),
        )

    def running(step, annual):
        return OperatingCost(
            step, f"state{step}", "SEK", MappingProxyType({}), annual, None
        )

    result = RenovationCostResult(
        (stage(1, 10000.0), stage(2, 20000.0)),
        "SEK",
        operating=(running(0, 9000.0), running(1, 7000.0), running(2, 4000.0)),
    )
    assert result.simple_payback_years(1) == pytest.approx(5.0)
    assert result.simple_payback_years(2) == pytest.approx(6.0)
    assert result.summary()["simple_payback_years_by_step"] == {1: 5.0, 2: 6.0}
    unknown = RenovationCostResult(
        (stage(1, None),), "SEK", operating=(running(0, 9000.0), running(1, 7000.0))
    )
    assert unknown.simple_payback_years(1) is None


def test_global_cost_and_discounted_payback_are_checkable_by_hand():
    from types import MappingProxyType

    from epsm_lca import OperatingCost, RenovationCostResult, StageCost

    stage = StageCost(
        1,
        "s1",
        (),
        "SEK",
        (),
        MappingProxyType({}),
        MappingProxyType({}),
        0.0,
        250.0,
        250.0,
        (2026,),
    )

    def running(step, annual, present):
        return OperatingCost(
            step,
            f"s{step}",
            "SEK",
            MappingProxyType({}),
            annual,
            None,
            present_value=present,
        )

    result = RenovationCostResult(
        (stage,), "SEK", operating=(running(0, 300.0, 600.0), running(1, 200.0, 400.0))
    )
    assert result.global_cost(0) == 600.0
    assert result.global_cost(1) == 650.0  # 250 invested + 400 operating
    assert result.discounted_payback_years(1) == pytest.approx(2.5)
    from epsm_lca import ReplacementCost

    replaced = RenovationCostResult(
        (stage,),
        "SEK",
        operating=result.operating,
        replacements=(
            ReplacementCost(0, "SEK", (), 0.0, 0.0, residual_value=0.0),
            ReplacementCost(1, "SEK", (), 100.0, 90.0, residual_value=30.0),
        ),
    )
    # 250 invested + 400 operating + 90 replaced − 30 still in use.
    assert replaced.global_cost(1) == 710.0
    unknown = RenovationCostResult(
        (stage,),
        "SEK",
        operating=result.operating,
        replacements=(ReplacementCost(1, "SEK", (), 100.0, 90.0),),
    )
    assert unknown.global_cost(1) is None
    discounted = RenovationCostResult(
        (stage,), "SEK", operating=result.operating, discount_rate=0.1
    )
    # Three discounted years repay 90.91 + 82.64 + 75.13 = 248.69 of 250.
    repaid = sum(100 / 1.1**t for t in (1, 2, 3))
    assert discounted.discounted_payback_years(1) == pytest.approx(
        3 + (250 - repaid) / (100 / 1.1**4)
    )
    never = RenovationCostResult(
        (stage,), "SEK", operating=result.operating, discount_rate=0.5
    )
    assert never.discounted_payback_years(1) is None
    assert never.summary()["discounted_payback_years_by_step"] == {1: None}


def test_cost_payback_follows_yearly_operating_costs():
    from types import MappingProxyType

    from epsm_lca import OperatingCost, RenovationCostResult, StageCost

    stage = StageCost(
        1,
        "s1",
        (),
        "SEK",
        (),
        MappingProxyType({}),
        MappingProxyType({}),
        0.0,
        250.0,
        250.0,
        (2026,),
    )
    base = OperatingCost(
        0, "s0", "SEK", MappingProxyType({}), 200.0, 600.0, yearly=(100.0, 200.0, 300.0)
    )
    after = OperatingCost(1, "s1", "SEK", MappingProxyType({}), 0.0, 0.0)
    result = RenovationCostResult(
        (stage,), "SEK", operating=(base, after), period_years=3
    )
    # Savings of 100, 200 and 300: 250 is repaid three quarters into year 2.
    assert result.simple_payback_years(1) == pytest.approx(1.75)
    discounted = RenovationCostResult(
        (stage,), "SEK", operating=(base, after), discount_rate=0.1, period_years=3
    )
    first = 100 / 1.1
    assert discounted.discounted_payback_years(1) == pytest.approx(
        1 + (250 - first) / (200 / 1.1**2)
    )


def test_catalogue_service_lives_drive_replacement_counts(library):
    from dataclasses import fields

    from epsm_core.building import RenovationStage

    if not any(f.name == "installed_by" for f in fields(RenovationStage)):
        pytest.skip("this epsm_core does not record installing measures")
    renovations = RenovationCatalogue.load(library)
    child = apply_candidates(
        building(library),
        renovations.get("insulate_wall.stone_wool_200"),
        renovations.get("upgrade_ventilation.ftx_080"),
    )
    settings = AssessmentSettings.from_building(
        child,
        period_years=60,
        catalogue=library,
        renovations=renovations,
        material_modules=("A1A3",),
        include_energy=False,
        include_replacements=True,
    )
    assert settings.service_lives["upgrade_ventilation.ftx_080"].years == 25
    assert settings.service_lives["insulate_wall.stone_wool_200"].years == 50
    stage = assess_renovation(child, settings).stages[0]
    assert stage.complete
    by = dict(child.stages[0].installed_by)
    lives = {"upgrade_ventilation.ftx_080": 2, "insulate_wall.stone_wool_200": 1}
    expected = sum(
        c["gwp_kgco2e"] * lives.get(by[c["occurrence_id"]], 0)
        for c in stage.contributions
        if c["module"] == "A1A3"
    )
    assert stage.replacement_kgco2e == pytest.approx(expected)
    assert expected > 0


def test_measures_are_bought_again_when_their_service_life_ends(library):
    renovations = RenovationCatalogue.load(library, costs=overlay())
    child = apply_candidates(
        building(library), renovations.get("insulate_wall.stone_wool_200")
    )
    settings = CostSettings.from_catalogue(
        renovations, period_years=60, discount_rate=0.03, include_replacements=True
    )
    result = assess_renovation_cost(child, settings)
    baseline, after = result.replacements
    assert baseline.total == 0 and baseline.lines == ()
    stage = result.stages[0]
    (line,) = after.lines
    assert (line["year"], line["cost"]) == (50.0, pytest.approx(stage.total))
    assert after.present_value == pytest.approx(stage.total / 1.03**50)
    assert result.summary()["replacement_cost_by_step"] == {0: 0.0, 1: after.total}
    # The year-50 purchase has 40 of its 50 years left at year 60.
    (left,) = after.residual_lines
    assert (left["last_purchase_year"], left["remaining_life_years"]) == (50.0, 40.0)
    assert left["residual"] == pytest.approx(0.8 * stage.total)
    assert after.residual_value == pytest.approx(0.8 * stage.total / 1.03**60)
    assert result.summary()["residual_value_by_step"] == {
        0: 0.0,
        1: pytest.approx(after.residual_value),
    }
    short = CostSettings.from_catalogue(
        renovations, period_years=40, include_replacements=True
    )
    brief = assess_renovation_cost(child, short).replacements[1]
    assert brief.lines == ()
    # Never replaced: 10 of 50 years are left, undiscounted at rate 0.
    assert brief.residual_value == pytest.approx(0.2 * stage.total)
    exact = CostSettings.from_catalogue(
        renovations, period_years=50, include_replacements=True
    )
    assert assess_renovation_cost(child, exact).replacements[1].residual_value == 0.0
    unknown = CostSettings(
        settings.estimates, period_years=60, include_replacements=True
    )
    missing = assess_renovation_cost(child, unknown).replacements[1]
    assert missing.total is None
    assert (
        "insulate_wall.stone_wool_200: service life is missing" in missing.requirements
    )
