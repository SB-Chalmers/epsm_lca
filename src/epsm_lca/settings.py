"""Assessment boundaries and sourced material and carrier factors."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field

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


