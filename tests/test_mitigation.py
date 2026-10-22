import pandas as pd
import pytest

from curtailmit.mitigation import DEFAULT_MARGINAL_PROXY_NO_CLASSIFICATION, compute_mitigation


def _fixtures():
    projection = pd.DataFrame({
        "scenario": ["TB", "TA"],
        "year": [2025, 2025],
        "E_curt_twh": [10.0, 12.0],
    })
    avg_factor = pd.DataFrame({"year": [2025], "factor_tco2_per_mwh": [0.1]})
    marginal_factor = pd.DataFrame({"year": [2025], "om_factor": [0.15], "cm_factor": [0.12]})
    return projection, avg_factor, marginal_factor


def test_compute_mitigation_classified():
    projection, avg, marg = _fixtures()
    result = compute_mitigation(projection, avg, marg, classification_available=True)
    assert {"mitigation_deficit_avg_tco2", "mitigation_deficit_marginal_tco2"}.issubset(result.columns)
    assert result.loc[0, "mitigation_deficit_avg_tco2"] == 10.0 * 1e6 * 0.1
    assert "classified" in result.loc[0, "marginal_proxy_used"]


def test_compute_mitigation_unclassified_fallback():
    projection, avg, marg = _fixtures()
    result = compute_mitigation(projection, avg, marg, classification_available=False)
    assert (result["marginal_proxy_used"] == DEFAULT_MARGINAL_PROXY_NO_CLASSIFICATION).all()
    assert (result["classification_available"] == False).all()


def test_missing_average_factor_raises():
    projection, avg, marg = _fixtures()
    avg_missing = avg[avg["year"] != 2025]
    with pytest.raises(ValueError):
        compute_mitigation(projection, avg_missing, marg, classification_available=True)
