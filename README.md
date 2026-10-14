# EPSM LCA

Apply sourced environmental factors to physical material occurrences and annual
delivered energy. The package owns assessment methods; `epsm_data` owns the
reusable `EnvironmentalFactor` records. `epsm.Building.simulate()` calls this
package automatically after the energy calculation.

Install alongside EPSM Data: `python -m pip install .` (Python 3.11+). Run tests
with `python -m pytest tests`. EPSM-owned code uses MIT; see LICENSE.

## Explicit assessment boundary

`AssessmentSettings` requires a positive reference period, an energy boundary,
baseline treatment (`retained` or `include`), and selected material modules.
Material factors map material identity → module → factor. Carrier factors use
kgCO2e/kWh and module B6. Every factor carries a source.

```python
from epsm_data import EnvironmentalFactor
from epsm_lca import AssessmentSettings

settings = AssessmentSettings(
    period_years=30,
    energy_boundary="space_heating_and_fans",
    baseline="retained",
    material_modules=("A1A3",),
    material_factors={},  # Add sourced factors for every installed material.
    carrier_factors={},  # Add sourced B6 factors for every delivered carrier.
)
```

`assess(quantities, flows, energy, settings)` returns an `LCAResult`. Missing
factors or unsupported energy boundaries yield `status='incomplete'` and a
`None` total. Known contributions and requirements remain inspectable.
`result.summary()` and `settings.summary()` provide compact inspection. Saved
result contributions and `to_dict()` outputs are independent copies; editing
them does not rewrite the assessment. No missing
quantity or impact is replaced by zero. Nonfinite calculated contributions or
totals also make the assessment incomplete, with finite known contributions
retained for inspection.

Installations are assessed once per actual transition, including like-for-like
replacement. Retained baseline materials are not repeatedly procured. `include`
requires the original baseline inventory after renovations. Each reached state
supplies operational energy over the same explicit reference period. Ancestor
states receive no invented operating years.

Supported modules are A1A3, A4, A5 for installations and C1–C4 for actual removals,
plus operational B6. Future replacements, biogenic timing, end-of-period
demolition, certification compliance and cost calculations are not inferred.
The result is a GWP assessment within its declared boundary, not automatically
a complete standardized whole-building LCA.
