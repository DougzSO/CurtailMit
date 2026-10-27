"""Task 13 tests: long-format final results layer (results_writer), OM/CM split, provenance guard, caveat propagation.

Default tests use a small mocked option E table with the same columns as processed/pte_curtailment_option_E.parquet; the integration test reads the real table.
"""

from __future__ import annotations

import inspect
import json

import numpy as np
import pandas as pd
import pytest

from curtailmit import results_writer as rw
from curtailmit.limitations import LimitationError, d25_limitation
from curtailmit.mitigation import REQUIRED_MODEL, ModelProvenanceError, compute_mitigation
from curtailmit.projection import OPTION_E_MODEL_LABEL, support_status

YEARS = (2025, 2030, 2040, 2050)
SCENARIOS = ("TB", "TA", "TG")
AVG = pd.DataFrame({"year": [2020, 2021, 2022, 2023, 2024, 2025], "factor_tco2_per_mwh": [0.0617, 0.1263, 0.0426, 0.0385, 0.0545, 0.0461]})
MARG = pd.DataFrame({"year": [2020, 2021, 2022, 2023, 2024, 2025], "om": [0.45, 0.6, 0.4, 0.38, 0.45, 0.41], "bm": [0.1, 0.05, 0.03, 0.03, 0.05, 0.07]})
MARG["cm"] = 0.5 * MARG["om"] + 0.5 * MARG["bm"]


def mock_option_e() -> pd.DataFrame:
    rows = []
    for si, sc in enumerate(SCENARIOS):
        for yi, y in enumerate(YEARS):
            w, s = 20.0 * (1 + yi) * (1 + 0.1 * si), 24.0 * (1 + yi)
            cond = y == 2050
            e_out = {2025: 0.01, 2030: 0.03, 2040: 0.38 if (sc, y) == ("TA", 2040) else 0.10, 2050: 0.62}[y]
            h_out = 0.12 if (sc, y) == ("TA", 2040) else 0.01
            status = support_status(e_out, h_out)
            wlo, whi = (w * 1.09, w * 1.3) if not cond else (w * 0.65, w * 1.2)  # the 2025-2040 wind band lies above the central value in the real table
            slo, shi = (s * 0.87, s * 1.13) if not cond else (s * 0.65, s * 1.2)
            row = {
                "scenario": sc, "year": y, "source": "pte_projection", "model": OPTION_E_MODEL_LABEL, "role": "production",
                "horizon_treatment": "decomposition_conditional" if cond else "band_plus_conformal",
                "E_curt_wind_twh": w, "E_curt_wind_twh_low": wlo, "E_curt_wind_twh_high": whi,
                "E_curt_solar_twh": s, "E_curt_solar_twh_low": slo, "E_curt_solar_twh_high": shi,
                "E_curt_twh": w + s, "E_curt_twh_low": wlo + slo, "E_curt_twh_high": whi + shi,
                "conformal80_wind_lo_twh": np.nan if cond else w * 0.3, "conformal80_wind_hi_twh": np.nan if cond else w * 3.0,
                "conformal80_solar_lo_twh": np.nan if cond else s * 0.4, "conformal80_solar_hi_twh": np.nan if cond else s * 2.8,
                "conformal80_total_lo_twh": np.nan if cond else (w + s) * 0.34, "conformal80_total_hi_twh": np.nan if cond else (w + s) * 2.9,
                "E_out": e_out, "H_out_wind": h_out, "H_out_solar": 0.0, "in_support_fraction": 1 - e_out, "flex_phi": 1.5,
                "support_status": status, "partially_out_of_support": status != "within_support",
                "conformal_available": not cond, "calibrated_label": not cond,
                "known_limitations": "D25;SOLAR_SHORT_RECORD", "drift_direction": "upward",
            }
            rows.append(row)
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def tables():
    oe = mock_option_e()
    central, sens = rw.build_final_results_with_sensitivity(oe, AVG, MARG, True)
    return oe, central, sens


# ------------------------------------------------------------------------------------------------------------- 1. provenance guard
def test_guard_constant_matches_projection_label():
    assert REQUIRED_MODEL == OPTION_E_MODEL_LABEL == "option_E_hourly"


