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
