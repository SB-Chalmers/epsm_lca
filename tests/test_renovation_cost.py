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
        "insulate_wall": RATE | {"items": [
            {"category": "material", "rate": 700.0, "driver": "element_area_m2"},
            {"category": "labour", "rate": 400.0, "driver": "element_area_m2", "labour_hours": 1.5},
            {"category": "overhead", "rate": 100.0, "driver": "building"}]},
        "upgrade_ventilation": RATE | {
            "items": [{"category": "material", "rate": 300.0, "driver": "supply_terminal_count"}],
            "coverage": "partial", "missing_scope": ["air handling units"]},
    }


def building(library):
    result = Building(
        preset="illustrative-reference",
        construction_set=library.get("mf_se02", state="existing").construction_set,
        geometry=GeometrySpec.from_footprint(Footprint.rectangle(20, 12), storeys=3,
                                             storey_height_m=2.8))
    result.hvac = result.hvac.with_changes(airflow=result.hvac.airflow.model_dump() | {
        "topology": "S", "mechanical_vent_l_s_m2": 0.0, "natural_exchange_ach": 0.5,
        "sensible_recovery_effectiveness": 0.0})
    return result


def test_stage_cost_is_rate_times_geometric_driver(library):
    renovations = RenovationCatalogue.load(library, costs=overlay())
    child = apply_candidates(building(library), renovations.get("insulate_wall.stone_wool_200"))
    area = dict(child.stages[0].quantities[0].drivers)["element_area_m2"]
    stage = assess_renovation_cost(child, CostSettings.from_catalogue(renovations)).stages[0]
    assert stage.status == "complete"
    assert stage.total == pytest.approx(1100 * area + 100)
    assert stage.by_category["labour"] == pytest.approx(400 * area)
    assert stage.labour_hours == pytest.approx(1.5 * area)


def test_partial_scope_missing_estimates_and_raw_operations_keep_totals_open(library):
    renovations = RenovationCatalogue.load(library, costs=overlay())
    base = building(library)
    child = apply_candidates(base, renovations.get("upgrade_ventilation.ftx_080"),
                             renovations.get("replace_window.u_0_90"))
    wall = next(e for e in child.elements if e.role == Role.EXT_WALL)
    child = child.renovate(ConstructionOperation("replace_element", Role.EXT_WALL,
                                                 element=wall.construction))
    result = assess_renovation_cost(child, CostSettings.from_catalogue(renovations))
    first, second = result.stages
    terminals = dict(child.stages[0].quantities[0].drivers)["supply_terminal_count"]
    assert first.priced_subtotal == pytest.approx(300 * terminals)
    assert first.total is None and result.total is None
    assert any("unpriced scope: air handling units" in r for r in first.requirements)
    assert any("no cost estimate for replace_window.u_0_90" in r for r in first.requirements)
    assert any("not a catalogue measure" in r for r in second.requirements)
    assert "seal_envelope.renovated_joints" in child.stages[0].measure_ids
    assert not any("seal_envelope" in r for r in first.requirements)  # priced with its host
    with pytest.raises(ValueError, match="convert prices"):
        CostSettings(dict(CostSettings.from_catalogue(renovations).estimates), currency="EUR")


def test_installed_products_are_assessed_from_boverket_by_mass(library):
    renovations = RenovationCatalogue.load(library)
    child = apply_candidates(building(library), renovations.get("upgrade_ventilation.ftx_080"))
    settings = AssessmentSettings.from_building(
        child, period_years=50, catalogue=library, renovations=renovations,
        material_modules=("A1A3",), include_energy=False)
    stage = assess_renovation(child, settings).stages[0]
    assert stage.status == "complete"
    mass = sum(i.mass_kg for i in child.installations)
    factor = settings.material_factors["duct.galvanised_steel_d160"]["A1A3"].value
    assert stage.material_kgco2e == pytest.approx(mass * factor)
    without = AssessmentSettings.from_building(child, period_years=50, catalogue=library,
                                               material_modules=("A1A3",), include_energy=False)
    assert assess_renovation(child, without).stages[0].status == "incomplete"


def test_pv_and_dhw_carbon_use_area_records_and_direct_factors(library):
    renovations = RenovationCatalogue.load(library)
    base = building(library)
    pv = apply_candidates(base, renovations.get("install_pv.roof_south_15"))
    settings = AssessmentSettings.from_building(pv, period_years=50, catalogue=library,
                                                renovations=renovations,
                                                material_modules=("A1A3",), include_energy=False)
    module = settings.material_factors["pv.module_mono_si"]["A1A3"]
    bos = settings.material_factors["pv.balance_of_system"]["A1A3"]
    assert (module.unit, module.value, bos.unit, bos.value) == ("m2", 119.0, "item", 460.0)
    kwp = dict(pv.stages[0].quantities[0].drivers)["pv_capacity_kwp"]
    stage = assess_renovation(pv, settings).stages[0]
    assert stage.material_kgco2e == pytest.approx(kwp * (1000 / 209 * 119 + 460), rel=1e-3)
    cost = assess_renovation_cost(pv, CostSettings.from_catalogue(renovations)).stages[0]
    assert cost.total == pytest.approx(12100 * kwp)

    dhw = apply_candidates(base, renovations.get("reduce_dhw.low_flow_fittings"))
    settings = AssessmentSettings.from_building(dhw, period_years=50, catalogue=library,
                                                renovations=renovations,
                                                material_modules=("A1A3",), include_energy=False)
    area = base.effective_load_reference_area_m2
    assert assess_renovation(dhw, settings).stages[0].material_kgco2e == pytest.approx(0.2 * area)
    assert assess_renovation_cost(dhw, CostSettings.from_catalogue(renovations)).stages[0].total == (
        pytest.approx(90 * area))