def test_provenance_guard_raises_named_exception_not_a_log(caplog):
    oe = mock_option_e()
    f = pd.DataFrame({"year": list(YEARS), "factor_tco2_per_mwh": 0.05})
    m = pd.DataFrame({"year": list(YEARS), "om_factor": 0.4, "cm_factor": 0.2})
    bad = {
        "missing": oe.drop(columns=["model"]),
        "reference": oe.assign(model="reference_national_curve"),
        "one_row": oe.assign(model=["option_E_hourly"] * (len(oe) - 1) + ["other"]),
        "nan": oe.assign(model=[None] + ["option_E_hourly"] * (len(oe) - 1)),
        "role": oe.assign(role="reference"),
    }
    for frame in bad.values():
        with pytest.raises(ModelProvenanceError):
            compute_mitigation(frame, f, m, True, require_model=True)
        with pytest.raises(ModelProvenanceError):
            rw.build_final_results(frame, AVG, MARG, True)
    assert issubclass(ModelProvenanceError, ValueError)
    assert len(compute_mitigation(oe, f, m, True, require_model=True)) == len(oe)
    assert not [r for r in caplog.records if "model" in r.getMessage() and r.levelname in ("WARNING", "ERROR")]


def test_reference_table_still_works_without_the_guard():
    oe = mock_option_e().assign(model="reference_national_curve", role="reference")
    f = pd.DataFrame({"year": list(YEARS), "factor_tco2_per_mwh": 0.05})
    m = pd.DataFrame({"year": list(YEARS), "om_factor": 0.4, "cm_factor": 0.2})
    assert compute_mitigation(oe, f, m, True).role.eq("reference").all()


# ------------------------------------------------------------------------------------------------------------- 2. OM / CM split
def test_om_cm_traceable_to_factors_and_never_summed(tables):
    oe, c, _ = tables
    t = c[(c.component == "total") & (c.year == 2030) & (c.scenario == "TB")].set_index("quantity")
    e = float(oe[(oe.scenario == "TB") & (oe.year == 2030)].E_curt_twh.iloc[0])
    assert t.loc["mitigation_deficit_avg", "central_value"] == pytest.approx(e * 1e6 * 0.0461)
    assert t.loc["mitigation_deficit_marginal_om", "central_value"] == pytest.approx(e * 1e6 * 0.41)
    assert t.loc["mitigation_deficit_marginal_cm", "central_value"] == pytest.approx(e * 1e6 * 0.5 * (0.41 + 0.07))
    assert set(c.quantity) == set(rw.QUANTITIES)
    assert not any("total_marginal" in q or "om_cm" in q for q in c.quantity)
    both = c[c.quantity.isin(["mitigation_deficit_marginal_om", "mitigation_deficit_marginal_cm"])]
    assert (both.groupby(["scenario", "year", "component"]).quantity.nunique() == 2).all()
    assert t.loc["mitigation_deficit_marginal_om", "marginal_proxy_note"].startswith("OM = DEB proxy, CM = REB proxy")


def test_range_after_split_equals_range_before_split(tables):
    oe, c, _ = tables
    lo = c[(c.quantity == "mitigation_deficit_marginal_om") & (c.component == "total")].set_index(["scenario", "year"]).conditional_range_low
    pre = oe.set_index(["scenario", "year"]).E_curt_twh_low * 1e6 * 0.41
    assert np.allclose(lo.sort_index(), pre.sort_index(), rtol=1e-12)


def test_emission_factor_declared_outside_the_range(tables):
    _, c, _ = tables
    m = c[c.quantity.str.startswith("mitigation")]
    assert m.range_basis.str.contains("energy range only; emission factor fixed at 2025, not included in range").all()
    assert (m.mcti_factor_year == "2025").all() and (c[~c.quantity.str.startswith("mitigation")].mcti_factor_year == "not_applicable").all()


