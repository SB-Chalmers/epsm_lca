# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Read already loaded Data climate records without guessing absent factors.

Boverket and external declarations retain their own methods and quantity units.
Whole-window kg factors use the resource's explicit kg/m2 conversion; no window
mass is invented in Core. Missing modules stay absent, including A5.1 waste.
"""

import json
import logging

from epsm_core import Building
from epsm_data import CarbonReference, Catalogue, EnvironmentalFactor
from epsm_data.contract import BOVERKET_REF, CARBON_REFERENCE, CARBON_REFERENCE_ID

from ._validation import number

logger = logging.getLogger(__name__)


def _external_reference(material, refs, catalogue):
    """Resolve portable references and reject contradictory saved source records."""
    references = []
    attached = getattr(material, "carbon_reference", None)
    if attached is not None:
        if not isinstance(attached, CarbonReference):
            raise ValueError("material carbon_reference must be a CarbonReference")
        references.append(attached)
    saved = refs.get(CARBON_REFERENCE)
    if saved is not None:
        if isinstance(saved, str):
            try:
                saved = json.loads(saved)
            except (TypeError, ValueError) as error:
                raise ValueError("Saved carbon_reference must contain valid JSON") from error
        try:
            references.append(CarbonReference.from_dict(saved))
        except (TypeError, ValueError) as error:
            raise ValueError(f"Invalid saved carbon_reference: {error}") from error
    identifier = refs.get(CARBON_REFERENCE_ID)
    if identifier is not None and (
        not isinstance(identifier, str) or not identifier.strip()
    ):
        raise ValueError("carbon_reference_id must be a nonempty string")
    identities = {reference.identifier for reference in references}
    if identifier is not None:
        identities.add(identifier)
    if len(identities) > 1:
        raise ValueError("Conflicting carbon_reference identifiers")
    if identities and catalogue is not None:
        resource = catalogue.carbon_references.get(next(iter(identities)))
        if resource is not None:
            references.append(resource)
    if identities and (
        getattr(material, "boverket_id", None) is not None
        or getattr(material, "embodied_carbon", None) is not None
        or refs.get(BOVERKET_REF) is not None
    ):
        raise ValueError("Conflicting Boverket and external carbon references")
    if not references:
        return None
    reference = references[0]
    if any(item.to_dict() != reference.to_dict() for item in references[1:]):
        raise ValueError(f"{reference.identifier}: conflicting carbon reference records")
    return reference


def building_factors(building, *, catalogue=None, production="conservative", renovations=None):
    """Collect known factors over the saved path, including removed products.

    ``renovations`` is a loaded epsm_data RenovationCatalogue; its Boverket
    records cover installed products such as ductwork and glazing units.
    Products without one carry their CarbonReference in the inventory row.
    """
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
    resources = dict(catalogue.boverket_resources) if catalogue is not None else {}
    if renovations is not None:
        resources.update(renovations.boverket_resources)
    factors = {}
    external_records = {}
    for row in rows:
        refs = dict(row.factor_refs)
        material = row.material
        carbon = material.embodied_carbon if material is not None else None
        reference = _external_reference(material, refs, catalogue)
        resource_id = (
            str(carbon.resource_id) if carbon is not None else refs.get(BOVERKET_REF)
        )
        resource = resources.get(resource_id)
        if reference is not None:
            record = reference.to_dict()
            if row.material_id in external_records and external_records[row.material_id] != record:
                raise ValueError(
                    f"{row.material_id}: conflicting carbon references along the renovation path"
                )
            external_records[row.material_id] = record
            found = reference.factors()
        elif resource is not None:
            values = {
                v["DataModuleCode"]: v["Value"]
                for item in resource["DataItems"]
                if item["PropertyCode"] == "GWP-GHG AR4"
                and item["PropertyUnitCode"] == "kg CO2 eq./kg"
                for v in item["DataValueItems"]
            }
            per_area = {
                v["DataModuleCode"]: v["Value"]
                for item in resource["DataItems"]
                if item["PropertyCode"] == "GWP-GHG AR4"
                and item["PropertyUnitCode"] == "kg CO2 eq./m²"
                for v in item["DataValueItems"]
            }
            if not values and not (per_area and row.area_m2 is not None):
                raise ValueError(
                    f"Boverket {resource_id}: supported GWP-GHG AR4 kg factors are missing"
                )
            unit, conversion = "kg", 1.0
            if not values:
                # Area-declared records, such as PV modules, apply to installed area.
                values, unit = per_area, "m2"
            elif row.kind == "window":
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
                    f"{source}; {column}; source value {values[column]} "
                    f"kgCO2e/{'m2' if unit == 'm2' and row.kind != 'window' else 'kg'}; "
                    f"conversion {conversion:g}",
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
