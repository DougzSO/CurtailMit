"""Task 8 tests: run_stage1 orchestration order, report generation, FAIL handling, fallback/calibration non-invocation. All steps are mocked."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from curtailmit import data_ingestion as di
from curtailmit import stage1_report as sr
from curtailmit.ons_solar_gap import DAILY_GAP_FILENAME, DISPATCHED_MONTHLY_FILENAME, SchemaFinding
from curtailmit.schemas import DataQualityReport


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_ROOT", str(tmp_path / "db"))
    (tmp_path / "db" / "raw" / "ons" / "capacity_factor").mkdir(parents=True)
    (tmp_path / "db" / "raw" / "ons" / "capacity_factor" / "x.parquet.manifest.json").write_text(
        json.dumps({"source_url": "u", "http_status": 200, "retrieved_at_utc": "2026-10-22T10:00:00+00:00", "sha256": "a", "byte_size": 1000}), encoding="utf-8")
    return tmp_path / "db"


def monthly_frame() -> pd.DataFrame:
    """2021-01..2023-12: gap ~100 MWmed (6-8 %) until 2023-03, then ~3000 MWmed (the D20 step)."""
    periods = pd.period_range("2021-01", "2023-12", freq="M")
    hours = np.array([p.days_in_month * 24 for p in periods])
    gap = np.array([100.0 if p < pd.Period("2023-04") else 3000.0 for p in periods])
    disp = np.full(len(periods), 1500.0)
    m = pd.DataFrame({"dispatched_mwmed": disp, "balanco_mwmed": disp + gap, "hours": hours, "hours_in_month": hours, "coverage": 1.0,
                      "dispatched_matched_mwh": disp * hours, "balanco_matched_mwh": (disp + gap) * hours}, index=periods)
    m["gap_mwmed"] = gap
    m["gap_gwh"] = gap * hours / 1000
    m["balanco_gwh"] = m["balanco_mwmed"] * hours / 1000
    m["gap_pct_of_balanco"] = 100 * m["gap_gwh"] / m["balanco_gwh"]
    return m


def make_steps(db: Path, calls: list[str], *, classification_available=True, drop_dispatched=False, wind_start="2022-01-01", fail_in: str | None = None) -> dict:
    interim, processed = db / "interim", db / "processed"
    interim.mkdir(exist_ok=True)
    processed.mkdir(exist_ok=True)

    def maybe_fail(name):
        calls.append(name)
        if fail_in == name:
            raise RuntimeError(f"{name} boom")

    def curtailment(targets, use_cache):
        maybe_fail("curtailment")
        return {"interim_path": str(interim / "ons_curtailment_raw.parquet"), "n_rows": 10, "packages": [
            {"source": "wind", "resolved_package_id": "wind-pkg", "earliest_date": wind_start, "latest_date": "2026-10-20", "n_rows": 1000},
            {"source": "solar", "resolved_package_id": "solar-pkg", "earliest_date": "2024-04-01", "latest_date": "2026-10-20", "n_rows": 500}]}

    def capacity_factor(targets, use_cache):
        maybe_fail("capacity_factor")
        return {"paths": {}, "findings": [SchemaFinding("2022-12"), SchemaFinding("2026-01", type_changes={"val_fatorcapacidade": "string -> double"})]}

    def generation(targets, use_cache):
        maybe_fail("generation")
        if not drop_dispatched:
            sr_monthly = monthly_frame().copy()
            out = sr_monthly.copy()
            out.index = out.index.astype(str)
            out.index.name = "month"
            out.reset_index().to_parquet(interim / DISPATCHED_MONTHLY_FILENAME, index=False)
            days = pd.date_range("2023-03-20", "2023-05-20", freq="D")
            gap = np.where(days < pd.Timestamp("2023-04-29"), 100.0, 3000.0)
            gap[days == pd.Timestamp("2023-05-10")] = 60.0  # isolated glitch day after the step
            pd.DataFrame({"day": days, "gap_mwmed": gap}).to_parquet(interim / DAILY_GAP_FILENAME, index=False)
        (processed / "baseline_2020_generation.json").write_text(json.dumps(
            {"source": "historical_ons", "year": 2020, "solar_twh": 5.23, "wind_twh": 54.30, "total_twh": 554.35, "penetration_pct": 10.74}), encoding="utf-8")
        return {"baseline_path": str(processed / "baseline_2020_generation.json"),
                "package": {"earliest_date": "2016-01-01", "latest_date": "2026-10-20", "n_rows": 1234}}

    def classification(targets, curtailment_result):
        maybe_fail("classification")
        if classification_available:
            (processed / "classification_available.json").write_text("{}", encoding="utf-8")
            return {"classification_available": True, "reason": None, "energy_mwh_by_category": {"DEB": 3000.0, "REB": 2000.0, "EUB": 1000.0, "(none)": 1.0},
                    "unclassified_energy_share": 1 / 6001}
        (processed / "classification_available.json").write_text("{}", encoding="utf-8")
        return {"classification_available": False, "reason": "dictionary missing", "energy_mwh_by_category": {}, "unclassified_energy_share": None}

    def mcti(targets, use_cache):
        maybe_fail("mcti")
        pd.DataFrame({"year": [2020, 2021], "om_is_derived": [True, True], "cm_is_derived": [True, True]}).to_parquet(processed / "mcti_margin_factors.parquet", index=False)
        return {"average_years": list(range(2006, 2026)), "average_partial_years": [2026], "margin_years": [2020, 2021], "margin_skipped": {2026: "incomplete"},
                "margin_path": str(processed / "mcti_margin_factors.parquet"), "manual_ingestion_used": []}

    return {"curtailment": curtailment, "capacity_factor": capacity_factor, "generation": generation, "classification": classification, "mcti": mcti}


def run(db, tmp_path, **kw):
    calls: list[str] = []
    steps = make_steps(db, calls, **{k: v for k, v in kw.items() if k != "markdown"})
    md = tmp_path / "out" / "report.md"
    return di.run_stage1(steps=steps, markdown_path=md, print_summary=False), calls, md


def test_order_and_report_artifacts(db, tmp_path, capsys):
    out, calls, md = run(db, tmp_path)
    assert calls == ["curtailment", "capacity_factor", "generation", "classification", "mcti"]  # dispatched solar before generation, classification after curtailment
    report = DataQualityReport.model_validate_json((db / "processed" / sr.REPORT_JSON_NAME).read_text(encoding="utf-8"))
    assert out["overall_status"] == report.overall_status == "degraded"
    assert list((db / "logs").glob("stage1_data_quality_report_*.json")) and md.exists()
    by_id = {c.id: c for c in report.checks}
    assert by_id["ons_wind_coverage"].status == "PASS" and by_id["ons_solar_coverage"].status == "WARNING"
    assert by_id["solar_2020_baseline"].status == "WARNING" and report.solar_curtailment_2020_baseline == "documented_zero_not_measured"
    assert by_id["dispatched_solar"].status == "PASS" and by_id["cf_schema"].status == "WARNING"
    assert by_id["pre_2023_gap"].status == "WARNING" and report.pre_2023_solar_gap["step_day"] == "2023-04-29"
    assert report.anomalous_days == ["2023-05-10 (gap 60 MWmed)"] and by_id["anomalous_days"].status == "WARNING"
    assert by_id["classification"].status == "PASS" and report.classification_unclassified_share_pct == pytest.approx(100 / 6001, abs=1e-4)
    assert by_id["mcti_margin"].status == "WARNING" and report.mcti_om_is_derived and report.mcti_cm_is_derived and report.mcti_skipped_years == {"2026": "incomplete"}
    assert by_id["pld"].status == "NOT APPLICABLE" and by_id["aneel_fallback"].status == "NOT APPLICABLE" and not report.pld_enabled
    assert by_id["validation_data"].status == "WARNING" and not report.validation_data_loaded
    assert report.manifest_summary["ons/capacity_factor"]["n_files"] == 1
    assert {c.status for c in report.checks} <= {"PASS", "WARNING", "NOT APPLICABLE", "FAIL"}
    assert "FAIL" not in {c.status for c in report.checks}


def test_calibration_readiness_is_separate_and_does_not_change_statuses(db, tmp_path):
    out, _, md = run(db, tmp_path)
    text = md.read_text(encoding="utf-8")
    checks_part, _, readiness = text.partition("## 4. Calibration readiness")
    assert "forward-looking, not a Stage 1 data-quality finding" in text and "P <= 29.4 %" in readiness and "docs/task9_calibration_report.md" in readiness
    assert "C_wind" not in checks_part.split("## 2. Checks")[1]  # no calibration content among the checked items
    assert out["report"]["calibration_readiness_note"] and all("C_wind" not in c["detail"] for c in out["report"]["checks"])


def test_secondary_fallback_and_calibration_are_never_invoked(db, tmp_path, monkeypatch):
    from curtailmit import aneel_client, calibration

    def boom(*a, **k):
        raise AssertionError("must not be called by run_stage1")

    monkeypatch.setattr(aneel_client, "fetch_generation_fallback", boom)
    for name in ("run_calibration", "build_technology_frames", "bootstrap_calibration_ci", "fit_calibration"):
        monkeypatch.setattr(calibration, name, boom)
    out, _, _ = run(db, tmp_path)
    assert out["report"]["aneel_fallback_invoked"] is False and out["report"]["fallback_sources_used"] == []
    src = Path(di.__file__).read_text(encoding="utf-8") + Path(sr.__file__).read_text(encoding="utf-8")
    assert "import aneel_client" not in src and "fetch_generation_fallback(" not in src and "import calibration" not in src and "run_calibration(" not in src


def test_step_failure_writes_a_fail_report_and_stops(db, tmp_path):
    calls: list[str] = []
    with pytest.raises(di.Stage1Error, match="generation"):
        di.run_stage1(steps=make_steps(db, calls, fail_in="generation"), markdown_path=tmp_path / "r.md", print_summary=False)
    assert calls == ["curtailment", "capacity_factor", "generation"]  # nothing after the failing step ran
    report = DataQualityReport.model_validate_json((db / "processed" / sr.REPORT_JSON_NAME).read_text(encoding="utf-8"))
    assert report.overall_status == "failed" and report.checks[0].status == "FAIL" and "generation boom" in report.checks[0].detail


def test_missing_dispatched_series_makes_the_report_failed_and_raises(db, tmp_path):
    with pytest.raises(di.Stage1Error, match="failed"):
        run(db, tmp_path, drop_dispatched=True)
    report = json.loads((db / "processed" / sr.REPORT_JSON_NAME).read_text(encoding="utf-8"))
    assert report["overall_status"] == "failed" and any(c["id"] == "dispatched_solar" and c["status"] == "FAIL" for c in report["checks"])


def test_wind_coverage_below_floor_is_a_fail(db, tmp_path):
    with pytest.raises(di.Stage1Error):
        run(db, tmp_path, wind_start="2022-03-01")


def test_unavailable_classification_is_a_warning_not_a_failure(db, tmp_path):
    out, _, _ = run(db, tmp_path, classification_available=False)
    checks = {c["id"]: c for c in out["report"]["checks"]}
    assert checks["classification"]["status"] == "WARNING" and out["report"]["classification_available"] is False


def test_all_pass_would_be_ok():
    checks_ok = [sr.CheckResult(id="a", name="a", status="PASS", detail="")]
    assert not any(c.status in ("WARNING", "FAIL") for c in checks_ok)


def test_manifest_summary_groups_by_source_folder(tmp_path):
    for sub, size in (("ons/a", 5), ("ons/a", 7), ("mcti/b", 1)):
        d = tmp_path / sub
        d.mkdir(parents=True, exist_ok=True)
        (d / f"f{size}.manifest.json").write_text(json.dumps({"byte_size": size, "retrieved_at_utc": f"2026-01-0{size % 9 + 1}T00:00:00+00:00"}), encoding="utf-8")
    s = sr.manifest_summary(tmp_path)
    assert s["ons/a"]["n_files"] == 2 and s["ons/a"]["total_bytes"] == 12 and s["mcti/b"]["n_files"] == 1


@pytest.mark.integration
def test_live_run_stage1_on_cached_database_root(tmp_path):
    """End to end on the real DATABASE_ROOT (raw files cached by earlier runs; MCTI and CKAN listings are fetched live). Run manually: pytest -m integration"""
    out = di.run_stage1(use_cache=True, markdown_path=tmp_path / "stage1_report.md", print_summary=False)
    assert out["overall_status"] in ("ok", "degraded")
    report = DataQualityReport(**out["report"])
    assert report.aneel_fallback_invoked is False and report.classification_available and not any(c.status == "FAIL" for c in report.checks)
    assert report.baseline_2020["total_twh"] == pytest.approx(554.35, abs=0.005)
