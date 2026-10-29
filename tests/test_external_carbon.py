"""Portable external declarations preserve known factors and missing modules."""

import json
from dataclasses import replace

import pytest
from epsm_core import Building, BuildingSnapshot
from epsm_data import CarbonReference, Catalogue
from epsm_data.domain import BuildingElement as Role

from epsm_lca import AssessmentSettings, assess_renovation
from epsm_lca.boverket import building_factors

SAND_ID = "material:4857e866ed223064"
TAGENE_ID = "EPD-IES-0005222:003"


def restored(building):
    return Building.from_snapshot(
        BuildingSnapshot.from_dict(
            json.loads(json.dumps(building.snapshot().to_dict()))
        )
    )


def office_building(catalogue):
    constructions = catalogue.for_year(
        "office", 1900, state="existing"
    ).construction_set
    # Catalogue ROOF is the conditioned top; Core's physical inventory calls it TOP_FLOOR.
    top = constructions.elements[Role.ROOF]
    constructions = constructions.with_element(
        Role.TOP_FLOOR,
        replace(
            top,
            application=Role.TOP_FLOOR,
            components=tuple(
                replace(component, application=Role.TOP_FLOOR)
                for component in top.components
            ),
        ),
    )
    return Building(preset="illustrative-reference", construction_set=constructions)


@pytest.mark.parametrize("with_catalogue", [False, True])
@pytest.mark.parametrize("installation", ["A5", "A5.1"])
def test_sand_proxy_survives_saved_building_and_keeps_missing_modules(
    with_catalogue, installation
):
    catalogue = Catalogue.load()
    building = restored(office_building(catalogue))
    sand = next(row for row in building.quantities() if row.material_id == SAND_ID)
    assert sand.material.boverket_id is None
    assert sand.material.carbon_reference.identifier == TAGENE_ID
    assert dict(sand.material.carbon_reference.modules) == {
        "A1A3": 0.002,
        "A4": None,
        "A5": None,
    }
    settings = AssessmentSettings.from_building(
        building,
        period_years=30,
        catalogue=catalogue if with_catalogue else None,
        baseline="include",
        include_energy=False,
        material_modules=("A1A3", "A4", installation),
    )
    factors = settings.material_factors[SAND_ID]
    assert set(factors) == {"A1A3"}
    assert factors["A1A3"].value == pytest.approx(0.002)
    assert factors["A1A3"].unit == "kg"
    source = factors["A1A3"].source
    assert TAGENE_ID in source and "proxy" in source.lower()
    assert "environdec.com/library/epd5222" in source
    assert "AR4" not in source
    report = assess_renovation(building, settings)
    assert not report.complete
    assert f"{SAND_ID}: factor A4 is missing" in report.baseline.requirements
    assert (
        f"{SAND_ID}: factor {installation} is missing" in report.baseline.requirements
    )
    contributions = [
        row for row in report.baseline.contributions if row["material_id"] == SAND_ID
    ]
    assert contributions and {row["module"] for row in contributions} == {"A1A3"}
    assert sum(row["gwp_kgco2e"] for row in contributions) == pytest.approx(
        sum(row.mass_kg for row in building.quantities() if row.material_id == SAND_ID)
        * 0.002
    )


def window_building():
    baseline = Building(preset="illustrative-reference")
    reference = CarbonReference(
        identifier="test:window-epd",
        name="Test window declaration",
        url="https://example.com/window-epd",
        method="Declared test GWP method",
        unit="m2",
        modules={"A1A3": 12.0, "A4": None, "A5": None},
    )
    window = replace(
        baseline.construction_set.elements[Role.WINDOW],
        boverket_id=None,
        carbon_reference=reference,
    )
    return restored(
        Building(
            preset="illustrative-reference",
            construction_set=baseline.construction_set.with_element(
                Role.WINDOW, window
            ),
        )
    ), reference


def test_window_reference_survives_inventory_and_snapshot_without_catalogue():
    building, reference = window_building()
    row = next(row for row in building.quantities() if row.kind == "window")
    assert row.material is None and row.mass_kg is None
    refs = dict(row.factor_refs)
    assert refs["carbon_reference_id"] == reference.identifier
    assert json.loads(refs["carbon_reference"]) == reference.to_dict()
    factors = building_factors(building)[row.material_id]
    assert factors == reference.factors()
    assert factors["A1A3"].unit == "m2"


@pytest.mark.parametrize(
    "change, message",
    [
        ({"carbon_reference_id": "another:source"}, "identifiers"),
        ({"carbon_reference": "invalid JSON"}, "valid JSON"),
        ({"boverket_id": "6000000084"}, "Boverket and external"),
    ],
)
def test_saved_external_reference_rejects_conflicting_source_metadata(
    monkeypatch, change, message
):
    building, _ = window_building()
    row = next(row for row in building.quantities() if row.kind == "window")
    row = replace(row, factor_refs=tuple((dict(row.factor_refs) | change).items()))
    monkeypatch.setattr(building, "quantities", lambda: (row,))
    with pytest.raises(ValueError, match=message):
        building_factors(building)


def test_source_id_only_reference_uses_explicitly_supplied_catalogue(monkeypatch):
    catalogue = Catalogue.load()
    building = office_building(catalogue)
    sand = next(row for row in building.quantities() if row.material_id == SAND_ID)
    row = replace(
        sand, material=None, factor_refs=(("carbon_reference_id", TAGENE_ID),)
    )
    monkeypatch.setattr(building, "quantities", lambda: (row,))
    assert SAND_ID not in building_factors(building)
    factors = building_factors(building, catalogue=catalogue)[SAND_ID]
    assert set(factors) == {"A1A3"}
    assert factors["A1A3"].value == pytest.approx(0.002)


def test_saved_reference_cannot_disagree_with_supplied_catalogue(monkeypatch):
    catalogue = Catalogue.load()
    building = office_building(catalogue)
    sand = next(row for row in building.quantities() if row.material_id == SAND_ID)
    changed = replace(sand.material.carbon_reference, method="Different method")
    row = replace(
        sand,
        material=None,
        factor_refs=(
            ("carbon_reference_id", TAGENE_ID),
            ("carbon_reference", json.dumps(changed.to_dict())),
        ),
    )
    monkeypatch.setattr(building, "quantities", lambda: (row,))
    with pytest.raises(ValueError, match="conflicting carbon reference records"):
        building_factors(building, catalogue=catalogue)


def test_attached_reference_cannot_disagree_with_saved_identifier(monkeypatch):
    building = office_building(Catalogue.load())
    sand = next(row for row in building.quantities() if row.material_id == SAND_ID)
    row = replace(sand, factor_refs=(("carbon_reference_id", "another:source"),))
    monkeypatch.setattr(building, "quantities", lambda: (row,))
    with pytest.raises(ValueError, match="Conflicting carbon_reference identifiers"):
        building_factors(building)


def test_same_material_cannot_change_source_record_with_unchanged_factor(monkeypatch):
    building, reference = window_building()
    row = next(row for row in building.quantities() if row.kind == "window")
    different = replace(reference, notes=("Different source record",))
    second = replace(
        row,
        factor_refs=(
            ("carbon_reference_id", reference.identifier),
            ("carbon_reference", json.dumps(different.to_dict())),
        ),
    )
    monkeypatch.setattr(building, "quantities", lambda: (row, second))
    with pytest.raises(ValueError, match="conflicting carbon references"):
        building_factors(building)
