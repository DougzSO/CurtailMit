"""Smoke tests for the reusable helpers of the Task 11E3 throwaway analysis scripts (analysis/, outside the package; synthetic data only)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))
import task11e3_2050_calibration as cal
import task11e3_error_growth as eg


def test_distance_metrics_are_zero_inside_the_support_and_one_when_everything_is_beyond():
    params = (0.8, 0.1, 40.0)
    r, pot = np.array([10.0, 20.0, 30.0]), np.ones(3)
    inside = eg.distance_metrics(r, pot, params, r_cap=50.0)
    assert inside == {"E_out": 0.0, "H_out": 0.0, "D_pp": 0.0}
    beyond = eg.distance_metrics(np.array([60.0, 70.0]), np.ones(2), params, r_cap=50.0)
    assert abs(beyond["E_out"] - 1.0) < 1e-12 and beyond["H_out"] == 1.0 and 10.0 <= beyond["D_pp"] <= 20.0


def test_splits_never_train_on_the_test_quarter_and_respect_temporal_order():
    months = pd.period_range("2022-01", "2024-12", freq="M")
    r95 = pd.Series(np.linspace(20, 60, len(months)), index=months)
    n = 0
    for family, mask, q in eg.make_splits(months, r95, "wind"):
        n += 1
        test_months = [m for m in months if m.asfreq("Q") == q]
        assert not any(mask[list(months).index(m)] for m in test_months)
        if family in ("expanding", "trunc_past") or family.startswith("rolling"):
            assert max(m for m, k in zip(months, mask, strict=True) if k) < min(test_months)
        if family.startswith("rolling_"):
            assert mask.sum() == int(family.split("_")[1])
    assert n > 20


def test_fit_relation_recovers_a_known_linear_error_growth():
    rng = np.random.default_rng(2)
    x = rng.random(400)
    df = pd.DataFrame({"E_out": x, "err_log": -0.1 - 0.5 * x + rng.normal(0, 0.05 + 0.2 * x), "test_quarter": rng.integers(0, 10, 400).astype(str)})
    f = eg.fit_relation(df)
    assert abs(f["a"] + 0.1) < 0.05 and abs(f["b"] + 0.5) < 0.1 and f["d"] > 0
    bs = eg.cluster_bootstrap(df, n=30)
    assert bs.shape[1] == 4 and len(bs) > 0


def test_neighbour_band_flags_insufficient_evidence_and_inverts_the_log_ratio():
    rng = np.random.default_rng(3)
    s = pd.DataFrame({"E_out": rng.random(60) * 0.3, "err_log": np.full(60, np.log(0.8)), "test_quarter": [str(i % 6) for i in range(60)]})
    b = cal.neighbour_band(s, 0.15, 100.0)
    assert abs(b["band_low"] - 125.0) < 1e-6 and abs(b["band_high"] - 125.0) < 1e-6  # obs = pred / 0.8
    assert cal.neighbour_band(s, 0.9, 100.0)["note"] == "insufficient neighbours"
