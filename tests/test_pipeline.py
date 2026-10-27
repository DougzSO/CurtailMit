"""Task 14: orchestrator (curtailmit.pipeline) and provenance stamps. Mocked stage actions on a temporary DATABASE_ROOT; no real data."""

from __future__ import annotations

import ast
import inspect
import json
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest
import yaml

from curtailmit import pipeline as pl
from curtailmit import provenance as prov

PROJECT = Path(__file__).resolve().parents[1]


# ----------------------------------------------------------------------------------------------------------------------------------- helpers
@pytest.fixture
def db(tmp_path, monkeypatch):
    root = tmp_path / "db"
    monkeypatch.setenv("DATABASE_ROOT", str(root))
    return root


def parse(*argv):
    return pl.build_parser().parse_args(list(argv))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class Recorder:
    """Mock stage actions: write the stage's output files (deterministic content) and remember the call order."""

    def __init__(self, fail: dict[str, BaseException] | None = None, content: str = "v1"):
        self.calls: list[str] = []
        self.fail = fail or {}
        self.content = content

    def _make(self, key: str, outputs):
        def action(ctx, args):
            self.calls.append(key)
            if key in self.fail:
                raise self.fail[key]
            for p in outputs(ctx).values():
                _write(p, f"{key}:{self.content}")
            return {"mock": key}

        return action

    def actions(self):
        return {s.key: self._make(s.key, s.outputs) for s in pl.SPECS}


@pytest.fixture
def ok_reference(monkeypatch, tmp_path):
    """A reference fixture and a final_results reader that agree (check_reference is tested separately against its real logic)."""
    ref = {"rtol": 1e-9, "n_rows": 2, "totals": [{"scenario": "TB", "year": 2025, "quantity": "curtailed_energy", "component": "total", "central_value": 43.8}]}
    path = tmp_path / "ref.json"
    path.write_text(json.dumps(ref), encoding="utf-8")
    df = pd.DataFrame({"scenario": ["TB", "TB"], "year": [2025, 2030], "quantity": ["curtailed_energy"] * 2, "component": ["total"] * 2, "central_value": [43.8, 60.0]})
    monkeypatch.setattr("curtailmit.results_writer.read_final_results", lambda p: df)
    return path


def run(args, rec, ref):
    return pl.run_pipeline(args, actions=rec.actions(), reference_path=ref)


def statuses(record):
    return {s["stage"]: (s["status"], s["kind"]) for s in record.stages}


# --------------------------------------------------------------------------------------------------------------------------------- order, skip
def test_first_run_executes_every_stage_in_order_and_writes_stamps(db, ok_reference):
    rec = Recorder()
    record = run(parse(), rec, ok_reference)
    assert rec.calls == ["stage1", "calibration", "projection", "results"]
    assert all(v == ("RAN", "missing") or v[0] == "RAN" for v in statuses(record).values())
    assert record.status == "SUCCESS" and record.reference_check["values_compared"] == 1
    for key in pl.STAGES:
        assert prov.read_stamp(db / "processed", key) is not None
    assert list((db / "logs").glob("pipeline_run_*.json"))


def test_second_run_with_use_cache_skips_everything_that_verifies(db, ok_reference):
    run(parse(), Recorder(), ok_reference)
    rec = Recorder()
    record = run(parse("--use-cache"), rec, ok_reference)
    assert rec.calls == []
    assert statuses(record) == {k: ("SKIPPED", "cached") for k in pl.STAGES}


def test_stage1_is_rerun_without_use_cache_because_remote_freshness_is_unverifiable(db, ok_reference):
    run(parse(), Recorder(), ok_reference)
    rec = Recorder()
    record = run(parse(), rec, ok_reference)
    assert rec.calls == ["stage1"]
    s1 = next(s for s in record.stages if s["stage"] == "stage1")
    assert s1["kind"] == "stale" and "freshness" in s1["detail"]
    assert statuses(record)["calibration"][0] == "SKIPPED"


def test_missing_stamp_with_existing_outputs_is_recomputed(db, ok_reference):
    run(parse(), Recorder(), ok_reference)
    prov.stamp_path(db / "processed", "projection").unlink()
    rec = Recorder()
    record = run(parse("--use-cache"), rec, ok_reference)
    assert rec.calls == ["projection"] and statuses(record)["projection"] == ("RAN", "missing")


