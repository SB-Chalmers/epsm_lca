# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Which factors move a saved renovation result most.

Every impact is factor × quantity, so scaling one driver's factors by
(1 ± fraction) moves a step's total by ±fraction × that driver's impact, and
moves its savings against the baseline by ±fraction × (baseline impact − step
impact). Nothing is recomputed: the ranking says which factors deserve a better
source first. A driver is one material, across all its modules and steps so far,
or one energy carrier.
"""

from __future__ import annotations

from ._validation import number
from .coverage import part_of, source_kind

TARGETS = ("total", "savings")


def step_drivers(report, step):
    """Impact of each driver in a step's total, with the source kinds behind it.

    The total is material impact so far plus this state's replacement and energy
    impacts, so material contributions accumulate from the baseline through the
    step while B4 and B6 come from the step alone.
    """
    rows = (report["baseline"], *report["stages"])
    impacts, kinds = {}, {}
    for row in rows[: step + 1]:
        for record in row["contributions"]:
            part = part_of(record)
            if part != "material" and row["step"] != step:
                continue
            key = (
                ("carrier", record["carrier"])
                if part == "energy"
                else ("material", record["material_id"])
            )
            impacts[key] = impacts.get(key, 0.0) + record["gwp_kgco2e"]
            kinds.setdefault(key, set()).add(source_kind(record["source"]))
    return impacts, kinds


def sensitivity(report, *, fraction=0.25, target="savings"):
    """Rank drivers by the swing a ±``fraction`` change in their factors causes.

    ``target`` is each step's ``total`` or its ``savings`` against the baseline
    (renovation steps only). Rows carry the driver's impact in the target, its
    share of the target, the swing and the resulting low and high values, sorted
    by swing within each step. Incomplete steps are left out: a ranking over
    partial contributions would be wrong.

    Examples
    --------
    >>> report = {"settings": {}, "baseline": {"step": 0, "status": "complete",
    ...     "total_kgco2e": 300.0, "savings_kgco2e": None, "contributions": [
    ...     {"module": "B6", "carrier": "heat", "gwp_kgco2e": 300.0, "source": "x"}]},
    ...     "stages": [{"step": 1, "status": "complete", "total_kgco2e": 260.0,
    ...     "savings_kgco2e": 40.0, "contributions": [
    ...     {"module": "A1A3", "material_id": "wool", "gwp_kgco2e": 20.0, "source": "x"},
    ...     {"module": "B6", "carrier": "heat", "gwp_kgco2e": 240.0, "source": "x"}]}]}
    >>> [(r["driver"], r["impact_kgco2e"], r["swing_kgco2e"]) for r in sensitivity(report)]
    [('heat', 60.0, 15.0), ('wool', -20.0, 5.0)]
    """
    if number(fraction, "sensitivity fraction") <= 0:
        raise ValueError("Sensitivity fraction must be finite and positive")
    if target not in TARGETS:
        raise ValueError(f"target must be one of {', '.join(TARGETS)}")
    baseline = report["baseline"]
    rows = (baseline, *report["stages"])
    if target == "savings":
        rows = rows[1:]
        reference, _ = step_drivers(report, 0)
    result = []
    for row in rows:
        value = row[f"{target}_kgco2e"]
        if row["status"] != "complete" or value is None:
            continue
        impacts, kinds = step_drivers(report, row["step"])
        if target == "savings":
            impacts = {
                key: reference.get(key, 0.0) - impacts.get(key, 0.0)
                for key in {*reference, *impacts}
            }
        ranked = sorted(impacts.items(), key=lambda item: -abs(item[1]))
        for (kind, driver), impact in ranked:
            swing = fraction * abs(impact)
            result.append(
                dict(
                    step=row["step"],
                    target=target,
                    driver_kind=kind,
                    driver=driver,
                    source_kinds=tuple(sorted(kinds.get((kind, driver), ()))),
                    impact_kgco2e=impact,
                    share=None if not value else impact / value,
                    swing_kgco2e=swing,
                    low_kgco2e=value - swing,
                    high_kgco2e=value + swing,
                )
            )
    return result
