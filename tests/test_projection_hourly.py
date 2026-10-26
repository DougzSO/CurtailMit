"""Tests for the option-E production projection (Task 11F-3): by-horizon treatment, D25 known-limitation propagation, reference labelling, mitigation guard.

Regression values come from tests/fixtures/option_e/golden.json (prototype functions + committed Task 11E2-11E4 tables); no network, no database root.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from curtailmit import hourly_model as hm
from curtailmit import hourly_uncertainty as hu
from curtailmit import limitations as lim
from curtailmit import projection as pj
from curtailmit.calibration import REGIONAL_REFERENCE_LABEL, fit_regional_reference, logistic
from curtailmit.mitigation import compute_mitigation, output_prefix

FIX = Path(__file__).parent / "fixtures" / "option_e"
GOLDEN = json.loads((FIX / "golden.json").read_text(encoding="utf-8"))
YEARS = (2025, 2030, 2040, 2050)


@pytest.fixture(scope="module")
def sample() -> pd.DataFrame:
    return pd.read_csv(FIX / "hourly_sample_2025H1.csv", index_col=0, parse_dates=True)


def make_bands(logq: float | None = 1.1) -> hu.HorizonBands:
    return hu.HorizonBands(band_factors={"wind": (1.09, 1.31), "solar": (0.87, 1.13)}, band_n={"wind": 7, "solar": 6}, conformal_logq={"wind": logq, "solar": 0.9, "unified": 1.05},
                           conformal_n_quarters={"wind": 13, "solar": 7, "unified": 7})


@pytest.fixture(scope="module")
def cal(sample) -> hm.HourlyCalibration:
    return hm.HourlyCalibration(hm.fit_hourly_curve(sample, "wind"), hm.fit_hourly_curve(sample, "solar"), hm.fit_hourly_curve(sample, "wind", L_fixed=1.0),
                                hm.fit_hourly_curve(sample, "solar", L_fixed=1.0), hm.BaseProfile.from_panel(sample, 2025), make_bands())


def pte_frame(scale_wind: float = 1.0) -> pd.DataFrame:
    """Three scenarios x four years, growing PTE totals (the 2040 TA row is the one of the golden sample projection)."""
    rows = []
    for sc, mult in (("TB", 0.8), ("TA", 1.0), ("TG", 0.9)):
        for y, (w, s, t) in {2025: (60.0, 40.0, 800.0), 2030: (90.0, 70.0, 900.0), 2040: (150.0, 120.0, 1100.0), 2050: (260.0, 190.0, 1400.0)}.items():
            m = mult if y > 2025 else 1.0
            rows.append({"scenario": sc, "year": y, "wind_gen_twh": w * m * scale_wind, "solar_gen_twh": s * m, "total_generation_twh": t, "wind_pct": 100 * w * m / t, "solar_pct": 100 * s * m / t, "P": 100 * (w + s) * m / t})
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def out(cal) -> pd.DataFrame:
    return pj.project_curtailment_hourly(pte_frame(), cal).set_index(["scenario", "year"])


# ----------------------------------------------------------------------------------------------- regression against the prototype
def test_projection_reproduces_the_prototype_on_the_sample(out):
    gp = GOLDEN["sample"]["projection_2040"]
    r = out.loc[("TA", 2040)]
    assert r.C_wind_central == pytest.approx(gp["wind"]["rate"], rel=1e-7) and r.C_solar_central == pytest.approx(gp["solar"]["rate"], rel=1e-7)
    assert r.E_curt_wind_twh == pytest.approx(gp["wind"]["rate"] * 150.0, rel=1e-7) and r.E_curt_solar_twh == pytest.approx(gp["solar"]["rate"] * 120.0, rel=1e-7)
    assert r.E_curt_wind_flex_phi_twh == pytest.approx(gp["wind"]["rate_flex"] * 150.0, rel=1e-7) and r.E_curt_solar_L1_twh == pytest.approx(gp["solar"]["rate_L1"] * 120.0, rel=1e-7)
    for t in ("wind", "solar"):
        assert (r[f"E_out_{t}"], r[f"H_out_{t}"], r[f"D_pp_{t}"]) == pytest.approx((gp[t]["dist"]["E_out"], gp[t]["dist"]["H_out"], gp[t]["dist"]["D_pp"]), rel=1e-7)


@pytest.mark.integration
def test_full_option_e_table_reproduces_the_committed_analysis_tables():
    from curtailmit.paths import get_processed_dir, get_raw_dir

    if not list(get_raw_dir("ons/generation_by_source").glob("Balanco_de_Energia_Subsistema-*.parquet")) or not (get_processed_dir() / "pte_curtailment_two_curves.parquet").exists():
        pytest.skip("local database root not populated")
    pte = pd.read_parquet(get_processed_dir() / "pte_curtailment_two_curves.parquet")
    cal = hm.run_hourly_calibration(hm.load_sin_panel(), write=False)
    got = pj.project_curtailment_hourly(pte, cal).set_index(["scenario", "year"])
    for g in GOLDEN["full_projection"]:
        r = got.loc[(g["scenario"], g["year"])]
        assert r.E_curt_wind_twh == pytest.approx(g["E_wind"], rel=1e-9) and r.E_curt_solar_twh == pytest.approx(g["E_solar"], rel=1e-9) and r.E_curt_twh == pytest.approx(g["E_total"], rel=1e-9)
        assert r.E_curt_flex_phi_twh == pytest.approx(g["flex_phi15_total"], rel=1e-9) and r.E_curt_L1_twh == pytest.approx(g["L1_total"], rel=1e-9) and r.curt_in_support_total_twh == pytest.approx(g["in_support_total"], rel=1e-9)
        for t in ("wind", "solar"):
            assert (r[f"E_out_{t}"], r[f"H_out_{t}"], r[f"D_pp_{t}"]) == pytest.approx((g[f"E_out_{t}"], g[f"H_out_{t}"], g[f"D_pp_{t}"]), rel=1e-9)
        if g["year"] in (2030, 2040):
            assert (r.E_curt_wind_twh_low, r.E_curt_wind_twh_high, r.E_curt_solar_twh_low, r.E_curt_solar_twh_high) == pytest.approx((g["wind_low"], g["wind_high"], g["solar_low"], g["solar_high"]), rel=1e-9)
            assert (r.conformal80_wind_lo_twh, r.conformal80_wind_hi_twh, r.conformal80_solar_lo_twh, r.conformal80_solar_hi_twh) == pytest.approx((g["conf_wind_lo"], g["conf_wind_hi"], g["conf_solar_lo"], g["conf_solar_hi"]), rel=1e-9)


# ----------------------------------------------------------------------------------------------- by-horizon treatment
def test_one_row_per_scenario_and_year_with_production_labels(out):
    assert len(out) == 12 and set(out.model) == {pj.OPTION_E_MODEL_LABEL} and set(out.role) == {"production"}
    assert (out.loc[(slice(None), 2050), "horizon_treatment"] == pj.HORIZON_CONDITIONAL).all() and (out.loc[(slice(None), [2025, 2030, 2040]), "horizon_treatment"] == pj.HORIZON_BAND).all()


def test_band_years_use_the_empirical_band_and_the_conformal_supplement(out):
    r = out.loc[("TA", 2030)]
    assert r.E_curt_wind_twh_low == pytest.approx(r.E_curt_wind_twh * 1.09) and r.E_curt_wind_twh_high == pytest.approx(r.E_curt_wind_twh * 1.31)
    assert r.E_curt_solar_twh_low == pytest.approx(r.E_curt_solar_twh * 0.87) and r.E_curt_twh_low == pytest.approx(r.E_curt_wind_twh_low + r.E_curt_solar_twh_low)
    assert r.conformal80_wind_lo_twh == pytest.approx(r.E_curt_wind_twh * math.exp(-1.1)) and r.conformal80_wind_hi_twh == pytest.approx(r.E_curt_wind_twh * math.exp(1.1))
    assert r.conformal80_total_hi_twh == pytest.approx(r.E_curt_twh * math.exp(1.05)) and bool(r.conformal_available) and bool(r.calibrated_label)


def test_2025_and_2040_get_the_same_treatment_as_2030(out):
    for y in (2025, 2040):
        r = out.loc[("TA", y)]
        assert r.horizon_treatment == pj.HORIZON_BAND and not math.isnan(r.conformal80_wind_lo_twh) and r.E_curt_wind_twh_high == pytest.approx(r.E_curt_wind_twh * 1.31)


def test_2050_has_no_conformal_no_calibrated_label_and_a_conditional_range(out):
    for sc in ("TB", "TA", "TG"):
        r = out.loc[(sc, 2050)]
        for c in ("conformal80_wind_lo_twh", "conformal80_wind_hi_twh", "conformal80_solar_lo_twh", "conformal80_solar_hi_twh", "conformal80_total_lo_twh", "conformal80_total_hi_twh"):
            assert math.isnan(r[c]), c
        assert not r.conformal_available and not r.calibrated_label and r.horizon_treatment == pj.HORIZON_CONDITIONAL
        assert r.E_curt_twh_low == pytest.approx(r.E_curt_flex_phi_twh) and r.E_curt_twh_high == pytest.approx(r.E_curt_L1_twh)
        assert r.E_curt_wind_twh_low == pytest.approx(r.E_curt_wind_flex_phi_twh) and r.E_curt_wind_twh_high == pytest.approx(r.E_curt_wind_L1_twh)
        assert r.E_curt_twh_low <= r.E_curt_twh <= r.E_curt_twh_high and r.flex_phi == 1.5


def test_unbounded_conformal_quantile_gives_nan_interval_in_band_years(cal):
    c2 = hm.HourlyCalibration(cal.wind, cal.solar, cal.wind_L1, cal.solar_L1, cal.profile, make_bands(logq=None))
    r = pj.project_curtailment_hourly(pte_frame(), c2).set_index(["scenario", "year"]).loc[("TA", 2030)]
    assert math.isnan(r.conformal80_wind_lo_twh) and math.isnan(r.conformal80_wind_hi_twh) and not math.isnan(r.conformal80_solar_lo_twh)
    assert r.E_curt_wind_twh_low == pytest.approx(r.E_curt_wind_twh * 1.09)  # the empirical band is unaffected


# ----------------------------------------------------------------------------------------------- decomposition and support
def test_decomposition_adds_up_and_support_fraction_is_consistent(out):
    for _, r in out.iterrows():
        assert r.curt_in_support_wind_twh + r.curt_out_support_wind_twh == pytest.approx(r.E_curt_wind_twh)
        assert r.curt_in_support_solar_twh + r.curt_out_support_solar_twh == pytest.approx(r.E_curt_solar_twh)
        assert r.curt_in_support_total_twh + r.curt_out_support_total_twh == pytest.approx(r.E_curt_twh)
        assert r.E_curt_twh == pytest.approx(r.E_curt_wind_twh + r.E_curt_solar_twh) and r.in_support_fraction == pytest.approx(1 - r.E_out) and 0 <= r.in_support_fraction <= 1
        assert r.partially_out_of_support == (r.support_status != "within_support") and bool(r.extrapolated_wind) == (r.H_out_wind > 0)
    assert (out.loc[(slice(None), 2050), "E_out"] >= out.loc[(slice(None), 2040), "E_out"].to_numpy()).all()


@pytest.mark.parametrize(("e_out", "h_out", "status"), [(0.02, 0.004, "within_support"), (0.15, 0.036, "within_support"), (0.376, 0.145, "partially_out_of_support"), (0.10, 0.12, "partially_out_of_support"),
                                                        (0.30, 0.0, "partially_out_of_support"), (0.62, 0.40, "mostly_out_of_support")])
def test_support_status_thresholds(e_out, h_out, status):
    assert pj.support_status(e_out, h_out) == status


def test_projection_without_a_scenario_year_raises(cal):
    with pytest.raises(pj.ProjectionError):
        pj.project_curtailment_hourly(pte_frame(), cal, years=(2035,))


def test_gross_basis_curtailed_is_generation_times_rate(out):
    r = out.loc[("TG", 2040)]
    assert r.E_curt_wind_twh == pytest.approx(r.wind_gen_twh * r.C_wind_central) and 0 <= r.C_wind_central <= 1


# ----------------------------------------------------------------------------------------------- D25 known limitation
def test_every_row_carries_the_d25_id_and_the_upward_direction(out):
    assert out.known_limitations.str.contains("D25").all() and out.known_limitations.str.contains(lim.SOLAR_SHORT_RECORD).all() and (out.drift_direction == "upward").all()


def test_d25_text_comes_from_the_adopted_decision_and_contains_its_quantified_figures():
    d = lim.d25_limitation()
    assert d["id"] == "D25" and d["adopted"] == "2026-10-26"
    for needle in ("+1.4 to +1.6", "+10-14", "+1-4 percent", "+15-20 TWh", "+34-52 TWh", "more likely low than high", "not corrected in the adopted specification of D24"):
        assert needle in d["text"], needle
    assert "10-14" in lim.D25_QUANTIFIED["wind_additional_2030"] and "34-52" in lim.D25_QUANTIFIED["wind_additional_2050"]
    assert "ADOPTED" not in d["text"] and "verbatim" not in d["text"]


def test_limitation_loader_refuses_a_decision_that_is_not_adopted(tmp_path):
    p = tmp_path / "d.yaml"
    p.write_text(yaml.safe_dump({"decisions": {"D25": {"status": "pending", "decided": "x"}}}), encoding="utf-8")
    with pytest.raises(lim.LimitationError, match="not 'adopted'"):
        lim.d25_limitation(p)
    with pytest.raises(lim.LimitationError, match="not found"):
        lim.load_adopted_decision("D99", p)


def test_table_is_written_with_limitations_in_metadata_and_sidecar(out, tmp_path):
    dest = lim.write_table_with_limitations(out.reset_index(), tmp_path / "t.parquet")
    side = json.loads((tmp_path / "t.parquet.limitations.json").read_text(encoding="utf-8"))
    meta = lim.read_table_limitations(dest)
    assert meta == side and side["drift_direction"] == "upward" and [x["id"] for x in side["known_limitations"]] == ["D25", "SOLAR_SHORT_RECORD", "D26_NOTE"]
    assert "38 percent" in side["known_limitations"][2]["text"] and "23 percent" in side["known_limitations"][2]["text"]
    assert len(pd.read_parquet(dest)) == 12


def test_build_option_e_table_end_to_end_on_a_synthetic_panel(tmp_path):
    from test_hourly_model import synthetic_panel

    table = pj.build_option_e_table(processed_dir=tmp_path, panel=synthetic_panel())
    assert len(table) == 12 and (tmp_path / pj.OPTION_E_FILENAME).exists() and (tmp_path / (pj.OPTION_E_FILENAME + ".limitations.json")).exists()
    for name in ("hourly_curve_wind.json", "hourly_curve_solar.json", "hourly_curve_wind_L1.json", "hourly_curve_solar_L1.json", hm.BASE_PROFILE_FILENAME, hm.HORIZON_BANDS_FILENAME):
        assert (tmp_path / name).exists(), name
    again = pj.build_option_e_table(processed_dir=tmp_path)  # second call reads the frozen calibration instead of refitting
    pd.testing.assert_frame_equal(table.reset_index(drop=True), again.reset_index(drop=True))
    assert not table.loc[table.year == 2050, "calibrated_label"].any()


# ----------------------------------------------------------------------------------------------- references and mitigation guard
def test_reference_regional_fit_is_labelled_and_recovers_a_logistic():
    P = np.linspace(40, 85, 30)
    ne = pd.DataFrame({"P": P, "C_wind": logistic(P, 0.25, 0.16, 76.0)})
    calib, label = fit_regional_reference(ne)
    assert label == REGIONAL_REFERENCE_LABEL == "reference_regional_NE" and calib.params["L"] == pytest.approx(0.25, abs=0.01)


def test_mitigation_guard_and_passthrough(out):
    avg = pd.DataFrame({"year": list(YEARS), "factor_tco2_per_mwh": 0.1})
    marg = pd.DataFrame({"year": list(YEARS), "om_factor": 0.5, "cm_factor": 0.3})
    flat = out.reset_index()
    with pytest.raises(ValueError, match="no 'model' column"):
        compute_mitigation(flat.drop(columns=["model"]), avg, marg, True, require_model=True)
    res = compute_mitigation(flat, avg, marg, True, require_model=True)
    assert (res.model == pj.OPTION_E_MODEL_LABEL).all() and (res.known_limitations.str.startswith("D25")).all() and (res.drift_direction == "upward").all()
    assert not res.loc[res.year == 2050, "calibrated_label"].any() and "mitigation_deficit_avg_tco2_low" in res.columns
    assert output_prefix(flat) == ""
    assert output_prefix(flat.assign(role="reference")) == "reference_"
