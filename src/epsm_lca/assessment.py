# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Apply explicit climate factors; Core owns quantities and Data owns factors.

Calculations use loaded values only. No simulation, data lookup or file access
occurs here. Settings/results remain exported for historical direct imports.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping

from epsm_lca._logging import context_logger
from epsm_lca._logging import operation as logged_operation

from ._validation import finite_sum, number, text
from .profiles import FactorProfile
from .result import LCAResult
from .settings import AssessmentSettings

logger = context_logger(__name__)
_FIELDS = ("mass_kg", "area_m2", "volume_m3", "count")


def _get(item, name, default=None):
    return (
        item.get(name, default)
        if isinstance(item, Mapping)
        else getattr(item, name, default)
    )


def quantity_record(row):
    """Detach occurrence identity and all known bases, including removed quantities."""
    identity = text(_get(row, "material_id"), "material_id")
    result = {
        key: _get(row, key)
        for key in (
            "occurrence_id",
            "material_name",
            "element_id",
            "component_id",
            "layer_id",
            "role",
            "kind",
        )
    }
    result["material_id"] = identity
    for field in _FIELDS:
        value = _get(row, field)
        result[field] = (
            None if value is None else number(value, field, nonnegative=True)
        )
    result["factor_refs"] = dict(_get(row, "factor_refs", {}) or {})
    return result


def flow_rows(flow):
    """Missing flow fields are invalid, never an empty recorded intervention."""
    result = []
    absent = object()
    for name in ("installed", "removed"):
        rows = _get(flow, name, absent)
        if (
            rows is absent
            or isinstance(rows, (str, bytes, Mapping))
            or not isinstance(rows, Iterable)
        ):
            raise ValueError(f"Renovation flow requires an explicit {name} sequence")
        result.append(tuple(rows))
    return tuple(result)


def material_impact(
    installed, removed, settings, *, stage_id=None, step=None, requirements=()
):
    """Count each occurrence once per selected module, retaining finite evidence."""
    missing, contributions, values = list(requirements), [], []
    for action, rows in (("installed", installed), ("removed", removed)):
        modules = tuple(
            m
            for m in settings.material_modules
            if m.startswith("A" if action == "installed" else "C")
        )
        for row in rows:
            record = quantity_record(row)
            identity = record["material_id"]
            for module in modules:
                factor = settings.material_factors.get(identity, {}).get(module)
                if factor is None:
                    missing.append(f"{identity}: factor {module} is missing")
                    continue
                field = {
                    "kg": "mass_kg",
                    "m2": "area_m2",
                    "m3": "volume_m3",
                    "item": "count",
                }[factor.unit]
                amount = record[field]
                if amount is None:
                    missing.append(f"{identity}: known nonnegative {field} is required")
                    continue
                impact = amount * factor.value
                if not math.isfinite(impact):
                    missing.append(
                        f"{identity}: calculated {module} impact must be finite"
                    )
                    continue
                values.append(impact)
                contributions.append(
                    dict(
                        occurrence_id=record["occurrence_id"],
                        material_id=identity,
                        action=action,
                        module=module,
                        quantity=amount,
                        unit=factor.unit,
                        factor_value=factor.value,
                        gwp_kgco2e=impact,
                        source=factor.source,
                        stage_id=stage_id,
                        step=step,
                    )
                )
    total = finite_sum(values)
    if total is None:
        missing.append("Calculated material impact total must be finite")
    return (
        (None if missing else total),
        tuple(dict.fromkeys(missing)),
        tuple(contributions),
    )


def factor_mean(factor):
    return factor.mean if isinstance(factor, FactorProfile) else factor.value


def annual_factor_product(factor, annual_kwh, hourly_kwh=None, *, flat=False):
    """Annual delivered energy times a constant or time-varying per-kWh factor.

    Returns ``(value, basis)``; value is None, with the reason as basis, when a
    varying factor meets annual-only energy and the flat approximation is off.
    """
    if not isinstance(factor, FactorProfile):
        return annual_kwh * factor.value, "constant"
    if hourly_kwh is not None:
        return factor.apply(hourly_kwh), f"hourly energy x {factor.kind} profile"
    if not factor.varies:
        return annual_kwh * factor.values[0], "constant"
    if flat:
        return annual_kwh * factor.mean, f"flat-demand approximation of a {factor.kind} profile"
    return None, (f"hourly delivered energy is needed for its {factor.kind} factor "
                  "(or allow the flat-demand approximation)")


