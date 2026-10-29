# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Price recorded renovation stages; Core owns quantities and Data owns rates.

Each catalogue measure in a Core renovation stage carries geometric quantity
drivers. A Data cost estimate gives rates per driver, split into material,
labour, subcontractor and overhead. Totals stay ``None`` whenever a rate, a
driver or part of a measure's scope is missing; the priced subtotal is always
reported. No currency conversion or price indexation is applied.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from epsm_core import Building
from epsm_data import MEASURE_TYPES, CostEstimate

from ._validation import finite_sum
from .assessment import annual_factor_product
from .energy import AnnualEnergy
from .profiles import FactorProfile

CATEGORIES = ("material", "labour", "subcontractor", "overhead")


@dataclass(frozen=True)
class CostSettings:
    """Cost estimates by candidate ID and energy prices by carrier, in one currency.

    ``carrier_prices`` are ``FactorProfile`` records in ``<currency>/kWh``: constant,
    weekday/weekend 24-hour, monthly or 8760 hourly. ``period_years`` turns annual
    operating cost into an undiscounted period total. Varying prices need hourly
    delivered energy unless ``flat_profile_for_annual_energy`` is set.

    Examples
    --------
    >>> settings = CostSettings({}, currency="SEK")
    >>> settings.currency
    'SEK'
    """

    estimates: Mapping[str, CostEstimate]
    currency: str = "SEK"
    carrier_prices: Mapping[str, FactorProfile] = field(default_factory=dict)
    period_years: float | None = None
    export_prices: Mapping[str, FactorProfile] = field(default_factory=dict)
    flat_profile_for_annual_energy: bool = False

    def __post_init__(self):
        for name in ("carrier_prices", "export_prices"):
            prices = dict(getattr(self, name))
            for carrier, price in prices.items():
                if (
                    not isinstance(price, FactorProfile)
                    or price.unit != f"{self.currency}/kWh"
                ):
                    raise ValueError(
                        f"{carrier}: prices must be FactorProfile records in "
                        f"{self.currency}/kWh"
                    )
            object.__setattr__(self, name, MappingProxyType(prices))
        if self.period_years is not None and not (
            isinstance(self.period_years, (int, float))
            and 0 < self.period_years < math.inf
        ):
            raise ValueError("period_years must be finite and positive")
        estimates = dict(self.estimates)
        for candidate_id, estimate in estimates.items():
            if not isinstance(estimate, CostEstimate):
                raise ValueError(
                    f"{candidate_id}: estimates must be epsm_data CostEstimate records"
                )
            if estimate.currency != self.currency:
                raise ValueError(
                    f"{candidate_id}: {estimate.currency} differs from {self.currency}; "
                    "convert prices before assessment"
                )
        object.__setattr__(self, "estimates", MappingProxyType(estimates))

    @classmethod
    def from_catalogue(cls, renovations, *, currency="SEK", **choices):
        """Collect the estimates already attached to a loaded RenovationCatalogue."""
        return cls(
            {c.candidate_id: c.cost for c in renovations if c.cost is not None},
            currency=currency,
            **choices,
        )


@dataclass(frozen=True)
class OperatingCost:
    """Delivered-energy cost of one building state (0 = baseline, n = after stage n)."""

    step: int
    state_id: str
    currency: str
    annual_by_carrier: Mapping[str, float]
    annual: float | None
    period: float | None
    lines: tuple[dict, ...] = ()
    requirements: tuple[str, ...] = ()

    @property
    def status(self):
        return "incomplete" if self.requirements else "complete"

    def to_dict(self):
        return {
            "step": self.step,
            "state_id": self.state_id,
            "currency": self.currency,
            "status": self.status,
            "annual": self.annual,
            "period": self.period,
            "annual_by_carrier": dict(self.annual_by_carrier),
            "lines": [dict(line) for line in self.lines],
            "requirements": list(self.requirements),
        }


@dataclass(frozen=True)
class StageCost:
    """Cost of one renovation stage, with every priced line and every gap."""

    step: int
    stage_id: str
    measure_ids: tuple[str, ...]
    currency: str
    lines: tuple[dict, ...]
    by_category: Mapping[str, float]
    by_measure: Mapping[str, float]
    labour_hours: float
    priced_subtotal: float
    total: float | None
    price_years: tuple[int, ...]
    requirements: tuple[str, ...] = ()

    @property
    def status(self):
        return "incomplete" if self.requirements else "complete"

    def to_dict(self):
        return {
            "step": self.step,
            "stage_id": self.stage_id,
            "measure_ids": list(self.measure_ids),
            "currency": self.currency,
            "status": self.status,
            "total": self.total,
            "priced_subtotal": self.priced_subtotal,
            "by_category": dict(self.by_category),
            "by_measure": dict(self.by_measure),
            "labour_hours": self.labour_hours,
            "price_years": list(self.price_years),
            "requirements": list(self.requirements),
            "lines": [dict(line) for line in self.lines],
        }


