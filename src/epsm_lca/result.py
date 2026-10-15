# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Validated fixed climate totals, including the historical EPSM result type."""

from __future__ import annotations

import json
from dataclasses import dataclass

from ._validation import finite_sum, number, optional_number, same_total, text


@dataclass(frozen=True, init=False, repr=False)
class LCAResult:
    """Fixed assessment totals in kg CO2e; missing totals are never zero.

    Parameters
    ----------
    status : {'complete', 'incomplete', 'failed'}
        Whether the requested calculation has all its required inputs.
    material_gwp_kgco2e, operational_gwp_kgco2e, total_gwp_kgco2e : float or None
        Finite climate impacts; total is absent for incomplete/failed results.
    requirements : iterable of str, optional
        Missing inputs or reason for failure.
    contributions : iterable of mapping, optional
        Known finite material and energy contributions with their sources.
    include_energy : bool, optional
        False makes a complete materials-only total possible without energy.
    assessment : mapping, optional
        Recorded choices and actual factors. Old results leave this unrecorded.

    Notes
    -----
    Construction and loading validate totals. Inspection returns independent
    copies and performs no I/O. Negative sourced impacts remain valid.

    Examples
    --------
    >>> result = LCAResult('complete', 10, 20, 30)
    >>> result.complete
    True
    >>> LCAResult.from_dict(result.to_dict()) == result
    True
    """

    status: str
    material_gwp_kgco2e: float | None
    operational_gwp_kgco2e: float | None
    total_gwp_kgco2e: float | None
    requirements: tuple[str, ...]
    include_energy: bool
    _contributions_json: str
    _assessment_json: str
    _contribution_count: int

    def __init__(
        self,
        status,
        material_gwp_kgco2e,
        operational_gwp_kgco2e,
        total_gwp_kgco2e,
        requirements=(),
        contributions=(),
        *,
        include_energy=True,
        assessment=None,
    ):
        if status not in {"complete", "incomplete", "failed"}:
            raise ValueError("Unknown LCA result status")
        if not isinstance(include_energy, bool):
            raise ValueError("include_energy must be True or False")
        if isinstance(requirements, str):
            raise ValueError("requirements must be a sequence of explanations")
        requirements = tuple(text(r, "requirement") for r in requirements)
        material = optional_number(material_gwp_kgco2e, "material total")
        operational = optional_number(operational_gwp_kgco2e, "energy total")
        total = optional_number(total_gwp_kgco2e, "combined total")
        if not include_energy and operational is not None:
            raise ValueError("Excluded energy must be None")
        if status == "complete":
            if (
                requirements
                or material is None
                or total is None
                or (include_energy and operational is None)
            ):
                raise ValueError(
                    "Complete results require all selected totals and no missing inputs"
                )
            expected = (
                finite_sum((material, operational)) if include_energy else material
            )
            if expected is None or not same_total(total, expected):
                raise ValueError(
                    "Combined total disagrees with material and energy totals"
                )
        elif total is not None or not requirements:
            raise ValueError(
                "Incomplete/failed results need explanations and no combined total"
            )
        if status == "failed" and (material is not None or operational is not None):
            raise ValueError("Failed results cannot claim calculated totals")
        records = tuple(dict(r) for r in contributions)
        for record in records:
            impact = number(record.get("gwp_kgco2e"), "contribution impact")
            if record.get("quantity") is not None:
                number(record["quantity"], "contribution quantity", nonnegative=True)
            if "factor_value" in record:
                factor = number(record["factor_value"], "contribution factor")
                quantity = number(
                    record.get("quantity"), "contribution quantity", nonnegative=True
                )
                if not same_total(impact, quantity * factor):
                    raise ValueError(
                        "Contribution impact disagrees with its quantity and factor"
                    )
            if "source" in record:
                text(record["source"], "contribution source")
            if record.get("gwp_kgco2e") is None:
                raise ValueError("Contribution impact is required")
            optional_number(record["gwp_kgco2e"], "contribution impact")
        for module, claimed in (("material", material), ("energy", operational)):
            selected = [
                r["gwp_kgco2e"]
                for r in records
                if (r.get("module") == "B6") == (module == "energy")
            ]
            if selected and claimed is not None:
                expected = finite_sum(selected)
                if expected is None or not same_total(claimed, expected):
                    raise ValueError(f"{module} total disagrees with its contributions")
        if assessment is not None:
            from .settings import AssessmentSettings

            assessment = AssessmentSettings.from_dict(assessment).to_dict()
            if assessment["include_energy"] != include_energy:
                raise ValueError("Recorded settings disagree with the energy selection")
        for name, value in (
            ("status", status),
            ("material_gwp_kgco2e", material),
            ("operational_gwp_kgco2e", operational),
            ("total_gwp_kgco2e", total),
            ("requirements", requirements),
            ("include_energy", include_energy),
            (
                "_contributions_json",
                json.dumps(records, sort_keys=True, allow_nan=False),
            ),
            (
                "_assessment_json",
                json.dumps(assessment, sort_keys=True, allow_nan=False),
            ),
            ("_contribution_count", len(records)),
        ):
            object.__setattr__(self, name, value)

    @property
    def complete(self) -> bool:
        """Whether every input required by the selected scope was available."""
        return self.status == "complete"

    @property
    def contributions(self) -> tuple[dict, ...]:
        """Independent copies of known per-occurrence and energy impacts."""
        return tuple(json.loads(self._contributions_json))

    @property
    def assessment(self) -> dict | None:
        """Saved choices and factors, or None for unrecorded old evidence."""
        return json.loads(self._assessment_json)

    @property
    def context_status(self) -> str:
        """Distinguish recorded settings from older unrecorded settings."""
        return "unrecorded" if self._assessment_json == "null" else "recorded"

    def summary(self) -> dict:
        """Inspect totals and counts without expanding the saved evidence."""
        return {
            "status": self.status,
            "material_gwp_kgco2e": self.material_gwp_kgco2e,
            "operational_gwp_kgco2e": self.operational_gwp_kgco2e,
            "total_gwp_kgco2e": self.total_gwp_kgco2e,
            "requirement_count": len(self.requirements),
            "context_status": self.context_status,
            "contribution_count": self._contribution_count,
        }

    def __repr__(self) -> str:
        return (
            f"LCAResult(status={self.status!r}, total_kgco2e={self.total_gwp_kgco2e!r}, "
            f"requirements={len(self.requirements)}, contributions={self._contribution_count})"
        )

    __str__ = __repr__

    def to_dict(self) -> dict:
        """Return the versioned portable assessment with independent evidence."""
        return {
            "format": "epsm-lca-result/2",
            "status": self.status,
            "material_gwp_kgco2e": self.material_gwp_kgco2e,
            "operational_gwp_kgco2e": self.operational_gwp_kgco2e,
            "total_gwp_kgco2e": self.total_gwp_kgco2e,
            "requirements": self.requirements,
            "contributions": self.contributions,
            "include_energy": self.include_energy,
            "assessment": self.assessment,
        }

    @classmethod
    def from_dict(cls, value: dict) -> LCAResult:
        """Load current or unversioned 0.1 results; never infer old sources."""
        data = dict(value)
        if data.pop("format", "epsm-lca-result/2") != "epsm-lca-result/2":
            raise ValueError("Unsupported LCA result format")
        try:
            return cls(**data)
        except TypeError as error:
            raise ValueError(f"Invalid LCA result: {error}") from error
