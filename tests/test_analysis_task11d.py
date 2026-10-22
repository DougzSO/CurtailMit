"""Smoke tests for the reusable helpers of the Task 11D throwaway analysis scripts (analysis/, outside the package; synthetic data only)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))
import task11d_pooled_panel as pooled
import task11d_time_confound as tc


def test_partial_corr_removes_a_pure_time_trend():
    rng = np.random.default_rng(0)
    t = np.arange(120, dtype=float)
    p = 0.5 * t + rng.normal(0, 1, 120)  # P is a noisy trend
    c = 0.01 * t + rng.normal(0, 0.05, 120)  # C depends on t only
    df = pd.DataFrame({"t": t, "P": p, "C": c})
    assert df.P.corr(df.C) > 0.8  # spurious without the control
    r, pval = tc.partial_corr(df, "P", "C", ["t"])
    assert abs(r) < 0.3 and pval > 0.01


def test_partial_corr_keeps_a_true_effect():
    rng = np.random.default_rng(1)
    t = np.arange(120, dtype=float)
    p = 0.5 * t + rng.normal(0, 5, 120)
    c = 0.01 * p + rng.normal(0, 0.02, 120)
    r, pval = tc.partial_corr(pd.DataFrame({"t": t, "P": p, "C": c}), "P", "C", ["t"])
    assert r > 0.5 and pval < 0.001


def test_international_points_are_well_formed():
    assert len(pooled.INTERNATIONAL) == 4
    for system, period, p, p_alt, c, lo, hi, basis, source in pooled.INTERNATIONAL:
        assert 0 < p <= p_alt <= 100 and 0 <= lo <= c <= hi <= 1
        assert system and period and basis and source


def test_frac_logit_recovers_a_slope():
    rng = np.random.default_rng(2)
    p = rng.uniform(10, 80, 60)
    c = 1 / (1 + np.exp(-(-4 + 0.04 * p)))
    df = pd.DataFrame({"P": p, "C": c})
    fit = pooled.frac_logit(df, ["P"])
    assert abs(fit.params["P"] - 0.04) < 0.005