@dataclass(frozen=True)
class RenovationCostResult:
    """Costs of every recorded renovation stage of one building."""

    stages: tuple[StageCost, ...]
    currency: str
    producer: Mapping[str, str] = field(default_factory=dict)
    operating: tuple[OperatingCost, ...] = ()

    @property
    def priced_subtotal(self):
        return finite_sum(s.priced_subtotal for s in self.stages) or 0.0

    @property
    def total(self):
        if not self.stages or any(s.total is None for s in self.stages):
            return None
        return finite_sum(s.total for s in self.stages)

    @property
    def status(self):
        parts = (*self.stages, *self.operating)
        return (
            "complete" if all(p.status == "complete" for p in parts) else "incomplete"
        )

    def summary(self):
        return {
            "currency": self.currency,
            "status": self.status,
            "total": self.total,
            "priced_subtotal": self.priced_subtotal,
            "step_count": len(self.stages),
            "incomplete_steps": [s.step for s in self.stages if s.status != "complete"],
            "annual_operating_by_step": {o.step: o.annual for o in self.operating},
        }

    def to_dict(self):
        return {
            **self.summary(),
            "producer": dict(self.producer),
            "stages": [s.to_dict() for s in self.stages],
            "operating": [o.to_dict() for o in self.operating],
        }


def operating_cost(building, settings, energy):
    """Price supplied delivered energy for every state that has it."""
    stages = tuple(building.stages)
    snapshot = building.snapshot()
    states = [stages[0].before if stages else snapshot]
    states.extend(
        stages[i + 1].before if i + 1 < len(stages) else snapshot
        for i in range(len(stages))
    )
    results = []
    for step, supplied in sorted(energy.items()):
        if (
            isinstance(step, bool)
            or not isinstance(step, int)
            or not 0 <= step < len(states)
        ):
            raise ValueError(
                "Energy step must identify baseline 0 or an existing renovation step"
            )
        if not isinstance(supplied, AnnualEnergy):
            raise ValueError(
                "Supply AnnualEnergy records; use AnnualEnergy.for_building"
            )
        if supplied.state_id != states[step].sha256:
            raise ValueError(
                f"Energy for step {step} describes a different building state"
            )
        lines, requirements, by_carrier = [], [], {}
        for carrier, annual_kwh in supplied.delivered_by_carrier.items():
            price = settings.carrier_prices.get(carrier)
            if price is None:
                requirements.append(f"{carrier}: energy price is missing")
                continue
            annual, basis = annual_factor_product(
                price,
                annual_kwh,
                supplied.hourly_by_carrier.get(carrier),
                flat=settings.flat_profile_for_annual_energy,
            )
            if annual is None:
                requirements.append(f"{carrier}: {basis}")
                continue
            by_carrier[carrier] = annual
            lines.append(
                {
                    "carrier": carrier,
                    "annual_kwh": annual_kwh,
                    "annual_cost": annual,
                    "average_price": annual / annual_kwh if annual_kwh else price.mean,
                    "price_kind": price.kind,
                    "basis": basis,
                    "source": price.source,
                }
            )
        exports_priced = True
        for carrier, annual_kwh in supplied.exported_by_carrier.items():
            if not annual_kwh:
                continue
            price = settings.export_prices.get(carrier)
            revenue, basis = (
                (None, "export price is missing")
                if price is None
                else annual_factor_product(
                    price,
                    annual_kwh,
                    supplied.exported_hourly_by_carrier.get(carrier),
                    flat=settings.flat_profile_for_annual_energy,
                )
            )
            if revenue is None:
                requirements.append(f"{carrier} export: {basis}")
                exports_priced = False
                continue
            key = f"{carrier}_export"
            by_carrier[key] = -revenue
            lines.append(
                {
                    "carrier": key,
                    "annual_kwh": annual_kwh,
                    "annual_cost": -revenue,
                    "average_price": revenue / annual_kwh,
                    "price_kind": price.kind,
                    "basis": basis,
                    "source": price.source,
                }
            )
        if settings.period_years is None:
            requirements.append("period_years is needed for a period operating cost")
        complete = exports_priced and all(
            c in by_carrier for c in supplied.delivered_by_carrier
        )
        annual = finite_sum(by_carrier.values()) if complete else None
        period = (
            annual * settings.period_years
            if annual is not None and settings.period_years is not None
            else None
        )
        results.append(
            OperatingCost(
                step,
                supplied.state_id,
                settings.currency,
                MappingProxyType(by_carrier),
                annual,
                period,
                tuple(lines),
                tuple(dict.fromkeys(requirements)),
            )
        )
    return tuple(results)


