# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Read already loaded Data climate records without guessing absent factors.

Boverket GWP-GHG AR4 values and units are preserved. Whole-window kg factors
use the resource's explicit kg/m2 conversion; no window mass is invented in Core.
A5.1 is waste only. Biogenic carbon and later lifecycle stages are not inferred.
"""

import logging

from epsm_core import Building
from epsm_data import Catalogue, EnvironmentalFactor

from ._validation import number

logger = logging.getLogger(__name__)


def building_factors(building, *, catalogue=None, production="conservative"):
    """Collect known factors over the saved path, including removed products."""
    if not isinstance(building, Building):
        raise ValueError("building must be an epsm_core Building")
    if catalogue is not None and not isinstance(catalogue, Catalogue):
        raise ValueError("catalogue must be an explicitly loaded epsm_data Catalogue")
    if production not in {"typical", "conservative"}:
        raise ValueError("production must be 'typical' or 'conservative'")
    rows = list(building.quantities())
    for stage in building.stages:
        rows.extend(stage.before.quantities())
        rows.extend(stage.after.quantities())
    resources = catalogue.detailed.boverket_resources if catalogue is not None else {}
    factors = {}
    for row in rows:
        refs = dict(row.factor_refs)
        material = row.material
        carbon = material.embodied_carbon if material is not None else None
        resource_id = (
            str(carbon.resource_id) if carbon is not None else refs.get("boverket_id")
        )
        resource = resources.get(resource_id)
        if resource is not None:
            values = {
                v["DataModuleCode"]: v["Value"]
                for item in resource["DataItems"]
                if item["PropertyCode"] == "GWP-GHG AR4"
                and item["PropertyUnitCode"] == "kg CO2 eq./kg"
                for v in item["DataValueItems"]
            }
            if not values:
                raise ValueError(
                    f"Boverket {resource_id}: supported GWP-GHG AR4 kg factors are missing"
                )
            unit, conversion = "kg", 1.0
            if row.kind == "window":
                conversions = [
                    c["Value"]
                    for c in resource.get("Conversions", [])
                    if c["Field"] == "Area" and c["Unit"] == "kg/m²"
                ]
                if len(conversions) != 1:
                    continue  # Unknown basis must remain a missing factor.
                conversion = number(
                    conversions[0], "Boverket window kg/m2", nonnegative=True
                )
                if conversion <= 0:
                    raise ValueError("Boverket window kg/m2 must be positive")
                unit = "m2"
            source = f"Boverket {resource_id}; version {resource['SourceVersion']}; GWP-GHG AR4"
            columns = {
                "A1A3": f"A1-A3 {production.title()}",
                "A4": "A4",
                "A5.1": "A5.1",
            }
            found = {
                module: EnvironmentalFactor(
                    values[column] * conversion,
                    unit,
                    module,
                    f"{source}; {column}; source value {values[column]} kgCO2e/kg; conversion {conversion:g}",
                )
                for module, column in columns.items()
                if column in values
            }
        elif carbon is not None:
            source = f"Boverket {carbon.resource_id}; Data resolved record; GWP-GHG AR4"
            fields = {
                "A1A3": f"A1_A3_{production}",
                "A4": "A4_transport",
                "A5.1": "A5_conservative",
            }
            found = {
                module: EnvironmentalFactor(
                    getattr(carbon, field), "kg", module, f"{source}; {field}"
                )
                for module, field in fields.items()
            }
        else:
            continue
        if row.material_id in factors and factors[row.material_id] != found:
            raise ValueError(
                f"{row.material_id}: conflicting climate values along the renovation path"
            )
        factors[row.material_id] = found
    logger.debug(
        "Selected Data climate factors for %d materials",
        len(factors),
        extra={
            "epsm_event": "lca.factors.selected",
            "epsm_context": {"building_id": building.identifier},
            "epsm_details": {
                "material_count": len(factors),
                "production": production,
                "catalogue_supplied": catalogue is not None,
            },
        },
    )
    return factors
