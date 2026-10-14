"""Immutable, inspectable assessment results."""

from __future__ import annotations

import json
from dataclasses import dataclass


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


