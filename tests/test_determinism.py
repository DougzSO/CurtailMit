"""Standing determinism guarantee (Task 15, decision D34 Scope A).

Guaranteed and tested here: same environment, same inputs, same machine -> byte-identical products, whatever PYTHONHASHSEED or BLAS thread count is used.
NOT guaranteed (and not claimed): bit-identical output across operating systems, CPUs, BLAS builds or library versions (parquet files embed the pyarrow version, `to_csv` follows the platform
line ending, floating-point reductions may differ in the last bits). Cross-platform reproducibility relies on the reference-value check (relative tolerance 1e-9, tests/fixtures/final_results/
reference_totals.json), which `curtailmit-run` enforces on every run (D24).

The unit tests use a synthetic panel and no curtailmit_database, so they run in standard CI. The real-pipeline comparison (3 states, 13 files) is the integration test at the end.
"""

from __future__ import annotations

import ast
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from curtailmit import pipeline as pl

PROJECT = Path(__file__).resolve().parents[1]
SRC = PROJECT / "src" / "curtailmit"
TESTS = Path(__file__).resolve().parent

# The calibration + projection products (the stochastic path: bootstrap with default_rng(seed=0)).
CALIBRATION_FILES = (*pl.CALIBRATION_PROCESSED, pl.OPTION_E, f"{pl.OPTION_E}.limitations.json")

_CHILD = """
import sys
sys.path.insert(0, {tests!r})
from pathlib import Path
from test_hourly_model import synthetic_panel
from curtailmit import projection as pj
pj.build_option_e_table(processed_dir=Path({out!r}), panel=synthetic_panel())
"""


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def _digest(directory: Path) -> dict[str, str]:
    missing = [n for n in CALIBRATION_FILES if not (directory / n).is_file()]
    assert not missing, f"products not written: {missing}"
    return {n: _md5(directory / n) for n in CALIBRATION_FILES}


def _build_in_subprocess(out: Path, hashseed: str, threads: str | None) -> None:
    env = {**os.environ, "PYTHONHASHSEED": hashseed}
    if threads:
        env.update({"OMP_NUM_THREADS": threads, "OPENBLAS_NUM_THREADS": threads, "MKL_NUM_THREADS": threads})
    # No `-I`/`-E`: those would also drop PYTHONHASHSEED, which is exactly the variable under test.
    subprocess.run([sys.executable, "-c", _CHILD.format(tests=str(TESTS), out=str(out))], env=env, check=True, capture_output=True, text=True, timeout=600)


@pytest.fixture(scope="module")
def reference_run(tmp_path_factory) -> dict[str, str]:
    from test_hourly_model import synthetic_panel

    from curtailmit import projection as pj

    out = tmp_path_factory.mktemp("determinism_reference")
    pj.build_option_e_table(processed_dir=out, panel=synthetic_panel())
    return _digest(out)


def test_repeated_run_in_the_same_process_is_byte_identical(reference_run, tmp_path):
    from test_hourly_model import synthetic_panel

    from curtailmit import projection as pj

    pj.build_option_e_table(processed_dir=tmp_path, panel=synthetic_panel())
    assert _digest(tmp_path) == reference_run


@pytest.mark.parametrize("hashseed, threads", [("1", "1"), ("987654", None)])
def test_other_hash_seed_and_thread_count_give_byte_identical_products(reference_run, tmp_path, hashseed, threads):
    _build_in_subprocess(tmp_path, hashseed, threads)
    assert _digest(tmp_path) == reference_run


# ---------------------------------------------------------------------------------------------------------------- source scan
def _production_modules() -> list[Path]:
    return sorted(SRC.glob("*.py"))


