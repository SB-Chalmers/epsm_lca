"""One example per renovation measure type: geometry quantities, carbon and cost.

A 1965 multi-family archetype (mf_se02, Existing) with a conditioned basement and
self-draught (S) ventilation receives each catalogue measure type in turn, each
as its own single-stage scenario from the same baseline:

1. Data supplies the candidate (what is installed) and, optionally, cost rates.
2. Core applies it through ``Building.renovate`` and derives quantity drivers
   (element and window areas, airflow, terminals, risers, ducts) from geometry.
3. LCA assesses A1-A3, A4 and A5.1 carbon from Boverket and prices the stage.

Licensed price data is never bundled. Pass a cost overlay built with
``epsm_data/tools/wikells_cost_overlay.py``; without it costs report as missing.

Run: python examples/renovation_measures.py [--costs OVERLAY.json] [--out DIR]
"""

import argparse
import json
from pathlib import Path

from epsm_core import Building, Footprint, GeometrySpec
from epsm_core.measures import apply_candidates
from epsm_data import Catalogue, RenovationCatalogue

from epsm_lca import (
    AssessmentSettings,
    CostSettings,
    assess_renovation,
    assess_renovation_cost,
)

# (candidates, basement) — the ceiling measure needs an unheated basement.
EXAMPLES = (
    ("insulate_wall.stone_wool_200", "heated"),
    ("insulate_wall.interior_wood_fibre_70", "heated"),
    ("insulate_roof.attic_loose_stone_wool_300", "heated"),
    ("insulate_roof.attic_cellulose_300", "heated"),
    (("insulate_basement.wall_stone_wool_40_gypsum", "insulate_basement.floor_eps_45_screed_50"),
     "heated"),
    ("insulate_basement.ceiling_stone_wool_100", "unheated"),
    ("replace_window.u_0_90", "heated"),
    ("upgrade_window.insulating_glass_inner_sash", "heated"),
    ("upgrade_ventilation.ftx_080", "heated"),
    ("upgrade_ventilation.f", "heated"),
    ("install_pv.roof_south_15", "heated"),
    ("reduce_dhw.low_flow_fittings", "heated"),
)
MODULES = ("A1A3", "A4", "A5.1")


def baseline(library, basement="heated"):
    """mf_se02 Existing on a 30 m x 12 m, four-storey block over a basement."""
    archetype = library.get("mf_se02", state="existing")
    building = Building(
        preset="illustrative-reference", identifier="mf_se02_example",
        construction_set=archetype.construction_set,
        geometry=GeometrySpec.from_footprint(Footprint.rectangle(30, 12), storeys=4,
                                             storey_height_m=2.8, basement_depth_m=2.4,
                                             basement_conditioned=basement == "heated"))
    # Self-draught, as typical for the era; the reference preset installs FTX.
    building.hvac = building.hvac.with_changes(airflow=building.hvac.airflow.model_dump() | {
        "topology": "S", "mechanical_vent_l_s_m2": 0.0, "natural_exchange_ach": 0.5,
        "sensible_recovery_effectiveness": 0.0})
    return building


def run(costs=None):
    library = Catalogue.load()
    renovations = RenovationCatalogue.load(library, costs=costs)
    bases = {kind: baseline(library, kind) for kind in ("heated", "unheated")}
    cost_settings = CostSettings.from_catalogue(renovations)
    report = []
    for example, basement in EXAMPLES:
        base = bases[basement]
        candidates = [renovations.get(i) for i in ((example,) if isinstance(example, str) else example)]
        renovated = apply_candidates(base, *candidates)
        settings = AssessmentSettings.from_building(
            renovated, period_years=50, catalogue=library, renovations=renovations,
            material_modules=MODULES, include_energy=False)
        carbon = assess_renovation(renovated, settings).stages[0]
        cost = assess_renovation_cost(renovated, cost_settings).stages[0]
        stage = renovated.stages[0]
        by_module = {}
        for line in carbon.contributions:
            by_module[line["module"]] = by_module.get(line["module"], 0.0) + line["gwp_kgco2e"]
        report.append({
            "measure_type": candidates[0].measure_type,
            "candidates": [c.candidate_id for c in candidates],
            "names": [c.name for c in candidates],
            "drivers": {q.measure_id: dict(q.drivers) for q in stage.quantities},
            "installed_rows": len(stage.material_flows.installed),
            "removed_rows": len(stage.material_flows.removed),
            "measure_ids": list(stage.measure_ids),
            "infiltration_ach": [base.hvac.airflow.envelope_infiltration_ach,
                                 renovated.hvac.airflow.envelope_infiltration_ach],
            "dhw_kwh_m2_year": [base.operation.dhw_kwh_m2_year,
                                renovated.operation.dhw_kwh_m2_year],
            "pv_kwp": sum(p.dc_capacity_kw for p in renovated.hvac.renewables.pv_systems)
            - sum(p.dc_capacity_kw for p in base.hvac.renewables.pv_systems),
            "installations": [i.to_dict() for i in renovated.installations],
            "carbon": {"status": carbon.status, "kgco2e": carbon.material_kgco2e,
                       "by_module": by_module, "requirements": list(carbon.requirements)},
            "cost": cost.to_dict(),
        })
    return report


def markdown(report):
    rows = ["| Candidates | Quantities | Other effect | Carbon A1–A5.1 (kg CO2e) "
            "| Cost (SEK excl. VAT) | Gaps |",
            "|---|---|---|---:|---:|---|"]
    for item in report:
        drivers = {k: v for d in item["drivers"].values() for k, v in d.items()
                   if k not in {"building", "renovated_envelope_area_m2", "envelope_share",
                                "infiltration_reduction"} and v
                   and not (k == "floor_area_m2" and item["measure_type"] != "reduce_dhw")}
        effects = []
        for label, (before, after), fmt in (
                ("infiltration ach", item["infiltration_ach"], ".3f"),
                ("DHW kWh/m2", item["dhw_kwh_m2_year"], ".1f")):
            if after != before:
                effects.append(f"{label} {before:{fmt}} → {after:{fmt}}")
        if item["pv_kwp"]:
            effects.append(f"PV {item['pv_kwp']:,.1f} kWp")
        quantities = ", ".join(f"{k} {v:,.1f}" for k, v in drivers.items())
        carbon = item["carbon"]["kgco2e"]
        cost = item["cost"]
        gaps = [*item["carbon"]["requirements"], *cost["requirements"]]
        rows.append("| {} | {} | {} | {} | {} | {} |".format(
            " + ".join(item["measure_ids"]), quantities, "; ".join(effects) or "–",
            f"{carbon:,.0f}" if carbon is not None
            else f"A1–A3 {item['carbon']['by_module'].get('A1A3', 0):,.0f} (partial)",
            f"{cost['total']:,.0f}" if cost["total"] is not None
            else f"≥ {cost['priced_subtotal']:,.0f} (partial)",
            "; ".join(gaps) or "–"))
    return "\n".join(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--costs", help="Private cost overlay JSON")
    parser.add_argument("--out", default="renovation_measures_results")
    args = parser.parse_args()
    report = run(args.costs)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "renovation_measures.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    (out / "renovation_measures.md").write_text(markdown(report) + "\n")
    print(markdown(report))


if __name__ == "__main__":
    main()
