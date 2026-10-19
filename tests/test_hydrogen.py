import pandas as pd
import pytest

from curtailmit.hydrogen import compute_hydrogen_potential


def test_compute_hydrogen_potential_ordering():
    mitigation = pd.DataFrame({"scenario": ["TB"], "year": [2025], "E_curt_twh": [10.0]})
    result = compute_hydrogen_potential(mitigation, sec_min=50, sec_central=52.5, sec_max=55)
    row = result.iloc[0]
    assert row["h2_potential_min_kg"] <= row["h2_potential_central_kg"] <= row["h2_potential_max_kg"]


def test_compute_hydrogen_potential_unit_conversion():
    mitigation = pd.DataFrame({"scenario": ["TB"], "year": [2025], "E_curt_twh": [1.0]})
    result = compute_hydrogen_potential(mitigation, sec_min=50, sec_central=50, sec_max=50)
    expected_kg = 1.0 * 1e9 / 50
    assert abs(result.iloc[0]["h2_potential_central_kg"] - expected_kg) < 1e-6


def test_invalid_sec_ordering_raises():
    mitigation = pd.DataFrame({"scenario": ["TB"], "year": [2025], "E_curt_twh": [1.0]})
    with pytest.raises(ValueError):
        compute_hydrogen_potential(mitigation, sec_min=55, sec_central=52.5, sec_max=50)
