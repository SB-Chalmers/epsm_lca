"""Time-varying carbon factors and energy prices on hourly or annual delivered energy."""

import json
import math

import pytest
from epsm_core import Building
from epsm_data import EnvironmentalFactor

from epsm_lca import (
    AnnualEnergy,
    AssessmentSettings,
    CostSettings,
    FactorProfile,
    RenovationResult,
    assess_renovation,
    assess_renovation_cost,
)

UNIT = "kgCO2e/kWh"
WEEKDAY = [0.04] * 7 + [0.08] * 15 + [0.04] * 2
WEEKEND = [0.03] * 24
MONTHLY = [0.09, 0.09, 0.08, 0.06, 0.04, 0.03, 0.03, 0.03, 0.04, 0.06, 0.08, 0.09]
HEAT = [3.0 if h // 24 < 120 or h // 24 > 280 else 0.5 for h in range(8760)]
POWER = [1.0 + (h % 24 > 16) for h in range(8760)]


def test_every_form_expands_onto_one_calendar_year():
    week = FactorProfile.weekday_weekend(WEEKDAY, WEEKEND, UNIT, "s")
    # 2025-01-01 is a Wednesday; 2025-01-04 is a Saturday.
    assert week.hourly_values[8] == 0.08 and week.hourly_values[72 + 8] == 0.03
    month = FactorProfile.monthly(MONTHLY, UNIT, "s")
    assert month.hourly_values[743] == 0.09 and month.hourly_values[24 * 59] == 0.08
    assert FactorProfile.constant(0.1, UNIT, "s").hourly_values == (0.1,) * 8760
    hourly = FactorProfile.hourly(range(8760), "SEK/kWh", "s")
    assert hourly.apply([1.0] * 8760) == pytest.approx(8759 * 8760 / 2)
    assert FactorProfile.from_dict(json.loads(json.dumps(week.to_dict()))) == week
    with pytest.raises(ValueError, match="needs 12"):
        FactorProfile.monthly([0.1] * 11, UNIT, "s")
    with pytest.raises(ValueError, match="non-leap"):
        FactorProfile.monthly(MONTHLY, UNIT, "s", year=2024)
    with pytest.raises(ValueError, match="per delivered kWh"):
        FactorProfile.constant(0.1, "kgCO2e", "s")


def test_hourly_energy_must_match_its_annual_totals():
    building = Building(preset="illustrative-reference")
    energy = AnnualEnergy.from_hourly(building, hourly_by_carrier={"electricity": POWER},
                                      source="synthetic")
    assert energy.delivered_by_carrier["electricity"] == pytest.approx(sum(POWER))
    assert AnnualEnergy.from_dict(json.loads(json.dumps(energy.to_dict()))) == energy
    with pytest.raises(ValueError, match="do not sum"):
        AnnualEnergy.for_building(building, delivered_by_carrier={"electricity": 1.0},
                                  hourly_by_carrier={"electricity": POWER}, source="s")
    with pytest.raises(ValueError, match="8760"):
        AnnualEnergy.from_hourly(building, hourly_by_carrier={"electricity": [1.0] * 24},
                                 source="s")


def test_carbon_weights_hourly_energy_and_refuses_unweighted_annual_energy(tmp_path):
    building = Building(preset="illustrative-reference")
    hourly = AnnualEnergy.from_hourly(building, hourly_by_carrier={
        "district_heating": HEAT, "electricity": POWER}, source="synthetic")
    grid = FactorProfile.weekday_weekend(WEEKDAY, WEEKEND, UNIT, "synthetic grid")
    heat = FactorProfile.monthly(MONTHLY, UNIT, "synthetic district heating")
    settings = AssessmentSettings(30, material_modules=("A1A3",),
                                  carrier_factors={"electricity": grid, "district_heating": heat})
    step = assess_renovation(building, settings, energy={0: hourly}).baseline
    expected = 30 * (grid.apply(POWER) + heat.apply(HEAT))
    assert step.energy_kgco2e == pytest.approx(expected)
    assert step.energy_kgco2e != pytest.approx(30 * (grid.mean * sum(POWER) + heat.mean * sum(HEAT)))
    path = RenovationResult.save(assess_renovation(building, settings, energy={0: hourly}),
                                 tmp_path / "result.json")
    assert RenovationResult.load(path).baseline.energy_kgco2e == pytest.approx(expected)

    annual = AnnualEnergy.for_building(building, delivered_by_carrier={
        "district_heating": sum(HEAT), "electricity": sum(POWER)}, source="annual")
    gap = assess_renovation(building, settings, energy={0: annual}).baseline
    assert gap.energy_kgco2e is None and len(gap.requirements) == 2
    flat = AssessmentSettings(30, material_modules=("A1A3",), flat_profile_for_annual_energy=True,
                              carrier_factors={"electricity": grid, "district_heating": heat})
    approx = assess_renovation(building, flat, energy={0: annual}).baseline
    assert approx.energy_kgco2e == pytest.approx(
        30 * (grid.mean * sum(POWER) + heat.mean * sum(HEAT)))
    assert {c["factor_basis"] for c in approx.contributions if "carrier" in c} == {
        "flat-demand approximation of a monthly profile",
        "flat-demand approximation of a weekday_weekend profile"}
    constant = AssessmentSettings(30, material_modules=("A1A3",), carrier_factors={
        "electricity": EnvironmentalFactor(0.05, "kWh", "B6", "s"),
        "district_heating": FactorProfile.constant(0.06, UNIT, "s")})
    assert assess_renovation(building, constant, energy={0: annual}).baseline.energy_kgco2e == (
        pytest.approx(30 * (0.05 * sum(POWER) + 0.06 * sum(HEAT))))
    assert AssessmentSettings.from_dict(json.loads(json.dumps(flat.to_dict()))) == flat


def test_operating_cost_uses_prices_of_any_form():
    building = Building(preset="illustrative-reference")
    energy = AnnualEnergy.from_hourly(building, hourly_by_carrier={
        "district_heating": HEAT, "electricity": POWER}, source="synthetic")
    spot = FactorProfile.hourly([0.6 + 0.4 * math.sin(h / 24 * 2 * math.pi) for h in range(8760)],
                                "SEK/kWh", "synthetic spot")
    tariff = FactorProfile.monthly([1.0] * 3 + [0.6] * 6 + [1.0] * 3, "SEK/kWh", "synthetic tariff")
    settings = CostSettings({}, carrier_prices={"electricity": spot, "district_heating": tariff},
                            period_years=30)
    operating = assess_renovation_cost(building, settings, energy={0: energy}).operating[0]
    assert operating.annual == pytest.approx(spot.apply(POWER) + tariff.apply(HEAT))
    assert operating.period == pytest.approx(30 * operating.annual)
    missing = CostSettings({}, carrier_prices={"electricity": spot}, period_years=30)
    gap = assess_renovation_cost(building, missing, energy={0: energy}).operating[0]
    assert gap.annual is None and "district_heating: energy price is missing" in gap.requirements
    with pytest.raises(ValueError, match="SEK/kWh"):
        CostSettings({}, carrier_prices={"electricity": FactorProfile.constant(1, "EUR/kWh", "s")})
