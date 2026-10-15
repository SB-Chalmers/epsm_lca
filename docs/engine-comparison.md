# Actual renovation comparison: EnergyPlus and RC

This is a historical comparison. Its version-specific results are retained as
evidence of that run; they are not current stabilization reference values. See
[verification](verification.md) for current compatibility checks.

Verified locally on 14 October 2026 with EnergyPlus 24.2.0, Core 0.2.0, Data 0.4.0
and LCA 0.2.0. The case uses Core's illustrative 20 × 12 m, three-storey geometry,
Data's 1960 multi-family Existing construction set, Advanced windows, then the
Advanced outer-wall insulation component. HVAC and operation remain the declared
reference assumptions. The same bundled Gothenburg EPW was used for both engines.

| Building state | EnergyPlus kWh/year | RC kWh/year | RC higher by |
| --- | ---: | ---: | ---: |
| Baseline | 78,302.76 | 92,807.60 | 18.52% |
| After windows | 70,256.72 | 83,794.75 | 19.27% |
| After insulation | 30,511.12 | 34,846.26 | 14.21% |

Both engines show approximately 10% less annual delivered energy after window
replacement, and approximately 60% less after both changes. Their absolute
energy values differ materially. This result does not establish accuracy against
measurements or make the two engines interchangeable.

| State | Materials so far, kg CO₂e | EnergyPlus total, kg CO₂e | RC total, kg CO₂e |
| --- | ---: | ---: | ---: |
| Baseline | 0.00 | 122,421.05 | 144,178.32 |
| After windows | 11,253.77 | 121,605.78 | 141,912.82 |
| After insulation | 26,182.54 | 76,916.13 | 83,418.85 |

Final climate savings are 45,504.92 kg CO₂e with EnergyPlus and 60,759.48 with RC.
These totals cover each state over 30 years, with Boverket conservative A1A3, A4
and A5.1 values plus explicit assumed window-removal factors. District-heating
and electricity climate factors are assumed at 0.05 and 0.1 kg CO₂e/kWh; each
window removal stage is assumed at 0.5 kg CO₂e/m². They are not sourced operating
or removal values from Boverket. Material quantities and impacts match between
engines; the different operational results explain the total differences.

Notebook 7 reruns this comparison and preserves new engine outputs and reports.
The exact dated outputs, assumptions and weather checksum are retained in
`examples/results/engine_comparison.json`. The complete local run directories
also contain the engine diagnostics, annual carrier totals and reloadable
assessment reports. New executions always get separate directories.
