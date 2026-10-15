# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Shared checks for quantities and accounting; no external access."""

import math
from numbers import Real


def number(value, name, *, nonnegative=False):
    """Reject booleans, wrong types and nonfinite numbers."""
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite number")
    try:
        valid = math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid or (nonnegative and value < 0):
        raise ValueError(
            f"{name} must be finite" + (" and nonnegative" if nonnegative else "")
        )
    return float(value)


def text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonempty text")
    return value


def optional_number(value, name):
    return None if value is None else number(value, name)


def same_total(actual, expected):
    """Allow summation rounding, not scientific uncertainty."""
    return math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-9)


def finite_sum(values):
    try:
        value = math.fsum(values)
    except (OverflowError, ValueError):
        return None
    return value if math.isfinite(value) else None
