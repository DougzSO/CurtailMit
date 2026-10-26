"""Tests for curtailmit.hourly_model and curtailmit.hourly_uncertainty (Task 11F-2): unit tests on synthetic data and regression tests against the validated analysis prototypes.

Golden values (tests/fixtures/option_e/golden.json) were produced by analysis/task11f_extract_golden.py from the PROTOTYPE functions (analysis/task11e*_common.py, task11e3_error_growth.py,
task11e4_conformal_prediction.py) and from the committed Task 11E2-11E4 tables; no network, no database root.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from curtailmit import hourly_model as hm
from curtailmit import hourly_uncertainty as hu

FIX = Path(__file__).parent / "fixtures" / "option_e"
GOLDEN = json.loads((FIX / "golden.json").read_text(encoding="utf-8"))
REL = 1e-7


def synthetic_panel(seed: int = 7) -> pd.DataFrame:
    """Seeded 48-month hourly SIN-like panel with a known logistic curtailment (identical to analysis/task11f_extract_golden.py::synthetic_panel)."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2022-01-01", "2025-12-31 23:00", freq="h")
    n = len(idx)
    t = np.linspace(0.0, 1.0, n)
    hour = idx.hour.to_numpy()
    load = 60000 + 12000 * np.sin(2 * np.pi * (hour - 14) / 24) + rng.normal(0, 1500, n)
    wind = 20000 * (0.4 + 1.3 * t) * (0.6 + 0.5 * np.sin(2 * np.pi * idx.dayofyear.to_numpy() / 365)) * rng.lognormal(0, 0.25, n)
    solar = 9000 * (0.3 + 1.4 * t) * np.clip(np.sin(np.pi * (hour - 6) / 12), 0, None) * rng.lognormal(0, 0.15, n)
    r = 100 * (wind + solar) / load
    rate_w = 0.7 / (1 + np.exp(-0.14 * (r - 41)))
    rate_s = 0.74 / (1 + np.exp(-0.10 * (r - 42)))
    return pd.DataFrame({"wind": wind * (1 - rate_w), "curt_wind": wind * rate_w, "solar_disp": solar * (1 - rate_s), "curt_solar": solar * rate_s, "load": load, "r": r}, index=idx)


@pytest.fixture(scope="module")
def syn() -> pd.DataFrame:
    return synthetic_panel()


@pytest.fixture(scope="module")
def sample() -> pd.DataFrame:
    return pd.read_csv(FIX / "hourly_sample_2025H1.csv", index_col=0, parse_dates=True)


def test_synthetic_panel_is_the_one_the_golden_values_were_computed_on(syn):
    assert math.isclose(float(syn.to_numpy().sum()), GOLDEN["synthetic"]["checksum"], rel_tol=1e-9)


# ----------------------------------------------------------------------------------------------- unit tests
def test_logistic_rate_is_bounded_by_L_and_has_midpoint_L_over_two():
    x = np.linspace(-50, 200, 100)
    y = hm.logistic_rate(x, 0.7, 0.14, 41.0)
    assert (y > 0).all() and (y <= 0.7 + 1e-12).all() and math.isclose(float(hm.logistic_rate(41.0, 0.7, 0.14, 41.0)), 0.35)


def test_monthbins_matches_a_direct_pandas_binning(sample):
    mb = hm.MonthBins(sample, "wind", "curt_wind")
    bins = mb.bins()
    pot = sample.wind + sample.curt_wind
    b = pd.cut(sample["r"], np.arange(0, float(sample["r"].max()) + 2.0, 2.0))
    direct = sample.assign(pot=pot, b=b).groupby("b", observed=True).apply(
        lambda d: pd.Series({"x": np.average(d["r"], weights=d["pot"].clip(lower=1e-9)), "rate": d["curt_wind"].sum() / d["pot"].sum(), "hours": len(d)}), include_groups=False
    )
    assert len(bins) == len(direct)
    np.testing.assert_allclose(bins["x"].to_numpy(), direct["x"].to_numpy(), rtol=1e-9)
    np.testing.assert_allclose(bins["rate"].to_numpy(), direct["rate"].to_numpy(), rtol=1e-9)
    np.testing.assert_array_equal(bins["hours"].to_numpy(), direct["hours"].to_numpy())


