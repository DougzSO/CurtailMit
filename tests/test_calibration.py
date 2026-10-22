from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from curtailmit.calibration import (
    apply_calibration,
    fit_calibration,
    load_calibration,
    logistic,
    save_calibration,
    validate_against_holdout,
)


def _make_synthetic(L=0.8, k=0.25, P0=40.0, n=30, seed=42):
    rng = np.random.default_rng(seed)
    P = np.linspace(0, 100, n)
    C = logistic(P, L, k, P0) + rng.normal(0, 0.01, n)
    return pd.DataFrame({"P": P, "C": C})


def test_fit_calibration_recovers_parameters():
    df = _make_synthetic()
    calib = fit_calibration(df)
    assert abs(calib.params["L"] - 0.8) < 0.1
    assert abs(calib.params["P0"] - 40.0) < 5.0
    assert calib.n_calibration_points == len(df)


def test_apply_calibration_matches_logistic():
    df = _make_synthetic()
    calib = fit_calibration(df)
    predicted = apply_calibration(50.0, calib.params)
    expected = logistic(np.array([50.0]), **calib.params)[0]
    assert abs(predicted - expected) < 1e-9


def test_validate_against_holdout():
    df = _make_synthetic(seed=1)
    holdout = _make_synthetic(seed=2, n=10)
    calib = fit_calibration(df)
    rmse = validate_against_holdout(calib, holdout)
    assert rmse >= 0
    assert rmse < 0.2


def test_save_and_load_roundtrip(tmp_path: Path):
    df = _make_synthetic()
    calib = fit_calibration(df)
    dest = tmp_path / "calib.json"
    save_calibration(calib, dest)
    loaded = load_calibration(dest)
    assert loaded.params == calib.params


def test_empty_dataframe_raises():
    with pytest.raises(ValueError):
        fit_calibration(pd.DataFrame({"P": [], "C": []}))


# ---------------------------------------------------------------- D21: bounded L and bootstrap CI

from curtailmit.calibration import bootstrap_calibration_ci


def test_fit_bounds_L_to_at_most_one_even_when_the_data_ask_for_more():
    df = _make_synthetic(L=1.4, k=0.2, P0=45.0, n=60)  # true asymptote above 100 %: unconstrained fit would return L ~ 1.4
    calib = fit_calibration(df)
    assert 0 < calib.params["L"] <= 1.0
    assert apply_calibration(100.0, calib.params) <= 1.0


def test_bounded_L_is_not_fixed_at_one():
    calib = fit_calibration(_make_synthetic(L=0.6, k=0.3, P0=40.0, n=60))
    assert calib.params["L"] == pytest.approx(0.6, abs=0.05)


def test_bootstrap_ci_shape_ordering_and_widening_with_extrapolation():
    rng = np.random.default_rng(3)
    P = rng.uniform(10, 30, 50)
    df = pd.DataFrame({"P": P, "C": np.clip(logistic(P, 1.0, 0.17, 35.0) + rng.normal(0, 0.04, 50), 0, 1)})
    ci = bootstrap_calibration_ci(df, [20.0, 30.0, 50.0], n_boot=50, seed=1)
    assert list(ci.columns) == ["P", "point", "lo", "hi", "width", "n_ok", "n_failed"]
    assert (ci.lo <= ci.hi).all() and (ci.lo >= 0).all() and (ci.hi <= 1).all()
    assert ci.n_ok.iloc[0] + ci.n_failed.iloc[0] == 50
    assert ci.width.iloc[2] > ci.width.iloc[0]  # far outside the sample the interval is wider than in-sample


def test_bootstrap_is_reproducible_and_rejects_empty():
    df = _make_synthetic(L=0.8, k=0.25, P0=40.0, n=30)
    a = bootstrap_calibration_ci(df, [40.0], n_boot=20, seed=7)
    b = bootstrap_calibration_ci(df, [40.0], n_boot=20, seed=7)
    pd.testing.assert_frame_equal(a, b)
    with pytest.raises(ValueError):
        bootstrap_calibration_ci(pd.DataFrame({"P": [], "C": []}), [40.0])


def test_bootstrap_counts_failed_refits(monkeypatch):
    import curtailmit.calibration as cal

    real, calls = cal.curve_fit, {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] > 1 and calls["n"] % 2 == 0:  # call 1 is the full-sample fit
            raise RuntimeError("no convergence")
        return real(*a, **k)

    monkeypatch.setattr(cal, "curve_fit", flaky)
    ci = bootstrap_calibration_ci(_make_synthetic(n=30), [40.0], n_boot=10, seed=0)
    assert ci.n_failed.iloc[0] == 5 and ci.n_ok.iloc[0] == 5
