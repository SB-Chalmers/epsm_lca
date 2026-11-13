# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Factor coverage and source mix of a saved renovation step.

Coverage says how much of a step's added and removed work has a factor for each
selected module, and which kinds of source its known impacts rest on. It never
fills a missing factor; it reports the share that is missing.
"""

from __future__ import annotations

from ._validation import text

SOURCE_KINDS = ("epd", "reference", "proxy", "boverket", "other")
PARTS = {"B4": "replacement", "B6": "energy"}


def source_kind(source):
    """Classify a factor source by where its value comes from.

    Data's ``CarbonReference`` writes ``identifier | method | url`` and adds
    ``proxy for: ...`` when the record stands in for another product; EPDs are
    references whose identifier starts with ``EPD``. ``Boverket`` resources are
    the climate database's generic values. Anything else, such as a factor
    typed in by hand, is ``other``.

    Examples
    --------
    >>> source_kind("EPD-IES-0005222:003 | GWP-GHG; EN 15804 | https://example.org")
    'epd'
    >>> source_kind("Boverket 1234; version 2024; GWP-GHG AR4")
    'boverket'
    """
    text(source, "factor source")
    if "proxy for:" in source:
        return "proxy"
    if source.startswith("Boverket "):
        return "boverket"
    if " | " in source:
        return "epd" if source.upper().startswith("EPD") else "reference"
    return "other"


def part_of(record):
    """Material (A and C modules), replacement (B4) or energy (B6)."""
    return PARTS.get(record.get("module"), "material")


def step_coverage(row, modules):
    """Factor coverage of one saved step, per selected material module.

    A modules apply to added work and C modules to removed work. For each
    module the record counts the occurrences with a contribution and the mass
    they represent, against all occurrences of that action. Occurrences with
    unknown mass are counted separately, so a mass share never pretends to
    cover them; shares are None when there is nothing to cover.
    """
    covered = {}
    for record in row["contributions"]:
        if part_of(record) == "material":
            covered.setdefault(record["module"], set()).add(record["occurrence_id"])
    result = []
    for module in modules:
        action = "added" if module.startswith("A") else "removed"
        rows = row[f"{action}_quantities"]
        ids = covered.get(module, set())
        known = [r for r in rows if r["mass_kg"] is not None]
        mass = sum(r["mass_kg"] for r in known)
        covered_mass = sum(r["mass_kg"] for r in known if r["occurrence_id"] in ids)
        hits = sum(1 for r in rows if r["occurrence_id"] in ids)
        result.append(
            dict(
                step=row["step"],
                module=module,
                action=action,
                occurrences=len(rows),
                covered_occurrences=hits,
                occurrence_share=None if not rows else hits / len(rows),
                mass_kg=mass,
                covered_mass_kg=covered_mass,
                mass_share=None if not known else covered_mass / mass if mass else None,
                mass_unknown_occurrences=len(rows) - len(known),
            )
        )
    return result


def source_mix(row):
    """Known impact of one saved step by part and source kind.

    Returns ``{part: {"total_kgco2e", "by_source_kind", "share_by_source_kind"}}``
    for the material, replacement and energy parts that have contributions.
    Shares are of the part's known total and None when that total is zero.
    """
    totals = {}
    for record in row["contributions"]:
        part = totals.setdefault(part_of(record), {})
        kind = source_kind(record["source"])
        part[kind] = part.get(kind, 0.0) + record["gwp_kgco2e"]
    return {
        part: {
            "total_kgco2e": sum(values.values()),
            "by_source_kind": dict(values),
            "share_by_source_kind": {
                kind: None if not sum(values.values()) else value / sum(values.values())
                for kind, value in values.items()
            },
        }
        for part, values in totals.items()
    }


def report_coverage(report):
    """Coverage and source mix for every step of a saved report."""
    modules = report["settings"]["material_modules"]
    return [
        dict(
            step=row["step"],
            status=row["status"],
            modules=step_coverage(row, modules),
            sources=source_mix(row),
        )
        for row in (report["baseline"], *report["stages"])
    ]
