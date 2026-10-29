# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Per-kWh carbon or price factors that vary over a year, on a fixed hourly calendar.

A profile is constant, a weekday/weekend pair of 24-hour schedules, 12 monthly
values or 8760 hourly values. Every form expands to the same 8760-hour year so
that it can be applied to hourly delivered energy. Hour 0 is 00:00-01:00 on
1 January in local standard time; Monday to Friday are weekdays and public
holidays are not distinguished. Leap years are not supported.
"""

from __future__ import annotations

import calendar
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import cached_property

from ._validation import text

HOURS = 8760
KINDS = {"constant": 1, "weekday_weekend": 48, "monthly": 12, "hourly": HOURS}


@dataclass(frozen=True)
class FactorProfile:
    """A sourced factor per delivered kWh, constant or varying through the year.

    Parameters
    ----------
    kind : {"constant", "weekday_weekend", "monthly", "hourly"}
        Form of ``values``: 1 value, 24 weekday then 24 weekend hours, 12 months
        or 8760 hours.
    values : sequence of float
        Finite factors in ``unit``. Negative values are allowed (for example spot
        prices); use them only when the source states them.
    unit : str
        Per-kWh unit, such as "kgCO2e/kWh" for B6 or "SEK/kWh" for prices.
    source : str
        Where the values come from.
    year : int, optional
        Non-leap calendar year used to place weekdays and months; 2025 by default.

    Examples
    --------
    >>> grid = FactorProfile.monthly([0.05] * 6 + [0.03] * 6, "kgCO2e/kWh", "example")
    >>> round(grid.apply([1.0] * 8760), 1)
    349.7
    """

    kind: str
    values: tuple[float, ...]
    unit: str
    source: str
    year: int = 2025

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"Profile kind must be one of {', '.join(KINDS)}")
        values = tuple(float(v) for v in self.values)
        if len(values) != KINDS[self.kind]:
            raise ValueError(f"A {self.kind} profile needs {KINDS[self.kind]} values")
        if any(not math.isfinite(v) for v in values):
            raise ValueError("Profile values must be finite")
        object.__setattr__(self, "values", values)
        text(self.source, "profile source")
        if not isinstance(self.unit, str) or not self.unit.endswith("/kWh"):
            raise ValueError(
                "Profile units are per delivered kWh, for example 'SEK/kWh'"
            )
        if (
            isinstance(self.year, bool)
            or not isinstance(self.year, int)
            or calendar.isleap(self.year)
        ):
            raise ValueError("Profiles use a non-leap calendar year of 8760 hours")

    @classmethod
    def constant(cls, value, unit, source):
        return cls("constant", (value,), unit, source)

    @classmethod
    def weekday_weekend(cls, weekday, weekend, unit, source, *, year=2025):
        if len(weekday) != 24 or len(weekend) != 24:
            raise ValueError("Weekday and weekend schedules need 24 hourly values each")
        return cls("weekday_weekend", (*weekday, *weekend), unit, source, year)

    @classmethod
    def monthly(cls, values, unit, source, *, year=2025):
        return cls("monthly", tuple(values), unit, source, year)

    @classmethod
    def hourly(cls, values, unit, source, *, year=2025):
        return cls("hourly", tuple(values), unit, source, year)

    @property
    def varies(self):
        return self.kind != "constant"

    @cached_property
    def hourly_values(self) -> tuple[float, ...]:
        """The profile on every hour of its calendar year."""
        if self.kind == "hourly":
            return self.values
        if self.kind == "constant":
            return self.values * HOURS
        start = datetime(self.year, 1, 1)
        result = []
        for hour in range(HOURS):
            moment = start + timedelta(hours=hour)
            if self.kind == "monthly":
                result.append(self.values[moment.month - 1])
            else:
                offset = 0 if moment.weekday() < 5 else 24
                result.append(self.values[offset + moment.hour])
        return tuple(result)

    @property
    def mean(self) -> float:
        """Time-average factor; equals the delivered-weighted value only for flat demand."""
        return math.fsum(self.hourly_values) / HOURS

    def apply(self, hourly_kwh: Sequence[float]) -> float:
        """Sum of hourly delivered kWh times the factor in each hour."""
        if len(hourly_kwh) != HOURS:
            raise ValueError("Hourly delivered energy needs 8760 values")
        return math.fsum(
            e * f for e, f in zip(hourly_kwh, self.hourly_values, strict=True)
        )

    def to_dict(self):
        return {
            "kind": self.kind,
            "values": list(self.values),
            "unit": self.unit,
            "source": self.source,
            "year": self.year,
        }

    @classmethod
    def from_dict(cls, data: Mapping):
        values = dict(data)
        values["values"] = tuple(values["values"])
        return cls(**values)

    def __repr__(self):
        return (
            f"FactorProfile(kind={self.kind!r}, unit={self.unit!r}, "
            f"mean={self.mean:.4g}, year={self.year})"
        )
