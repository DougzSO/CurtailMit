"""Smoke tests for the reusable helpers of the Task 11E2 throwaway analysis scripts (analysis/, outside the package; synthetic data only)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))
import task11e2_common as c2
import task11e2_options_table as ot
import task11e2_transmission_mechanism as tm
import task11e_common as cm


def _hourly(n_days: int = 120, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-01", periods=24 * n_days, freq="h")
    load = 100 + 20 * rng.random(len(idx))
    pot = 100 * rng.random(len(idx))
    r = 100 * pot / load
    curt = cm.logistic_w(r, 0.8, 0.12, 45.0) * pot
    return pd.DataFrame({"wind": pot - curt, "curt_wind": curt, "load": load, "r": r}, index=idx)


def test_monthbins_matches_the_reference_binning_and_recovers_the_curve():
    h = _hourly()
    ref = cm.binned(h, "r", "wind", "curt_wind")
    got = c2.MonthBins(h, "wind", "curt_wind").bins()
    ref = ref[ref.hours >= 15].reset_index(drop=True)
    got = got[got.hours >= 15].reset_index(drop=True)
    n = min(len(ref), len(got))
    assert np.allclose(ref["rate"][:n], got["rate"][:n], atol=1e-9) and np.allclose(ref["x"][:n], got["x"][:n], atol=1e-9)
    p = c2.fit_logistic(c2.MonthBins(h, "wind", "curt_wind").bins())
    assert abs(p[0] - 0.8) < 0.1 and abs(p[2] - 45.0) < 5.0


def test_fixed_L_fit_and_bootstrap_return_bounded_parameters():
    h = _hourly()
    mb = c2.MonthBins(h, "wind", "curt_wind")
    p = c2.fit_logistic(mb.bins(), L_fixed=1.0)
    assert p[0] == 1.0 and p[1] > 0
    bs = c2.bootstrap_params(mb, 12, seed=3)
    assert bs.shape[1] == 3 and len(bs) > 0 and (bs[:, 0] <= 1.0).all() and (bs[:, 1] > 0).all()


def test_projected_r_is_the_identity_at_the_base_year_and_scales_with_phi():
    prof = {"W": np.array([10.0, 20.0]), "S": np.array([5.0, 0.0]), "LD": np.array([100.0, 100.0])}
    f1 = {"a_wind": 1.0, "a_solar": 1.0, "a_load": 1.0}
    assert np.allclose(c2.projected_r(prof, f1), [15.0, 20.0])
    f2 = {"a_wind": 2.0, "a_solar": 4.0, "a_load": 2.0}
    assert np.allclose(c2.projected_r(prof, f2, phi=2.0), [(20 + 20) / 200 * 100 / 2, 20.0 / 2])
    assert abs(c2.projected_rate(np.array([10.0, 80.0]), np.array([1.0, 1.0]), (0.8, 0.2, 40.0), r_cap=10.0) - cm.logistic_w(10.0, 0.8, 0.2, 40.0)) < 1e-12


def test_partial_corr_removes_a_common_trend():
    t = np.arange(60.0)
    rng = np.random.default_rng(0)
    df = pd.DataFrame({"t": t, "x": t + rng.normal(0, 1, 60), "y": t + rng.normal(0, 1, 60)})
    assert df["x"].corr(df["y"]) > 0.95 and abs(c2.partial_corr(df, "x", "y", ["t"])) < 0.4


def test_net_basis_inversion_is_zero_when_there_is_no_curtailment_and_bounded_otherwise():
    real = np.full(24, 10.0)
    load = np.full(24, 100.0)
    w, s, _ = ot.net_basis_twh(real, real, load, (1e-9, 0.1, 40.0), (1e-9, 0.1, 40.0), 1.0, 1.0)
    assert abs(w) < 1e-6 and abs(s) < 1e-6
    w2, _, _ =ot.net_basis_twh(real * 4, real * 4, load, (0.7, 0.1, 20.0), (0.7, 0.1, 20.0), 1.0, 1.0)
    assert 0 < w2 <= 1 / (1 - 0.7) - 1 + 1e-9  # potential cannot exceed real / (1 - L)


def test_constraint_description_classifier():
    assert tm.classify_description(None) == "no_description"
    assert tm.classify_description("Controle de frequência do SIN.") == "system_frequency"
    assert tm.classify_description("Controle do fluxo: FNESE # Fluxo Nordeste/Sudeste - Conforme SGI 1") == "interchange_flow_control"
    assert tm.classify_description("Controle de inequação: CONTROLE DE CARREGAMENTO DA TRANSFORMAÇÃO 500/345 KV DA SE RIO NOVO DO SUL - IO-ON.SE.5RJ") == "SE_side_network"
    assert tm.classify_description("Controle de inequação: LIMITAÇÃO DA TRANSMISSÃO NA LT 500 KV AÇU III / JAGUARUANA II - IO-ON.NE.5NE") == "NE_internal_network"
    assert tm.classify_description("Desligamento das LT 525 kV Povo Novo / Marmeleiro C2") == "outage_other"
    assert tm.classify_description("qualquer outra coisa") == "other_named"
