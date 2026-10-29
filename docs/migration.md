# Moving from 0.3 to 0.4

Saved settings now use `epsm-lca-settings/2` and renovation reports use
`epsm-lca-renovation/2`. Older settings and reports are not read; rerun the
assessment to produce them again. Settings gain the optional
`reference_area_m2` and `reference_area_basis`.

# Moving from 0.1 to 0.2

Existing EPSM calls to `assess` keep their argument order and result attribute
names. AssessmentSettings also keeps its original positional fields; omitted
choices now have documented renovation defaults. `include_energy` is an
additional field. Settings mappings are copied and read-only, and `deepcopy`
and `dataclasses.replace` continue to work.

For new standalone use, prefer `assess_renovation(building, settings, energy=...)`.
It extracts Core's recorded path and returns baseline and per-step results.
`AnnualEnergy.for_building` captures the state and supplied annual totals. It does
not run an engine or guarantee the supplied totals are correct.

Malformed flow records now raise ValueError. Missing installed/removed fields no
longer mean zero work. Wrong types, boolean quantities, nonfinite input totals and
contradictory completion claims are rejected. Missing scientific inputs still
produce inspectable incomplete results.

Valid unversioned 0.1 LCAResult dictionaries and settings remain readable.
LCAResult reports `context_status='unrecorded'` for old results without assessment
settings; no period or source is invented. New LCAResult dictionaries use
`epsm-lca-result/2`, settings use `epsm-lca-settings/1`, annual energy uses
`epsm-lca-energy/1`, and complete renovation reports use `epsm-lca-renovation/1`.
Unknown formats are rejected rather than guessed.

Renovation report files retain the building and ordered history, factor values,
covered stages, supplied energy, source descriptions, quantities and original
producer versions. Loading verifies the climate answers against those saved
inputs without accessing a catalogue, running energy or rewriting the file.
Old single-state results cannot recover an unrecorded full renovation report.

Core is now a declared runtime dependency, since the new main interface accepts
its Building directly. Plotting, notebook and documentation tools remain optional
extras. The package configures no logging handlers or levels.