def test_monthbins_month_weights_select_months(sample):
    mb = hm.MonthBins(sample, "wind", "curt_wind")
    only_jan = mb.bins(np.array([1.0, 0, 0, 0, 0, 0]))
    jan = hm.MonthBins(sample[sample.index.month == 1], "wind", "curt_wind").bins()
    np.testing.assert_allclose(only_jan["rate"].to_numpy(), jan["rate"].to_numpy(), rtol=1e-12)
    assert only_jan["hours"].sum() == (sample.index.month == 1).sum()


def test_fit_recovers_the_known_curve_on_the_synthetic_panel(syn):
    c = hm.fit_hourly_curve(syn, "wind")
    assert c.L == pytest.approx(0.7, abs=0.02) and c.k == pytest.approx(0.14, abs=0.01) and c.x0 == pytest.approx(41, abs=0.7)
    assert c.n_months == 48 and c.window_start == "2022-01-01" and c.r_cap > 40


def test_fit_with_L_fixed_pins_the_asymptote(syn):
    c1 = hm.fit_hourly_curve(syn, "wind", L_fixed=1.0)
    assert c1.L == 1.0 and c1.k > 0


def test_solar_and_unified_use_the_solar_window(syn):
    assert hm.fit_hourly_curve(syn, "solar").window_start == "2024-04-01"
    u = hm.fit_hourly_curve(syn, "unified")
    assert u.n_months == 21 and 0 < u.L <= 1


def test_fit_raises_when_too_few_bins_are_populated():
    bins = pd.DataFrame({"x": [10.0, 20.0], "pot": [1.0, 1.0], "rate": [0.1, 0.2], "hours": [100, 100]})
    with pytest.raises(hm.HourlyModelError):
        hm.fit_logistic(bins)


def test_r_cap_is_the_last_populated_bin():
    bins = pd.DataFrame({"x": [10.0, 20.0, 30.0, 70.0], "pot": 1.0, "rate": 0.1, "hours": [100, 50, 15, 14]})
    assert hm.r_cap_of(bins) == 30.0


def test_curve_rate_cap_clips_at_the_support_edge():
    c = hm.HourlyCurve("wind", 0.7, 0.14, 41.0, 60.0, 10, 100, "2022-01-01")
    assert float(c.rate(90.0, cap=True)) == pytest.approx(float(c.rate(60.0))) and float(c.rate(90.0)) > float(c.rate(60.0))
    assert c.with_L(1.0).L == 1.0 and c.with_L(1.0).k == c.k


def test_extrapolation_metrics_hand_case():
    c = hm.HourlyCurve("wind", 1.0, 0.1, 40.0, 50.0, 1, 1, "x")
    r = np.array([30.0, 50.0, 60.0, 80.0])
    pot = np.ones(4)
    m = hm.extrapolation_metrics(r, pot, c.params, c.r_cap)
    f = hm.logistic_rate(r, *c.params)
    assert m["H_out"] == 0.5 and m["E_out"] == pytest.approx(f[2:].sum() / f.sum())
    assert m["D_pp"] == pytest.approx(np.average([10.0, 30.0], weights=f[2:]))
    assert hm.extrapolation_metrics(np.array([10.0, 20.0]), np.ones(2), c.params, c.r_cap) == {"E_out": 0.0, "H_out": 0.0, "D_pp": 0.0}


