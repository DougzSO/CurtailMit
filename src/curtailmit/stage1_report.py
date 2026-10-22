"""Task 8 - Stage 1 data-quality report: metrics, per-item status checks, JSON + Markdown rendering.

Reads the Stage 1 step results and the artifacts they wrote (DATABASE_ROOT) and builds a validated `schemas.DataQualityReport`.
Every checked item gets one status: PASS / WARNING (documented, non-blocking limitation, never reported as a plain pass) /
NOT APPLICABLE / FAIL. A FAIL makes the overall status "failed" and `run_stage1` raises.

The calibration-readiness paragraph (D21/D22) is a forward-looking methodological note carried into Stage 3; it is kept apart from
the checks and never changes the status of a Stage 1 acquisition check.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from curtailmit.ons_solar_gap import DAILY_GAP_FILENAME, DISPATCHED_MONTHLY_FILENAME, analyse_gap, find_step_day, glitch_days, load_dispatched_monthly
from curtailmit.schemas import CheckResult, CoverageInfo, DataQualityReport
from curtailmit.validation import resolve_ons_min_coverage

logger = logging.getLogger(__name__)

REPORT_JSON_NAME = "data_quality_report.json"
GLITCH_THRESHOLD_MWMED = 500.0  # a post-step day whose gap falls below this looks like dispatched-only (D20 addendum: 2024-11-09)
CALIBRATION_NOTE = (
    "Forward-looking methodological limitation carried into Stage 3 (D21/D22), not a Stage 1 acquisition defect. Curtailment is modeled as two "
    "independent technology-specific curves, C_wind(P) and C_solar(P), both functions of the shared P(t) = wind_pct + solar_pct. Both curves are "
    "fit on data with P <= 29.4 % and are extrapolated for every PTE scenario/year above that. Their bootstrap intervals cover sampling uncertainty "
    "only, not the logistic functional form. Details: docs/task9_calibration_report.md."
)


def _cov(earliest: Any, latest: Any, n: int) -> CoverageInfo:
    return CoverageInfo(earliest_date=str(earliest) if earliest is not None else None, latest_date=str(latest) if latest is not None else None, n_records=int(n))


def manifest_summary(raw_root: Path) -> dict[str, dict[str, Any]]:
    """Per top-level raw source folder: retrieval-manifest count, total bytes, earliest/latest retrieval time (from the manifests on disk)."""
    summary: dict[str, dict[str, Any]] = {}
    if not raw_root.exists():
        return summary
    for manifest_path in sorted(raw_root.rglob("*.manifest.json")):
        rel = manifest_path.relative_to(raw_root).parts
        key = "/".join(rel[:2]) if len(rel) > 2 else rel[0]
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        entry = summary.setdefault(key, {"n_files": 0, "total_bytes": 0, "first_retrieved_utc": None, "last_retrieved_utc": None})
        entry["n_files"] += 1
        entry["total_bytes"] += int(data.get("byte_size", 0))
        ts = data.get("retrieved_at_utc")
        if ts:
            entry["first_retrieved_utc"] = min(filter(None, [entry["first_retrieved_utc"], ts]))
            entry["last_retrieved_utc"] = max(filter(None, [entry["last_retrieved_utc"], ts]))
    return summary


def _gap_metrics(processed_interim: Path) -> tuple[dict[str, Any], list[str], pd.DataFrame | None]:
    """D20 secondary gap and anomalous days, computed from the stored dispatched/balance series (never typed in)."""
    monthly_path = processed_interim / DISPATCHED_MONTHLY_FILENAME
    if not monthly_path.exists():
        return {}, [], None
    monthly = load_dispatched_monthly(monthly_path)
    info: dict[str, Any] = {"months": len(monthly), "first_month": str(monthly.index.min()), "last_month": str(monthly.index.max())}
    anomalies: list[str] = []
    if len(monthly) >= 18:
        analysis = analyse_gap(monthly)
        info.update({
            "step_month": analysis.first_nontrivial_month,
            "pre_step_gap_mwmed_min": round(analysis.pre_step_gap_mwmed_min, 1), "pre_step_gap_mwmed_max": round(analysis.pre_step_gap_mwmed_max, 1),
            "pre_step_gap_pct_min": round(analysis.pre_step_gap_pct_min, 1), "pre_step_gap_pct_max": round(analysis.pre_step_gap_pct_max, 1),
            "pre_step_first_abs_month": analysis.first_pct_above_threshold_month,
        })
        daily_path = processed_interim / DAILY_GAP_FILENAME
        if analysis.first_nontrivial_month and daily_path.exists():
            daily = pd.read_parquet(daily_path).set_index("day")["gap_mwmed"]
            step_day, after_gap, before_gap = find_step_day(daily, analysis.first_nontrivial_month)
            info.update({"step_day": str(step_day.date()), "step_day_gap_mwmed": round(after_gap), "day_before_gap_mwmed": round(before_gap)})
            after = (pd.Period(analysis.first_nontrivial_month) + 1).start_time
            anomalies = [f"{d.date()} (gap {v:.0f} MWmed)" for d, v in glitch_days(daily, str(after.date()), GLITCH_THRESHOLD_MWMED).items()]
    return info, anomalies, monthly


def build_report(results: dict[str, Any], interim_dir: Path, processed_dir: Path, raw_root: Path) -> DataQualityReport:
    """Assemble the validated report from step results + artifacts. Pure reading: no network, no writes."""
    targets, config, validation_data = results["targets"], results["config"], results["validation_data"]
    checks: list[CheckResult] = []

    def add(id_: str, name: str, status: str, detail: str, *decisions: str) -> None:
        checks.append(CheckResult(id=id_, name=name, status=status, detail=detail, decisions=list(decisions)))

    # --- config / PTE table (roadmap section 7)
    max_p = max(v.penetration_pct for sc in ("TB", "TA", "TG") for v in getattr(config.pte_scenarios, sc).values())
    add("config", "scenarios.yaml valid; solar_pct + wind_pct <= 100 for every (s,t)", "PASS", f"PTE table validated against schemas.py; maximum P = {max_p:.1f} %.")

    # --- ONS curtailment coverage
    packages = {p["source"]: p for p in results["curtailment"]["packages"]}
    ons_pkgs = targets["ons"]["packages"]
    coverage = {}
    for source, key in (("wind", "curtailment_wind"), ("solar", "curtailment_solar")):
        p = packages[source]
        coverage[source] = _cov(p.get("earliest_date"), p.get("latest_date"), p.get("n_rows", 0))
        floor = resolve_ons_min_coverage(source, ons_pkgs[key])
        ok = p.get("earliest_date") is not None and date.fromisoformat(p["earliest_date"]) <= floor
        if not ok:
            add(f"ons_{source}_coverage", f"ONS {source} curtailment reaches its coverage floor {floor}", "FAIL", f"earliest {p.get('earliest_date')} is after the floor {floor}.", "D14")
        elif source == "wind":
            add("ons_wind_coverage", f"ONS wind curtailment coverage (floor {floor})", "PASS",
                f"{p['earliest_date']} -> {p['latest_date']}, {p['n_rows']:,} half-hourly rows, package {p['resolved_package_id']}.", "D13", "D14")
        else:
            add("ons_solar_coverage", f"ONS solar curtailment coverage (floor {floor})", "WARNING",
                f"{p['earliest_date']} -> {p['latest_date']}, {p['n_rows']:,} rows. Solar curtailment is not published before 2024-04-01, so 2022-2024-03 has "
                "no solar curtailment (wind only); the floor is per package and never the wind default.", "D14")
    add("solar_2020_baseline", "2020 solar curtailment baseline", "WARNING",
        "documented_zero_not_measured: an assumption (ONS publishes no solar curtailment before 2024-04), not a measurement. ANEEL SIGA centralized PV capacity "
        "(3.3 GW in 2020 vs 17.2 GW in 2024) is corroborating context only, not proof that 2020 solar curtailment was negligible.", "D14")

    # --- dispatched solar (D20)
    gap_info, anomalies, monthly = _gap_metrics(interim_dir)
    findings = results["capacity_factor"]["findings"]
    differences = [f"{f.label}: " + "; ".join(x for x in (
        f"missing {f.missing_required}" if f.missing_required else "", f"added {f.columns_added}" if f.columns_added else "",
        f"removed {f.columns_removed}" if f.columns_removed else "", f"types {f.type_changes}" if f.type_changes else "") if x) for f in findings if not f.identical]
    unusable = [f.label for f in findings if not f.usable]
    n_files = len(findings)
    if unusable:
        add("cf_schema", "Capacity-factor files (fator-capacidade-2) schema", "FAIL", f"required columns missing in {unusable}.", "D20")
    elif differences:
        add("cf_schema", "Capacity-factor files (fator-capacidade-2) schema", "WARNING",
            f"{n_files} files, required columns present in all; non-blocking differences vs the Task 6B reference schema: {differences[:3]}{' ...' if len(differences) > 3 else ''} "
            f"({len(differences)} files; the changed column is not used).", "D20")
    else:
        add("cf_schema", "Capacity-factor files (fator-capacidade-2) schema", "PASS", f"{n_files} files, schema identical to the Task 6B reference.", "D20")
    dispatched_from = (ons_pkgs["generation_by_source"].get("solar_basis") or {}).get("dispatched_from")
    if monthly is None:
        add("dispatched_solar", "Dispatched solar series (solar basis of P(t), from solar_basis.dispatched_from)", "FAIL", f"{DISPATCHED_MONTHLY_FILENAME} was not written.", "D20")
        dispatched_cov = CoverageInfo()
    else:
        dispatched_cov = _cov(gap_info["first_month"], gap_info["last_month"], gap_info["months"])
        add("dispatched_solar", f"Dispatched solar series is the solar basis of P(t) from {dispatched_from}", "PASS",
            f"{gap_info['months']} months {gap_info['first_month']} -> {gap_info['last_month']}, hour-for-hour match with val_gersolar (months or hours missing would have raised). "
            "Raw val_gersolar is kept only as the diagnostic solar_gen_ons_balance_raw_mwh.", "D20")
        if gap_info.get("step_month"):
            add("pre_2023_gap", "Pre-step gap between val_gersolar and dispatched solar", "WARNING",
                f"Step located at {gap_info.get('step_day', gap_info['step_month'])} (daily gap {gap_info.get('day_before_gap_mwmed', '?')} -> {gap_info.get('step_day_gap_mwmed', '?')} MWmed). Before it the gap is not zero: {gap_info['pre_step_gap_mwmed_min']}-{gap_info['pre_step_gap_mwmed_max']} MWmed, "
                f"{gap_info['pre_step_gap_pct_min']}-{gap_info['pre_step_gap_pct_max']} % of val_gersolar (from {gap_info['pre_step_first_abs_month']}); documented, not corrected, "
                "not material for calibration (no curtailment data in that window affects the solar term).", "D20")
        else:
            add("pre_2023_gap", "Pre-step gap between val_gersolar and dispatched solar", "NOT APPLICABLE", "series too short to locate the step.", "D20")
        add("anomalous_days", "Isolated anomalous days in the solar gap after the step", "WARNING" if anomalies else "PASS",
            ("; ".join(anomalies) + " - isolated, unexplained (the balance looks dispatched-only on that day)") if anomalies else "none found.", "D20")

    # --- generation (D15, D16)
    gen_pkg = results["generation"]["package"]
    gen_cov = _cov(gen_pkg.get("earliest_date"), gen_pkg.get("latest_date"), gen_pkg.get("n_rows", 0))
    baseline_path = Path(results["generation"]["baseline_path"])
    baseline = json.loads(baseline_path.read_text(encoding="utf-8")) if baseline_path.exists() else {}
    hist = ons_pkgs["generation_by_source"].get("history_start_year")
    if not baseline or baseline.get("source") != "historical_ons":
        add("generation", "ONS generation by source and 2020 baseline (tagged historical_ons)", "FAIL", "baseline_2020_generation.json missing or not tagged historical_ons.", "D15")
    else:
        add("generation", f"ONS generation by source (history from {hist}) and 2020 baseline", "PASS",
            f"{gen_pkg.get('earliest_date')} -> {gen_pkg.get('latest_date')}, {gen_pkg.get('n_rows', 0):,} rows; 2020 baseline {baseline['total_twh']:.2f} TWh total, "
            f"{baseline['wind_twh']:.2f} wind, {baseline['solar_twh']:.2f} solar, penetration {baseline['penetration_pct']:.2f} %, source historical_ons. "
            f"History floor {hist} (earlier resources have gaps, D15).", "D15")
    add("scope_d16", "Generation basis: ONS SIN (calibration) vs PTE/BLUES (projection)", "WARNING",
        "Not reconciled by design: calibration and the 2020 baseline use ONS SIN data (source: historical_ons), PTE years use the PTE total as published (source: pte_projection); "
        "applying C(P) across both bases is an assumption.", "D16")

    # --- classification
    cls = results["classification"]
    by_cat = {k: round(v / 1000, 3) for k, v in (cls.get("energy_mwh_by_category") or {}).items()}
    share = cls.get("unclassified_energy_share")
    share_pct = round(100 * share, 4) if share is not None else None
    if cls["classification_available"]:
        add("classification", "Curtailment classification (DEB/REB/EUB), flag propagated", "PASS",
            f"classification_available = true; energy (GWh) by category: {by_cat}; no-DEB/REB/EUB share {share_pct} % of curtailed energy (rows without a reason code or with an unmapped code, kept in the aggregate).", "D17")
    else:
        add("classification", "Curtailment classification (DEB/REB/EUB), flag propagated", "WARNING",
            f"classification_available = false (D6 fallback to the unclassified aggregate): {cls.get('reason')}", "D6", "D17")

    # --- MCTI
    mcti = results["mcti"]
    required = targets["mcti"].get("required_years")
    avg_years, margin_years, skipped = list(mcti["average_years"]), list(mcti["margin_years"]), {str(k): v for k, v in mcti.get("margin_skipped", {}).items()}
    margin_path = Path(mcti["margin_path"])
    om_derived = cm_derived = None
    if margin_path.exists():
        margins = pd.read_parquet(margin_path)
        om_derived, cm_derived = bool(margins["om_is_derived"].all()), bool(margins["cm_is_derived"].all())
    add("mcti_average", f"MCTI average SIN factor covers required years {required}", "PASS", f"complete years {avg_years[0]}..{avg_years[-1]}; MCTI-published annual values.", "D8", "D18")
    partial = mcti.get("average_partial_years") or []
    add("mcti_margin", f"MCTI margin factors (OM/BM/CM) cover required years {required}", "WARNING",
        f"years {margin_years}; skipped (beyond the required window): {skipped or 'none'}; partial average years not used: {partial or 'none'}; "
        f"om_is_derived = {om_derived} (annual OM = mean of 12 published monthly values), cm_is_derived = {cm_derived} (CM = 0.5 OM + 0.5 BM); only BM is MCTI-published. "
        "How factors apply to later projection years is a Task 13 choice.", "D12", "D18")
    if mcti.get("manual_ingestion_used"):
        add("mcti_manual", "MCTI manual ingestion used", "WARNING", f"manual files used for {mcti['manual_ingestion_used']} (declared limitation).", "D18")

    # --- validation data, PLD, ANEEL fallback, MMGD API
    vd_loaded = bool(validation_data.get("years"))
    add("validation_data", "2026-2029 validation_data loaded (kept apart from calibration data)", "PASS" if vd_loaded else "WARNING",
        "loaded." if vd_loaded else "config/scenarios.yaml validation_data.years is empty - to be filled from the 2026-2029 prospection table; nothing in Stage 1 depends on it.")
    pld_cfg = targets.get("ccee_pld", {})
    add("pld", "CCEE PLD (optional)", "NOT APPLICABLE", f"pld.enabled = {bool(pld_cfg.get('enabled', False))}; CCEE returns HTTP {pld_cfg.get('http_status_observed', 403)} (WAF block), closed permanently; non-blocking.", "D10")
    add("aneel_fallback", "ANEEL generation fallback", "NOT APPLICABLE",
        "not invoked: every ONS step succeeded (the fallback is never part of the normal run). It would supply installed capacity only, not generation energy.", "D19")
    add("mmgd_api", "ONS verified-load / MMGD API", "NOT APPLICABLE", "inconclusive in Task 6B (area-code semantics unclear); not a required source and not used.", "D20")

    # --- manifests
    manifests = manifest_summary(raw_root)
    n_manifests = sum(v["n_files"] for v in manifests.values())
    add("manifests", "Retrieval manifests (source URL, HTTP status, sha256, retrieval time) next to every raw file", "PASS" if n_manifests else "FAIL",
        f"{n_manifests} manifests in {len(manifests)} raw source folders.")

    # --- classification flag propagation, 2020 tag (roadmap section 7)
    flag_path = processed_dir / "classification_available.json"
    add("classification_flag", "classification_available flag written for downstream stages", "PASS" if flag_path.exists() else "FAIL",
        f"{flag_path.name} {'present' if flag_path.exists() else 'missing'}.", "D6")

    status = "failed" if any(c.status == "FAIL" for c in checks) else ("degraded" if any(c.status == "WARNING" for c in checks) else "ok")
    mcti_cov = _cov(f"{avg_years[0]}" if avg_years else None, f"{avg_years[-1]}" if avg_years else None, len(avg_years))
    return DataQualityReport(
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        ons_wind_coverage=coverage["wind"], ons_solar_coverage=coverage["solar"],
        classification_available=bool(cls["classification_available"]), classification_reason=str(cls.get("reason") or ""),
        mcti_average_factor_coverage=mcti_cov, mcti_marginal_factor_years=margin_years,
        fallback_sources_used=[], validation_data_loaded=vd_loaded, overall_status=status,
        ons_generation_coverage=gen_cov, dispatched_solar_coverage=dispatched_cov, solar_basis_dispatched_from=dispatched_from,
        baseline_2020={k: baseline[k] for k in ("source", "year", "solar_twh", "wind_twh", "total_twh", "penetration_pct") if k in baseline},
        pre_2023_solar_gap={k: v for k, v in gap_info.items() if k.startswith(("pre_step", "step_")) or k == "day_before_gap_mwmed"}, anomalous_days=anomalies,
        capacity_factor_schema_differences=differences,
        classification_energy_gwh_by_category=by_cat, classification_unclassified_share_pct=share_pct,
        mcti_average_years=avg_years, mcti_skipped_years=skipped, mcti_om_is_derived=om_derived, mcti_cm_is_derived=cm_derived,
        mcti_manual_ingestion_used=list(mcti.get("manual_ingestion_used") or []),
        pld_enabled=bool(pld_cfg.get("enabled", False)), aneel_fallback_invoked=False,
        manifest_summary=manifests, checks=checks, calibration_readiness_note=CALIBRATION_NOTE,
    )


def failed_report(step: str, exc: Exception, validation_data: dict) -> DataQualityReport:
    """Minimal report written when a step raises: one FAIL check naming the step and the error (so the failure is recorded, not just logged)."""
    return DataQualityReport(
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        ons_wind_coverage=CoverageInfo(), ons_solar_coverage=CoverageInfo(), classification_available=False, classification_reason=f"not reached: step '{step}' failed",
        mcti_average_factor_coverage=CoverageInfo(), validation_data_loaded=bool(validation_data.get("years")), overall_status="failed",
        checks=[CheckResult(id=f"step_{step}", name=f"Stage 1 step '{step}'", status="FAIL", detail=f"{type(exc).__name__}: {exc}")],
        calibration_readiness_note=CALIBRATION_NOTE,
    )


def render_markdown(report: DataQualityReport) -> str:
    """Human-readable report (docs/stage1_data_quality_report.md). Generated by `run_stage1`; do not edit by hand."""
    counts = {s: sum(1 for c in report.checks if c.status == s) for s in ("PASS", "WARNING", "NOT APPLICABLE", "FAIL")}
    cov = lambda c: f"{c.earliest_date} -> {c.latest_date} ({c.n_records:,})"
    lines = [
        "# Stage 1 Data Quality Report",
        "",
        (f"Generated by `data_ingestion.run_stage1` at {report.timestamp_utc}. Machine-readable twin: `processed/{REPORT_JSON_NAME}` in DATABASE_ROOT. "
        "Do not edit by hand; re-run Stage 1."),
        "",
        (f"**Overall status: {report.overall_status.upper()}** - PASS {counts['PASS']}, WARNING {counts['WARNING']} (documented, non-blocking limitations), "
        f"NOT APPLICABLE {counts['NOT APPLICABLE']}, FAIL {counts['FAIL']}."),
        "",
        ("Status labels: **PASS** the check holds; **WARNING** a known, documented limitation (never counted as a plain pass); **NOT APPLICABLE** the item is "
        "disabled or not part of the normal run; **FAIL** blocks Stage 1."),
        "",
        "## 1. Coverage summary",
        "",
        "| Dataset | Coverage (records = rows) |", "|---|---|",
        f"| ONS wind curtailment | {cov(report.ons_wind_coverage)} |",
        f"| ONS solar curtailment | {cov(report.ons_solar_coverage)} |",
        f"| ONS generation by source (SIN, hourly) | {cov(report.ons_generation_coverage)} |",
        f"| Dispatched solar (monthly, D20) | {report.dispatched_solar_coverage.earliest_date} -> {report.dispatched_solar_coverage.latest_date} ({report.dispatched_solar_coverage.n_records} months) |",
        f"| MCTI average factor (complete years) | {report.mcti_average_factor_coverage.earliest_date} -> {report.mcti_average_factor_coverage.latest_date} |",
        f"| MCTI margin factors (years) | {report.mcti_marginal_factor_years} |",
        "",
        "Retrieval manifests (`fetch_and_cache` writes one next to every raw file):", "",
        "| Raw source folder | Files | Total MB | First retrieved (UTC) | Last retrieved (UTC) |", "|---|---:|---:|---|---|",
    ]
    for key, v in report.manifest_summary.items():
        lines.append(f"| {key} | {v['n_files']} | {v['total_bytes'] / 1e6:,.1f} | {v['first_retrieved_utc']} | {v['last_retrieved_utc']} |")
    lines += ["", "## 2. Checks", "", "| # | Item | Status | Decisions | Detail |", "|---|---|---|---|---|"]
    for i, c in enumerate(report.checks, 1):
        lines.append(f"| {i} | {c.name} | **{c.status}** | {', '.join(c.decisions) or '-'} | {c.detail.replace('|', '/')} |")
    lines += [
        "", "## 3. Key limitations (all WARNING items above, in one place)", "",
        "- Solar curtailment starts 2024-04-01 (wind 2022-01-01); the 2020 solar curtailment baseline is a documented zero, not a measurement (D14).",
        ("- Calibration solar is the ONS-dispatched series from 2021-01; `val_gersolar` includes an estimated MMGD component from 2023-04-29 (D20). "
        f"Pre-step gap: {report.pre_2023_solar_gap}. Anomalous days: {report.anomalous_days or 'none'}."),
        "- ONS SIN (calibration) and PTE/BLUES (projection) generation bases are not reconciled by design (D16).",
        "- MCTI annual OM and CM are derived/computed (D12/D18); how factors apply to projection years is a Task 13 choice.",
        "- CCEE PLD is permanently blocked (HTTP 403) and disabled (D10); the ANEEL fallback was not invoked and would give capacity only (D19).",
        "", "## 4. Calibration readiness (forward-looking, not a Stage 1 data-quality finding)", "",
        report.calibration_readiness_note,
        "", "This subsection does not affect the status of any check in section 2.", "",
    ]
    return "\n".join(lines)


def write_report(report: DataQualityReport, processed_dir: Path, logs_dir: Path, markdown_path: Path) -> dict[str, Path]:
    """Write processed/data_quality_report.json, logs/stage1_data_quality_report_{timestamp}.json and the Markdown report."""
    payload = report.model_dump_json(indent=2)
    stamp = datetime.fromisoformat(report.timestamp_utc).strftime("%Y%m%dT%H%M%SZ")
    paths = {
        "json": processed_dir / REPORT_JSON_NAME,
        "json_timestamped": logs_dir / f"stage1_data_quality_report_{stamp}.json",
        "markdown": markdown_path,
    }
    paths["json"].write_text(payload, encoding="utf-8")
    paths["json_timestamped"].write_text(payload, encoding="utf-8")
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    logger.info("Stage 1 report written: %s", {k: str(v) for k, v in paths.items()})
    return paths


def summary_table(report: DataQualityReport) -> str:
    """Plain-text table for stdout."""
    width = max(len(c.name) for c in report.checks) if report.checks else 10
    rows = [f"Stage 1 data-quality report - overall: {report.overall_status.upper()}", "-" * (width + 20)]
    rows += [f"{c.status:<15} {c.name}" for c in report.checks]
    return "\n".join(rows)
