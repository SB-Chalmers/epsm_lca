"""Unknown historical stock stays strict when it enters an assessed material flow."""

from dataclasses import replace

import pytest
from epsm_core import Building
from epsm_data import Catalogue, ConstructionOperation
from epsm_data.domain import BuildingElement as Role

from epsm_lca import AssessmentSettings, assess_renovation

STOCK = {
    "material:24606d33cd33ee52",
    "material:622fee5beaa8a10c",
    "material:d9698d5db7cf2fc0",
}
COKE = "material:24606d33cd33ee52"


def _building():
    payload = Catalogue.load().to_dict()
    for mid in STOCK:
        payload["materials"][mid].pop("boverket_id", None)
        payload["materials"][mid]["carbon_assessment"] = {
            "status": "retained_existing_unmapped", "reason": "Retained original stock."
        }
    catalogue = Catalogue(payload)
    return catalogue, Building(
        preset="illustrative-reference",
        construction_set=catalogue.get("mf_se01").construction_set,
    )


def _settings(building, catalogue, **changes):
    return AssessmentSettings.from_building(
        building, period_years=30, catalogue=catalogue, include_energy=False,
        material_modules=("A1A3", "C4"), **changes,
    )


def test_known_addition_counts_only_intervention_and_preserves_unquantified_stock():
    catalogue, baseline = _building()
    cap = baseline.construction_set.elements[Role.GROUND_FLOOR].components[-1]
    renovated = baseline.renovate(ConstructionOperation(
        "add_component", Role.GROUND_FLOOR, component=cap, position=2,
    ))
    flow = renovated.material_flows[-1]
    assert STOCK <= {row.material_id for row in flow.retained}
    assert not STOCK & {row.material_id for row in flow.installed}
    settings = _settings(renovated, catalogue)
    assert all(not settings.material_factors.get(mid) for mid in STOCK)
    report = assess_renovation(renovated, settings)
    assert report.complete
    assert report.stages[-1].material_kgco2e > 0
    assert not STOCK & {row["material_id"] for row in report.stages[-1].contributions}
    for mid in STOCK:
        assert catalogue.materials[mid].embodied_carbon is None
        assert catalogue.materials[mid].carbon_reference is None


def test_including_original_inventory_still_requires_unknown_production_factors():
    catalogue, building = _building()
    report = assess_renovation(building, _settings(building, catalogue, baseline="include"))
    assert not report.complete
    assert report.baseline.total_kgco2e is None
    for mid in STOCK:
        assert f"{mid}: factor A1A3 is missing" in report.baseline.requirements


@pytest.mark.parametrize("action,module", [("install", "A1A3"), ("remove", "C4")])
def test_new_or_removed_unknown_stock_is_never_silently_excluded(action, module):
    catalogue, baseline = _building()
    top = baseline.construction_set.elements[Role.TOP_FLOOR]
    ash = next(component for component in top.components
               if any(share.material.json_id == COKE
                      for slot in component.layers for share in slot.layer.materials))
    if action == "install":
        operation = ConstructionOperation("add_component", Role.TOP_FLOOR, component=ash, position=0)
    else:
        replacement = replace(top, components=tuple(c for c in top.components if c is not ash))
        operation = ConstructionOperation("replace_element", Role.TOP_FLOOR, element=replacement)
    renovated = baseline.renovate(operation)
    report = assess_renovation(renovated, _settings(renovated, catalogue))
    assert not report.complete
    assert report.stages[-1].material_kgco2e is None
    assert f"{COKE}: factor {module} is missing" in report.stages[-1].requirements