def test_assemble_sin_panel_sums_subsystems_and_computes_r():
    ts = pd.to_datetime(["2025-01-01 00:00", "2025-01-01 00:00", "2025-01-01 01:00", "2025-01-01 01:00"])
    bal = pd.DataFrame({"ts": ts, "sub": ["N", "NE", "N", "NE"], "wind": [10.0, 30.0, 20.0, 20.0], "load": [100.0, 100.0, 100.0, 300.0]})
    sol = pd.DataFrame({"ts": ts[:2], "sub": ["N", "NE"], "solar_disp": [5.0, 5.0]})
    cur = pd.DataFrame({"ts": ts[:1], "sub": ["NE"], "curt_wind": [10.0], "curt_solar": [0.0]})
    p = hm.assemble_sin_panel(bal, sol, cur)
    assert list(p.columns) == ["wind", "solar_disp", "curt_wind", "curt_solar", "load", "r"]
    assert p.loc["2025-01-01 00:00", "r"] == pytest.approx(100 * (40 + 10 + 10) / 200)  # wind 40 + solar 10 + curtailed 10 over load 200
    assert p.loc["2025-01-01 01:00", "solar_disp"] == 0.0 and p.loc["2025-01-01 01:00", "r"] == pytest.approx(100 * 40 / 400)


def test_base_profile_and_scale_factors_errors(sample):
    prof = hm.BaseProfile.from_panel(sample, 2025)
    assert len(prof.wind) == len(sample) and prof.year == 2025
    with pytest.raises(hm.HourlyModelError):
        hm.BaseProfile.from_panel(sample, 2030)
    pte = pd.DataFrame({"scenario": ["TA"], "year": [2025], "wind_gen_twh": [1.0], "solar_gen_twh": [1.0], "total_generation_twh": [10.0]})
    with pytest.raises(hm.HourlyModelError):
        hm.scale_factors(pte, "TA", 2040)


def test_projected_r_scales_with_totals_and_flexibility(sample):
    prof = hm.BaseProfile.from_panel(sample, 2025)
    f = hm.ScaleFactors(2.0, 3.0, 1.5, 100.0, 50.0)
    r = hm.projected_r(prof, f)
    np.testing.assert_allclose(r, 100 * (2.0 * prof.wind + 3.0 * prof.solar) / (1.5 * prof.load))
    np.testing.assert_allclose(hm.projected_r(prof, f, 1.5), r / 1.5)
    unit = hm.projected_r(prof, hm.ScaleFactors(1, 1, 1, 1, 1))
    np.testing.assert_allclose(unit, 100 * (prof.wind + prof.solar) / prof.load)


def test_curve_and_bands_roundtrip(tmp_path):
    c = hm.HourlyCurve("wind", 0.7, 0.14, 41.0, 60.0, 10, 100, "2022-01-01")
    hm.save_curve(c, tmp_path / "c.json")
    assert hm.load_curve(tmp_path / "c.json") == c
    b = hu.HorizonBands(band_factors={"wind": (1.1, 1.3)}, conformal_logq={"wind": 1.2, "solar": None}, conformal_n_quarters={"wind": 13})
    b.save(tmp_path / "b.json")
    b2 = hu.HorizonBands.load(tmp_path / "b.json")
    assert b2.band_factors == {"wind": (1.1, 1.3)} and b2.logq("wind") == 1.2 and math.isinf(b2.logq("solar")) and math.isinf(b2.logq("missing"))


# ----------------------------------------------------------------------------------------------- uncertainty instruments
def test_weighted_quantile_conformal_finite_sample_rule():
    s = np.arange(1.0, 6.0)  # n = 5 unit weights: 80 % needs ceil(6 x 0.8) = 5 <= 5 (finite); 90 % needs ceil(6 x 0.9) = 6 > 5 (unbounded)
    w = np.ones(5)
    assert hu.weighted_quantile_conformal(s, w, 1.0, 0.2) == 5.0
    assert math.isinf(hu.weighted_quantile_conformal(s, w, 1.0, 0.1))
    assert math.isinf(hu.conformal_logq(pd.DataFrame(columns=["err_log", "test_quarter"])))


def test_conformal_interval_is_multiplicative_and_nan_when_unbounded():
    lo, hi = hu.conformal_interval(10.0, math.log(2))
    assert lo == pytest.approx(5.0) and hi == pytest.approx(20.0)
    assert all(math.isnan(v) for v in hu.conformal_interval(10.0, float("inf")))


