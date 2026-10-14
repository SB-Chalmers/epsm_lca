"""Apply sourced factors to occurrences and delivered energy.

Ordered interventions have no inferred dates. Each reached state supplies one
annual operational result, repeated over the explicitly selected assessment
period. Production/installation factors apply to actual installations; selected
end-of-life factors apply to actual removals. Future replacements are not
invented from the reference period. This is a declared-boundary GWP calculation,
not a claim of compliance with a whole-building certification method.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from typing import Mapping

from epsm_data import EnvironmentalFactor


@dataclass(frozen=True)
class AssessmentSettings:
    """Explicit boundary, period and sourced factors; no implicit factor lookup.

    ``baseline='retained'`` assesses interventions only; ``include`` also counts
    the original inventory. Material factor keys are material IDs then modules.
    Carrier factors are in kgCO2e/kWh for B6. Sources remain in saved settings.
    """

    period_years: float
    energy_boundary: str
    baseline: str
    material_modules: tuple[str, ...]
    material_factors: Mapping[str, Mapping[str, EnvironmentalFactor]] = field(
        default_factory=dict
    )
    carrier_factors: Mapping[str, EnvironmentalFactor] = field(default_factory=dict)

    def __post_init__(self):
        if not math.isfinite(self.period_years) or self.period_years <= 0:
            raise ValueError("period_years must be finite and positive")
        if not self.energy_boundary or self.baseline not in {"retained", "include"}:
            raise ValueError(
                "Supply an energy boundary and baseline='retained' or 'include'"
            )
        supported = {"A1A3", "A4", "A5", "C1", "C2", "C3", "C4"}
        if not self.material_modules or set(self.material_modules) - supported:
            raise ValueError(
                "Select material modules from A1A3, A4, A5, C1, C2, C3, C4"
            )
        if len(set(self.material_modules)) != len(self.material_modules):
            raise ValueError("Material modules must be unique")
        for factors in self.material_factors.values():
            for module, factor in factors.items():
                if module != factor.module or factor.unit == "kWh":
                    raise ValueError(
                        "Material factor module/basis does not match its mapping"
                    )
        for factor in self.carrier_factors.values():
            if factor.module != "B6" or factor.unit != "kWh":
                raise ValueError("Operational factors require module B6 and unit kWh")

    def summary(self):
        """Return bounded assessment choices and factor counts without I/O."""
        return {
            "period_years": self.period_years,
            "energy_boundary": self.energy_boundary,
            "baseline": self.baseline,
            "material_modules": self.material_modules,
            "material_factor_count": sum(
                len(factors) for factors in self.material_factors.values()
            ),
            "carrier_factor_count": len(self.carrier_factors),
        }

    def __repr__(self):
        summary = self.summary()
        return (
            f"AssessmentSettings(period_years={self.period_years!r}, "
            f"energy_boundary={self.energy_boundary[:64]!r}, baseline={self.baseline!r}, "
            f"material_factors={summary['material_factor_count']}, "
            f"carrier_factors={summary['carrier_factor_count']})"
        )

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        data = dict(value)
        data["material_modules"] = tuple(data["material_modules"])
        data["material_factors"] = {
            key: {
                module: EnvironmentalFactor(**factor)
                for module, factor in factors.items()
            }
            for key, factors in data.get("material_factors", {}).items()
        }
        data["carrier_factors"] = {
            key: EnvironmentalFactor(**factor)
            for key, factor in data.get("carrier_factors", {}).items()
        }
        return cls(**data)


@dataclass(frozen=True, init=False, repr=False)
class LCAResult:
    """Fixed assessment output; missing totals mean incomplete assessment.

    Contribution inspection and serialization return independent copies. Editing
    either copy never changes this saved result. ``summary()`` and ``repr`` keep
    routine inspection compact; ``contributions`` retains the complete evidence.
    """

    status: str
    material_gwp_kgco2e: float | None
    operational_gwp_kgco2e: float | None
    total_gwp_kgco2e: float | None
    requirements: tuple[str, ...]
    _contributions_json: str
    _contribution_count: int

    def __init__(
        self,
        status,
        material_gwp_kgco2e,
        operational_gwp_kgco2e,
        total_gwp_kgco2e,
        requirements=(),
        contributions=(),
    ):
        records = tuple(contributions)
        for name, value in (
            ("status", status),
            ("material_gwp_kgco2e", material_gwp_kgco2e),
            ("operational_gwp_kgco2e", operational_gwp_kgco2e),
            ("total_gwp_kgco2e", total_gwp_kgco2e),
            ("requirements", tuple(requirements)),
            (
                "_contributions_json",
                json.dumps(records, sort_keys=True, allow_nan=False),
            ),
            ("_contribution_count", len(records)),
        ):
            object.__setattr__(self, name, value)

    @property
    def complete(self):
        return self.status == "complete"

    @property
    def contributions(self):
        """Independent copies of the per-occurrence and operational evidence."""
        return tuple(json.loads(self._contributions_json))

    def summary(self):
        """Return totals and record counts without expanding contributions."""
        return {
            "status": self.status,
            "material_gwp_kgco2e": self.material_gwp_kgco2e,
            "operational_gwp_kgco2e": self.operational_gwp_kgco2e,
            "total_gwp_kgco2e": self.total_gwp_kgco2e,
            "requirement_count": len(self.requirements),
            "contribution_count": self._contribution_count,
        }

    def __repr__(self):
        return (
            f"LCAResult(status={self.status[:32]!r}, total_gwp_kgco2e={self.total_gwp_kgco2e!r}, "
            f"requirements={len(self.requirements)}, contributions={self._contribution_count})"
        )

    def to_dict(self):
        return {
            "status": self.status,
            "material_gwp_kgco2e": self.material_gwp_kgco2e,
            "operational_gwp_kgco2e": self.operational_gwp_kgco2e,
            "total_gwp_kgco2e": self.total_gwp_kgco2e,
            "requirements": self.requirements,
            "contributions": self.contributions,
        }

    @classmethod
    def from_dict(cls, value):
        return cls(**value)


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
                material_total += impact
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
        impact = annual_kwh * settings.period_years * factor.value
        operational_total += impact
        contributions.append(
            dict(
                carrier=carrier,
                module="B6",
                quantity=annual_kwh * settings.period_years,
                unit="kWh",
                gwp_kgco2e=impact,
                source=factor.source,
            )
        )
    material = None if material_missing else material_total
    operational = None if operational_missing else operational_total
    return LCAResult(
        "incomplete" if missing else "complete",
        material,
        operational,
        None if missing else material_total + operational_total,
        tuple(dict.fromkeys(missing)),
        tuple(contributions),
    )
