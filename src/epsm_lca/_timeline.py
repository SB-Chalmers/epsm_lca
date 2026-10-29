# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Years of an assessment period, for amounts that differ or are discounted by year."""

from __future__ import annotations

import math


def years(period):
    """Yield (year, share) for years 1..ceil(period); only the last can be partial.

    Examples
    --------
    >>> list(years(2.5))
    [(1, 1.0), (2, 1.0), (3, 0.5)]
    """
    for year in range(1, math.ceil(period) + 1):
        yield year, min(1.0, period - (year - 1))


def present_value(annual, period, *, rate=0.0, escalation=0.0):
    """Sum an annual amount over the period, escalated and discounted each year.

    Year ``t`` is valued at ``annual * (1 + escalation)**t / (1 + rate)**t``. With
    both rates zero this is ``annual * period``.

    Examples
    --------
    >>> present_value(100.0, 2, rate=0.0)
    200.0
    >>> round(present_value(100.0, 2, rate=0.1), 4)
    173.5537
    """
    if annual is None:
        return None
    growth = (1 + escalation) / (1 + rate)
    return math.fsum(annual * share * growth**year for year, share in years(period))


def discounted_payback(investment, annual_saving, *, rate=0.0, escalation=0.0):
    """Years until discounted savings repay an investment; None if never.

    The year that completes repayment is interpolated linearly. Savings that
    shrink in value faster than they accumulate never repay; the search stops
    after 1,000 years.

    Examples
    --------
    >>> discounted_payback(250.0, 100.0)
    2.5
    >>> discounted_payback(1000.0, 100.0, rate=0.1) is None
    True
    """
    if investment is None or annual_saving is None or annual_saving <= 0:
        return None
    if investment <= 0:
        return 0.0
    growth = (1 + escalation) / (1 + rate)
    repaid = 0.0
    for year in range(1, 1001):
        value = annual_saving * growth**year
        if repaid + value >= investment:
            return year - 1 + (investment - repaid) / value
        repaid += value
    return None