def test_the_only_random_number_generators_are_explicitly_seeded():
    """default_rng must be called with an explicit `seed` argument; no `random` module, `np.random.seed`, shuffle, multiprocessing or n_jobs anywhere in src/."""
    forbidden_imports = {"random", "multiprocessing", "concurrent", "threading", "secrets"}
    forbidden_names = {"shuffle", "permutation", "RandomState", "n_jobs"}
    constructions = []
    for path in _production_modules():
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not forbidden_imports & {a.name.split(".")[0] for a in node.names}, f"{path.name}: forbidden import {[a.name for a in node.names]}"
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] not in forbidden_imports, f"{path.name}: forbidden import from {node.module}"
            elif isinstance(node, ast.Attribute):
                assert node.attr not in forbidden_names, f"{path.name}:{node.lineno}: forbidden attribute {node.attr}"
                if node.attr == "seed" and isinstance(node.value, ast.Attribute) and node.value.attr == "random":
                    pytest.fail(f"{path.name}:{node.lineno}: np.random.seed (global state) is not allowed")
            elif isinstance(node, ast.keyword):
                assert node.arg not in forbidden_names, f"{path.name}:{node.value.lineno}: forbidden keyword {node.arg}"
            elif isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", None)) == "default_rng":
                constructions.append((path.name, node))
    assert constructions, "the scan found no default_rng call: the bootstrap moved, update this test"
    for name, node in constructions:
        assert len(node.args) == 1 and not node.keywords and isinstance(node.args[0], ast.Name) and node.args[0].id == "seed", f"{name}:{node.lineno}: default_rng must receive the explicit `seed` argument"
    assert {n for n, _ in constructions} <= {"hourly_model.py", "calibration.py"}, "an unexpected module builds a random generator"


def test_production_seed_defaults_are_fixed_integers():
    """The seed defaults of the production bootstrap are literal integers (not time- or environment-derived)."""
    tree = ast.parse((SRC / "hourly_model.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "bootstrap_curve_params")
    args = fn.args
    defaults = dict(zip([a.arg for a in args.args][-len(args.defaults):], args.defaults, strict=True))
    assert isinstance(defaults["seed"], ast.Constant) and defaults["seed"].value == 0


# ---------------------------------------------------------------------------------------------------------------- real pipeline
def _run_downstream(hashseed: str, threads: str | None) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONHASHSEED": hashseed}
    if threads:
        env.update({"OMP_NUM_THREADS": threads, "OPENBLAS_NUM_THREADS": threads, "MKL_NUM_THREADS": threads})
    cmd = [sys.executable, "-m", "curtailmit.pipeline", "--skip-stage1", "--force-calibration", "--force-projection", "--force-results"]
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=1800, check=False)


@pytest.mark.integration
def test_real_pipeline_is_byte_identical_across_hash_seeds_and_thread_counts():
    """Full real-pipeline comparison (needs the local curtailmit_database; formalises the manual check of the Task 15-1 design).

    The three states are: the files already on disk, a forced recompute with PYTHONHASHSEED=1 and one BLAS thread, and a forced recompute with PYTHONHASHSEED=987654 and default threading. The 13
    products (6 calibration files, the Option E table + sidecar, 5 final-results files) must have identical MD5 in all three. Bit-identity across platforms is NOT claimed: there the
    reference-value check (rtol 1e-9, D24) is the guarantee. A difference here is a stop-and-report finding, not something to tolerate.
    """
    from curtailmit.paths import get_outputs_dir, get_processed_dir

    processed, tables = get_processed_dir(), get_outputs_dir("tables")
    files = [processed / n for n in CALIBRATION_FILES] + [tables / n for n in pl.FINAL_FILES]
    if not all(p.is_file() for p in files):
        pytest.skip("pipeline products not present in the local database (run curtailmit-run first)")
    assert len(files) == 13
    baseline = {p.name: _md5(p) for p in files}
    for hashseed, threads in (("1", "1"), ("987654", None)):
        proc = _run_downstream(hashseed, threads)
        assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
        assert {p.name: _md5(p) for p in files} == baseline, f"products differ with PYTHONHASHSEED={hashseed}, threads={threads}"
