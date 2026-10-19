import pytest
from curtailmit.schemas import ScenarioYearData


def test_valid_penetration():
    data = ScenarioYearData(solar_pct=12, wind_pct=14, total_generation_twh=836)
    assert data.penetration_pct == 26
    assert round(data.solar_wind_generation_twh, 1) == 217.4


def test_invalid_penetration_raises():
    with pytest.raises(ValueError):
        ScenarioYearData(solar_pct=60, wind_pct=60, total_generation_twh=800)
