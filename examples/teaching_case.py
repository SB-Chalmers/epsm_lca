# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Small declared inputs shared by the notebooks; no assessment code is copied.

All factors and annual energy in the teaching case are invented. Catalogue
examples use Data's explicitly loaded Boverket records instead.
"""

from dataclasses import replace

from epsm_core import Building, FacadeSpec, Footprint, GlazingSpec
from epsm_data import (
    ConstructionOperation,
    EnvironmentalFactor,
    RenovationMeasure,
    reference_construction_set,
)
from epsm_data.domain import BuildingElement as Role

from epsm_lca import AnnualEnergy, AssessmentSettings


def make_baseline(construction_set=None):
    constructions = construction_set or reference_construction_set()
    window = constructions.elements[Role.WINDOW]
    facade = FacadeSpec(
        default_wwr=0.2,
        glazing=GlazingSpec(
            u_value_w_m2k=window.u_value,
            solar_heat_gain_coefficient=window.shgc,
            visible_transmittance=window.vt,
        ),
    )
    return Building.from_footprint(
        Footprint.rectangle(5, 5),
        storeys=1,
        storey_height_m=2.5,
        construction_set=constructions,
        facade=facade,
        identifier="teaching-building",
    )


def renovation_options(baseline):
    window = replace(
        baseline.construction_set.elements[Role.WINDOW],
        name="teaching.replacement-window",
        u_value=1.0,
    )
    windows = RenovationMeasure(
        "replace_windows",
        "envelope",
        "Replace windows",
        "Teaching choice",
        "window",
        operations=(
            ConstructionOperation("replace_element", Role.WINDOW, element=window),
        ),
    )
    original = baseline.construction_set.elements[Role.EXT_WALL].components[0]
    slot = reference_construction_set().elements[Role.EXT_WALL].components[0].layers[0]
    layer = replace(
        slot.layer,
        name="Extra insulation",
        thickness=0.1,
        materials=tuple(replace(part, thickness=0.1) for part in slot.layer.materials),
    )
    component = replace(
        original,
        name="Extra wall insulation",
        layers=(replace(slot, layer=layer, position=0),),
    )
    insulation = RenovationMeasure(
        "insulate_walls",
        "envelope",
        "Insulate walls",
        "Add 100 mm teaching insulation",
        "wall",
        operations=(
            ConstructionOperation(
                "add_component", Role.EXT_WALL, component=component, position=0
            ),
        ),
    )
    return windows, insulation


def teaching_settings(building, *, include_energy=True):
    factors = {}
    for flow in building.material_flows:
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
            values.update({m: 0.5 for m in ("C1", "C2", "C3", "C4")})
            factors[row.material_id] = {
                m: EnvironmentalFactor(v, unit, m, "SYNTHETIC teaching factor")
                for m, v in values.items()
            }
    return AssessmentSettings(
        30,
        material_factors=factors,
        include_energy=include_energy,
        carrier_factors={
            "electricity": EnvironmentalFactor(
                0.1, "kWh", "B6", "SYNTHETIC electricity factor"
            )
        },
    )


def supplied_energy(*buildings, annual_kwh):
    if len(buildings) != len(annual_kwh):
        raise ValueError("Supply one annual kWh value per building state")
    return {
        step: AnnualEnergy.for_building(
            building,
            delivered_by_carrier={"electricity": amount},
            source="ASSUMED annual teaching energy; no simulation",
        )
        for step, (building, amount) in enumerate(zip(buildings, annual_kwh))
    }


def show_table(report):
    print(
        "Step | Materials this step | Materials so far | Energy | Total | Savings (kg CO2e)"
    )
    for row in report.table():
        values = [
            row[key]
            for key in (
                "material_kgco2e",
                "material_so_far_kgco2e",
                "energy_kgco2e",
                "total_kgco2e",
                "savings_kgco2e",
            )
        ]
        print(
            row["step"],
            " | ",
            " | ".join(
                "missing/excluded" if v is None else f"{v:,.2f}" for v in values
            ),
        )
        for requirement in row["requirements"]:
            print("  Needed:", requirement)