def test_changed_input_makes_the_stage_stale_and_unchanged_downstream_is_still_skipped(db, ok_reference):
    run(parse(), Recorder(), ok_reference)
    _write(db / "raw" / "ons" / "capacity_factor" / "new_month.parquet", "new data")
    rec = Recorder()
    record = run(parse("--use-cache"), rec, ok_reference)
    assert rec.calls == ["stage1", "calibration"]  # the recomputed calibration reproduces identical bytes, so projection and results verify and are skipped
    assert statuses(record)["calibration"] == ("RAN", "stale")
    assert "inputs changed" in next(s for s in record.stages if s["stage"] == "calibration")["detail"]
    assert statuses(record)["projection"][0] == "SKIPPED"


def test_changed_upstream_content_propagates_downstream(db, ok_reference):
    run(parse(), Recorder(), ok_reference)
    rec = Recorder(content="v2")
    record = run(parse("--use-cache", "--force-calibration"), rec, ok_reference)
    assert rec.calls == ["calibration", "projection", "results"]
    assert statuses(record)["calibration"] == ("RAN", "forced") and statuses(record)["projection"] == ("RAN", "stale")


def test_modified_output_artifact_is_not_trusted(db, ok_reference):
    run(parse(), Recorder(), ok_reference)
    (db / "outputs" / "tables" / "final_results.csv").write_text("tampered", encoding="utf-8")
    rec = Recorder()
    record = run(parse("--use-cache"), rec, ok_reference)
    assert rec.calls == ["results"] and "modified since the stamp" in next(s for s in record.stages if s["stage"] == "results")["detail"]


def test_changed_adopted_decision_invalidates_the_stage(db, ok_reference, monkeypatch, tmp_path):
    run(parse(), Recorder(), ok_reference)
    data = yaml.safe_load((PROJECT / "config" / "discovered_sources.yaml").read_text(encoding="utf-8"))
    data["decisions"]["D28"]["decided"] = "changed text"
    alt = tmp_path / "alt.yaml"
    alt.write_text(yaml.safe_dump(data), encoding="utf-8")
    monkeypatch.setattr(prov, "DECISIONS_PATH", alt)
    rec = Recorder()
    record = run(parse("--use-cache"), rec, ok_reference)
    assert rec.calls == ["results"] and "decisions changed: D28" in next(s for s in record.stages if s["stage"] == "results")["detail"]


def test_changed_code_or_params_invalidate_the_stamp(db):
    fp = {"inputs": {"a": "1"}, "decisions": {"D24": "x"}, "code": {"hourly_model": "h1"}, "params": {"base_year": 2025}}
    out = {"o": db / "o.txt"}
    _write(out["o"], "x")
    prov.write_stamp(db, "calibration", fp, out)
    assert prov.decide(db, "calibration", fp, out).action == "skip"
    changed = {**fp, "code": {"hourly_model": "h2"}}
    d = prov.decide(db, "calibration", changed, out)
    assert d.action == "run" and d.kind == "stale" and "code changed: hourly_model" in d.detail
    d = prov.decide(db, "calibration", {**fp, "params": {"base_year": 2024}}, out)
    assert d.action == "run" and "params changed" in d.detail
    assert prov.decide(db, "calibration", fp, out, force=True).kind == "forced"
    assert prov.decide(db, "calibration", fp, out, trust_blocker="why").action == "run"


@pytest.mark.parametrize("flag,expected", [("--force-stage1", ["stage1"]), ("--force-projection", ["projection"]), ("--force-results", ["results"]), ("--force-all", ["stage1", "calibration", "projection", "results"])])
def test_force_flags(db, ok_reference, flag, expected):
    run(parse(), Recorder(), ok_reference)
    rec = Recorder()
    record = run(parse("--use-cache", flag), rec, ok_reference)
    assert rec.calls == expected
    assert all(statuses(record)[k] == ("RAN", "forced") for k in expected)