def energy_impact(energy, settings):
    """Assess one annual building state; never accumulate ancestors' operating years."""
    if not settings.include_energy:
        return None, (), ()
    missing, contributions, values = [], [], []
    if (
        not _get(energy, "complete", False)
        or not _get(energy, "annual", False)
        or _get(energy, "boundary") != settings.energy_boundary
    ):
        missing.append(
            "Complete annual delivered energy for the selected boundary is required"
        )
    carriers = _get(energy, "delivered_by_carrier", {})
    if carriers is None:
        carriers = {}
    if not isinstance(carriers, Mapping):
        raise ValueError("Delivered energy must map carrier names to annual kWh")
    if not carriers:
        missing.append("Delivered energy by carrier is missing")
    hourly = _get(energy, "hourly_by_carrier", None) or {}
    for carrier, value in carriers.items():
        text(carrier, "energy carrier")
        factor = settings.carrier_factors.get(carrier)
        if value is None:
            missing.append(f"{carrier}: annual delivered energy is missing")
            continue
        annual_kwh = number(
            value, f"{carrier}: annual delivered energy", nonnegative=True
        )
        if factor is None:
            missing.append(f"{carrier}: operational factor is missing")
            continue
        annual, basis = annual_factor_product(
            factor, annual_kwh, hourly.get(carrier),
            flat=settings.flat_profile_for_annual_energy)
        if annual is None:
            missing.append(f"{carrier}: {basis}")
            continue
        period_kwh = annual_kwh * settings.period_years
        impact = annual * settings.period_years
        if not math.isfinite(period_kwh) or not math.isfinite(impact):
            missing.append(
                f"{carrier}: calculated period energy and operational impact must be finite"
            )
            continue
        values.append(impact)
        contributions.append(
            dict(
                carrier=carrier,
                module="B6",
                quantity=period_kwh,
                unit="kWh",
                factor_value=annual / annual_kwh if annual_kwh else factor_mean(factor),
                gwp_kgco2e=impact,
                source=factor.source,
                factor_basis=basis,
            )
        )
    total = finite_sum(values)
    if total is None:
        missing.append("Calculated operational impact total must be finite")
    return (
        (None if missing else total),
        tuple(dict.fromkeys(missing)),
        tuple(contributions),
    )


@logged_operation(
    "lca.assessment",
    result_details=lambda result: {
        "status": result.status,
        "requirement_count": len(result.requirements),
        "contribution_count": result.summary()["contribution_count"],
    },
)
def assess(
    quantities,
    flows,
    energy,
    settings=None,
    *,
    baseline_quantities=None,
    requirements=(),
) -> LCAResult:
    """Assess a reached state and all its interventions (the existing EPSM route).

    Parameters
    ----------
    quantities : iterable
        Current physical occurrences, with kg, m2, m3 or item quantities.
    flows : iterable
        Ordered interventions with explicit installed and removed sequences.
    energy : object or mapping
        Complete annual delivered energy by carrier, boundary and annual flag.
    settings : AssessmentSettings, optional
        Declared period and factors; absent settings produce an incomplete result.
    baseline_quantities : iterable, optional
        Original inventory, required for include-baseline after renovation.
    requirements : iterable of str, optional
        Unresolved physical history passed by Core/EPSM.

    Returns
    -------
    LCAResult
        Fixed totals, sourced contributions and missing-input explanations.

    Notes
    -----
    New building-based use is taught through assess_renovation. No input is
    changed and no energy calculation is started.

    Examples
    --------
    >>> result = assess((), (), None)
    >>> result.status
    'incomplete'
    """
    if settings is None:
        return LCAResult(
            "incomplete",
            None,
            None,
            None,
            (*requirements, "Assessment settings are required"),
        )
    if not isinstance(settings, AssessmentSettings):
        raise ValueError("settings must be AssessmentSettings")
    missing, contributions, values = list(requirements), [], []
    flows = tuple(flows)
    if settings.baseline == "include":
        if flows and baseline_quantities is None:
            missing.append("Original baseline inventory is required")
        else:
            total, gaps, records = material_impact(
                quantities if baseline_quantities is None else baseline_quantities,
                (),
                settings,
                step=0,
            )
            missing.extend(gaps)
            contributions.extend(records)
            if total is not None:
                values.append(total)
    for flow in flows:
        installed, removed = flow_rows(flow)
        total, gaps, records = material_impact(
            installed,
            removed,
            settings,
            stage_id=_get(flow, "stage_id"),
            step=_get(flow, "order"),
        )
        missing.extend(gaps)
        contributions.extend(records)
        if total is not None:
            values.append(total)
    material = finite_sum(values)
    if material is None:
        missing.append("Calculated material impact total must be finite")
    material = None if missing else material
    operational, energy_missing, records = energy_impact(energy, settings)
    missing.extend(energy_missing)
    contributions.extend(records)
    total = None
    if not missing:
        total = (
            finite_sum((material, operational)) if settings.include_energy else material
        )
        if total is None:
            missing.append("Calculated combined impact total must be finite")
    return LCAResult(
        "incomplete" if missing else "complete",
        material,
        operational,
        total,
        tuple(dict.fromkeys(missing)),
        tuple(contributions),
        include_energy=settings.include_energy,
        assessment=settings.to_dict(),
    )