def test_d29_central_and_sensitivity_are_separate_and_queryable(tables):
    oe, c, s = tables
    key = ["scenario", "year", "quantity", "component"]
    m = c[c.quantity == "mitigation_deficit_avg"].set_index(key)
    ms = s[s.quantity == "mitigation_deficit_avg"].set_index(key)
    mean_f = AVG[AVG.year.between(2021, 2025)].factor_tco2_per_mwh.mean()
    e = oe.set_index(["scenario", "year"]).E_curt_twh
    for (sc, y, q, comp), r in m.iterrows():
        if comp != "total":
            continue
        assert r.central_value == pytest.approx(e[(sc, y)] * 1e6 * 0.0461)
        assert ms.loc[(sc, y, q, comp), "central_value"] == pytest.approx(e[(sc, y)] * 1e6 * mean_f)
        assert r[rw.SENSITIVITY_COLUMN] == pytest.approx(ms.loc[(sc, y, q, comp), "central_value"])
    assert (s.mcti_factor_year[s.quantity.str.startswith("mitigation")] == "mean_2021_2025").all()
    assert c[~c.quantity.str.startswith("mitigation")][rw.SENSITIVITY_COLUMN].isna().all()
    assert (c.central_value[c.quantity == "curtailed_energy"].to_numpy() == s.central_value[s.quantity == "curtailed_energy"].to_numpy()).all()  # the energy side is identical


def test_factor_year_missing_raises():
    with pytest.raises(Exception, match="Missing years"):
        rw.build_final_results(mock_option_e(), AVG[AVG.year != 2025], MARG, True)


# ------------------------------------------------------------------------------------------------------------- 3. schema and naming
def test_required_names_and_row_grid(tables):
    oe, c, _ = tables
    for col in ("central_value", "conditional_range_low", "conditional_range_high", "range_basis", "horizon_treatment", "known_limitations", "calibrated_label", "support_status", "drift_direction"):
        assert col in c.columns
    assert len(c) == len(oe) * (4 * 3 + 1) == 156
    assert set(c.horizon_treatment) == {"band_plus_conformal", "decomposition_conditional"}
    assert c.range_basis.str.strip().str.len().gt(0).all()
    assert (c.conditional_range_low <= c.conditional_range_high).all()


def test_no_statistical_confidence_language_anywhere(tables):
    _, c, s = tables
    assert not [col for col in c.columns if rw.FORBIDDEN_LANGUAGE.search(col)]
    for frame in (c, s):
        for col in rw._TEXT_COLUMNS:
            assert not frame[col].astype(str).map(lambda x: bool(rw.FORBIDDEN_LANGUAGE.search(x))).any()
    for bad in ("ci_low", "ci_high", "confidence_level", "x_ci"):
        assert rw.FORBIDDEN_LANGUAGE.search(bad)
    new_part = inspect.getsource(rw).split("# Task 13 (D27 option A)", 1)[1]
    lines = [ln for ln in new_part.splitlines() if "FORBIDDEN_LANGUAGE = re.compile" not in ln]  # the rule that forbids the words is the only place that may spell them
    assert not rw.FORBIDDEN_LANGUAGE.search(" ".join(lines))


def test_validator_rejects_forbidden_names_and_texts(tables):
    _, c, _ = tables
    with pytest.raises(rw.FinalResultsError, match="column names"):
        rw.validate_final_results(c.assign(ci_low=1.0))
    with pytest.raises(rw.FinalResultsError, match="wording"):
        rw.validate_final_results(c.assign(range_basis=c.range_basis + "; 80 percent confidence"))


# ------------------------------------------------------------------------------------------------------------- 4. caveat propagation, all horizons
def test_caveats_on_every_row_for_every_horizon_and_after_filtering(tables, tmp_path):
    _, c, _ = tables
    for y in YEARS:
        sub = c[(c.year == y) & (c.quantity == "mitigation_deficit_marginal_cm") & (c.component == "wind")]
        assert len(sub) == 3
        assert sub.known_limitations.str.contains("D25").all() and sub.drift_direction.eq("upward").all()
        assert sub.known_limitations_text.str.contains("D25").all() and sub.calibrated_label.eq(y != 2050).all()
        assert sub.support_status.notna().all()
    p = tmp_path / "x.csv"
    c[c.year == 2050].to_csv(p, index=False)
    back = pd.read_csv(p)
    assert back.known_limitations.eq("D25;SOLAR_SHORT_RECORD").all() and back.calibrated_label.eq(False).all()
    assert back.known_limitations_text.str.contains("flexibility assumption").all()