def test_skip_stage1_is_a_labelled_partial_run(db, ok_reference):
    for key in pl.STAGE1_PROCESSED:
        _write(db / "processed" / key, "x")
    _write(db / "raw" / "ons" / "x.parquet", "x")
    rec = Recorder()
    record = run(parse("--skip-stage1"), rec, ok_reference)
    assert "stage1" not in rec.calls and record.status == "SUCCESS_PARTIAL"
    s1 = record.stages[0]
    assert s1["status"] == "SKIPPED" and "NOT verified" in s1["detail"]


def test_skip_stage1_without_products_fails(db, ok_reference):
    with pytest.raises(pl.PipelineError):
        run(parse("--skip-stage1"), Recorder(), ok_reference)


def test_skip_stage1_cannot_be_combined_with_force():
    with pytest.raises(SystemExit):
        pl.main(["--skip-stage1", "--force-all"])


def test_stage_that_does_not_produce_its_outputs_fails(db, ok_reference):
    rec = Recorder()
    actions = rec.actions()
    actions["calibration"] = lambda ctx, args: {}
    with pytest.raises(pl.PipelineError, match="did not produce"):
        pl.run_pipeline(parse(), actions=actions, reference_path=ok_reference)


# -------------------------------------------------------------------------------------------------------------------------------- gates, exit
def _gate_cases():
    from curtailmit.data_ingestion import Stage1Error
    from curtailmit.mitigation import ModelProvenanceError
    from curtailmit.results_writer import FinalResultsError, SupportStatusConflictError

    return [("stage1", Stage1Error("x")), ("projection", ModelProvenanceError("bad model")), ("results", SupportStatusConflictError("conflict")), ("results", FinalResultsError("bad table"))]


@pytest.mark.parametrize("stage,exc", _gate_cases())
def test_gate_exceptions_stop_the_run_write_the_failure_record_and_exit_2(db, ok_reference, stage, exc, monkeypatch):
    rec = Recorder(fail={stage: exc})
    with pytest.raises(type(exc)):
        run(parse(), rec, ok_reference)
    later = pl.STAGES[pl.STAGES.index(stage) + 1:]
    assert not set(later) & set(rec.calls)
    body = json.loads(next((db / "logs").glob("pipeline_run_*.json")).read_text(encoding="utf-8"))
    assert body["status"] == "FAILED" and body["failure"]["stage"] == stage and body["failure"]["error_type"] == type(exc).__name__ and body["failure"]["gate"] is True
    monkeypatch.setattr(pl, "DEFAULT_ACTIONS", {**pl.DEFAULT_ACTIONS, **{k: v for k, v in rec.actions().items()}})
    assert pl.main([]) == pl.EXIT_GATE


def test_non_gate_exception_exits_1_and_is_not_swallowed(db, ok_reference, monkeypatch):
    rec = Recorder(fail={"calibration": RuntimeError("boom")})
    with pytest.raises(RuntimeError):
        run(parse(), rec, ok_reference)
    monkeypatch.setattr(pl, "DEFAULT_ACTIONS", rec.actions())
    assert pl.main([]) == pl.EXIT_ERROR


def test_d25_not_adopted_aborts_in_the_precheck_before_any_stage(db, ok_reference, monkeypatch, tmp_path):
    data = yaml.safe_load((PROJECT / "config" / "discovered_sources.yaml").read_text(encoding="utf-8"))
    data["decisions"]["D25"]["status"] = "pending"
    alt = tmp_path / "alt.yaml"
    alt.write_text(yaml.safe_dump(data), encoding="utf-8")
    monkeypatch.setattr("curtailmit.limitations.DECISIONS_PATH", alt)
    from curtailmit.limitations import LimitationError

    rec = Recorder()
    with pytest.raises(LimitationError):
        run(parse(), rec, ok_reference)
    assert rec.calls == []
    assert json.loads(next((db / "logs").glob("pipeline_run_*.json")).read_text(encoding="utf-8"))["failure"]["stage"] == "pre-check"


def test_pld_enabled_is_an_error_not_a_silent_skip(db, ok_reference, monkeypatch, tmp_path):
    from curtailmit import data_ingestion

    cfg = yaml.safe_load(data_ingestion.CONFIG_PATH.read_text(encoding="utf-8"))
    cfg["pld"]["enabled"] = True
    alt = tmp_path / "scenarios.yaml"
    alt.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    monkeypatch.setattr(data_ingestion, "CONFIG_PATH", alt)
    with pytest.raises(pl.PipelineError, match="pld"):
        run(parse(), Recorder(), ok_reference)


