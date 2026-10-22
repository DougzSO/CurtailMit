"""Smoke tests for the reusable helpers of the Task 11E throwaway analysis scripts (analysis/, outside the package; synthetic data only)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))
import task11e_common as cm


def test_active_at_respects_entry_and_deactivation():
    reg = pd.DataFrame({"dat_entradaoperacao": pd.to_datetime(["2020-01-01", "2023-06-01", "2020-01-01"]), "dat_desativacao": pd.to_datetime([None, None, "2022-03-01"])})
    a = cm.active_at(reg, pd.Timestamp("2023-01-31"))
    assert a.tolist() == [True, False, False]  # second not yet in service, third already deactivated
    assert cm.active_at(reg, pd.Timestamp("2023-12-31")).tolist() == [True, True, False]


def _hourly(n_days: int = 90, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-01", periods=24 * n_days, freq="h")
    load = 100 + 20 * rng.random(len(idx))
    vre = 100 * rng.random(len(idx))
    r = 100 * vre / load
    true_rate = cm.logistic_w(r, 0.8, 0.12, 45.0)
    wind_pot = vre
    curt = true_rate * wind_pot
    return pd.DataFrame({"wind": wind_pot - curt, "curt_wind": curt, "load": load, "r": r}, index=idx)


def test_binned_fit_recovers_a_known_curve_and_monthly_prediction_matches():
    h = _hourly()
    params = cm.fit_binned(cm.binned(h, "r", "wind", "curt_wind"))
    assert abs(params[0] - 0.8) < 0.1 and abs(params[2] - 45.0) < 5.0
    pred = cm.predict_monthly(h, params, "r", "wind", "curt_wind")
    obs = h.groupby(h.index.to_period("M"))["curt_wind"].sum() / h.groupby(h.index.to_period("M"))[["wind", "curt_wind"]].sum().sum(axis=1)
    assert np.allclose(pred.to_numpy(), obs.to_numpy(), atol=0.03)


def test_logistic_w_is_bounded_and_monotone():
    x = np.linspace(0, 200, 50)
    y = cm.logistic_w(x, 0.7, 0.1, 40.0)
    assert y.min() >= 0 and y.max() <= 0.7 and np.all(np.diff(y) >= 0)
