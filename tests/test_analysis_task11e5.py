"""Smoke tests for the reusable helpers of the Task 11E5 throwaway analysis scripts (analysis/, outside the package; synthetic data only)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))
import task11e5_drift_characterization as ch
import task11e5_drift_hypotheses as hy
import task11e5_extended_model as em


def _monthly(step_at: int | None = None, slope: float = 0.0, n: int = 57, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.period_range("2022-01", periods=n, freq="M")
    t = (idx.year - 2022) + (idx.month - 0.5) / 12
    y = slope * np.asarray(t, float) + rng.normal(0, 0.3, n)
    if step_at is not None:
        y = y + 4.0 * (np.arange(n) >= step_at)
    return pd.DataFrame({"res_pp": y, "t_years": np.asarray(t, float)}, index=idx)


def test_trend_with_ci_recovers_a_known_slope_and_brackets_it():
    tr = ch.trend_with_ci(_monthly(slope=1.5), n_boot=300)
    assert abs(tr["slope_pp_per_year"] - 1.5) < 0.15 and tr["NW_CI_lo"] < 1.5 < tr["NW_CI_hi"] and tr["boot_CI_lo"] < 1.5 < tr["boot_CI_hi"]


def test_break_vs_trend_prefers_the_step_when_the_series_has_a_step_and_the_trend_otherwise():
    step = hy.break_vs_trend(_monthly(step_at=36)).set_index("model")
    step_row = next(m for m in step.index if m.startswith("step"))
    assert step.loc[step_row, "break_month"] in ("2024-12", "2025-01", "2025-02") and step.loc[step_row, "dBIC_vs_linear"] < -5
    trend = hy.break_vs_trend(_monthly(slope=1.5)).set_index("model")
    assert trend.loc["linear trend", "bic"] <= trend.loc["constant", "bic"] - 20


def test_shift_share_is_an_exact_decomposition():
    rng = np.random.default_rng(2)
    n = 4000
    d = pd.DataFrame({"year": rng.choice([2023, 2026], n), "r": rng.uniform(20, 40, n), "grp": rng.choice(["a", "b"], n, p=[0.6, 0.4])})
    d["pot"] = rng.uniform(1, 2, n)
    d["curt"] = d["pot"] * np.where(d.year == 2026, 0.3, 0.1) * np.where(d.grp == "a", 1.0, 1.4)
    out = hy.shift_share(d, "grp", 2023, 2026)
    assert abs(out["total_pp"] - (out["within_pp"] + out["composition_pp"])) < 1e-9 and out["within_pp"] > 0


def test_model_functions_are_bounded_and_nest_the_base_curve():
    x = np.linspace(0, 120, 25)
    t, step = np.full(25, 3.0), np.ones(25)
    th = np.array([0.7, 0.12, 40.0, 0.0])
    base = em.f_model("base", th[:3], x, t, step)
    for nm in ("linear", "saturate", "step", "ktrend"):
        assert np.allclose(em.f_model(nm, th, x, t, step), base)  # a zero trend term gives the base curve
    shifted = em.f_model("linear", np.array([0.7, 0.12, 40.0, 0.5]), x, t, step)
    assert (shifted >= base - 1e-12).all() and shifted.max() <= 0.7 + 1e-12  # left shift: never lower, never above L


def test_compounding_never_exceeds_the_asymptote():
    idx = pd.date_range("2025-01-01", periods=24 * 30, freq="h")
    h = pd.DataFrame({"wind": 50.0, "curt_wind": 10.0, "solar_disp": 20.0, "curt_solar": 0.0, "load": 100.0, "r": np.linspace(20, 70, len(idx))}, index=idx)
    out = ch.compounding(h, (0.7, 0.14, 41.0), slope=5.0)
    assert (out["rate_pct"] <= 70.0 + 1e-9).all() and len(out) > 0
