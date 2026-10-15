# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Assess a Core building and its actual renovation steps using supplied energy."""

from __future__ import annotations

from collections.abc import Mapping
from importlib.metadata import PackageNotFoundError, version

from epsm_core import Building

from epsm_lca._logging import context_logger
from epsm_lca._logging import operation as logged_operation

from ._validation import finite_sum
from ._version import __version__
from .assessment import energy_impact, flow_rows, material_impact, quantity_record
from .energy import AnnualEnergy
from .renovation_result import RenovationResult, StageResult
from .settings import AssessmentSettings

logger = context_logger(__name__)


@logged_operation(
    "lca.renovation",
    result_details=lambda result: {
        "status": result.summary()["status"],
        "step_count": result.summary()["step_count"],
        "incomplete_step_count": len(result.summary()["incomplete_steps"]),
    },
)
def assess_renovation(
    building: Building,
    settings: AssessmentSettings,
    *,
    energy: Mapping[int, AnnualEnergy] | None = None,
) -> RenovationResult:
    """Calculate climate impacts for the baseline and every renovation step.

    Parameters
    ----------
    building : epsm_core.Building
        The final building, retaining Core's recorded renovation history.
    settings : AssessmentSettings
        Period, material stages, actual factors and covered energy uses.
    energy : mapping of int to AnnualEnergy, optional
        Supplied annual kWh: 0 is baseline, 1..n are renovation steps. Missing
        entries keep material results useful but combined totals incomplete.

    Returns
    -------
    RenovationResult
        Fixed step quantities, climate impacts, comparisons and saved inputs.

    Raises
    ------
    ValueError
        Invalid building/settings, unknown step or energy for a different state.

    Notes
    -----
    Original construction is excluded by default. Every state uses the same
    period; energy from different steps is never added together. No inputs are
    changed, no catalogue is loaded and no simulation is started. An unrecorded
    physical edit keeps affected material totals incomplete.

    Examples
    --------
    A baseline without renovation can be assessed for materials only.

    >>> from epsm_core import Building
    >>> report = assess_renovation(Building(preset="illustrative-reference"), AssessmentSettings(30, include_energy=False))
    >>> report.baseline.total_kgco2e
    0.0
    >>> len(report.stages)
    0
    """
    context = (
        {"building_id": building.identifier} if isinstance(building, Building) else {}
    )
    try:
        result = _assess_renovation(building, settings, energy=energy)
    except (ValueError, TypeError) as error:
        logger.error(
            "Building renovation assessment rejected invalid inputs",
            extra={
                "epsm_event": "lca.renovation.failed",
                "epsm_context": context,
                "epsm_details": {
                    "code": "lca.inputs.invalid",
                    "error_type": type(error).__name__,
                },
            },
        )
        raise
    return result


