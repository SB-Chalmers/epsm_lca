# Verification

## Current compatibility, 15 October 2026

LCA 0.2.0 is part of the Core/RC 0.3.0 and EPSM/Database 0.2.0 stabilization
candidate combination. The [compatibility manifest](https://github.com/SB-Chalmers/epsm/blob/dev/compatibility.json)
records source pins. [LCA compatibility PR 6](https://github.com/SB-Chalmers/epsm_lca/pull/6)
passed its installed-wheel matrix on Python 3.11 and 3.13, using both pinned
and supported `dev` Core/Data dependencies. It includes package and docstring
checks, five offline notebooks in fresh kernels, and API documentation checks.

[EPSM 0.2.0 verification PR 9](https://github.com/SB-Chalmers/epsm/pull/9) passed the
platform matrix, including three real annual RC states, complete renovation
assessments with explicit factors, and saved/reloaded source evidence. Each
platform run uploads exact revisions and installed versions. These results
establish software execution and evidence retention for the named runs, not
accuracy against measured buildings. Required imports fail when unavailable;
live provider acquisition and live national services are outside that route.

[LCA example PR 7](https://github.com/SB-Chalmers/epsm_lca/pull/7) declares the
required RC policies in the public annual helper. All seven notebooks also passed
locally in fresh Python 3.12 kernels with Core/RC 0.3.0 and EPSM 0.2.0, including
actual EnergyPlus 24.2. These example policies are modelling assumptions.

The numerical comparison below remains dated to its original versions. Core
height policy and RC recovery behavior affect energy outputs, so those old
numbers must not be presented as results for the current combination. LCA module
limits and assumed climate/removal factors still apply.

## Historical verification on 14 October 2026

The implementation is on `codex/building-renovation-lca`, version 0.2.0.

- **78 package tests passed** against the built, installed LCA/Core/Data wheels.
- **9 docstring examples passed** against the installed package.
- **9 existing EPSM checks passed** with the updated LCA implementation, including
  stable results, renovation paths, energy reuse and a real RC calculation.
- **All seven notebooks passed from fresh kernels**, first against the source
  implementation and then against the installed wheels. The last two include
  actual annual RC and EnergyPlus calculations, not mocked energy outputs.
- Ruff lint, formatting, local Markdown file links and `git diff --check` passed.
- The Sphinx API documentation built with warnings treated as errors.
- Statement coverage was **90.2%** and branch coverage **78.2%** for the installed
  package test suite. These percentages describe exercised code, not accuracy.

Package tests and notebooks used Python 3.13.5. Existing EPSM checks also ran in
the shared Python 3.12 environment. The installed-wheel checks used a temporary
environment sharing third-party libraries with the base environment; every EPSM
package import was checked to come from its newly installed wheel, with no
neighbouring source checkout on the import path.

The tested distributions were LCA 0.2.0, Core 0.2.0, Data 0.4.0, EPSM 0.1.0 and
RC 0.2.0. Actual EnergyPlus runs used 24.2.0-94a887817b. The
[engine comparison](engine-comparison.md) records their actual annual energy and
climate results, with sources, assumed factors and the shared weather identity.

The example CLI retains full engine files, annual carrier totals, assessment JSON
and comparison CSV in separate run folders. Plot exports were also rendered and
visually inspected. They show missing values explicitly and leave source data
unchanged.

The hosted workflow is prepared for Python 3.11 and 3.13 using pinned Core/Data
commits. It has not been run from this local branch. It requires read-only
`EPSM_DATA_DEPLOY_KEY` and `EPSM_CORE_DEPLOY_KEY` repository secrets; absent access
fails its prerequisite check. No release, merge or publication was performed.

The climate scope remains the declared renovation work and supplied energy.
Future replacements and final demolition are not inferred. Actual end-to-end
examples use Boverket material values, while carrier climate factors and window
removal factors are explicitly labelled assumptions. Successful software/engine
checks do not establish accuracy against measured buildings.

## Historical merge preparation on 15 October 2026

Examples and test buildings now select Core's illustrative reference preset
explicitly. Core's current development version leaves an unconfigured Building
empty; no physical inputs are inferred by LCA. The package and docstring checks
also pass against that current Core checkout (76 tests passed, with the two
optional plotting tests skipped because Matplotlib is absent there). All 78
package checks pass with plotting in the installed, previously tested wheel set.

The release workflow combines the installed-wheel tests, docstring examples,
five offline notebooks and documentation checks in one job per Python version.
It uses pinned Core and Data sources and dedicated read-only access.
