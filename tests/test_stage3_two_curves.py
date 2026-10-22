"""Task 11B tests: D22 two-curve application to PTE scenarios, low/central/high propagation, and the mitigation carry-through. Mocked fixtures."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from curtailmit import projection as pj
from curtailmit.calibration import CalibrationResult, TechnologyCurve, fit_calibration, logistic
from curtailmit.mitigation import compute_mitigation
from curtailmit.schemas import CalibrationParams, PTEScenarioTable, ScenarioYearData


def curve(name, L, k, P0, p_min, p_max, seed) -> tuple[TechnologyCurve, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    P = rng.uniform(p_min, p_max, 40)
    frame = pd.DataFrame({"P": P, "C": np.clip(logistic(P, L, k, P0) + rng.normal(0, 0.02, 40), 0, 1)})
    params = fit_calibration(frame)  # the central curve is the real fit of the frame, as in run_calibration (so it sits inside its own bootstrap interval)
    return TechnologyCurve(name, params, 0.02, 40, p_min, p_max), frame


def result() -> CalibrationResult:
    wind, wf = curve("wind", 1.0, 0.17, 35.0, 10.0, 30.0, 1)
    solar, sf = curve("solar", 1.0, 0.09, 38.0, 15.0, 40.0, 2)  # a different observed range than wind
    absurd = CalibrationParams(params={"L": 0.001, "k": 0.001, "P0": 999.0}, fit_date_utc="x", n_calibration_points=1)
    diag = TechnologyCurve("combined_diagnostic", absurd, 0.0, 1, 0.0, 1.0, primary=False)
    return CalibrationResult(wind, solar, diag, wf, sf, pd.DataFrame())


def pte_table() -> PTEScenarioTable:
    def yr(solar, wind, total=1000.0):
        return ScenarioYearData(solar_pct=solar, wind_pct=wind, total_generation_twh=total)

    base = {2025: yr(10, 15), 2030: yr(15, 15), 2040: yr(20, 20), 2050: yr(20, 40)}
    return PTEScenarioTable(TB=base, TA={**base, 2050: yr(20, 45)}, TG=base)


def test_combination_rule_closed_form_and_diagnostic_curve_not_used():
    res = result()
    out = pj.project_curtailment_two_curves(pte_table(), res, n_boot=20, seed=0)
    assert len(out) == 12 and set(out.year) == {2025, 2030, 2040, 2050}
    row = out[(out.scenario == "TB") & (out.year == 2040)].iloc[0]
    pw, ps = res.wind.calibration.params, res.solar.calibration.params
    cw, cs = logistic(np.array([40.0]), pw["L"], pw["k"], pw["P0"])[0], logistic(np.array([40.0]), ps["L"], ps["k"], ps["P0"])[0]
    assert row.P == 40.0 and row.wind_gen_twh == pytest.approx(200.0) and row.solar_gen_twh == pytest.approx(200.0)
    assert row.wind_curtailed_twh_central == pytest.approx(200.0 * cw) and row.solar_curtailed_twh_central == pytest.approx(200.0 * cs)
    assert row.total_curtailed_twh_central == pytest.approx(row.wind_curtailed_twh_central + row.solar_curtailed_twh_central)
    assert row.E_curt_twh == row.total_curtailed_twh_central and row.source == "pte_projection"  # D16 label, no rescaling
    assert row.total_generation_twh == 1000.0


def test_extrapolation_flags_are_per_technology():
    out = pj.project_curtailment_two_curves(pte_table(), result(), n_boot=10).set_index(["scenario", "year"])
    assert not out.loc[("TB", 2025), "extrapolated_wind"] and not out.loc[("TB", 2025), "extrapolated_solar"]  # P = 25
    p40 = out.loc[("TB", 2040)]  # P = 40: wind range ends at 30, solar's at 40 -> wind extrapolated, solar not
    assert p40.extrapolated_wind and not p40.extrapolated_solar
    p65 = out.loc[("TA", 2050)]
    assert p65.extrapolated_wind and p65.extrapolated_solar


def test_low_central_high_ordering_and_total_bounds_are_the_sum_of_component_bounds():
    out = pj.project_curtailment_two_curves(pte_table(), result(), n_boot=40, seed=3)
    for level_lo, level_hi in (("low", "central"), ("central", "high")):
        for col in ("wind_curtailed_twh", "solar_curtailed_twh", "total_curtailed_twh"):
            assert (out[f"{col}_{level_lo}"] <= out[f"{col}_{level_hi}"] + 1e-9).all()
    for level in ("low", "high"):
        assert (out[f"total_curtailed_twh_{level}"] - out[f"wind_curtailed_twh_{level}"] - out[f"solar_curtailed_twh_{level}"]).abs().max() < 1e-9
    far = out[(out.scenario == "TA") & (out.year == 2050)].iloc[0]
    near = out[(out.scenario == "TA") & (out.year == 2025)].iloc[0]
    assert (far.C_wind_high - far.C_wind_low) > (near.C_wind_high - near.C_wind_low)  # wider far outside the calibrated range


def test_bootstrap_is_reproducible_with_the_same_seed():
    a = pj.project_curtailment_two_curves(pte_table(), result(), n_boot=15, seed=5)
    b = pj.project_curtailment_two_curves(pte_table(), result(), n_boot=15, seed=5)
    pd.testing.assert_frame_equal(a, b)


def test_missing_year_fails_explicitly():
    table = pte_table()
    del table.TB[2040]
    with pytest.raises(pj.ProjectionError, match="TB"):
        pj.project_curtailment_two_curves(table, result(), n_boot=5)


def test_mitigation_carries_low_central_high_and_the_wind_solar_split():
    proj = pj.project_curtailment_two_curves(pte_table(), result(), n_boot=15, seed=1)
    years = sorted(proj.year.unique())
    avg = pd.DataFrame({"year": years, "factor_tco2_per_mwh": [0.10, 0.08, 0.06, 0.04]})
    marg = pd.DataFrame({"year": years, "om_factor": [0.5, 0.45, 0.4, 0.35], "cm_factor": [0.3, 0.3, 0.3, 0.3]})
    out = compute_mitigation(proj, avg, marg, classification_available=True)
    r = out[(out.scenario == "TB") & (out.year == 2040)].iloc[0]
    src = proj[(proj.scenario == "TB") & (proj.year == 2040)].iloc[0]
    assert r.mitigation_deficit_avg_tco2 == pytest.approx(src.E_curt_twh * 1e6 * 0.06)
    assert r.mitigation_deficit_avg_tco2_low == pytest.approx(src.E_curt_twh_low * 1e6 * 0.06)
    assert r.mitigation_deficit_avg_tco2_high == pytest.approx(src.E_curt_twh_high * 1e6 * 0.06)
    assert r.mitigation_deficit_marginal_tco2_high == pytest.approx(src.E_curt_twh_high * 1e6 * 0.4)  # one marginal factor, passed through unchanged
    assert r.mitigation_deficit_avg_wind_tco2 + r.mitigation_deficit_avg_solar_tco2 == pytest.approx(r.mitigation_deficit_avg_tco2)
    assert r.mitigation_deficit_avg_tco2_low <= r.mitigation_deficit_avg_tco2 <= r.mitigation_deficit_avg_tco2_high
    assert "mitigation_deficit_marginal_om_tco2" not in out.columns  # the OM/CM split is Task 13
    assert bool(r.extrapolated_wind) == bool(src.extrapolated_wind)


def test_mitigation_without_the_new_columns_is_unchanged():
    proj = pd.DataFrame({"scenario": ["TB"], "year": [2025], "E_curt_twh": [10.0]})
    avg, marg = pd.DataFrame({"year": [2025], "factor_tco2_per_mwh": [0.1]}), pd.DataFrame({"year": [2025], "om_factor": [0.5], "cm_factor": [0.3]})
    out = compute_mitigation(proj, avg, marg, True)
    assert list(out.columns) == ["scenario", "year", "E_curt_twh", "mitigation_deficit_avg_tco2", "mitigation_deficit_marginal_tco2", "marginal_proxy_used", "classification_available"]


@pytest.mark.integration
def test_live_pte_curtailment_on_real_database_root():
    """Needs Stage 1 artifacts in the real DATABASE_ROOT. Run manually: pytest -m integration"""
    from curtailmit.paths import get_processed_dir

    if not (get_processed_dir() / "ons_penetration_monthly.parquet").exists():
        pytest.skip("Stage 1 outputs not present")
    out = pj.build_pte_curtailment_table(n_boot=100)
    assert len(out) == 12 and (out.total_curtailed_twh_low <= out.total_curtailed_twh_high).all()
    assert out.loc[out.year >= 2040, ["extrapolated_wind", "extrapolated_solar"]].all().all()
    assert not out.loc[out.year == 2025, "extrapolated_wind"].any()
