# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""B4 replacement of renovation work whose service life ends within the period.

Work installed by a renovation measure is replaced ``ceil(period / life) - 1``
times, at years ``life``, ``2 * life`` and so on (EN 15978). Each replacement
installs the same occurrence again and removes the worn one, so it counts the
selected installation (A) and removal (C) modules once more. Existing
components of the baseline are not replaced: their remaining lives are unknown.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from ._validation import finite_sum, number, text


@dataclass(frozen=True)
class ServiceLife:
    """A sourced service life in years for a renovation candidate or measure.

    Examples
    --------
    >>> ServiceLife(25, "Catalogue assumption").replacement_years(60)
    (25.0, 50.0)
    """

    years: float
    source: str

    def __post_init__(self):
        if number(self.years, "service life years") <= 0:
            raise ValueError("Service life years must be finite and positive")
        text(self.source, "service life source")
        object.__setattr__(self, "years", float(self.years))

    def replacement_years(self, period):
        """Years in which the work is replaced within ``period``."""
        count = max(math.ceil(period / self.years) - 1, 0)
        return tuple(self.years * k for k in range(1, count + 1))

    def to_dict(self):
        return {"years": self.years, "source": self.source}


def life_for(service_lives: Mapping, measure_id, candidate_id=None):
    """Service life by catalogue candidate ID, else by measure ID."""
    if candidate_id is not None and candidate_id in service_lives:
        return service_lives[candidate_id]
    return service_lives.get(measure_id)


def surviving_installations(stages):
    """Installed occurrences still present after ``stages``, with their stage.

    Returns ``{occurrence_id: (row, stage)}``. Occurrences removed by a later
    stage are dropped, so replaced windows are not replaced again.
    """
    from .assessment import flow_rows

    present = {}
    for stage in stages:
        installed, removed = flow_rows(stage.material_flows)
        for row in removed:
            present.pop(row.occurrence_id, None)
        for row in installed:
            present[row.occurrence_id] = (row, stage)
    return present


def replacement_impact(stages, settings, *, step):
    """B4 impact of replacing surviving renovation work over the period.

    Returns ``(total, requirements, contributions)`` like ``material_impact``.
    Each contribution keeps its original module as ``replaced_module`` and the
    replacement ``year``; its module is ``B4``.
    """
    from .assessment import material_impact

    missing, records, values = [], [], []
    for occurrence, (row, stage) in surviving_installations(stages).items():
        recorded = getattr(stage, "installed_by", None)
        if recorded is None:
            missing.append(
                "Core does not record which measure installed each material; "
                "update epsm_core to count replacements"
            )
            continue
        measure = dict(recorded).get(occurrence)
        if measure is None:
            missing.append(f"{occurrence}: the installing measure is unknown")
            continue
        candidates = {q.measure_id: q.candidate_id for q in stage.quantities}
        life = life_for(settings.service_lives, measure, candidates.get(measure))
        if life is None:
            missing.append(f"{measure}: service life is missing")
            continue
        replaced = life.replacement_years(settings.period_years)
        if not replaced:
            continue
        total, gaps, parts = material_impact(
            (row,), (row,), settings, stage_id=stage.stage_id, step=step
        )
        missing.extend(gaps)
        for year in replaced:
            for part in parts:
                records.append(
                    dict(
                        part,
                        module="B4",
                        replaced_module=part["module"],
                        measure_id=measure,
                        year=year,
                        service_life_years=life.years,
                        service_life_source=life.source,
                    )
                )
            if total is not None:
                values.append(total)
    total = finite_sum(values)
    if total is None:
        missing.append("Calculated replacement impact total must be finite")
    return (
        (None if missing else total),
        tuple(dict.fromkeys(missing)),
        tuple(records),
    )