def test_quarter_weights_give_each_quarter_total_weight_one():
    q = pd.Series(["2024Q1", "2024Q1", "2024Q2", "2024Q2", "2024Q2", "2024Q3"])
    w = hu.quarter_weights(q)
    assert w.sum() == pytest.approx(3.0) and w[0] == pytest.approx(0.5) and w[2] == pytest.approx(1 / 3)


def test_band_factors_invert_the_relative_error():
    lo, hi = hu.band_factors(pd.Series([-20.0, 10.0, -5.0]))  # pred = obs x (1 + e): truth = pred / (1 + e)
    assert lo == pytest.approx(1 / 1.10) and hi == pytest.approx(1 / 0.80)


def test_annual_backtest_in_sample_scheme_matches_a_hand_computation(syn):
    errs = hu.annual_backtest_errors(syn, "wind")
    row = errs[(errs.scheme == "in-sample") & (errs.year == 2025)].iloc[0]
    d = syn[syn.index >= "2022-01-01"]
    p = hm.fit_logistic(hm.MonthBins(d, "wind", "curt_wind").bins())
    sel = d.index.year == 2025
    pred = float((hm.logistic_rate(d["r"].to_numpy()[sel], *p) * (d.wind + d.curt_wind).to_numpy()[sel]).sum()) / 1e6
    assert row.pred_twh == pytest.approx(pred, rel=1e-9) and row.err_pct == pytest.approx(100 * (pred - row.obs_twh) / row.obs_twh, rel=1e-9)
    assert set(errs.scheme) == {"in-sample", "train 2022-24", "train 2023-24", "loyo 2025"} and (errs.year >= 2025).all()
    assert set(hu.annual_backtest_errors(syn, "solar").scheme) == {"in-sample", "train to 2025-06", "loyo 2025"}  # the synthetic sample ends in 2025: no 2026 test period


# ----------------------------------------------------------------------------------------------- regression against the prototypes
@pytest.mark.parametrize("tech", ["wind", "solar"])
def test_sample_fit_reproduces_the_prototype(sample, tech):
    g = GOLDEN["sample"][tech]
    c = hm.fit_hourly_curve(sample, tech)
    np.testing.assert_allclose(c.params, g["params"], rtol=REL)
    assert c.r_cap == pytest.approx(g["r_cap"], rel=REL)
    bins = hm.MonthBins(sample, *hm.TECH_COLUMNS[tech]).bins()
    np.testing.assert_allclose(bins["x"].to_numpy(), g["bins_x"], rtol=REL)
    np.testing.assert_allclose(bins["rate"].to_numpy(), g["bins_rate"], rtol=REL)
    np.testing.assert_allclose(hm.fit_hourly_curve(sample, tech, L_fixed=1.0).params, g["params_L1"], rtol=REL)


def test_sample_projection_reproduces_the_prototype(sample):
    g = GOLDEN["sample"]
    pte = pd.DataFrame({"scenario": ["TA"] * 2, "year": [2025, 2040], "wind_gen_twh": [60.0, 150.0], "solar_gen_twh": [40.0, 120.0], "total_generation_twh": [800.0, 1100.0]})
    prof = hm.BaseProfile.from_panel(sample, 2025)
    f = hm.scale_factors(pte, "TA", 2040)
    gp = g["projection_2040"]
    assert (f.a_wind, f.a_solar, f.a_load) == pytest.approx((gp["a_wind"], gp["a_solar"], gp["a_load"]))
    r, r15 = hm.projected_r(prof, f), hm.projected_r(prof, f, 1.5)
    assert float(r.sum()) == pytest.approx(gp["r_sum"], rel=REL) and float(r15.sum()) == pytest.approx(gp["r_flex_sum"], rel=REL)
    for tech, pot in (("wind", prof.wind * f.a_wind), ("solar", prof.solar * f.a_solar)):
        c, c1 = hm.fit_hourly_curve(sample, tech), hm.fit_hourly_curve(sample, tech, L_fixed=1.0)
        gt = gp[tech]
        assert hm.projected_rate(r, pot, c) == pytest.approx(gt["rate"], rel=REL)
        assert hm.projected_rate(r, pot, c, cap=True) == pytest.approx(gt["rate_capped"], rel=REL)
        assert hm.projected_rate(r15, pot, c) == pytest.approx(gt["rate_flex"], rel=REL)
        assert hm.projected_rate(r, pot, c1) == pytest.approx(gt["rate_L1"], rel=REL)
        dm = hm.extrapolation_metrics(r, pot, c.params, c.r_cap)
        assert {k: dm[k] for k in ("E_out", "H_out", "D_pp")} == pytest.approx(gt["dist"], rel=REL)


