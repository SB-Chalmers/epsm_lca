# epsm_lca guide

Run commands from the repository root unless stated otherwise.

Calculate the climate impact of a building renovation, one step at a time.
Start with an `epsm_core.Building`, assign constructions from `epsm_data`, and
apply your renovation choices. LCA uses the recorded changes and your supplied
annual energy. It does not run an energy simulation.

The report shows the baseline and every renovation step: materials added and
removed, their impacts, material impact so far, energy impact, total impact and
savings compared with the baseline. Results are in **kg CO₂e**: climate impact
expressed as an equivalent mass of carbon dioxide.

**Version:** 0.3.0. Python 3.11 or newer. This is a climate assessment
of declared work and supplied energy, not a claim of complete building
certification. Future replacements, final demolition and dated operating periods
are not inferred.

## Install and start

Install alongside Core 0.9.0+ and Data 0.7.0+. These dependencies currently live in
private EPSM repositories; install their tested wheels first if they are not
available from your package index.

```sh
python -m pip install '.[examples]'
```

Start with the [five worked notebooks](../examples/README.md). They need no engine,
database or network once the packages are installed. They include embodied
(material) and operational (energy) impacts, with answers you can check by hand.

This short example explicitly selects Core’s illustrative building preset. Its
geometry, services and use assumptions are teaching inputs; replace them with
your own building information for a study.

```python
from epsm_core import Building
from epsm_data import reference_construction_set
from epsm_lca import AssessmentSettings, assess_renovation

baseline = Building(
    preset="illustrative-reference",
    construction_set=reference_construction_set(),
)
settings = AssessmentSettings(30, include_energy=False)
report = assess_renovation(baseline, settings)
print(report.table())
```

For your actual renovations:

```python
# windows and insulation are resolved renovation definitions from Data.
step_1 = baseline.renovate(windows)
step_2 = step_1.renovate(insulation)
report = assess_renovation(step_2, settings, energy=energy_by_step)
```

The second snippet shows the call shape; the notebooks provide the complete
window, insulation, factor and energy definitions. Set `include_energy=True`
when passing energy. To apply both changes together, use
`baseline.renovate(windows, insulation)` instead.

## Material impacts and removed quantities

By default, original materials are retained without charging again for their
original production. New work counts production, transport and installation;
removed materials count removal, transport, treatment and disposal. Select
`baseline="include"` if you also want original construction counted once.

`AssessmentSettings` selects the stages covered by the calculation. The default
selection is A1A3, A4, A5 and C1–C4. Each selected stage needs a factor for the
materials that actually pass through it. Factors come from Data's
`EnvironmentalFactor` records, in kg CO₂e per kg, m², m³ or item.

Inspect quantities separately from their impacts:

```python
report.stages[0].removed_quantities
report.quantities(action="removed", step=1, by_material=True)
report.quantities(action="added", by_material=True)
```

All available mass, volume, area and counts remain available even if an impact
factor is missing. Unknown quantities remain `None`, including when grouped.
Replacing the same windows twice counts two installations and two removals.

## Use Boverket values already held by Data

You do not need to re-enter Boverket Klimatdatabas values. Load your Data
catalogue explicitly, then use:

```python
settings = AssessmentSettings.from_building(
    step_2,
    period_years=30,
    catalogue=catalogue,
    production="conservative",  # Or "typical"; the choice is recorded.
    carrier_factors=carrier_factors,
)
```

This collects known factors throughout the renovation history, including removed
products. Material values already attached to Data materials also work without a
catalogue argument. Whole windows use their Boverket resource and its explicit
kg/m² conversion. Their unknown physical mass remains unknown.

Boverket's **A5.1 covers installation waste**, not the entire A5 stage. This helper
therefore selects A1A3, A4, A5.1 and C1–C4; it does not silently claim complete A5
coverage. The source, chosen production column and conversion remain recorded.
The bundled GWP-GHG AR4 values are used as supplied; biogenic timing is not added.
Missing removal factors and operating-energy factors still need your declared
sources. Add them through `material_factors` and `carrier_factors`.

[Notebook 5](../examples/05_use_catalogue_and_boverket.ipynb) demonstrates the actual
catalogue values and deliberately shows where broader coverage remains incomplete.

## Operational impacts

Supply annual delivered energy, not thermal demand. Keep heating carriers and
fan electricity separate when your source provides separate totals. State which
uses are included and where the numbers came from:

```python
from epsm_lca import AnnualEnergy

energy_by_step = {
    0: AnnualEnergy.for_building(
        baseline, delivered_by_carrier={"electricity": 10000},
        source="Teaching assumption; replace with measured or simulated totals",
    ),
    1: AnnualEnergy.for_building(
        step_1, delivered_by_carrier={"electricity": 9000},
        source="Teaching assumption; replace with measured or simulated totals",
    ),
    2: AnnualEnergy.for_building(
        step_2, delivered_by_carrier={"electricity": 8000},
        source="Teaching assumption; replace with measured or simulated totals",
    ),
}
```

Step 0 is the baseline. Each energy record is tied to the building state it
belongs to. The default covered uses are space heating and ventilation fans;
supply a different matching `boundary` and `energy_boundary` for other declared
uses. A carrier factor is in kg CO₂e/kWh and has the B6 stage label.

For every row, energy impact is annual kWh × years × the carrier's climate factor.
Total impact is **materials so far + this row's energy impact**. Savings is
**baseline total − this row's total**; positive means a reduction. Energy impacts
from different rows are comparisons and are never added together.

The teaching examples use a 0.1 kg CO₂e/kWh factor and 30 years. Baseline energy
is 30,000 kg CO₂e. After windows, total impact is 27,220 and savings are 2,780.
After insulation, total impact is 24,500 and savings are 5,500. Those energy
values are assumptions, not predicted energy savings. Substitute annual totals
from your measurement or simulation, and a sourced factor, for research use.

