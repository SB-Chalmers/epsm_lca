# Worked building renovation examples

Read the notebooks in order. Each runs independently and uses the shared,
explicit input definitions in [teaching_case.py](teaching_case.py). That file
only constructs inputs and formats a table; all climate calculations use the
installed package.

| Notebook | What you learn |
| --- | --- |
| [01 Baseline](01_understand_the_baseline.ipynb) | Build with Core, assign Data constructions, inspect known quantities |
| [02 One step](02_one_renovation_step.ipynb) | Replace windows and add insulation together; material and operational impacts |
| [03 Two steps](03_two_renovation_steps.ipynb) | Calculate each step, cumulative materials and baseline savings |
| [04 Missing inputs](04_missing_inputs_and_saved_results.ipynb) | Keep removed quantities, inspect missing factors and save/reload a report |
| [05 Catalogue and Boverket](05_use_catalogue_and_boverket.ipynb) | Use real Data factors, source references and window area conversions |

Use Python 3.11+, LCA 0.2.0, Core 0.3.0 and Data 0.4.0. Install the tested private
Core/Data distributions first, then `python -m pip install '.[examples]'` from
the LCA repository. Select that Python environment as your notebook kernel.
Start the kernel in this `examples/` folder so `teaching_case.py` is available.
No neighbouring checkout, database, engine or network access is needed.

Notebooks 1–4 use invented construction/factor/energy inputs. Each selected factor
is declared and the answers are explained by hand. Notebook 5 explicitly loads
the bundled Data catalogue and uses Boverket version 02.07.000, GWP-GHG AR4.
It preserves the conservative/typical choice and the source's quantity basis.
It does not present A5.1 installation waste as the full A5 stage.

Operational energy in notebooks 2–4 is **supplied annual delivered energy** for
space heating and ventilation fans. It is not calculated by an engine. Replace
those annual values and the energy factors with your project sources. Material
and energy impacts are shown separately and combined for each building state.

Restart and run all cells. Each notebook asserts its expected answers. To run all
five with fresh kernels: `python scripts/run_examples.py` from the repository
root. The runner uses the current Python and writes executed copies only under
`build/executed-examples/`. Saved-report examples use temporary directories and
clean up afterwards; no persistent study files are overwritten.

## Actual end-to-end results

[06 Actual energy and renovation](06_actual_energy_and_renovation.ipynb) runs real
annual RC energy calculations for the baseline, window replacement and added
wall insulation, then passes those outputs into LCA. It uses Data's Existing and
Advanced products with Boverket factors. The electricity/district-heating climate
factors and window-removal factors are clearly labelled assumptions.

Install the `integration` and `examples` extras as well. The integration extra
needs private EPSM 0.2.0+ and RC 0.3.0+. The helper explicitly selects
`epsm_rc_5r1c_v1`, `sensible_only_unlimited_supply` airflow and
`conductance_multiplier` ground treatment. These are modelling assumptions. Their bundled Gothenburg EPW supplies the
weather; no service or EnergyPlus installation is needed for the RC route.
Run all six notebooks with `python scripts/run_examples.py --integration`.

The same case is available as a script:

```sh
python examples/actual_renovation.py --plot
```

Each invocation creates a separate run folder under `outputs/actual-renovation/`.
It keeps weather, engine outputs, EPSM evaluations, annual carrier totals,
`renovation.json`, `comparison.csv`, and an optional SVG plot. An optional
`--engine energyplus --weather path/to/weather.epw` uses your installed EnergyPlus;
it does not replace a missing engine with made-up results.

[07 Compare EnergyPlus and RC](07_compare_energyplus_and_rc.ipynb) reruns both
engines with the same weather, constructions, changes and climate factors. It
requires EnergyPlus 24.2. Set `ENERGYPLUS_EXE` to your executable before starting
the kernel, or pass `energyplus_exe` to `run_case`. Run all seven with
`python scripts/run_examples.py --energyplus`. The CLI also accepts
`--engine energyplus --energyplus-exe path/to/energyplus`.

The exact verification results from 14 October 2026 are retained in
[engine_comparison.json](results/engine_comparison.json). This is a dated result
record, not a live test or a claim that the engines are equally accurate.