def test_synthetic_curves_reproduce_the_prototype(syn):
    for tech, g in GOLDEN["synthetic"]["curves"].items():
        c = hm.fit_hourly_curve(syn, tech)
        np.testing.assert_allclose(c.params, g["params"], rtol=REL)
        assert c.r_cap == pytest.approx(g["r_cap"], rel=REL) and c.n_months == g["n_months"]


@pytest.mark.parametrize("tech", ["wind", "solar", "unified"])
def test_quarter_splits_and_conformal_reproduce_the_prototype(syn, tech):
    g = GOLDEN["synthetic"]["splits"][tech]
    sp = hu.quarter_splits(syn, tech).sort_values(["family", "test_quarter"]).reset_index(drop=True)
    ref = pd.DataFrame(g).sort_values(["family", "test_quarter"]).reset_index(drop=True)
    assert len(sp) == len(ref) > 0
    assert list(sp.family) == list(ref.family) and list(sp.test_quarter) == list(ref.test_quarter) and list(sp.train_months) == list(ref.train_months)
    np.testing.assert_allclose(sp["err_log"].to_numpy(), ref["err_log"].to_numpy(), rtol=1e-6, atol=1e-9)
    q_ref = GOLDEN["synthetic"]["conformal_logq"][tech]
    assert hu.conformal_logq(sp) == pytest.approx(q_ref, rel=1e-6)


def test_weighted_conformal_quantile_reproduces_the_prototype():
    g = GOLDEN["synthetic"]["wqc"]
    assert hu.weighted_quantile_conformal(np.array(g["scores"]), np.array(g["weights"]), 1.0, g["alpha"]) == pytest.approx(g["q"], rel=1e-12)
    assert math.isinf(g["q_infeasible"]) and math.isinf(hu.weighted_quantile_conformal(np.array(g["scores"][:3]), np.array(g["weights"][:3]), 1.0, 0.1))


def test_horizon_bands_on_the_synthetic_panel_are_well_formed(syn):
    b = hu.build_horizon_bands(syn)
    assert set(b.band_factors) == {"wind", "solar"} and all(lo < hi for lo, hi in b.band_factors.values())
    assert b.conformal_n_quarters["wind"] >= 12 and np.isfinite(b.logq("wind")) and b.phi_low == 1.5


# ----------------------------------------------------------------------------------------------- full-sample regression (needs the local database root)
@pytest.mark.integration
def test_full_sample_calibration_reproduces_the_committed_analysis_tables():
    from curtailmit.paths import get_raw_dir

    if not list(get_raw_dir("ons/generation_by_source").glob("Balanco_de_Energia_Subsistema-*.parquet")):
        pytest.skip("ONS raw data not present")
    h = hm.load_sin_panel(refresh=True)
    for tech in ("wind", "solar"):
        c = hm.fit_hourly_curve(h, tech)
        g = GOLDEN["full_curves"][tech]
        np.testing.assert_allclose(c.params, (g["L"], g["k"], g["x0"]), rtol=1e-9)
        assert c.r_cap == pytest.approx(g["r_cap15"], rel=1e-9)
    b = hu.build_horizon_bands(h)
    for t, q in GOLDEN["full_conformal_logq80"].items():
        assert b.logq(t) == pytest.approx(q, rel=1e-9)
    for t, (lo, hi) in GOLDEN["full_band_factors"].items():
        assert b.band_factors[t] == pytest.approx((lo, hi), rel=1e-9)
