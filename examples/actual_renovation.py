# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Actual annual energy runs followed by material and operational LCA.

Uses Data's Existing/Advanced construction products and real Boverket values.
Energy uses the chosen actual engine and bundled Gothenburg weather. Operational
climate factors and window-removal factors are explicitly declared assumptions;
these results demonstrate software execution, not measured building accuracy.
"""

import argparse
import csv
import json
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from uuid import uuid4

from epsm_core import Building as CoreBuilding
from epsm_data import (
    Catalogue,
    ConstructionOperation,
    EnvironmentalFactor,
    RenovationMeasure,
)
from epsm_data.domain import BuildingElement as Role

from epsm_lca import AnnualEnergy, AssessmentSettings, assess_renovation


def run_case(*, output, engine="epsm_rc", weather_path=None, energyplus_exe=None):
    """Run baseline and two real renovation states, preserving every artifact."""
    from epsm import Building, Weather

    catalogue = Catalogue.load()
    existing = catalogue.for_year(
        "multi_family", 1960, state="existing"
    ).construction_set
    advanced = catalogue.for_year(
        "multi_family", 1960, state="advanced"
    ).construction_set
    baseline = CoreBuilding(
        preset="illustrative-reference",
        identifier="catalogue-renovation-example",
        construction_set=existing,
    )
    windows = RenovationMeasure(
        "advanced_windows",
        "envelope",
        "Replace windows",
        "Data Advanced window product",
        "window",
        operations=(
            ConstructionOperation(
                "replace_element", Role.WINDOW, element=advanced.elements[Role.WINDOW]
            ),
        ),
    )
    insulation_component = advanced.elements[Role.EXT_WALL].components[0]
    if not all(
        part.material.embodied_carbon is not None
        for slot in insulation_component.layers
        for part in slot.layer.materials
    ):
        raise ValueError(
            "Example insulation requires Data's sourced material carbon values"
        )
    insulation = RenovationMeasure(
        "advanced_insulation",
        "envelope",
        "Insulate walls",
        "Data Advanced outer insulation component",
        "wall",
        operations=(
            ConstructionOperation(
                "add_component",
                Role.EXT_WALL,
                component=insulation_component,
                position=0,
            ),
        ),
    )
    one = baseline.renovate(windows)
    two = one.renovate(insulation)
    removal_factors = {
        row.material_id: {
            module: EnvironmentalFactor(
                0.5,
                "m2",
                module,
                "ASSUMED example window removal/treatment: 0.5 kgCO2e/m2 for each C stage; not Boverket data",
            )
            for module in ("C1", "C2", "C3", "C4")
        }
        for row in one.material_flows[-1].removed
    }
    settings = AssessmentSettings.from_building(
        two,
        period_years=30,
        catalogue=catalogue,
        production="conservative",
        material_factors=removal_factors,
        carrier_factors={
            "district_heat": EnvironmentalFactor(
                0.05,
                "kWh",
                "B6",
                "ASSUMED example district heating factor; replace with a sourced provider value",
            ),
            "electricity": EnvironmentalFactor(
                0.1,
                "kWh",
                "B6",
                "ASSUMED example electricity factor; replace with a sourced supply value",
            ),
        },
    )
    weather = Weather.from_epw(
        weather_path or files("epsm_rc") / "data/epw/goteborg.epw"
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = Path(output).resolve() / f"run-{stamp}-{uuid4().hex[:8]}"
    directory.mkdir(parents=True, exist_ok=False)
    annual, evaluations = {}, []
    for step, core_building in enumerate((baseline, one, two)):
        model = Building.from_snapshot(core_building.snapshot())
        model.restore_lineage(core_building.lineage_to_dict())
        evaluation = model.simulate(
            engine=engine,
            weather=weather,
            directory=directory / f"step-{step}",
            **(
                {"energyplus": str(energyplus_exe)}
                if engine == "energyplus" and energyplus_exe is not None
                else {}
            ),
        )
        if not evaluation.energy.complete or not evaluation.energy.annual:
            raise ValueError(
                f"Step {step} lacks accepted complete annual delivered energy: {evaluation.energy.requirements}"
            )
        annual[step] = AnnualEnergy.for_building(
            core_building,
            delivered_by_carrier=evaluation.energy.delivered_by_carrier,
            boundary=evaluation.energy.boundary,
            source=f"Actual {engine} annual run; evaluation {evaluation.id}; weather SHA256 {weather.sha256}",
        )
        evaluations.append(
            dict(
                step=step,
                evaluation_id=evaluation.id,
                engine=engine,
                annual_delivered_kwh=evaluation.energy.annual_delivered_energy_kwh,
                delivered_by_carrier=evaluation.energy.delivered_by_carrier,
                diagnostics=evaluation.energy.diagnostics,
            )
        )
    report = assess_renovation(two, settings, energy=annual)
    if not report.complete:
        raise ValueError(
            f"End-to-end assessment incomplete: {[s.requirements for s in report.stages]}"
        )
    report_path = report.save(directory / "renovation.json")
    with (directory / "comparison.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(report.table()[0]))
        writer.writeheader()
        writer.writerows(report.table())
    (directory / "energy_runs.json").write_text(
        json.dumps(evaluations, indent=2, allow_nan=False) + "\n"
    )
    return {
        "report": report,
        "report_path": report_path,
        "directory": directory,
        "energy_runs": evaluations,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--engine", choices=("epsm_rc", "energyplus"), default="epsm_rc"
    )
    parser.add_argument("--weather", type=Path)
    parser.add_argument("--energyplus-exe", type=Path)
    parser.add_argument(
        "--output", type=Path, default=Path("outputs/actual-renovation")
    )
    parser.add_argument("--plot", action="store_true")
    args = parser.parse_args()
    result = run_case(
        output=args.output,
        engine=args.engine,
        weather_path=args.weather,
        energyplus_exe=args.energyplus_exe,
    )
    if args.plot:
        result["report"].plot().savefig(result["directory"] / "climate-impact.svg")
    from teaching_case import show_table

    show_table(result["report"])
    for row in result["energy_runs"]:
        print(
            f"Step {row['step']}: {row['annual_delivered_kwh']:,.2f} kWh/year ({row['engine']})"
        )
    print("Saved actual results:", result["directory"])


if __name__ == "__main__":
    main()
