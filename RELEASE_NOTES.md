# LCA 0.3.0 — renovation cost and time-varying energy (29 October 2026)

`assess_renovation_cost` prices renovation stages from the catalogue's cost
estimates and supplied energy. Carrier carbon factors and prices accept constant,
weekday/weekend, monthly or 8760-hour `FactorProfile`s. `AnnualEnergy.from_delivered`
takes Core's delivered energy with exports; `export_credit` reports module D
outside the totals. External `CarbonReference` declarations are read beside
Boverket factors for materials, windows and installed products. Requires Data 0.7.0
(the renovation catalogue and `epsm_data.contract`) and Core 0.9.0.

# Release 0.2.0 — 15 October 2026

Assessment and renovation operation context, completion status/counts, durations and report persistence.

Libraries emit through Python's standard logging without configuring output.
Instrumented operations accept optional keyword-only `log_context`; identifiers
stay separate from scientific inputs, saved models and cache keys. INFO shows
major stages; DEBUG adds decisions and timing. Standalone commands support
`--log-level`, including `OFF`, where the package provides a command.

The EPSM application configures the combined stderr and optional DEBUG JSONL
output with `configure_logging`; `enabled=False` disables both destinations.
Existing callers and supported older collaborator signatures remain supported.
No new mandatory dependency is introduced by the logging implementation.

The coordinated release was requested for manual review and local validation
because GitHub refused to start several hosted jobs due to account billing.
Hosted checks that did not run are not counted as passes. See the
[coordinated verification record](https://github.com/SB-Chalmers/epsm_development/blob/main/docs/logging-verification.md)
for exact tested revisions, executed checks and remaining limitations.
