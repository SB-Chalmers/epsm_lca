# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Fixed step results and portable renovation reports, with visible missing inputs."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ._timeline import repay, years
from ._validation import finite_sum, number, optional_number, same_total
from .assessment import quantity_record
from .indicators import payback_years, per_area
from .result import LCAResult
from .settings import AssessmentSettings


def aggregate_quantities(rows):
    """Combine each basis separately; one unknown amount keeps that basis unknown."""
    groups = {}
    for row in rows:
        group = groups.setdefault(
            row["material_id"],
            dict(
                material_id=row["material_id"],
                material_name=row.get("material_name"),
                occurrence_count=0,
                mass_kg=0.0,
                volume_m3=0.0,
                area_m2=0.0,
                count=0.0,
            ),
        )
        group["occurrence_count"] += 1
        for field in ("mass_kg", "volume_m3", "area_m2", "count"):
            value = row.get(field)
            if value is None or group[field] is None:
                group[field] = None
            else:
                group[field] = finite_sum((group[field], value))
    return list(groups.values())


@dataclass(frozen=True, init=False, repr=False)
class StageResult:
    """One baseline/renovation step with fixed quantities and climate impacts.

    Attributes
    ----------
    step : int
        Zero is baseline; renovation steps start at one.
    material_kgco2e, material_so_far_kgco2e : float or None
        Impact of this step and accumulated material impact through this step.
    replacement_kgco2e : float or None
        B4 replacement of this state's renovation work over the period; None
        when replacements are not counted or cannot be completed.
    energy_kgco2e, total_kgco2e, savings_kgco2e : float or None
        This state's energy impact, combined total and baseline minus total.
    added_quantities, removed_quantities : tuple of dict
        Independent occurrence records with known kg, m3, m2 and counts.
    requirements : tuple of str
        Missing information; no unknown value is substituted with zero.

    Notes
    -----
    State, quantities and contributions are independent copies. Inspection does
    no I/O. See the renovation notebooks for construction and comparison examples.

    Examples
    --------
    >>> from epsm_core import Building
    >>> from epsm_lca import AssessmentSettings, assess_renovation
    >>> step = assess_renovation(Building(preset="illustrative-reference"), AssessmentSettings(30, include_energy=False)).baseline
    >>> step.summary()['step']
    0
    >>> step.quantities(action='removed', by_material=True)
    []
    >>> StageResult.from_dict(step.to_dict()) == step
    True
    """

    _json: str
    _summary_json: str

    def __init__(
        self,
        *,
        step,
        stage_id,
        measure_ids,
        state_id,
        state,
        material_kgco2e,
        material_so_far_kgco2e,
        energy_kgco2e,
        total_kgco2e,
        savings_kgco2e,
        status,
        requirements=(),
        added_quantities=(),
        removed_quantities=(),
        contributions=(),
        include_energy=True,
        diagnostic_codes=None,
        replacement_kgco2e=None,
    ):
        from epsm_core import BuildingSnapshot

        if isinstance(step, bool) or not isinstance(step, int) or step < 0:
            raise ValueError("Step must be zero or a positive integer")
        if (step == 0 and stage_id is not None) or (
            step > 0 and not isinstance(stage_id, str)
        ):
            raise ValueError("Renovation steps require an identity; baseline has none")
        if BuildingSnapshot.from_dict(state).sha256 != state_id:
            raise ValueError("Saved building state disagrees with its identity")
        material = optional_number(material_kgco2e, "step material impact")
        cumulative = optional_number(material_so_far_kgco2e, "material impact so far")
        operating = optional_number(energy_kgco2e, "energy impact")
        total = optional_number(total_kgco2e, "total climate impact")
        replacement = optional_number(replacement_kgco2e, "replacement impact")
        savings = optional_number(savings_kgco2e, "climate savings")
        LCAResult(  # B4 belongs to the material side of the combined total.
            status,
            cumulative
            if replacement is None or cumulative is None
            else finite_sum((cumulative, replacement)),
            operating,
            total,
            requirements,
            include_energy=include_energy,
        )
        if status == "complete" and material is None:
            raise ValueError("Complete steps require known material impact")
        records = tuple(dict(r) for r in contributions)
        for r in records:
            number(r.get("gwp_kgco2e"), "contribution impact")

        def part(record):
            return record.get("module") if record.get("module") in {"B4", "B6"} else "A"

        for kind, claimed in (("A", material), ("B4", replacement), ("B6", operating)):
            values = [r["gwp_kgco2e"] for r in records if part(r) == kind]
            if values and claimed is not None:
                expected = finite_sum(values)
                if expected is None or not same_total(claimed, expected):
                    raise ValueError("Step total disagrees with its contributions")
        added = tuple(quantity_record(r) for r in added_quantities)
        removed = tuple(quantity_record(r) for r in removed_quantities)
        codes = [] if status == "complete" else ["lca.inputs.missing"]
        if diagnostic_codes is not None and list(diagnostic_codes) != codes:
            raise ValueError("Saved diagnostic codes disagree with the step status")
        data = dict(
            step=step,
            stage_id=stage_id,
            measure_ids=tuple(measure_ids),
            state_id=state_id,
            state=state,
            material_kgco2e=material,
            material_so_far_kgco2e=cumulative,
            energy_kgco2e=operating,
            total_kgco2e=total,
            savings_kgco2e=savings,
            replacement_kgco2e=replacement,
            status=status,
            requirements=tuple(requirements),
            added_quantities=added,
            removed_quantities=removed,
            contributions=records,
            include_energy=include_energy,
            diagnostic_codes=codes,
        )
        object.__setattr__(
            self, "_json", json.dumps(data, sort_keys=True, allow_nan=False)
        )
        summary = {
            k: data[k]
            for k in (
                "step",
                "stage_id",
                "state_id",
                "material_kgco2e",
                "material_so_far_kgco2e",
                "energy_kgco2e",
                "total_kgco2e",
                "savings_kgco2e",
                "replacement_kgco2e",
                "status",
                "requirements",
            )
        }
        summary.update(added_count=len(added), removed_count=len(removed))
        summary["diagnostic_codes"] = codes
        object.__setattr__(
            self, "_summary_json", json.dumps(summary, sort_keys=True, allow_nan=False)
        )

    def __getattr__(self, name):
        summary = json.loads(self._summary_json)
        if name in summary:
            return tuple(summary[name]) if name == "requirements" else summary[name]
        data = self.to_dict()
        if name in data:
            return (
                tuple(data[name])
                if name
                in {
                    "measure_ids",
                    "added_quantities",
                    "removed_quantities",
                    "contributions",
                }
                else data[name]
            )
        raise AttributeError(name)

    @property
    def complete(self) -> bool:
        return self.status == "complete"

    def summary(self) -> dict:
        """Return fixed step totals and quantity counts, without expanding lists."""
        return json.loads(self._summary_json)

    def quantities(
        self, *, action: str = "removed", by_material: bool = False
    ) -> list[dict]:
        """Inspect removed or added quantities, optionally grouped by material.

        Unknown mass, area, volume or count stays None even during grouping.
        No material or disposal impacts are recalculated by this operation.
        """
        if action not in {"added", "removed"}:
            raise ValueError("action must be 'added' or 'removed'")
        rows = list(getattr(self, action + "_quantities"))
        return aggregate_quantities(rows) if by_material else rows

    def to_dict(self) -> dict:
        """Return independent step evidence for its enclosing versioned report."""
        return json.loads(self._json)

    @classmethod
    def from_dict(cls, value: Mapping) -> StageResult:
        """Validate a saved step's values and building identity."""
        try:
            return cls(**dict(value))
        except TypeError as error:
            raise ValueError(f"Invalid saved step: {error}") from error

    def __repr__(self) -> str:
        s = self.summary()
        return f"StageResult(step={s['step']}, status={s['status']!r}, total_kgco2e={s['total_kgco2e']!r}, added={s['added_count']}, removed={s['removed_count']})"

    __str__ = __repr__