def test_reference_mismatch_is_a_gate_and_always_runs_even_when_every_stage_was_skipped(db, ok_reference, monkeypatch):
    run(parse(), Recorder(), ok_reference)
    bad = json.loads(ok_reference.read_text(encoding="utf-8"))
    bad["totals"][0]["central_value"] = 44.0
    ok_reference.write_text(json.dumps(bad), encoding="utf-8")
    rec = Recorder()
    with pytest.raises(pl.ReferenceMismatchError):
        run(parse("--use-cache"), rec, ok_reference)
    assert rec.calls == []  # all skipped, the check still ran and failed
    failure = json.loads(max((db / "logs").glob("pipeline_run_*.json")).read_text(encoding="utf-8"))["failure"]
    assert failure["stage"] == "reference-check" and failure["gate"] is True and failure["diagnostics"]["n_differences"] == 1
    assert pl.ReferenceMismatchError in pl.gate_errors()


def test_check_reference_logic(db, ok_reference, monkeypatch):
    ctx = pl.Context.build(create=True)
    assert pl.check_reference(ctx, ok_reference)["values_compared"] == 1
    ref = json.loads(ok_reference.read_text(encoding="utf-8"))
    ref["totals"][0]["central_value"] = 43.8 * (1 + 1e-10)  # inside rtol
    ok_reference.write_text(json.dumps(ref), encoding="utf-8")
    pl.check_reference(ctx, ok_reference)
    ref["totals"][0]["year"] = 2099  # absent row
    ok_reference.write_text(json.dumps(ref), encoding="utf-8")
    with pytest.raises(pl.ReferenceMismatchError):
        pl.check_reference(ctx, ok_reference)
    with pytest.raises(pl.PipelineError):
        pl.check_reference(ctx, ok_reference.with_name("absent.json"))


def test_project_reference_fixture_is_complete():
    ref = json.loads(pl.REFERENCE_PATH.read_text(encoding="utf-8"))
    assert ref["n_rows"] == pl.EXPECTED_FINAL_ROWS and len(ref["totals"]) == 60
    energy = {(t["scenario"], t["year"]): t["central_value"] for t in ref["totals"] if t["quantity"] == "curtailed_energy"}
    assert len(energy) == 12 and round(energy[("TB", 2025)], 1) == 43.8 and round(energy[("TB", 2050)], 1) == 354.8 and round(energy[("TA", 2040)], 1) == 242.4


# ------------------------------------------------------------------------------------------------------------------------ dry run, paths, entry
def test_dry_run_creates_nothing_and_calls_no_stage(tmp_path, monkeypatch):
    root = tmp_path / "does_not_exist_yet"
    monkeypatch.setenv("DATABASE_ROOT", str(root))
    rec = Recorder()
    record = pl.run_pipeline(parse("--dry-run"), actions=rec.actions())
    assert rec.calls == [] and record.status == "DRY_RUN" and not root.exists()
    assert [s["status"] for s in record.stages] == ["PLANNED"] * 4 and all(s["kind"] in ("missing", "stale") for s in record.stages)


