"""Smoke tests for the reusable helpers of the Task 11E4 throwaway analysis scripts (analysis/, outside the package; synthetic data only)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))
import task11e4_conformal_prediction as cp
import task11e4_ne_hourly as ne
import task11e4_subhourly_feasibility as sh


def test_conformal_quantile_obeys_the_finite_sample_rule():
    ones = lambda n: np.ones(n)
    s = lambda n: np.arange(1.0, n + 1)
    assert cp.weighted_quantile_conformal(s(4), ones(4), 1.0, 0.2) == 4.0  # ceil(5 x 0.8) = 4 <= 4
    assert np.isinf(cp.weighted_quantile_conformal(s(3), ones(3), 1.0, 0.2))  # ceil(4 x 0.8) = 4 > 3: unbounded
    assert cp.weighted_quantile_conformal(s(9), ones(9), 1.0, 0.1) == 9.0  # ceil(10 x 0.9) = 9
    assert np.isinf(cp.weighted_quantile_conformal(s(8), ones(8), 1.0, 0.1))
    assert cp.weighted_quantile_conformal(s(20), ones(20), 1.0, 0.2) == 17.0  # ceil(21 x 0.8) = 17: the 17th smallest of 20


def test_conformal_empirical_coverage_on_exchangeable_data():
    rng = np.random.default_rng(4)
    hits, trials = 0, 400
    for _ in range(trials):
        cal, test = np.abs(rng.normal(size=30)), abs(rng.normal())
        hits += int(test <= cp.weighted_quantile_conformal(cal, np.ones(30), 1.0, 0.2))
    assert hits / trials >= 0.77  # nominal 0.80, binomial slack


def test_quarter_weights_give_every_quarter_unit_mass_and_ess_is_bounded():
    df = pd.DataFrame({"test_quarter": ["a", "a", "a", "b"], "err_log": [0.1, 0.2, 0.3, 0.4]})
    w = cp.quarter_weights(df)
    assert np.isclose(w.sum(), 2.0) and np.isclose(w[:3].sum(), 1.0)
    assert np.isclose(cp.ess(np.ones(10)), 10.0) and cp.ess(np.array([1.0, 0.0, 0.0])) == 1.0
    assert cp.plain_weighted_quantile(np.array([1.0, 2.0, 3.0, 4.0]), np.ones(4), 0.5) == 2.0


def test_subhourly_series_builds_the_share_of_load_and_the_hourly_aggregation():
    idx = pd.date_range("2025-01-01", periods=4, freq="30min")
    panel = pd.DataFrame({"wind_real_NE": [10.0, 30.0, 10.0, 10.0], "wind_curt_NE": [0.0, 10.0, 0.0, 0.0], "solar_real_NE": [0.0] * 4, "solar_curt_NE": [0.0] * 4, "load_NE": [100.0] * 4}, index=idx)
    d = sh.series(panel, ["NE"])
    assert np.allclose(d["r30"], [10, 40, 10, 10]) and np.allclose(d["r1h"].iloc[:2], 25.0)  # hour mean of potential 10 and 40 over load 100
    dist = sh.distribution(d, "NE")
    assert dist["r30_max"] == 40.0 and dist["r1h_max"] == 25.0 and dist["max_ratio"] == 1.6


def test_ne_distribution_and_coverage_helpers_return_consistent_shapes():
    idx = pd.date_range("2025-01-01", periods=48, freq="h")
    h = pd.DataFrame({"r": np.linspace(5, 60, 48)}, index=idx)
    nef = pd.DataFrame({"rne": np.linspace(50, 300, 48)}, index=idx)
    out = ne.distribution(nef, h)
    assert list(out["metric"]) == ["SIN r", "NE r_NE"] and out.loc[1, "max"] == 300.0 and out.loc[0, "max_over_p50"] > 1
