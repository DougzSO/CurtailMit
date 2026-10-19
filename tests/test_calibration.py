import numpy as np
import pandas as pd
import pytest
from pathlib import Path

from curtailmit.calibration import (
    fit_calibration, apply_calibration, validate_against_holdout,
    save_calibration, load_calibration, logistic,
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
