"""End-to-end orchestration of the CurtailMit production path (Task 14; decisions D31, D32).

    pre-check -> Stage 1 -> hourly calibration -> Option E projection -> final results -> reference-value check -> summary

Invocation: `curtailmit-run` (console script), `python -m curtailmit.pipeline`, or `scripts/run_pipeline.py` (thin shim). See docs/orchestration.md.

Rules enforced here (and by tests/test_pipeline.py):
- Nothing is swallowed. Any exception is written to logs/pipeline_run_<UTC>.json (stage, error type, message, diagnostics) and re-raised by `run_pipeline`; `main` turns it into a non-zero exit code,
  2 for the hard gates (`gate_errors()`), 1 for anything else. No flag disables a gate or selects another model.
- A stage is skipped only when `provenance.decide` verifies its existing outputs against a stamp (inputs, adopted decisions, code, parameters, outputs). The default whenever that cannot be
  established (no stamp, a changed item, missing outputs) is to RE-RUN; existing files are never trusted because they exist.
- Stage 1 downloads from remote sources whose freshness cannot be verified offline: without --use-cache it is always re-run; with --use-cache the SHA-256-verified local cache is reused.
- The retired national/regional calibration (Tasks 7-11D) is reference-only (D24) and is not imported or called here.
- The reference-value check always runs, after the final results, whichever stages were skipped or re-run.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from curtailmit import provenance as prov

logger = logging.getLogger(__name__)

EXIT_OK, EXIT_ERROR, EXIT_GATE = 0, 1, 2
REFERENCE_PATH = prov.PROJECT_ROOT / "tests" / "fixtures" / "final_results" / "reference_totals.json"
REFERENCE_RTOL = 1e-9
STAGES = ("stage1", "calibration", "projection", "results")
EXPECTED_FINAL_ROWS = 156

STAGE1_MODULES = ("data_ingestion", "acquisition", "ckan", "ons_client", "ons_generation", "ons_classification", "ons_solar_gap", "ons_mmgd_probe", "mcti_client", "manual_ingestion", "aneel_client",
                  "stage1_report", "manifest", "schemas", "validation", "paths")
CALIBRATION_MODULES = ("hourly_model", "hourly_uncertainty", "paths")
PROJECTION_MODULES = ("projection", "hourly_model", "hourly_uncertainty", "limitations", "data_ingestion", "schemas", "mitigation", "paths")
RESULTS_MODULES = ("results_writer", "mitigation", "hydrogen", "emission_factors", "limitations", "projection", "paths")
STAGE1_DECISIONS = ("D14", "D15", "D17", "D18", "D20", "D22")
CALIBRATION_DECISIONS = ("D24", "D25")
PROJECTION_DECISIONS = ("D24", "D25", "D26")
RESULTS_DECISIONS = ("D18", "D23", "D24", "D25", "D27", "D28", "D29", "D30")
STAGE1_PROCESSED = ("classification_available.json", "mcti_average_factor_annual.parquet", "mcti_margin_factors.parquet", "ons_penetration_monthly.parquet", "ons_curtailment_classified.parquet",
                    "data_quality_report.json")
CALIBRATION_PROCESSED = ("hourly_curve_wind.json", "hourly_curve_solar.json", "hourly_curve_wind_L1.json", "hourly_curve_solar_L1.json", "hourly_base_profile.parquet", "hourly_horizon_bands.json")
OPTION_E = "pte_curtailment_option_E.parquet"
RAW_ONS_INPUTS = ("generation_by_source", "capacity_factor", "curtailment_wind", "curtailment_solar")
FINAL_FILES = ("final_results.csv", "final_results.parquet", "final_results.parquet.limitations.json", "final_results_mcti_sensitivity.csv", "final_results_mcti_sensitivity.parquet")
CONFIG_FILES = ("scenarios.yaml", "acquisition_targets.yaml", "paths.yaml")


class PipelineError(RuntimeError):
    """A pipeline precondition or stage contract was violated (exit code 1)."""

    def __init__(self, message: str, diagnostics: dict | None = None):
        super().__init__(message)
        self.diagnostics = diagnostics or {}


class ReferenceMismatchError(PipelineError):
    """final_results does not reproduce reference_totals.json (a hard gate, exit code 2)."""


def gate_errors() -> tuple[type[BaseException], ...]:
    """The hard gates: exceptions whose exit code is 2."""
    from curtailmit.data_ingestion import Stage1Error
    from curtailmit.limitations import LimitationError
    from curtailmit.mitigation import ModelProvenanceError
    from curtailmit.results_writer import FinalResultsError, SupportStatusConflictError

    return (Stage1Error, LimitationError, ModelProvenanceError, SupportStatusConflictError, FinalResultsError, ReferenceMismatchError)


# ----------------------------------------------------------------------------------------------------------------------------------- context
@dataclass(frozen=True)
class Context:
    root: Path
    raw: Path
    interim: Path
    processed: Path
    logs: Path
    tables: Path

    @classmethod
    def build(cls, create: bool) -> Context:
        from curtailmit import paths

        if create:
            root = paths.get_database_root()
            return cls(root, root / "raw", paths.get_interim_dir(), paths.get_processed_dir(), paths.get_logs_dir(), paths.get_outputs_dir("tables"))
        lay = paths.planned_layout()
        return cls(lay["root"], lay["root"] / "raw", lay["interim"], lay["processed"], lay["logs"], lay["tables"])


@dataclass
class StageSpec:
    key: str
    label: str
    force_attr: str
    fingerprint: Callable[[Context], dict]
    outputs: Callable[[Context], dict[str, Path]]
    trust_blocker: Callable[[argparse.Namespace], str | None] = lambda args: None


def _config_hashes() -> dict[str, str]:
    return {f"config/{n}": prov.sha256_file(prov.PROJECT_ROOT / "config" / n) for n in CONFIG_FILES}


def _fp_stage1(ctx: Context) -> dict:
    return {"inputs": {**{f"raw/{k}": v for k, v in prov.tree_hashes(ctx.raw).items()}, **_config_hashes()}, "decisions": prov.decision_hashes(STAGE1_DECISIONS), "code": prov.code_hashes(STAGE1_MODULES), "params": {}}


def _out_stage1(ctx: Context) -> dict[str, Path]:
    return {f"processed/{n}": ctx.processed / n for n in STAGE1_PROCESSED}


def _fp_calibration(ctx: Context) -> dict:
    inputs = {}
    for d in RAW_ONS_INPUTS:
        inputs.update({f"raw/ons/{d}/{k}": v for k, v in prov.tree_hashes(ctx.raw / "ons" / d, (".parquet",)).items()})
    return {"inputs": inputs, "decisions": prov.decision_hashes(CALIBRATION_DECISIONS), "code": prov.code_hashes(CALIBRATION_MODULES), "params": {"base_year": 2025, "panel_start": "2022-01-01", "panel_cache": "rebuilt"}}


def _out_calibration(ctx: Context) -> dict[str, Path]:
    return {f"processed/{n}": ctx.processed / n for n in CALIBRATION_PROCESSED}


def _fp_projection(ctx: Context) -> dict:
    inputs = prov.file_hashes({f"processed/{n}": ctx.processed / n for n in CALIBRATION_PROCESSED})
    inputs["config/scenarios.yaml"] = _config_hashes()["config/scenarios.yaml"]
    return {"inputs": inputs, "decisions": prov.decision_hashes(PROJECTION_DECISIONS), "code": prov.code_hashes(PROJECTION_MODULES), "params": {"recalibrate": False, "years": [2025, 2030, 2040, 2050]}}


def _out_projection(ctx: Context) -> dict[str, Path]:
    return {f"processed/{OPTION_E}": ctx.processed / OPTION_E, f"processed/{OPTION_E}.limitations.json": ctx.processed / f"{OPTION_E}.limitations.json"}


def _fp_results(ctx: Context) -> dict:
    ups = {f"processed/{n}": ctx.processed / n for n in (OPTION_E, f"{OPTION_E}.limitations.json", "mcti_average_factor_annual.parquet", "mcti_margin_factors.parquet", "classification_available.json")}
    inputs = prov.file_hashes(ups)
    inputs["config/scenarios.yaml"] = _config_hashes()["config/scenarios.yaml"]
    return {"inputs": inputs, "decisions": prov.decision_hashes(RESULTS_DECISIONS), "code": prov.code_hashes(RESULTS_MODULES), "params": {"central_factor_year": 2025, "sensitivity": "mean_2021_2025"}}


def _out_results(ctx: Context) -> dict[str, Path]:
    return {f"tables/{n}": ctx.tables / n for n in FINAL_FILES}


def _stage1_blocker(args: argparse.Namespace) -> str | None:
    return None if args.use_cache else "remote data freshness cannot be verified offline; without --use-cache Stage 1 is always re-run (pass --use-cache to reuse the SHA-256-verified local cache)"


SPECS = (
    StageSpec("stage1", "Stage 1 (data acquisition + quality report)", "force_stage1", _fp_stage1, _out_stage1, _stage1_blocker),
    StageSpec("calibration", "hourly calibration (Option E curves, bands)", "force_calibration", _fp_calibration, _out_calibration),
    StageSpec("projection", "Option E projection (PTE scenarios)", "force_projection", _fp_projection, _out_projection),
    StageSpec("results", "final results (long format, OM/CM, H2)", "force_results", _fp_results, _out_results),
)


# ---------------------------------------------------------------------------------------------------------------------- default stage actions
def _run_stage1(ctx: Context, args: argparse.Namespace) -> dict:
    from curtailmit.data_ingestion import run_stage1

    result = run_stage1(use_cache=args.use_cache)  # raises Stage1Error when the data-quality report has a FAIL
    return {"overall_status": result["overall_status"]}


def _run_calibration(ctx: Context, args: argparse.Namespace) -> dict:
    from curtailmit.hourly_model import load_sin_panel, run_hourly_calibration

    panel = load_sin_panel(refresh=True)  # conservative: the interim panel cache is never reused, it is rebuilt from the raw files that were just fingerprinted
    run_hourly_calibration(panel, ctx.processed)
    return {"panel_rows": len(panel)}


def _run_projection(ctx: Context, args: argparse.Namespace) -> dict:
    from curtailmit.mitigation import check_provenance
    from curtailmit.projection import build_option_e_table

    missing = [n for n in CALIBRATION_PROCESSED if not (ctx.processed / n).is_file()]
    if missing:
        raise PipelineError(f"hourly calibration products missing: {missing}; the projection would silently recalibrate", {"missing": missing})
    table = build_option_e_table(processed_dir=ctx.processed, recalibrate=False)
    check_provenance(table)  # ModelProvenanceError unless every row is option_E_hourly / production
    if len(table) != 12:
        raise PipelineError(f"Option E table has {len(table)} rows, expected 12 (3 scenarios x 4 years)", {"rows": len(table)})
    return {"rows": len(table)}


def _run_results(ctx: Context, args: argparse.Namespace) -> dict:
    from curtailmit.results_writer import read_final_results, run_final_results

    paths = run_final_results(ctx.processed, ctx.tables)
    for key in ("csv", "parquet"):  # re-read validation of what was written
        df = read_final_results(paths[key])
        if len(df) != EXPECTED_FINAL_ROWS:
            raise PipelineError(f"{paths[key].name} has {len(df)} rows after re-reading, expected {EXPECTED_FINAL_ROWS}", {"rows": len(df)})
    return {"rows": EXPECTED_FINAL_ROWS}


DEFAULT_ACTIONS: dict[str, Callable[[Context, argparse.Namespace], dict | None]] = {"stage1": _run_stage1, "calibration": _run_calibration, "projection": _run_projection, "results": _run_results}


# ----------------------------------------------------------------------------------------------------------------------------- reference check
def check_reference(ctx: Context, reference_path: Path = REFERENCE_PATH) -> dict:
    """Compare final_results.parquet with reference_totals.json (relative tolerance REFERENCE_RTOL). Raises ReferenceMismatchError listing every difference."""
    from curtailmit.results_writer import read_final_results

    if not Path(reference_path).is_file():
        raise PipelineError(f"reference fixture not found: {reference_path}")
    ref = json.loads(Path(reference_path).read_text(encoding="utf-8"))
    rtol = float(ref.get("rtol", REFERENCE_RTOL))
    df = read_final_results(ctx.tables / "final_results.parquet")
    problems = []
    if len(df) != ref["n_rows"]:
        problems.append({"what": "n_rows", "expected": ref["n_rows"], "got": len(df)})
    index = {(r.scenario, int(r.year), r.quantity, r.component): float(r.central_value) for r in df.itertuples()}
    for item in ref["totals"]:
        key = (item["scenario"], int(item["year"]), item["quantity"], item["component"])
        got = index.get(key)
        if got is None or not math.isclose(got, float(item["central_value"]), rel_tol=rtol, abs_tol=1e-12):
            problems.append({"what": "central_value", "key": list(key), "expected": item["central_value"], "got": got})
    if problems:
        raise ReferenceMismatchError(f"final_results does not reproduce {Path(reference_path).name}: {len(problems)} difference(s), first: {problems[0]}", {"differences": problems[:50], "n_differences": len(problems)})
    return {"values_compared": len(ref["totals"]), "rtol": rtol, "reference": str(reference_path)}


# ---------------------------------------------------------------------------------------------------------------------------------- pre-check
def precheck(ctx: Context, args: argparse.Namespace) -> dict:
    """Fail fast, before any download: scenarios config, PLD disabled (D10), D25 adopted, reference fixture readable, gate wiring, database layout."""
    from curtailmit.data_ingestion import CONFIG_PATH, load_config
    from curtailmit.limitations import limitations_payload

    load_config()  # raises on solar_pct + wind_pct > 100
    with open(CONFIG_PATH, encoding="utf-8") as f:
        pld_enabled = bool((yaml.safe_load(f).get("pld") or {}).get("enabled", False))
    if pld_enabled:
        raise PipelineError("config pld.enabled is true but no PLD stage exists (D10: CCEE closed); refusing to run instead of silently skipping it")
    limitations_payload()  # LimitationError unless D25 is adopted
    if not REFERENCE_PATH.is_file():
        raise PipelineError(f"reference fixture not found: {REFERENCE_PATH}")
    json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    gates = gate_errors()
    if not all(isinstance(g, type) and issubclass(g, BaseException) for g in gates):
        raise PipelineError("gate wiring is inconsistent")
    if args.skip_stage1 and not (ctx.raw / "ons").is_dir():
        raise PipelineError(f"--skip-stage1 needs the Stage 1 products but {ctx.raw / 'ons'} does not exist")
    return {"d25": "adopted", "pld_enabled": False, "reference_fixture": str(REFERENCE_PATH), "gates": [g.__name__ for g in gates]}


# ---------------------------------------------------------------------------------------------------------------------------------- orchestrator
@dataclass
class StageRecord:
    stage: str
    status: str
    kind: str
    detail: str
    seconds: float = 0.0

    @property
    def line(self) -> str:
        return f"{self.status} ({self.detail})" if self.status == "SKIPPED" else f"RAN ({self.kind}: {self.detail})"


@dataclass
class RunRecord:
    started_utc: str
    database_root: str
    args: dict
    partial: bool
    status: str = "RUNNING"
    stages: list[dict] = field(default_factory=list)
    precheck: dict = field(default_factory=dict)
    reference_check: dict = field(default_factory=dict)
    outputs: dict = field(default_factory=dict)
    failure: dict = field(default_factory=dict)


def _forced(args: argparse.Namespace, spec: StageSpec) -> bool:
    return bool(args.force_all or getattr(args, spec.force_attr))


def decide_stage(ctx: Context, args: argparse.Namespace, spec: StageSpec) -> prov.Decision:
    """Skip/run decision of one stage against the files on disk NOW. It is evaluated just before the stage, never in advance, so a stage sees the outputs its upstream stages have just written."""
    if spec.key == "stage1" and args.skip_stage1:
        return prov.Decision("skip", "cached", "--skip-stage1: explicit partial run, existing Stage 1 products reused")
    return prov.decide(ctx.processed, spec.key, spec.fingerprint(ctx), spec.outputs(ctx), force=_forced(args, spec), trust_blocker=spec.trust_blocker(args))


def plan(ctx: Context, args: argparse.Namespace) -> list[tuple[StageSpec, prov.Decision]]:
    """Read-only plan for --dry-run. A stage downstream of one that will run is planned as a re-run: it is re-checked against the new upstream outputs when the real run reaches it."""
    out, upstream_runs = [], None
    for spec in SPECS:
        dec = decide_stage(ctx, args, spec)
        if dec.action == "skip" and upstream_runs:
            dec = prov.Decision("run", "stale", f"upstream stage '{upstream_runs}' will run; this stage is verified against its new outputs when the run reaches it")
        if dec.action == "run" and upstream_runs is None:
            upstream_runs = spec.key
        out.append((spec, dec))
    return out


def _write_record(ctx: Context, record: RunRecord) -> Path:
    ctx.logs.mkdir(parents=True, exist_ok=True)
    path = ctx.logs / f"pipeline_run_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.json"
    path.write_text(json.dumps(record.__dict__, indent=2, default=str), encoding="utf-8")
    return path


def _say(text: str) -> None:
    print(text, flush=True)


def run_pipeline(args: argparse.Namespace, actions: dict[str, Callable] | None = None, reference_path: Path | None = None) -> RunRecord:
    """Run the pipeline. `actions` overrides the stage callables (tests); it can only replace the callables, never the gates, the skip decision or the reference check."""
    actions = {**DEFAULT_ACTIONS, **(actions or {})}
    ctx = Context.build(create=not args.dry_run)
    record = RunRecord(datetime.now(timezone.utc).isoformat(), str(ctx.root), {k: v for k, v in vars(args).items()}, partial=bool(args.skip_stage1))
    _say(f"CurtailMit pipeline | database root: {ctx.root}")
    stage_name = "pre-check"
    try:
        record.precheck = precheck(ctx, args)
        _say("[pre-check] OK: scenarios config valid, PLD disabled (D10), D25 adopted, reference fixture readable, gates wired")
        if args.dry_run:
            for i, (spec, dec) in enumerate(plan(ctx, args), 1):
                _say(f"[{i}/4] {spec.key:<12} plan: {dec.label}")
                record.stages.append({"stage": spec.key, "status": "PLANNED", "kind": dec.kind, "detail": dec.detail})
            _say("[ref] reference-value check would run after the final results")
            record.status = "DRY_RUN"
            _say("DRY RUN complete: configuration, imports and gate wiring verified; no stage executed and nothing written (input files were only read to hash them).")
            return record
        for i, spec in enumerate(SPECS, 1):
            stage_name = spec.key
            dec = decide_stage(ctx, args, spec)
            rec = StageRecord(spec.key, "SKIPPED" if dec.action == "skip" else "RAN", dec.kind, dec.detail)
            if spec.key == "stage1" and args.skip_stage1:
                missing = [k for k, p in _out_stage1(ctx).items() if not p.is_file()]
                if missing:
                    raise PipelineError(f"--skip-stage1: Stage 1 products missing: {missing}", {"missing": missing})
                stamp = prov.read_stamp(ctx.processed, "stage1")
                verified = bool(stamp) and not prov.compare(stamp, _fp_stage1(ctx), _out_stage1(ctx))
                rec.detail += "; stamp verified" if verified else "; products NOT verified (no current stamp)"
            elif dec.action == "run":
                t0 = time.perf_counter()
                extra = actions[spec.key](ctx, args)
                rec.seconds = round(time.perf_counter() - t0, 1)
                outs = spec.outputs(ctx)
                absent = [k for k, p in outs.items() if not Path(p).is_file()]
                if absent:
                    raise PipelineError(f"stage {spec.key} finished but did not produce {absent}", {"missing": absent})
                prov.write_stamp(ctx.processed, spec.key, spec.fingerprint(ctx), outs, extra if isinstance(extra, dict) else {})
            _say(f"[{i}/4] {spec.key:<12} {rec.line}")
            record.stages.append(rec.__dict__)
        stage_name = "reference-check"
        record.reference_check = check_reference(ctx, reference_path or REFERENCE_PATH)
        _say(f"[ref] reference-value check OK: {record.reference_check['values_compared']} values within rtol {record.reference_check['rtol']}")
        record.outputs = {k: str(p) for k, p in _out_results(ctx).items()}
        record.status = "SUCCESS_PARTIAL" if record.partial else "SUCCESS"
        path = _write_record(ctx, record)
        _say("SUMMARY: " + record.status + (" (Stage 1 not executed: --skip-stage1)" if record.partial else ""))
        for k, v in record.outputs.items():
            _say(f"  {k}: {v}")
        _say(f"  run record: {path}")
        return record
    except Exception as exc:
        if args.dry_run:
            raise
        record.status = "FAILED"
        record.failure = {"stage": stage_name, "error_type": type(exc).__name__, "reason": str(exc), "gate": isinstance(exc, gate_errors()), "diagnostics": getattr(exc, "diagnostics", {})}
        path = _write_record(ctx, record)
        logger.error("PIPELINE FAILED at %s: %s: %s (record: %s)", stage_name, type(exc).__name__, exc, path)
        raise


# ------------------------------------------------------------------------------------------------------------------------------------- CLI
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="curtailmit-run", description="Run the CurtailMit production pipeline end to end (Stage 1 -> hourly calibration -> Option E -> final results).")
    p.add_argument("--database-root", help="Override DATABASE_ROOT (relative values are resolved against the project root).")
    p.add_argument("--use-cache", action="store_true", help="Stage 1: reuse SHA-256-verified cached raw files instead of downloading again (and allow Stage 1 to be skipped when its stamp verifies).")
    p.add_argument("--skip-stage1", action="store_true", help="Explicit PARTIAL run: reuse the existing Stage 1 products without re-running Stage 1.")
    for name in ("stage1", "calibration", "projection", "results"):
        p.add_argument(f"--force-{name}", action="store_true", help=f"Recompute the {name} stage regardless of a valid stamp.")
    p.add_argument("--force-all", action="store_true", help="Recompute every stage.")
    p.add_argument("--dry-run", action="store_true", help="Validate configuration, imports and gate wiring and print the skip/run plan; executes no stage and writes nothing.")
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.skip_stage1 and (args.force_stage1 or args.force_all):
        parser.error("--skip-stage1 cannot be combined with --force-stage1 or --force-all")
    if args.database_root:
        os.environ["DATABASE_ROOT"] = args.database_root
    try:
        run_pipeline(args)
    except Exception as exc:  # noqa: BLE001 - reported with its type, never swallowed: the exit code is non-zero
        code = EXIT_GATE if isinstance(exc, gate_errors()) else EXIT_ERROR
        print(f"PIPELINE FAILED ({type(exc).__name__}): {exc}", file=sys.stderr, flush=True)
        return code
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
