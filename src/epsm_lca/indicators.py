# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Decision indicators derived from fixed results; nothing new is assumed."""

from __future__ import annotations


def payback_years(investment, annual_saving):
    """Years until constant annual savings repay an investment; None if never.

    Unknown inputs or savings that are zero or negative give None. An investment
    that is already zero or negative pays back immediately.

    Examples
    --------
    >>> payback_years(1000.0, 250.0)
    4.0
    >>> payback_years(1000.0, -5.0) is None
    True
    """
    if investment is None or annual_saving is None or annual_saving <= 0:
        return None
    return max(investment, 0.0) / annual_saving


def per_area(value, area):
    """Divide by a reference area; unknown values or areas stay None."""
    return None if value is None or area is None else value / area
