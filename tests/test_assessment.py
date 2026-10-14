from types import SimpleNamespace as NS

import pytest

from epsm_data import EnvironmentalFactor as Factor
from epsm_lca import AssessmentSettings, assess


def row(identity="wood", mass=10):
    return NS(material_id=identity, occurrence_id=identity, mass_kg=mass,
              volume_m3=None, area_m2=2, count=None)


def settings(**changes):
    values = dict(period_years=30, energy_boundary="space_heating_and_fans",
                  baseline="retained", material_modules=("A1A3",),
                  material_factors={"wood": {"A1A3": Factor(2, "kg", "A1A3", "test")}},
                  carrier_factors={"electricity": Factor(.1, "kWh", "B6", "test")})
    values.update(changes)
    return AssessmentSettings(**values)


def energy():
    return NS(delivered_by_carrier={"electricity": 100}, complete=True,
              boundary="space_heating_and_fans", annual=True)


def test_path_counts_each_installation_and_never_retained_inventory():
    flow = NS(installed=(row(),), removed=(row(),), retained=(row(),))
    result = assess((row(),), (flow, flow), energy(), settings())
    assert result.complete
    assert result.material_gwp_kgco2e == 40
    assert result.operational_gwp_kgco2e == 300
    assert result.total_gwp_kgco2e == 340


def test_missing_factor_is_incomplete_with_no_total():
    result = assess((row(),), (), energy(), settings(baseline="include", material_factors={}))
    assert not result.complete
    assert result.total_gwp_kgco2e is None
    assert "wood" in " ".join(result.requirements)


def test_unknown_mass_cannot_be_zero_and_wrong_boundary_rejected():
    result = assess((row(mass=None),), (), energy(), settings(baseline="include"))
    assert result.material_gwp_kgco2e is None
    result = assess((), (), energy(), settings(energy_boundary="whole_building"))
    assert result.total_gwp_kgco2e is None


def test_factor_updates_only_change_assessment_and_roundtrip_settings():
    config = settings()
    assert AssessmentSettings.from_dict(config.to_dict()) == config
    result = assess((), (), energy(), config)
    assert type(result).from_dict(result.to_dict()) == result


@pytest.mark.parametrize("period", [0, -1, float("nan")])
def test_invalid_period(period):
    with pytest.raises(ValueError):
        settings(period_years=period)
