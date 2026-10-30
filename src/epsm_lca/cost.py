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

from ._timeline import discounted_payback, present_value, repay, years
from ._validation import finite_sum
from .assessment import annual_factor_product, period_factor_product
from .energy import AnnualEnergy
from .indicators import payback_years
from .profiles import FactorProfile, FactorTrajectory
from .replacement import ServiceLife, life_for, surviving_installations

CATEGORIES = ("material", "labour", "subcontractor", "overhead")


@dataclass(frozen=True)
class CostSettings:
    """Cost estimates by candidate ID and energy prices by carrier, in one currency.

    ``carrier_prices`` are ``FactorProfile`` records in ``<currency>/kWh``: constant,
    weekday/weekend 24-hour, monthly or 8760 hourly. ``period_years`` turns annual
    operating cost into an undiscounted period total. Varying prices need hourly
    delivered energy unless ``flat_profile_for_annual_energy`` is set.

    A price can also be a ``FactorTrajectory`` with one profile per year of
    ``period_years``; ``price_escalation`` must then be 0, since the trajectory
    states each year's price.

    With ``include_replacements``, each priced measure is bought again whenever
    its ``service_lives`` entry (by candidate or measure ID) ends within
    ``period_years``, at the same stage price, discounted to its year.

    ``discount_rate`` and ``price_escalation`` are real annual rates (0.03 is 3 %)
    used for present values, global cost and discounted payback. Investments are
    made at the start of year 1; operating cost in year ``t`` is multiplied by
    ``(1 + price_escalation)**t / (1 + discount_rate)**t``. Both are 0 by default,
    which keeps present values equal to the undiscounted period totals.

    Examples
    --------
    >>> settings = CostSettings({}, currency="SEK")
    >>> settings.currency
    'SEK'
    """

    estimates: Mapping[str, CostEstimate]
    currency: str = "SEK"
    carrier_prices: Mapping[str, FactorProfile | FactorTrajectory] = field(
        default_factory=dict
    )
    period_years: float | None = None
    export_prices: Mapping[str, FactorProfile | FactorTrajectory] = field(
        default_factory=dict
    )
    flat_profile_for_annual_energy: bool = False
    discount_rate: float = 0.0
    price_escalation: float = 0.0
    include_replacements: bool = False
    service_lives: Mapping[str, ServiceLife] = field(default_factory=dict)

    def __post_init__(self):
        if not isinstance(self.include_replacements, bool):
            raise ValueError("include_replacements must be True or False")
        if any(not isinstance(v, ServiceLife) for v in self.service_lives.values()):
            raise ValueError("service_lives must map IDs to ServiceLife records")
        object.__setattr__(
            self, "service_lives", MappingProxyType(dict(self.service_lives))
        )
        for name in ("discount_rate", "price_escalation"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= -1
            ):
                raise ValueError(f"{name} must be a finite rate above -1")
            object.__setattr__(self, name, float(value))
        for name in ("carrier_prices", "export_prices"):
            prices = dict(getattr(self, name))
            for carrier, price in prices.items():
                if (
                    not isinstance(price, (FactorProfile, FactorTrajectory))
                    or price.unit != f"{self.currency}/kWh"
                ):
                    raise ValueError(
                        f"{carrier}: prices must be FactorProfile records in "
                        f"{self.currency}/kWh"
                    )
                if isinstance(price, FactorTrajectory):
                    if self.period_years is None or not price.covers(self.period_years):
                        raise ValueError(
                            f"{carrier}: a price trajectory must cover period_years"
                        )
                    if self.price_escalation:
                        raise ValueError(
                            f"{carrier}: a price trajectory already states each "
                            "year's price; set price_escalation to 0"
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
        """Collect the estimates and service lives of a loaded RenovationCatalogue."""
        lives = {
            c.candidate_id: ServiceLife(
                c.service_life_years,
                "epsm_data renovation catalogue service_life_years",
            )
            for c in renovations
            if c.service_life_years is not None
        }
        choices["service_lives"] = {**lives, **choices.get("service_lives", {})}
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
    present_value: float | None = None
    yearly: tuple[float, ...] | None = None

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
            "present_value": self.present_value,
            "yearly": None if self.yearly is None else list(self.yearly),
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
class ReplacementCost:
    """Measures of one state bought again within the period, and what is left.

    ``lines`` are the purchases by year. ``residual_lines`` give each measure's
    remaining life at the end of the period, valued as the share of its last
    purchase still unused (EN 15459 straight-line residual value), and
    ``residual_value`` is their present value.
    """

    step: int
    currency: str
    lines: tuple[dict, ...]
    total: float | None
    present_value: float | None
    requirements: tuple[str, ...] = ()
    residual_lines: tuple[dict, ...] = ()
    residual_value: float | None = None

    @property
    def status(self):
        return "incomplete" if self.requirements else "complete"

    def to_dict(self):
        return {
            "step": self.step,
            "currency": self.currency,
            "status": self.status,
            "total": self.total,
            "present_value": self.present_value,
            "lines": [dict(line) for line in self.lines],
            "residual_lines": [dict(line) for line in self.residual_lines],
            "residual_value": self.residual_value,
            "requirements": list(self.requirements),
        }


@dataclass(frozen=True)
class RenovationCostResult:
    """Costs of every recorded renovation stage of one building."""

    stages: tuple[StageCost, ...]
    currency: str
    producer: Mapping[str, str] = field(default_factory=dict)
    operating: tuple[OperatingCost, ...] = ()
    discount_rate: float = 0.0
    price_escalation: float = 0.0
    period_years: float | None = None
    replacements: tuple[ReplacementCost, ...] = ()

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
        parts = (*self.stages, *self.operating, *self.replacements)
        return (
            "complete" if all(p.status == "complete" for p in parts) else "incomplete"
        )

    def investment_so_far(self, step):
        """Stage costs through ``step``; None when any of them is incomplete."""
        totals = [s.total for s in self.stages if s.step <= step]
        return None if None in totals else finite_sum(totals) or 0.0

    def simple_payback_years(self, step):
        """Undiscounted years until operating savings repay stages 1..``step``.

        The saving is the baseline's annual operating cost minus this state's.
        None when either cost is unknown or the state does not save money.

        Examples
        --------
        >>> RenovationCostResult((), "SEK").simple_payback_years(1) is None
        True
        """
        yearly = self._yearly_savings(step, 0.0)
        if yearly is not None:
            return repay(self.investment_so_far(step), yearly)
        return payback_years(self.investment_so_far(step), self.annual_saving(step))

    def annual_saving(self, step):
        """Baseline annual operating cost minus this state's; None if unknown."""
        annual = {o.step: o.annual for o in self.operating}
        if annual.get(0) is None or annual.get(step) is None:
            return None
        return annual[0] - annual[step]

    def _yearly_savings(self, step, rate):
        """Discounted yearly savings when a price trajectory was used, else None."""
        states = {o.step: o for o in self.operating}
        base, state = states.get(0), states.get(step)
        if (
            base is None
            or state is None
            or (base.yearly is None and state.yearly is None)
            or base.annual is None
            or state.annual is None
        ):
            return None
        shares = list(years(self.period_years))

        def series(o):
            return o.yearly or [o.annual * share for _, share in shares]

        return [
            (b - a) / (1 + rate) ** year
            for (year, _), b, a in zip(shares, series(base), series(state))
        ]

    def global_cost(self, step):
        """Stage costs through ``step`` plus this state's operating present value.

        Step 0 is the baseline's operating present value alone. Counted
        replacements add their present value and subtract the residual value
        of the work still in use at the end of the period. None when an
        investment, the state's operating cost or its replacements are
        incomplete.

        Examples
        --------
        >>> RenovationCostResult((), "SEK").global_cost(0) is None
        True
        """
        investment = 0.0 if step == 0 else self.investment_so_far(step)
        running = {o.step: o.present_value for o in self.operating}.get(step)
        if investment is None or running is None:
            return None
        if self.replacements:
            replaced = {r.step: r for r in self.replacements}.get(step)
            if (
                replaced is None
                or replaced.present_value is None
                or replaced.residual_value is None
            ):
                return None
            running += replaced.present_value - replaced.residual_value
        return investment + running

    def discounted_payback_years(self, step):
        """Years until discounted operating savings repay stages 1..``step``.

        With price trajectories, savings are followed year by year and must
        repay within the period.
        """
        yearly = self._yearly_savings(step, self.discount_rate)
        if yearly is not None:
            return repay(self.investment_so_far(step), yearly)
        return discounted_payback(
            self.investment_so_far(step),
            self.annual_saving(step),
            rate=self.discount_rate,
            escalation=self.price_escalation,
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
            "simple_payback_years_by_step": {
                s.step: self.simple_payback_years(s.step) for s in self.stages
            },
            "discount_rate": self.discount_rate,
            "price_escalation": self.price_escalation,
            "global_cost_by_step": {
                o.step: self.global_cost(o.step) for o in self.operating
            },
            "discounted_payback_years_by_step": {
                s.step: self.discounted_payback_years(s.step) for s in self.stages
            },
            "replacement_cost_by_step": {r.step: r.total for r in self.replacements},
            "residual_value_by_step": {
                r.step: r.residual_value for r in self.replacements
            },
        }

    def to_dict(self):
        return {
            **self.summary(),
            "producer": dict(self.producer),
            "stages": [s.to_dict() for s in self.stages],
            "operating": [o.to_dict() for o in self.operating],
            "replacements": [r.to_dict() for r in self.replacements],
        }


def replacement_cost(building, settings, stage_costs):
    """Replacement purchases of every state's surviving priced measures.

    Each surviving measure also gets a residual line: the share of its last
    purchase (the original at year 0 or the last replacement) whose life runs
    past the period, discounted from the period's end. Work whose life ends
    exactly with the period leaves nothing.
    """
    stages = tuple(building.stages)
    period = settings.period_years or 0
    results = []
    for step in range(len(stages) + 1):
        lines, residual, missing = [], [], []
        if settings.period_years is None:
            missing.append("period_years is needed to count replacements")
        surviving = surviving_installations(stages[:step])
        for stage, cost in zip(stages[:step], stage_costs):
            recorded = dict(getattr(stage, "installed_by", ()) or ())
            candidates = {q.measure_id: q.candidate_id for q in stage.quantities}
            for measure_id, amount in cost.by_measure.items():
                own = {k for k, m in recorded.items() if m == measure_id}
                if own and not own & surviving.keys():
                    continue  # a later stage removed this work
                life = life_for(
                    settings.service_lives, measure_id, candidates.get(measure_id)
                )
                if life is None:
                    missing.append(f"{measure_id}: service life is missing")
                    continue
                if cost.total is None:
                    missing.append(
                        f"{measure_id}: stage {cost.step} cost is incomplete; "
                        "its replacement cost is unknown"
                    )
                replaced = life.replacement_years(period)
                for year in replaced:
                    lines.append(
                        {
                            "measure_id": measure_id,
                            "stage": cost.step,
                            "year": year,
                            "cost": amount,
                            "present_value": amount
                            / (1 + settings.discount_rate) ** year,
                            "service_life_years": life.years,
                            "service_life_source": life.source,
                        }
                    )
                last = replaced[-1] if replaced else 0.0
                remaining = max(last + life.years - period, 0.0)
                left = amount * remaining / life.years
                residual.append(
                    {
                        "measure_id": measure_id,
                        "stage": cost.step,
                        "last_purchase_year": last,
                        "remaining_life_years": remaining,
                        "residual": left,
                        "present_value": left / (1 + settings.discount_rate) ** period,
                        "service_life_years": life.years,
                        "service_life_source": life.source,
                    }
                )
        missing = tuple(dict.fromkeys(missing))
        results.append(
            ReplacementCost(
                step,
                settings.currency,
                tuple(lines),
                None if missing else finite_sum(x["cost"] for x in lines) or 0.0,
                None
                if missing
                else finite_sum(x["present_value"] for x in lines) or 0.0,
                missing,
                tuple(residual),
                None
                if missing
                else finite_sum(x["present_value"] for x in residual) or 0.0,
            )
        )
    return tuple(results)


def _priced(price, annual_kwh, hourly_kwh, settings):
    """Annual cost and, for a trajectory, each year's cost over the period."""
    if not isinstance(price, FactorTrajectory):
        annual, basis = annual_factor_product(
            price, annual_kwh, hourly_kwh, flat=settings.flat_profile_for_annual_energy
        )
        return annual, None, basis
    total, yearly, basis = period_factor_product(
        price,
        annual_kwh,
        hourly_kwh,
        settings.period_years,
        flat=settings.flat_profile_for_annual_energy,
    )
    return (None if total is None else total / settings.period_years), yearly, basis


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
        lines, requirements, by_carrier, yearly_by_carrier = [], [], {}, {}
        for carrier, annual_kwh in supplied.delivered_by_carrier.items():
            price = settings.carrier_prices.get(carrier)
            if price is None:
                requirements.append(f"{carrier}: energy price is missing")
                continue
            annual, yearly, basis = _priced(
                price, annual_kwh, supplied.hourly_by_carrier.get(carrier), settings
            )
            if annual is None:
                requirements.append(f"{carrier}: {basis}")
                continue
            by_carrier[carrier] = annual
            if yearly is not None:
                yearly_by_carrier[carrier] = yearly
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
            revenue, yearly, basis = (
                (None, None, "export price is missing")
                if price is None
                else _priced(
                    price,
                    annual_kwh,
                    supplied.exported_hourly_by_carrier.get(carrier),
                    settings,
                )
            )
            if revenue is None:
                requirements.append(f"{carrier} export: {basis}")
                exports_priced = False
                continue
            key = f"{carrier}_export"
            by_carrier[key] = -revenue
            if yearly is not None:
                yearly_by_carrier[key] = tuple(-v for v in yearly)
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
        yearly = None
        if yearly_by_carrier and period is not None:
            shares = list(years(settings.period_years))
            yearly = tuple(
                math.fsum(
                    yearly_by_carrier[c][i] if c in yearly_by_carrier else a * share
                    for c, a in by_carrier.items()
                )
                for i, (_, share) in enumerate(shares)
            )
            period = math.fsum(yearly)
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
                None
                if period is None
                else present_value(
                    annual,
                    settings.period_years,
                    rate=settings.discount_rate,
                    escalation=settings.price_escalation,
                )
                if yearly is None
                else math.fsum(
                    v / (1 + settings.discount_rate) ** year
                    for (year, _), v in zip(years(settings.period_years), yearly)
                ),
                yearly,
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
        hourly prices; present values use the settings' discount rate.

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
        settings.discount_rate,
        settings.price_escalation,
        settings.period_years,
        replacement_cost(building, settings, stages)
        if settings.include_replacements
        else (),
    )