## Payback and per-area results

Each `report.table()` row also reports:

- `renovation_kgco2e`: material impact so far minus the baseline's.
- `annual_energy_saving_kgco2e`: the baseline's energy impact minus this row's,
  divided by the period.
- `carbon_payback_years`: renovation carbon ÷ annual energy saving. It is `None`
  when energy is excluded or unknown, or when the row does not save energy.
- `total_kgco2e_per_m2` and `total_kgco2e_per_m2_year`, when the settings have a
  reference area.

In the teaching example, windows add 220 kg CO₂e and save 100 kg a year, so they
pay back in 2.2 years; both steps add 500 kg and save 200 kg a year: 2.5 years.

Set `reference_area_m2` with a `reference_area_basis` that says what the area is,
for example `"Atemp"`. `AssessmentSettings.from_building` uses Core's conditioned
floor area, labelled as such, unless you pass your own. One area is used for every
row. `assess_renovation_cost(...).simple_payback_years(step)` gives the matching
undiscounted cost payback: stage costs through that step ÷ the annual operating
cost saving against the baseline.

## Missing inputs, saving and plotting

Missing factors, unknown quantities and unresolved physical edits leave totals
incomplete. Known quantities and contributions remain available. A missing
energy entry does not erase another step's result. Excluded energy is labelled
as excluded rather than reported as zero. Invalid inputs raise `ValueError`.

```python
print(report.summary())
print(report.stages[0].requirements)
report.save("renovation.json")
restored = type(report).load("renovation.json")
figure = report.plot()  # Requires the plot or examples extra.
figure.savefig("renovation.svg")
```

Saving writes UTF-8 JSON and refuses an existing file unless `overwrite=True`.
The parent directory must exist. Publication is atomic. Loading checks the
saved format, building history and accounting against the saved inputs. Choices,
factors, sources, quantities, building states and original producer versions are
retained. Returned dictionaries and lists are independent copies.

## Logging

The application chooses log output; the library never calls `basicConfig`, sets
levels or installs console/file handlers. For a notebook or small script:

```python
import logging

logging.basicConfig(level=logging.INFO)
```

The module loggers use the EPSM handbook fields `epsm_event`, `epsm_context` and
`epsm_details`. Assessment starts/finishes and saved reports use INFO, individual
step counts use DEBUG, missing inputs use WARNING, and rejected inputs use ERROR.
Duration uses a monotonic clock. Building records, full quantity lists and secrets
are not logged. Returned requirements remain the record of missing inputs.

## Checks and compatibility

```sh
python -m pip install '.[dev,examples,docs]'
python -m pytest tests --doctest-modules src/epsm_lca
ruff check src tests examples scripts
ruff format --check src tests examples scripts
python scripts/run_examples.py
python -m sphinx -b html -W --keep-going docs build/docs
```

The existing `assess(quantities, flows, energy, settings)` and `LCAResult` continue
to support EPSM automatic assessments. Valid unversioned 0.1 results remain
readable; missing old assessment details are labelled `unrecorded`.
See [migration notes](../docs/migration.md) and [calculation rules](../docs/calculation.md).

Development work starts from `dev` on a `codex/...` branch and returns through
review to `dev`. Stable releases go to `main` after release checks.
Maintainer contact: [repository issues](https://github.com/SB-Chalmers/epsm_lca/issues).
For a study, record this package version, the Data/Core versions, selected climate
sources and your actual annual energy sources. Software checks do not establish
accuracy against measured buildings.

EPSM-owned code and examples use the [MIT license](../LICENSE). Boverket and other
source-data terms remain attached to Data's records; the software license does
not change them.

## Actual end-to-end example

[Notebook 6](../examples/06_actual_energy_and_renovation.ipynb) and
[actual_renovation.py](../examples/actual_renovation.py) run real annual energy for the
baseline and both renovation steps. Install `.[integration,examples]`, then run
`python examples/actual_renovation.py --plot`. Each run retains its own engine
outputs, energy totals, comparison table and report. Material factors use Data's
Boverket values; removal and carrier climate factors are explicitly labelled
assumptions. The optional integration remains separate from the LCA calculation.

The hosted workflow builds and tests wheels with fixed Core/Data commits on
Python 3.11 and 3.13. Its private dependency check requires read-only
`EPSM_DATA_DEPLOY_KEY` and `EPSM_CORE_DEPLOY_KEY` repository secrets. Missing access
fails the check clearly. Actual RC runs are verified through the integration
example; the ordinary hosted job does not claim to have run that engine.

[Notebook 7](../examples/07_compare_energyplus_and_rc.ipynb) reruns both engines.
The [dated comparison](../docs/engine-comparison.md) records the actual results.
In this case RC gives about 14–19% higher delivered energy, while both engines
show substantial savings after window replacement and insulation.

The [verification record](../docs/verification.md) lists the checks that actually ran
and the remaining hosted-CI prerequisite.

## Operation logging

Library calls use Python's standard `logging` module and install no console or
file output. Instrumented operations accept optional keyword-only `log_context`
with small identifier mappings; nested events carry operation and parent IDs.
INFO describes major stages; DEBUG exposes selections, conversions and caches.
Logging context does not change physical models or scientific cache inputs.

For an application using EPSM's coordinated logging setup:

```python
from epsm import configure_logging, reset_logging

configure_logging(directory="outputs/example")  # INFO stderr, DEBUG JSONL
# Run operations here.
configure_logging(enabled=False)  # Stop console and file logging.
reset_logging()  # Restore the host application's settings.
```

EPSM is needed only for this combined configuration, not for ordinary library
logging. Existing scripts can keep using `logging.basicConfig(level=logging.INFO)`.