def yearly_energy(row, period):
    """Each year's B6 impact when a trajectory was used; otherwise None."""
    records = [c for c in row["contributions"] if c.get("module") == "B6"]
    if not any("yearly_gwp_kgco2e" in c for c in records):
        return None
    return [
        sum(
            c["yearly_gwp_kgco2e"][year - 1]
            if "yearly_gwp_kgco2e" in c
            else c["gwp_kgco2e"] * share / period
            for c in records
        )
        for year, share in years(period)
    ]


def indicators(row, report):
    """Renovation carbon, payback and per-area totals for one saved row.

    Renovation carbon is material impact so far minus the baseline's. Annual
    saving is the baseline's energy impact minus this row's, over the period.
    With yearly factor trajectories, payback follows the yearly savings and is
    None when they do not repay within the period.
    """
    baseline, settings = report["baseline"], report["settings"]
    period, area = settings["period_years"], settings["reference_area_m2"]
    renovation = (
        None
        if row["material_so_far_kgco2e"] is None
        or baseline["material_so_far_kgco2e"] is None
        else row["material_so_far_kgco2e"] - baseline["material_so_far_kgco2e"]
    )
    saving = (
        None
        if row["step"] == 0
        or row["energy_kgco2e"] is None
        or baseline["energy_kgco2e"] is None
        else (baseline["energy_kgco2e"] - row["energy_kgco2e"]) / period
    )
    payback = payback_years(renovation, saving)
    if saving is not None:
        before, after = yearly_energy(baseline, period), yearly_energy(row, period)
        if before is not None or after is not None:
            flat = [share / period for _, share in years(period)]
            before = before or [baseline["energy_kgco2e"] * s for s in flat]
            after = after or [row["energy_kgco2e"] * s for s in flat]
            payback = repay(renovation, [b - a for b, a in zip(before, after)])
    total_per_m2 = per_area(row["total_kgco2e"], area)
    return {
        "renovation_kgco2e": renovation,
        "annual_energy_saving_kgco2e": saving,
        "carbon_payback_years": payback,
        "total_kgco2e_per_m2": total_per_m2,
        "total_kgco2e_per_m2_year": None
        if total_per_m2 is None
        else total_per_m2 / period,
    }