def _assess_renovation(building, settings, *, energy=None, emit=True):
    """Share the same accounting between assessment and saved-input verification."""
    if not isinstance(building, Building):
        raise ValueError("building must be an epsm_core Building")
    if not isinstance(settings, AssessmentSettings):
        raise ValueError("settings must be AssessmentSettings")
    if energy is None:
        energy = {}
    if not isinstance(energy, Mapping):
        raise ValueError("energy must map step numbers to AnnualEnergy records")
    if energy and not settings.include_energy:
        raise ValueError(
            "Supplied energy would be excluded; set include_energy=True or omit energy"
        )
    for step, annual in energy.items():
        if (
            isinstance(step, bool)
            or not isinstance(step, int)
            or not 0 <= step <= len(building.stages)
        ):
            raise ValueError(
                "Energy step must identify baseline 0 or an existing renovation step"
            )
        if not isinstance(annual, AnnualEnergy):
            raise ValueError(
                "Supply AnnualEnergy records; use AnnualEnergy.for_building"
            )
    snapshot = building.snapshot()
    stages = tuple(building.stages)
    states = [stages[0].before] if stages else [snapshot]
    # A declared nonmaterial authoring revision is the reached state used before
    # the next intervention. Material-affecting revisions remain explicit gaps.
    states.extend(
        stages[i + 1].before if i + 1 < len(stages) else snapshot
        for i in range(len(stages))
    )
    history = {}
    for link in building.authoring_links:
        if link.changes_material_inventory:
            history[link.after_stage] = (
                f"Material history after step {link.after_stage}: an edit changed quantities or identities; "
                "record the physical work as a renovation or revise the baseline",
            )
    cumulative = 0.0
    baseline_total = None
    results = []
    for step, state in enumerate(states):
        supplied = energy.get(step)
        if supplied is not None and supplied.state_id != state.sha256:
            raise ValueError(
                f"Energy for step {step} describes a different building state"
            )
        if supplied is not None and supplied.boundary != settings.energy_boundary:
            raise ValueError(
                f"Energy for step {step} covers different uses from the assessment"
            )
        gaps = list(history.get(step, ()))
        if step == 0:
            try:
                original = tuple(state.quantities())
            except ValueError as error:
                original = ()
                gaps.append(f"Baseline material quantities are unavailable: {error}")
            installed = original if settings.baseline == "include" else ()
            removed = ()
            stage_id, measures = None, ()
        else:
            stage = stages[step - 1]
            if stage.order != step or not stage.stage_id:
                raise ValueError("Core renovation stages must have ordered identities")
            installed, removed = flow_rows(stage.material_flows)
            stage_id, measures = stage.stage_id, stage.measure_ids
        material, material_gaps, material_records = material_impact(
            installed,
            removed,
            settings,
            step=step,
            stage_id=stage_id,
            requirements=gaps,
        )
        cumulative = (
            None
            if cumulative is None or material is None
            else finite_sum((cumulative, material))
        )
        operating, energy_gaps, energy_records = energy_impact(supplied, settings)
        missing = [*material_gaps, *energy_gaps]
        if cumulative is None and not material_gaps:
            missing.append(
                "Material impact so far is unavailable; check earlier steps or nonfinite sums"
            )
        total = None
        if not missing:
            total = (
                finite_sum((cumulative, operating))
                if settings.include_energy
                else cumulative
            )
            if total is None:
                missing.append("Calculated combined impact total must be finite")
        if step == 0:
            baseline_total = total
        savings = (
            finite_sum((baseline_total, -total))
            if baseline_total is not None and total is not None
            else None
        )
        records = (
            *material_records,
            *(
                dict(r, step=step, stage_id=stage_id, source_energy=supplied.source)
                for r in energy_records
            ),
        )
        result = StageResult(
            step=step,
            stage_id=stage_id,
            measure_ids=measures,
            state_id=state.sha256,
            state=state.to_dict(),
            material_kgco2e=material,
            material_so_far_kgco2e=cumulative,
            energy_kgco2e=operating,
            total_kgco2e=total,
            savings_kgco2e=savings,
            status="incomplete" if missing else "complete",
            requirements=tuple(dict.fromkeys(missing)),
            contributions=records,
            added_quantities=tuple(quantity_record(r) for r in installed),
            removed_quantities=tuple(quantity_record(r) for r in removed),
            include_energy=settings.include_energy,
        )
        results.append(result)
        if emit:
            logger.debug(
                "Assessed renovation step %d: %s",
                step,
                result.status,
                extra={
                    "epsm_event": "lca.step.completed",
                    "epsm_context": {
                        "building_id": building.identifier,
                        "stage": step,
                        "state_id": state.sha256,
                    },
                    "epsm_details": {
                        "added_count": len(installed),
                        "removed_count": len(removed),
                        "requirement_count": len(result.requirements),
                    },
                },
            )
            if missing:
                logger.warning(
                    "Step %d needs %d missing inputs",
                    step,
                    len(result.requirements),
                    extra={
                        "epsm_event": "lca.inputs.missing",
                        "epsm_context": {
                            "building_id": building.identifier,
                            "stage": step,
                        },
                        "epsm_details": {
                            "code": "lca.inputs.missing",
                            "requirement_count": len(result.requirements),
                        },
                    },
                )
    producer = {"epsm_lca": __version__, "method": "declared-renovation-gwp/1"}
    for package in ("epsm_core", "epsm_data"):
        try:
            producer[package] = version(package)
        except PackageNotFoundError:
            producer[package] = "unrecorded"
    return RenovationResult(
        baseline=results[0],
        stages=tuple(results[1:]),
        settings=settings,
        building=snapshot.to_dict(),
        lineage=building.lineage_to_dict(),
        energy=energy,
        producer=producer,
    )