def test_2050_is_conditional_and_has_no_supplement(tables):
    _, c, _ = tables
    y = c[c.year == 2050]
    assert (y.horizon_treatment == "decomposition_conditional").all() and not y.calibrated_label.any()
    assert y.supplement_low.isna().all() and y.supplement_high.isna().all()
    assert y.supplement_basis.str.startswith("not_available").all()
    assert y.range_basis.str.contains("flexibility_assumption_phi_1.5_to_L1").all()
    o = c[c.year < 2050]
    assert o.calibrated_label.all() and o.supplement_low.notna().all() and o.range_basis.str.contains("empirical_annual_backtest_band").all()
    assert (o.supplement_low <= o.supplement_high).all()


def test_text_summary_figures_match_adopted_d25():
    text = d25_limitation()["text"]
    assert "1.4" in text and "1.6" in text and "2022-2026" in text
    row = pd.Series({"known_limitations": "D25;SOLAR_SHORT_RECORD", "support_status": "within_support", "in_support_fraction": 1.0, "horizon_treatment": "band_plus_conformal"})
    assert "+1.4 to +1.6 pp per year" in rw.limitations_text(row)


def test_validator_rejects_calibrated_2050_and_missing_caveats(tables):
    _, c, _ = tables
    with pytest.raises(rw.FinalResultsError, match="calibrated_label"):
        rw.validate_final_results(c.assign(calibrated_label=True))
    with pytest.raises(rw.FinalResultsError):
        rw.validate_final_results(c.assign(known_limitations="SOLAR_SHORT_RECORD"))
    with pytest.raises(rw.FinalResultsError, match="supplement"):
        d = c.copy()
        d.loc[d.year == 2050, "supplement_low"] = 1.0
        rw.validate_final_results(d)


def test_d25_must_be_adopted_to_attach_the_limitation(tmp_path):
    bad = tmp_path / "d.yaml"
    bad.write_text("decisions:\n  D25:\n    status: pending\n    decided: x\n", encoding="utf-8")
    with pytest.raises(LimitationError):
        d25_limitation(bad)


# ------------------------------------------------------------------------------------------------------------- 5. support status (TA / 2040)
def test_ta_2040_partial_support_flag_propagates_to_every_row(tables):
    _, c, _ = tables
    ta40 = c[(c.scenario == "TA") & (c.year == 2040)]
    assert len(ta40) == 13 and ta40.partially_out_of_support.all() and (ta40.support_status == "partially_out_of_support").all()
    assert ta40.known_limitations_text.str.contains("no historical analogue").all()
    others = c[(c.year == 2040) & (c.scenario != "TA")]
    assert not others.partially_out_of_support.any() and (others.support_status == "within_support").all()
    assert c[c.year == 2050].partially_out_of_support.all() and (c[c.year == 2050].support_status == "mostly_out_of_support").all()


def test_support_status_conflict_with_the_upstream_rule_stops():
    oe = mock_option_e()
    oe.loc[(oe.scenario == "TB") & (oe.year == 2030), "support_status"] = "mostly_out_of_support"
    with pytest.raises(rw.SupportStatusConflictError):
        rw.build_final_results(oe, AVG, MARG, True)


# ------------------------------------------------------------------------------------------------------------- 6. classification, I/O
def test_unclassified_wording_has_no_deb_reb(tables):
    oe, _, _ = tables
    c = rw.build_final_results(oe, AVG, MARG, False)
    notes = " ".join(c.marginal_proxy_note.unique())
    assert "aggregate (unclassified)" in notes and "DEB" not in notes and "REB" not in notes and not c.classification_available.any()


def test_write_read_round_trip_and_sidecar(tables, tmp_path):
    _, c, s = tables
    paths = rw.write_final_results(c, s, tmp_path)
    for k in ("csv", "parquet", "limitations", "sensitivity_csv", "sensitivity_parquet"):
        assert paths[k].exists()
    back = rw.read_final_results(paths["csv"])
    pd.testing.assert_frame_equal(back[["scenario", "year", "quantity", "component"]], c[["scenario", "year", "quantity", "component"]])
    assert np.allclose(back.central_value, c.central_value) and back.known_limitations.eq(c.known_limitations).all()
    side = json.loads(paths["limitations"].read_text(encoding="utf-8"))
    ids = [x["id"] for x in side["known_limitations"]]
    assert ids[0] == "D25" and side["known_limitations"][0]["text"] == d25_limitation()["text"]
    assert "point-value emission factor" in side["uncertainty_composition"] and "2021-2025" in side["emission_factor_rule"]
    assert rw.read_final_results(paths["parquet"]).shape == c.shape