@dataclass(frozen=True, init=False, repr=False)
class RenovationResult:
    """Baseline and every renovation step, including quantities and saved inputs.

    Attributes
    ----------
    baseline : StageResult
        Original building, step zero.
    stages : tuple of StageResult
        Ordered renovation steps. Their energy impacts are comparisons, not sums.
    settings : AssessmentSettings
        Fixed assessment choices and factors.
    complete : bool
        True only when all requested steps have their selected totals.

    Examples
    --------
    Use the worked notebooks to create a report, then inspect report.table(),
    report.stages[0].removed_quantities and report.quantities(by_material=True).
    Saving and plotting are explicit operations.

    >>> from epsm_core import Building
    >>> from epsm_lca import AssessmentSettings, assess_renovation
    >>> report = assess_renovation(Building(preset="illustrative-reference"), AssessmentSettings(30, include_energy=False))
    >>> report.table()[0]['total_kgco2e']
    0.0
    >>> report.summary()['step_count']
    0
    >>> report.quantities(action='removed')
    []
    >>> from pathlib import Path
    >>> from tempfile import TemporaryDirectory
    >>> with TemporaryDirectory() as directory:
    ...     path = report.save(Path(directory) / 'report.json')
    ...     restored = RenovationResult.load(path)
    ...     assert restored == report
    """

    _json: str
    _summary_json: str

    def __init__(
        self, *, baseline, stages, settings, building, lineage, energy, producer
    ):
        stages = tuple(stages)
        if baseline.step != 0 or tuple(s.step for s in stages) != tuple(
            range(1, len(stages) + 1)
        ):
            raise ValueError(
                "Report steps must begin at baseline and be ordered without gaps"
            )
        cumulative = 0.0
        for row in (baseline, *stages):
            cumulative = (
                None
                if cumulative is None or row.material_kgco2e is None
                else finite_sum((cumulative, row.material_kgco2e))
            )
            if (cumulative is None) != (row.material_so_far_kgco2e is None) or (
                cumulative is not None
                and not same_total(cumulative, row.material_so_far_kgco2e)
            ):
                raise ValueError(
                    "Material impact so far disagrees with the preceding steps"
                )
            expected = (
                finite_sum((baseline.total_kgco2e, -row.total_kgco2e))
                if baseline.total_kgco2e is not None and row.total_kgco2e is not None
                else None
            )
            if (expected is None) != (row.savings_kgco2e is None) or (
                expected is not None and not same_total(expected, row.savings_kgco2e)
            ):
                raise ValueError(
                    "Climate savings disagree with the baseline comparison"
                )
        data = {
            "format": "epsm-lca-renovation/2",
            "baseline": baseline.to_dict(),
            "stages": [s.to_dict() for s in stages],
            "settings": settings.to_dict(),
            "building": building,
            "lineage": lineage,
            "energy": {str(step): value.to_dict() for step, value in energy.items()},
            "producer": producer,
        }
        object.__setattr__(
            self, "_json", json.dumps(data, sort_keys=True, allow_nan=False)
        )
        final = indicators(data["stages"][-1] if stages else data["baseline"], data)
        summary = dict(
            status="complete"
            if all(s.complete for s in (baseline, *stages))
            else "incomplete",
            step_count=len(stages),
            period_years=settings.period_years,
            include_energy=settings.include_energy,
            baseline_total_kgco2e=baseline.total_kgco2e,
            final_total_kgco2e=(stages[-1] if stages else baseline).total_kgco2e,
            final_savings_kgco2e=(stages[-1] if stages else baseline).savings_kgco2e,
            final_carbon_payback_years=final["carbon_payback_years"],
            reference_area_m2=settings.reference_area_m2,
            reference_area_basis=settings.reference_area_basis,
            incomplete_steps=[s.step for s in (baseline, *stages) if not s.complete],
        )
        object.__setattr__(
            self, "_summary_json", json.dumps(summary, sort_keys=True, allow_nan=False)
        )

    @property
    def baseline(self) -> StageResult:
        return StageResult.from_dict(self.to_dict()["baseline"])

    @property
    def stages(self) -> tuple[StageResult, ...]:
        return tuple(StageResult.from_dict(s) for s in self.to_dict()["stages"])

    @property
    def settings(self) -> AssessmentSettings:
        return AssessmentSettings.from_dict(self.to_dict()["settings"])

    @property
    def complete(self) -> bool:
        return self.summary()["status"] == "complete"

    def summary(self) -> dict:
        """Inspect period, completeness and final comparison without material lists."""
        return json.loads(self._summary_json)

    def table(self) -> list[dict]:
        """Return one independent row per state; impacts are in kg CO2e.

        Each row also has its renovation carbon, carbon payback in years and,
        with a reference area, totals per m² and per m² and year. These are
        derived from the row and the baseline; unknown inputs give None.
        """
        data = self.to_dict()
        return [
            {
                **{
                    k: row[k]
                    for k in (
                        "step",
                        "measure_ids",
                        "material_kgco2e",
                        "material_so_far_kgco2e",
                        "replacement_kgco2e",
                        "energy_kgco2e",
                        "total_kgco2e",
                        "savings_kgco2e",
                        "status",
                        "requirements",
                    )
                },
                **indicators(row, data),
            }
            for row in (data["baseline"], *data["stages"])
        ]

    def quantities(
        self,
        *,
        action: str = "removed",
        step: int | None = None,
        by_material: bool = False,
    ) -> list[dict]:
        """Inspect added/removed occurrences for all steps or one selected step.

        Baseline quantities are shown only when original construction is included.
        Without grouping, each row retains its step and stage identity. Unknown
        quantity bases remain unknown when grouping repeated removals.
        """
        if step is not None and (
            isinstance(step, bool)
            or not isinstance(step, int)
            or not 0 <= step <= self.summary()["step_count"]
        ):
            raise ValueError(
                "step must identify the baseline or an existing renovation step"
            )
        rows = []
        for result in (self.baseline, *self.stages):
            if step is None or step == result.step:
                rows.extend(
                    dict(row, step=result.step, stage_id=result.stage_id)
                    for row in result.quantities(action=action)
                )
        return aggregate_quantities(rows) if by_material else rows

    def to_dict(self) -> dict:
        """Return independent complete inputs and results in report format 2."""
        return json.loads(self._json)

    @classmethod
    def from_dict(cls, value: Mapping) -> RenovationResult:
        """Load a report and verify saved accounting against its saved inputs.

        This recalculates the small climate sums from saved values, without
        fetching data or running energy. Original producer versions are retained.
        """
        from epsm_core import BuildingSnapshot

        from .energy import AnnualEnergy
        from .renovation import _assess_renovation

        data = dict(value)
        if data.get("format") != "epsm-lca-renovation/2":
            raise ValueError("Unsupported renovation report format")
        required = {
            "format",
            "baseline",
            "stages",
            "settings",
            "building",
            "lineage",
            "energy",
            "producer",
        }
        if set(data) != required:
            raise ValueError("Renovation report fields are missing or unknown")
        building = BuildingSnapshot.from_dict(data["building"]).to_building()
        building.restore_lineage(data["lineage"])
        energy = {
            int(step): AnnualEnergy.from_dict(record)
            for step, record in data["energy"].items()
        }
        if any(str(int(step)) != step for step in data["energy"]):
            raise ValueError("Saved energy step names must be canonical integers")
        if (
            not isinstance(data["producer"], dict)
            or data["producer"].get("method") != "declared-renovation-gwp/1"
        ):
            raise ValueError("Unsupported or missing climate calculation method")
        baseline = StageResult.from_dict(data["baseline"])
        stages = tuple(StageResult.from_dict(s) for s in data["stages"])
        settings = AssessmentSettings.from_dict(data["settings"])
        result = cls(
            baseline=baseline,
            stages=stages,
            settings=settings,
            building=data["building"],
            lineage=data["lineage"],
            energy=energy,
            producer=data["producer"],
        )
        expected = _assess_renovation(building, settings, energy=energy, emit=False)
        if (
            result.to_dict()["baseline"] != expected.to_dict()["baseline"]
            or result.to_dict()["stages"] != expected.to_dict()["stages"]
        ):
            raise ValueError(
                "Saved renovation results disagree with the recorded inputs"
            )
        return result

    def save(self, path: str | Path, *, overwrite: bool = False) -> Path:
        """Save UTF-8 JSON atomically; existing files require overwrite=True.

        Relative paths use the caller's working directory. Parent directories
        must exist. The returned path identifies the saved complete report.
        """
        from .io import save_report

        return save_report(self, path, overwrite=overwrite)

    @classmethod
    def load(cls, path: str | Path) -> RenovationResult:
        """Read and validate a UTF-8 JSON report without modifying the file."""
        from .io import load_report

        return load_report(path)

    def plot(self, *, ax=None, show: bool = False):
        """Return a Matplotlib figure comparing materials and energy by step.

        Requires the plot extra. Missing totals stay visible as gaps with labels;
        excluded energy is labelled. No file is saved or engine run.

        Parameters
        ----------
        ax : matplotlib.axes.Axes, optional
            Use an existing axis without clearing its contents.
        show : bool, optional
            Display explicitly when True; default False.

        Returns
        -------
        matplotlib.figure.Figure
            Editable figure; save it explicitly with figure.savefig(path).

        Examples
        --------
        With the plot extra installed, use ``figure = report.plot()`` and
        ``figure.savefig('renovation.svg')``. The worked notebooks create the
        report and demonstrate this export without copying the calculation.
        """
        from .plotting import plot_report

        return plot_report(self, ax=ax, show=show)

    def __repr__(self) -> str:
        s = self.summary()
        return f"RenovationResult(steps={s['step_count']}, status={s['status']!r}, final_kgco2e={s['final_total_kgco2e']!r})"

    __str__ = __repr__
