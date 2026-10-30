# Time-varying energy factors and prices

Delivered grid energy, such as district heating and electricity, can carry carbon
factors (B6) and prices that change through the year. Both use one record,
`FactorProfile`, in four forms:

| Form | Values | Constructor |
|---|---|---|
| constant | 1 | `FactorProfile.constant(v, unit, source)` |
| weekday / weekend | 24 + 24 hours | `FactorProfile.weekday_weekend(weekday, weekend, unit, source)` |
| monthly | 12 | `FactorProfile.monthly(values, unit, source)` |
| hourly | 8760 | `FactorProfile.hourly(values, unit, source)` |

Every form expands onto one 8760-hour calendar year. The default year is 2025;
leap years are not supported. Hour 0 is 00:00–01:00 on 1 January, local standard
time. Monday to Friday count as weekdays, and public holidays are not distinguished.
Carbon profiles are in `kgCO2e/kWh`; price profiles are in `<currency>/kWh`.

```python
grid = FactorProfile.weekday_weekend(weekday24, weekend24, "kgCO2e/kWh", "source")
heat = FactorProfile.monthly(monthly12, "kgCO2e/kWh", "source")
settings = AssessmentSettings(50, carrier_factors={"electricity": grid, "district_heating": heat})

energy = AnnualEnergy.from_hourly(building, hourly_by_carrier={
    "electricity": kwh_8760, "district_heating": kwh_8760}, source="EnergyPlus run")
result = assess_renovation(building, settings, energy={0: energy})

costs = CostSettings.from_catalogue(renovations, period_years=50, carrier_prices={
    "electricity": FactorProfile.hourly(spot_8760, "SEK/kWh", "source"),
    "district_heating": FactorProfile.monthly(tariff12, "SEK/kWh", "source")})
operating = assess_renovation_cost(building, costs, energy={0: energy}).operating
```

## Weighting rules

- With hourly delivered energy, the annual value is the sum of each hour's energy
  times that hour's factor.
- With annual energy only, a varying profile is reported as a missing input,
  because its weighting is unknown. Set `flat_profile_for_annual_energy=True` to
  use the profile's time average instead. Each contribution is then labelled as a
  flat-demand approximation.
- Constant factors, including the existing `EnvironmentalFactor` B6 records, work
  with either kind of energy.

Operating cost is reported for every state that has supplied energy: annual cost
by carrier, and the period total (`period_years` × annual). No discounting or price
escalation is applied.

## From a simulation run to delivered energy

Core converts one run into hourly purchased and exported energy per carrier
(`district_heating`, `electricity`, `fuel`) from the building's declared delivery:

```python
from epsm_core.delivered import delivered_energy

delivered = delivered_energy(result, building, dhw_carrier="district_heating")
energy = AnnualEnergy.from_delivered(building, delivered, source="EnergyPlus run")
settings = AssessmentSettings(50, energy_boundary=energy.boundary, carrier_factors=...)
```

- **Space heating:** carrier input from `HeatingDeliverySpec` (district heat,
  direct electric, heat pump or fuel, with losses, efficiency and COP).
- **Fans:** electricity, when a specific fan power is declared.
- **Exhaust-air heat pump:** its electricity, plus backup heat on the carrier you
  state with `fvp_backup_carrier`.
- **Domestic hot water:** inside the boundary only when you state `dhw_carrier`
  (and `dhw_efficiency`, which is above 1 for a heat pump).
- **Boundary:** the covered uses become the energy boundary, for example
  `space_heating_fans_and_dhw`. The assessment settings must use the same boundary.
- **PV:** generation is used on site in the hour it is produced, up to the covered
  electricity use. The surplus is recorded as exported electricity. Electricity
  outside the boundary (household or property electricity) is not offset.
- **Export, carbon:** the credit is reported by `export_credit()` as module D
  (avoided grid electricity at the electricity profile). It is never added to B6
  or to combined totals.
- **Export, cost:** `CostSettings(export_prices=...)` credits export revenue in the
  operating cost. Exports without a price leave the operating cost incomplete.

## Factors and prices that change from year to year

A `FactorTrajectory` holds one `FactorProfile` per year of the assessment period,
for example a grid that decarbonises or a scenario of energy prices. Year 1 is the
first year of the period, and a partial last year counts for its share.

```python
from epsm_lca import FactorTrajectory

grid = FactorTrajectory.from_values(
    [0.10 - 0.002 * year for year in range(30)], "kgCO2e/kWh", "Scenario source"
)
settings = AssessmentSettings(30, carrier_factors={"electricity": grid})
```

- The trajectory must cover every year of the period; later years are never
  extrapolated, and a shorter trajectory is rejected.
- Each year can itself be a weekday/weekend, monthly or hourly profile; those
  still need hourly delivered energy unless the flat approximation is allowed.
- B6 contributions list `yearly_gwp_kgco2e`. Carbon payback then follows the
  yearly savings and is `None` when they do not repay within the period.
- As a price, a trajectory needs `period_years`. `price_escalation` must be 0,
  since the trajectory already states each year's price. Operating costs list
  `yearly` costs, discounted year by year; paybacks follow them.