# ------------------------------------------------------------------------------------------------------------- 7. legacy compatibility (D27 option A)
def test_legacy_resultsrow_still_importable_and_marked_deprecated():
    assert "DEPRECATED" in rw.ResultsRow.__doc__ and "DEPRECATION" in rw.__doc__
    assert rw.RESULTS_COLUMNS[0] == "scenario" and callable(rw.write_results_csv) and callable(rw.load_results_json)


# ------------------------------------------------------------------------------------------------------------- integration (real table)
@pytest.mark.integration
def test_real_option_e_table_end_to_end(tmp_path):
    oe = rw.load_option_e_table()
    assert len(oe) == 12 and (oe.model == "option_E_hourly").all()
    avg, margins = rw.load_emission_factors()
    cls = True
    central, sens = rw.build_final_results_with_sensitivity(oe, avg, margins, cls)
    assert len(central) == 156 and len(sens) == 156
    paths = rw.write_final_results(central, sens, tmp_path)
    back = rw.read_final_results(paths["parquet"])
    assert back.shape == central.shape
    e = back[(back.quantity == "curtailed_energy") & (back.component == "total")].set_index(["scenario", "year"])
    tbl = oe.set_index(["scenario", "year"])
    for key in tbl.index:
        assert e.loc[key, "central_value"] == pytest.approx(tbl.loc[key, "E_curt_twh"], rel=1e-12)
        assert e.loc[key, "conditional_range_low"] == pytest.approx(tbl.loc[key, "E_curt_twh_low"], rel=1e-12)
        assert e.loc[key, "conditional_range_high"] == pytest.approx(tbl.loc[key, "E_curt_twh_high"], rel=1e-12)
    # values quoted in the Task 11F report
    for (sc, y), want in {("TB", 2025): 43.8, ("TB", 2030): 64.3, ("TB", 2040): 127.6, ("TB", 2050): 354.8, ("TA", 2040): 242.4, ("TA", 2050): 536.1, ("TG", 2040): 181.4, ("TG", 2050): 333.9}.items():
        assert e.loc[(sc, y), "central_value"] == pytest.approx(want, abs=0.06)
    f25 = float(avg.loc[avg.year == 2025, "factor_tco2_per_mwh"].iloc[0])
    om25, cm25 = (float(margins.loc[margins.year == 2025, c].iloc[0]) for c in ("om", "cm"))
    for q, f in (("mitigation_deficit_avg", f25), ("mitigation_deficit_marginal_om", om25), ("mitigation_deficit_marginal_cm", cm25)):
        m = back[(back.quantity == q) & (back.component == "total")].set_index(["scenario", "year"])
        for key in tbl.index:
            assert m.loc[key, "central_value"] == pytest.approx(tbl.loc[key, "E_curt_twh"] * 1e6 * f, rel=1e-12)
    y50 = back[back.year == 2050]
    assert not y50.calibrated_label.any() and y50.supplement_low.isna().all() and (y50.horizon_treatment == "decomposition_conditional").all()
    assert set(back[(back.year == 2040) & back.partially_out_of_support].scenario) == {"TA"}
    assert back.known_limitations.str.contains("D25").all() and not [c for c in back.columns if rw.FORBIDDEN_LANGUAGE.search(c)]
    mean_f = avg[avg.year.between(2021, 2025)].factor_tco2_per_mwh.mean()
    sa = sens[(sens.quantity == "mitigation_deficit_avg") & (sens.component == "total")].set_index(["scenario", "year"])
    assert sa.loc[("TB", 2050), "central_value"] == pytest.approx(tbl.loc[("TB", 2050), "E_curt_twh"] * 1e6 * mean_f, rel=1e-12)
    side = json.loads(paths["limitations"].read_text(encoding="utf-8"))
    assert side["known_limitations"][0]["text"] == d25_limitation()["text"]