def assess_renovation_cost(
    building: Building,
    settings: CostSettings,
    *,
    energy: Mapping[int, AnnualEnergy] | None = None,
) -> RenovationCostResult:
    """Price every renovation stage recorded on a Core building, and supplied energy use.

    Parameters
    ----------
    building : epsm_core.Building
        The renovated building; its stages carry the measures' quantity drivers.
    settings : CostSettings
        Cost estimates by candidate ID and energy prices by carrier.
    energy : mapping of int to AnnualEnergy, optional
        Delivered energy per state, as for ``assess_renovation``: 0 is the
        baseline and n the state after stage n. Hourly values are weighted by
        hourly prices; no discounting is applied.

    Returns
    -------
    RenovationCostResult
        Per-stage lines, category and measure subtotals, labour hours, gaps, and
        the operating cost of each state with supplied energy.

    Examples
    --------
    >>> from epsm_core import Building
    >>> result = assess_renovation_cost(Building(preset="illustrative-reference"),
    ...                                 CostSettings({}))
    >>> result.stages
    ()
    """
    if not isinstance(building, Building):
        raise ValueError("building must be an epsm_core Building")
    if not isinstance(settings, CostSettings):
        raise ValueError("settings must be CostSettings")
    stages = []
    for step, stage in enumerate(building.stages, 1):
        lines, requirements, years = [], [], set()
        quantified = {q.measure_id: q for q in stage.quantities}
        for measure_id in stage.measure_ids:
            if measure_id not in quantified:
                requirements.append(
                    f"{measure_id}: not a catalogue measure; no quantities to price"
                )
        for quantities in stage.quantities:
            estimate = settings.estimates.get(quantities.candidate_id)
            kind = MEASURE_TYPES.get(quantities.measure_type)
            if estimate is None and kind is not None and kind.priced_with_host:
                continue  # e.g. sealing: its work is inside the host measure's rates
            if estimate is None:
                requirements.append(
                    f"{quantities.measure_id}: no cost estimate for {quantities.candidate_id}"
                )
                continue
            years.add(estimate.price_year)
            if estimate.coverage == "partial":
                requirements.append(
                    f"{quantities.measure_id}: unpriced scope: "
                    + ", ".join(estimate.missing_scope)
                )
            drivers = dict(quantities.drivers)
            for item in estimate.items:
                amount = drivers.get(item.driver)
                if amount is None:
                    requirements.append(
                        f"{quantities.measure_id}: quantity driver {item.driver} is missing"
                    )
                    continue
                value = amount * item.rate
                if not math.isfinite(value):
                    requirements.append(f"{quantities.measure_id}: cost must be finite")
                    continue
                lines.append(
                    {
                        "measure_id": quantities.measure_id,
                        "candidate_id": quantities.candidate_id,
                        "measure_type": quantities.measure_type,
                        "category": item.category,
                        "description": item.description,
                        "driver": item.driver,
                        "quantity": amount,
                        "rate": item.rate,
                        "cost": value,
                        "labour_hours": None
                        if item.labour_hours is None
                        else item.labour_hours * amount,
                        "price_year": estimate.price_year,
                        "source": item.source,
                    }
                )
        if len(years) > 1:
            requirements.append(
                "Estimates use different price years; no indexation is applied"
            )
        by_category = {
            c: finite_sum(line["cost"] for line in lines if line["category"] == c)
            or 0.0
            for c in CATEGORIES
        }
        by_measure = {}
        for line in lines:
            by_measure[line["measure_id"]] = (
                by_measure.get(line["measure_id"], 0.0) + line["cost"]
            )
        subtotal = finite_sum(line["cost"] for line in lines) or 0.0
        requirements = tuple(dict.fromkeys(requirements))
        stages.append(
            StageCost(
                step,
                stage.stage_id,
                stage.measure_ids,
                settings.currency,
                tuple(lines),
                MappingProxyType(by_category),
                MappingProxyType(by_measure),
                finite_sum(
                    line["labour_hours"]
                    for line in lines
                    if line["labour_hours"] is not None
                )
                or 0.0,
                subtotal,
                None if requirements else subtotal,
                tuple(sorted(years)),
                requirements,
            )
        )
    from ._version import __version__

    return RenovationCostResult(
        tuple(stages),
        settings.currency,
        {"epsm_lca": __version__, "method": "catalogue-unit-rates/1"},
        operating_cost(building, settings, energy or {}),
    )
