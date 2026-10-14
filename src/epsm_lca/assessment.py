"""Apply explicit factors to material transitions and annual delivered energy.

This is a declared-boundary GWP calculation, not whole-building LCA
certification. The public settings and result names remain re-exported here for
callers that imported from ``epsm_lca.assessment`` directly.
"""

from __future__ import annotations

import math

from .result import LCAResult
from .settings import AssessmentSettings


def _get(item, name, default=None):
    return (
        item.get(name, default)
        if isinstance(item, dict)
        else getattr(item, name, default)
    )


def assess(
    quantities,
    flows,
    energy,
    settings=None,
    *,
    baseline_quantities=None,
    requirements=(),
):
    """Assess current state and cumulative interventions without double counting.

    ``baseline_quantities`` is necessary for include-baseline assessment after
    renovation. Unknown masses, absent factors, unsupported energy boundaries
    and failed energy calculations produce requirements instead of zero impacts.
    """
    missing = list(requirements)
    if settings is None:
        return LCAResult(
            "incomplete",
            None,
            None,
            None,
            tuple(missing + ["Assessment settings are required"]),
        )
    # Roundtrip freezes inputs and also validates mappings changed after construction.
    settings = AssessmentSettings.from_dict(settings.to_dict())
    flows = tuple(flows)
    installations, removals = [], []
    if settings.baseline == "include":
        if flows and baseline_quantities is None:
            missing.append("Original baseline inventory is required")
        else:
            installations.extend(
                quantities if baseline_quantities is None else baseline_quantities
            )
    for flow in flows:
        installations.extend(_get(flow, "installed", ()))
        removals.extend(_get(flow, "removed", ()))
    material_total, contributions = 0.0, []
    material_missing = bool(missing)
    for action, rows in (("installed", installations), ("removed", removals)):
        modules = [
            m
            for m in settings.material_modules
            if m.startswith("A" if action == "installed" else "C")
        ]
        for row in rows:
            material_id = _get(row, "material_id")
            for module in modules:
                factor = settings.material_factors.get(material_id, {}).get(module)
                if factor is None:
                    missing.append(f"{material_id}: factor {module} is missing")
                    material_missing = True
                    continue
                attribute = {
                    "kg": "mass_kg",
                    "m2": "area_m2",
                    "m3": "volume_m3",
                    "item": "count",
                }[factor.unit]
                amount = _get(row, attribute)
                if amount is None or not math.isfinite(amount) or amount < 0:
                    missing.append(
                        f"{material_id}: known nonnegative {attribute} is required"
                    )
                    material_missing = True
                    continue
                impact = amount * factor.value
                if not math.isfinite(impact):
                    missing.append(
                        f"{material_id}: calculated {module} impact must be finite"
                    )
                    material_missing = True
                    continue
                next_total = material_total + impact
                if not math.isfinite(next_total):
                    missing.append("Calculated material impact total must be finite")
                    material_missing = True
                else:
                    material_total = next_total
                contributions.append(
                    dict(
                        occurrence_id=_get(row, "occurrence_id"),
                        material_id=material_id,
                        action=action,
                        module=module,
                        quantity=amount,
                        unit=factor.unit,
                        gwp_kgco2e=impact,
                        source=factor.source,
                    )
                )
    operational_total = 0.0
    operational_missing = False
    if (
        not _get(energy, "complete", False)
        or not _get(energy, "annual", False)
        or _get(energy, "boundary") != settings.energy_boundary
    ):
        missing.append(
            "Complete annual delivered energy for the selected boundary is required"
        )
        operational_missing = True
    carriers = _get(energy, "delivered_by_carrier", {})
    if not carriers:
        missing.append("Delivered energy by carrier is missing")
        operational_missing = True
    for carrier, annual_kwh in carriers.items():
        factor = settings.carrier_factors.get(carrier)
        if (
            factor is None
            or annual_kwh is None
            or not math.isfinite(annual_kwh)
            or annual_kwh < 0
        ):
            missing.append(
                f"{carrier}: valid delivered energy and operational factor are required"
            )
            operational_missing = True
            continue
        period_kwh = annual_kwh * settings.period_years
        impact = period_kwh * factor.value
        if not math.isfinite(period_kwh) or not math.isfinite(impact):
            missing.append(
                f"{carrier}: calculated period energy and operational impact must be finite"
            )
            operational_missing = True
            continue
        next_total = operational_total + impact
        if not math.isfinite(next_total):
            missing.append("Calculated operational impact total must be finite")
            operational_missing = True
        else:
            operational_total = next_total
        contributions.append(
            dict(
                carrier=carrier,
                module="B6",
                quantity=period_kwh,
                unit="kWh",
                gwp_kgco2e=impact,
                source=factor.source,
            )
        )
    material = None if material_missing else material_total
    operational = None if operational_missing else operational_total
    total = None if missing else material_total + operational_total
    if total is not None and not math.isfinite(total):
        missing.append("Calculated combined impact total must be finite")
        total = None
    return LCAResult(
        "incomplete" if missing else "complete",
        material,
        operational,
        total,
        tuple(dict.fromkeys(missing)),
        tuple(contributions),
    )