def test_database_root_argument_is_applied_and_printed(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_ROOT", str(tmp_path / "initial"))  # restored by monkeypatch after main() overrides it
    target = tmp_path / "other_db"
    assert pl.main(["--dry-run", "--database-root", str(target)]) == 0
    assert str(target.resolve()) in capsys.readouterr().out and not target.exists()


def test_module_invocation_dry_run_works_and_touches_nothing(tmp_path):
    root = tmp_path / "db_module"
    out = subprocess.run([sys.executable, "-m", "curtailmit.pipeline", "--dry-run"], env={**__import__("os").environ, "DATABASE_ROOT": str(root)}, capture_output=True, text=True, timeout=120, check=False)
    assert out.returncode == 0, out.stderr
    assert "DRY RUN complete" in out.stdout and not root.exists()


def test_console_script_and_shim_are_declared():
    meta = (PROJECT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'curtailmit-run = "curtailmit.pipeline:main"' in meta
    shim = (PROJECT / "scripts" / "run_pipeline.py").read_text(encoding="utf-8")
    assert "from curtailmit.pipeline import main" in shim and len(shim.splitlines()) <= 8  # no logic in the shim
    assert callable(pl.main)


def test_resolve_database_root_without_create_touches_nothing(tmp_path, monkeypatch):
    from curtailmit import paths

    monkeypatch.setenv("DATABASE_ROOT", str(tmp_path / "nope"))
    assert paths.resolve_database_root(create=False) == (tmp_path / "nope").resolve() and not (tmp_path / "nope").exists()
    assert paths.planned_layout()["processed"] == (tmp_path / "nope").resolve() / "processed" and not (tmp_path / "nope").exists()


# --------------------------------------------------------------------------------------------------------- retired models are unreachable
RETIRED = {"run_calibration", "fit_calibration", "fit_regional_reference", "build_pte_curtailment_table", "project_curtailment_two_curves", "bootstrap_calibration_ci", "load_calibration"}


def _mentions(source: str) -> bool:
    word = "[A-Za-z0-9_]"
    return any(re.search(f"(?<!{word}){re.escape(name)}(?!{word})", source) for name in RETIRED)


def test_pipeline_does_not_import_or_call_retired_reference_models():
    tree = ast.parse(Path(pl.__file__).read_text(encoding="utf-8"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names} | {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not (RETIRED & names) and not (RETIRED & imported)
    assert not any(m and m.endswith("calibration") and m.startswith("curtailmit") and "hourly" not in m for m in imported)


def test_production_path_functions_do_not_reach_retired_models():
    from curtailmit import hourly_model, projection, results_writer

    for fn in (projection.build_option_e_table, projection.project_curtailment_hourly, hourly_model.run_hourly_calibration, hourly_model.load_sin_panel, results_writer.run_final_results,
               results_writer.build_final_results):
        src = inspect.getsource(fn)
        assert not _mentions(src), f"{fn.__name__} references a retired model"
    for fn in (pl._run_stage1, pl._run_calibration, pl._run_projection, pl._run_results):
        assert not _mentions(inspect.getsource(fn))


def test_fingerprint_inputs_are_all_resolvable():
    for ids in (pl.STAGE1_DECISIONS, pl.CALIBRATION_DECISIONS, pl.PROJECTION_DECISIONS, pl.RESULTS_DECISIONS):
        assert set(prov.decision_hashes(ids)) == set(ids)
    for mods in (pl.STAGE1_MODULES, pl.CALIBRATION_MODULES, pl.PROJECTION_MODULES, pl.RESULTS_MODULES):
        assert set(prov.code_hashes(mods)) == set(mods)
    with pytest.raises(prov.ProvenanceError):
        prov.code_hashes(["no_such_module"])
    with pytest.raises(prov.ProvenanceError):
        prov.decision_hashes(["D999"])


def test_requirements_txt_mirrors_pyproject_dependencies():
    meta = (PROJECT / "pyproject.toml").read_text(encoding="utf-8")
    block = re.search(r"dependencies = \[(.*?)\]", meta, re.DOTALL).group(1) + re.search(r"dev = \[(.*?)\]", meta, re.DOTALL).group(1)
    declared = {re.split(r"[<>=]", x)[0].strip().lower() for x in re.findall(r'"([^"]+)"', block)}
    required = {re.split(r"[<>=]", x)[0].strip().lower() for x in (PROJECT / "requirements.txt").read_text(encoding="utf-8-sig").splitlines() if x.strip()}
    assert declared == required


def test_ci_workflow_declares_three_jobs_and_states_the_integration_exclusion():
    text = (PROJECT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    wf = yaml.safe_load(text)
    assert set(wf["jobs"]) == {"lint", "unit-tests", "smoke-test"}
    assert "integration" in wf["jobs"]["unit-tests"]["name"] and "curtailmit_database" in text and "never present in CI" in text
    assert 'pytest -v -m "not integration"' in text and "ruff check src tests" in text and "curtailmit-run --dry-run" in text
    assert "DATABASE_ROOT" in wf["env"]
    assert all(step.get("with", {}).get("python-version", "3.11") == "3.11" for job in wf["jobs"].values() for step in job["steps"])
    assert 'pip install -e ".[dev]"' in text and "requirements.txt" not in text.split("jobs:")[1]
