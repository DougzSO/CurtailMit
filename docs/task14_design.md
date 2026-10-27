# Task 14-1 - Design proposal: end-to-end orchestration command and CI

Status: PROPOSAL, awaiting explicit approval. Design only: no `src/`, `scripts/`, `.github/` or test file was changed in this task. Implementation is Task 14, contingent on approval of this document and on the two decisions in section 0 (registered as `pending` D31 and D32 in `config/discovered_sources.yaml`).

Inputs read: `scripts/run_pipeline.py` (full), `.github/workflows/ci.yml` (full), `Makefile`, `pyproject.toml`, `requirements.txt`, `.env.example`, `src/curtailmit/paths.py`, `data_ingestion.py` (`run_stage1`), `hourly_model.py`, `projection.py`, `limitations.py`, `results_writer.py`, `mitigation.py`, `calibration.py` (reference section), `config/scenarios.yaml`, the Task 14 text of `docs/claude_commands.md`, and the GitHub Actions history of the remote (`gh run list`, `gh run view --log`).

## 0. STOP-AND-REPORT items

Two of the three stop triggers fired, one in a milder form. Nothing was changed or fixed.

### 0.1 `run_pipeline.py` (trigger 1: NOT fired; trigger 2: fired in part)

- The file is **`scripts/run_pipeline.py`**, not the repository root (the task text says `run_pipeline.py`). 17 lines, from the initial skeleton (`cb803d5`) and the pre-build commit `dbf547b`.
- It calls **only `run_stage1()`** and prints the result. The rest is a comment: `# TODO: Stage 2 (calibration), Stage 3 (projection), Stage 4 (mitigation), Stage 5 (hydrogen), Stage 6 (results_writer) - to be added incrementally.`
- It does **not** import calibration, the national or regional curves, the hourly model or the projection. It therefore contains **no stale model logic and no wiring of retired components**: nothing conflicts with D24 and nothing needs to be overwritten. Its only stale content is the stage numbering in the TODO (Stages 2-3 were later replaced by the Option E hourly model), which a rewrite replaces anyway.
- `make run` calls it, so today "the full pipeline" means Stage 1 only.

### 0.2 Existing CI (trigger 3: FIRED, in a form different from the one anticipated)

`.github/workflows/ci.yml` exists. It does **not** run integration tests and does **not** reference `curtailmit_database` paths: it runs `pytest -v -m "not integration"` and `ruff check src tests` on Python 3.11. But:

1. **Every GitHub Actions run so far has failed (13 of 13, all `failure`).** The last failed run (`ea74cb5`, 2026-10-21) shows `117 passed` and then the lint step failing with 26 ruff errors (23 auto-fixable; import ordering and similar). Those lint errors were fixed locally afterwards, but see 2.
2. **The remote is 37 commits behind local `main`** (`main...origin/main [ahead 37]`). Nothing from Tasks 7-13 (calibration, hourly model, projection, limitations, final results; 356 local tests) has ever been seen by CI. The CI status of the public repository today reflects the 2026-10-21 skeleton, not the code described in the article.
3. **One default (non-integration) test would fail in CI.** With `DATABASE_ROOT` pointed at an empty directory (the CI situation), the default suite gives `1 failed, 355 passed, 14 deselected`: `tests/test_analysis_task11e5.py::test_compounding_never_exceeds_the_asymptote` calls `analysis/task11e2_common.load_pte()`, which reads `processed/pte_curtailment_two_curves.parquet` from the local database. It is not marked `integration` (it passes locally only because the file exists). This is exactly the leak the Task 14-1 constraint warns about.
4. The `integration` marker description in `pyproject.toml` says "require live network access", which is incomplete: the Task 11F/13 integration tests (`test_hourly_model.py`, `test_projection_hourly.py`, `test_final_results.py`, ...) need the **local database**, not the network. The workflow does not say why integration tests are excluded.
5. Installation uses `pip install -r requirements.txt` + `pip install -e .`, not `pip install -e ".[dev]"`; `requirements.txt` and `pyproject.toml` duplicate the dependency list (drift risk). Minor: the log warns that Node.js 20 actions (`checkout@v4`, `setup-python@v5`) are deprecated.

### 0.3 Stages with no automated invocation (trigger 2) - see inventory in section 1

Four items have no runnable entry point (hourly calibration, Option E projection, final results, and the Option E "golden" regression value extraction). Everything except the last is a thin wrapper around a function that already exists and is tested; Task 14 builds those wrappers inside the orchestrator (not as separate scripts). The remaining items are scope questions registered as **D31** (section 0.4).

### 0.4 Decision candidates registered as `pending`

- **D31 - scope of "end to end".** Recommended: Stage 1 (acquisition + quality report) -> hourly calibration -> Option E projection -> final results, plus read-back validation. Explicitly out of scope: the analysis scripts (`analysis/task11*.py`, throwaway diagnostics), the retired national/regional calibration (kept as labelled references, never invoked), PLD (disabled, D10), figures and the limitations report (Task 13B), the run manifest (Task 15). Alternatives: include the reference model in a `--with-references` mode (not recommended: it adds a path by which a `role="reference"` table can sit beside production output).
- **D32 - CI test isolation.** Recommended: fix the one leaking test by replacing the local-file read with a synthetic table (monkeypatching `load_pte`), in a test-only change; point CI at an empty `DATABASE_ROOT` so any other leak fails loudly. Alternative: mark the test `integration` (loses its coverage in CI). Also decide when the 37 local commits are pushed (the push is the user's action; the design does not assume it).

## 1. Inventory of the pipeline stages and their invocation today

| # | Stage | Function (module) | How it is run today | Needs `curtailmit_database` | Mocked unit tests |
|---|---|---|---|---|---|
| 1 | Stage 1: ONS curtailment, capacity factor (+ solar dispatched gap, D20/D22), generation by source, DEB/REB/EUB classification, MCTI factors, validation data, data-quality report | `data_ingestion.run_stage1` | `make stage1` = `python -m curtailmit.data_ingestion`; `scripts/run_pipeline.py` | Yes (writes raw/interim/processed/logs; live network unless `use_cache`) | Yes (`tests/test_stage1.py`, step overrides) |
| 2 | Hourly panel (SIN) and Option E calibration (curves, L=1 variants, base profile, horizon bands) | `hourly_model.load_sin_panel`, `run_hourly_calibration` | **No entry point.** Only reachable through `projection.build_option_e_table(recalibrate=True)` or by hand | Yes (raw/ons parquet, interim cache) | Synthetic panel; real regression is `@integration` |
| 3 | Option E projection, 12 rows, limitations sidecar | `projection.build_option_e_table` | **No entry point** (called from tests and `analysis/task11f_*`) | Yes (processed/) | Yes; golden regression in `@integration` |
| 4 | Limitations (D25 text, must be `adopted`) | `limitations.limitations_payload` | Implicit inside stage 3 | No (reads `config/discovered_sources.yaml`) | Yes |
| 5 | OM/CM mitigation, hydrogen | `mitigation.compute_mitigation(require_model=True, split_margins=True)`, `hydrogen.compute_hydrogen_potential` | Implicit inside stage 6 | No | Yes |
| 6 | Final results (long format, sensitivity companion, sidecar) | `results_writer.run_final_results` | **No entry point** | Yes (reads processed/, writes outputs/tables) | Yes (mocked table); real table in `@integration` |
| - | National/regional calibration, two-curve table | `calibration.run_calibration`, `projection.build_pte_curtailment_table` | Only analysis scripts and tests | Yes | labelled `role="reference"`; **never in the orchestrated run** |
| - | Analysis scripts | `analysis/task11*.py` | `python analysis/<file>.py` by hand | Yes | Helper smoke tests only |

CI-safe (public repo only): stages 4 and 5, and the unit tests of all stages with mocked data. Everything else needs the local database.

## 2. Orchestration command

### 2.1 Form and name

Logic in a new module **`src/curtailmit/pipeline.py`** (importable, so it is unit-testable), exposed as a console script **`curtailmit-run`** (`[project.scripts] curtailmit-run = "curtailmit.pipeline:main"`), and **`scripts/run_pipeline.py`** is rewritten as a three-line shim that calls `pipeline.main()`. Justification: the console script follows `pip install -e ".[dev]"` with no path assumptions and is what CI can smoke-test (`curtailmit-run --help`); the shim keeps `make run` and the Task 14 text of `docs/claude_commands.md` ("rewrite scripts/run_pipeline.py") valid. A script-only solution would leave the orchestration logic outside the package and harder to test.

### 2.2 Stage sequence

`curtailmit-run` with no flags runs, in order, and stops at the first failure:

0. **Preflight.** Resolve the database root (2.3), print it, require it to exist and to contain `raw/` or be creatable; load `config/scenarios.yaml` (raises on solar_pct + wind_pct > 100); require `pld.enabled == false` (D10; if true, **error**, not a silent skip, because no PLD stage exists); `limitations.limitations_payload()` (fails unless D25 is `adopted`) - fail fast before any download.
1. **Stage 1**: `run_stage1(use_cache=args.use_cache)`; its `Stage1Error` on any FAIL check propagates.
2. **Hourly calibration**: `panel = hourly_model.load_sin_panel(refresh=True)` when Stage 1 ran in this invocation (otherwise the interim cache would be silently stale; with `--skip-stage1` it is read as is and the summary says so), then `run_hourly_calibration(panel, processed_dir)`. Explicit, never "load the frozen one": `build_option_e_table` falls back to a previously saved calibration if the base-profile file exists, which an orchestrator must not do implicitly (`recalibrate=True` is passed).
3. **Option E projection**: `projection.build_option_e_table(recalibrate=False)` on the calibration just written (writes `pte_curtailment_option_E.parquet` + sidecar), then `mitigation.check_provenance(table)`: all 12 rows `model == option_E_hourly`, `role == production`.
4. **Final results**: `results_writer.run_final_results()` (uses `compute_mitigation(require_model=True)`, recomputes the support status), then **read-back validation**: `read_final_results(...)` + `validate_final_results` on what was written (156 rows, no forbidden wording, caveat columns present).
5. **Reference check** (`--verify-reference`, default on when the reference fixture exists): compare the written `curtailed_energy` totals with the Task 11F/13 reference values (2.4).
6. **Summary**: one console block with each stage status/duration, the output paths (`final_results.csv/.parquet`, sidecar, sensitivity companion, Stage 1 quality report), the support status counts and the reference-check result.

Flags: `--use-cache` (acquisition cache, default off, as in the Task 14 text), `--skip-stage1` (marks the summary "PARTIAL RUN: Stage 1 not executed, existing products reused" and exits with code 0 only if every later gate passes), `--dry-run` (prints the plan and the resolved paths, touches nothing), `--verify-reference/--no-verify-reference`. **No flag disables a gate and no flag selects another model.** The `--integration` flag of the old Task 14 text is **not** adopted: live calls are a property of Stage 1 (`use_cache`), and integration tests stay a pytest concern (superseding note to be added to `docs/claude_commands.md`, append-only).

The retired references (`calibration.run_calibration`, `build_pte_curtailment_table`, `project_curtailment_two_curves`, `fit_regional_reference`) are **not imported by `pipeline.py`**; a unit test enforces it (2.5).

### 2.3 Database path

No relative literals in the orchestrator. It reuses `curtailmit.paths`, which already resolves `DATABASE_ROOT` from the environment variable or `.env` (default `../curtailmit_database`) against the project root with `Path.resolve()`, plus the `config/paths.yaml` sub-directories (`get_processed_dir`, `get_outputs_dir("tables")`, ...). Proposed additions to `pipeline.py` only: the resolved root is printed at the start and in the summary; CLI `--database-root PATH` sets `os.environ["DATABASE_ROOT"]` before any path function is called (so a typo cannot silently create a new empty tree: preflight requires `raw/` to exist unless Stage 1 is going to run). Windows users keep `Join-Path`-style semantics because everything is `pathlib`; no string concatenation of separators.

### 2.4 Hard gates in a full run

Every gate is an exception raised by the stage function; the orchestrator **does not catch-and-continue**.

| Gate | Where it fires | In the orchestrated run |
|---|---|---|
| D25 not `adopted` (`LimitationError`) | preflight and `build_option_e_table` | run aborts before download |
| `Stage1Error` | `run_stage1` | abort, Stage 1 FAIL report is already written |
| `ModelProvenanceError` | `check_provenance` after stage 3 and `compute_mitigation(require_model=True)` in stage 4 | abort; no `final_results` written (the write happens after the check) |
| `SupportStatusConflictError` | `build_final_results` (recompute vs table) | abort before any file is written |
| `FinalResultsError` (missing columns, no D25 id, no classification flag) | stage 4 | abort |
| Reference mismatch | stage 5 | abort **after** the files are written, run marked `FAILED_REFERENCE` (the files exist but the run does not report success) |

Mechanics: `pipeline.run()` wraps each stage in `try/except Exception as exc`, writes `logs/pipeline_run_<UTC timestamp>.json` with `{stages: [{name, status, seconds}], failed_stage, error_type, error}`, logs `PIPELINE FAILED at stage <n> <name>: <ErrorType>: <message>`, and **re-raises**; `main()` converts it into a non-zero exit code (`2` for the gate exceptions above, `1` for anything else). A failed run never prints the success summary. No default values are substituted at any point.

Reference values for stage 5 and for the manual verification: the 12 `curtailed_energy` totals of Task 11F/13 (TB 43.8 / 64.3 / 127.6 / 354.8 TWh; TA 2040 242.4 partial support and 2050 536.1; TG 2040 181.4 and 2050 333.9, ...), stored once in `tests/fixtures/final_results/reference_totals.json` taken from the current output (committed, small; it is derived from the table that is already reconciled to 1e-12 with Task 11F), compared with a relative tolerance of 1e-9 (floating point only). Calibration is deterministic (seeded bootstrap, `n_boot` fixed), so a drift beyond that is a real change and must be a conscious decision, not an automatic re-baseline.

## 3. CI workflow (near-final draft)

Replaces `.github/workflows/ci.yml` in Task 14. Lint runs before the tests (fails fast), installs through the declared extras, and points `DATABASE_ROOT` at an empty runner directory so that any test silently reading the local database fails instead of passing by accident.

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

# IMPORTANT - what this workflow does NOT run:
# tests marked @pytest.mark.integration. They need the local data repository (curtailmit_database:
# ONS/MCTI raw files, processed tables), which is never pushed to GitHub, and some also need live network access.
# CI therefore runs the unit suite (mocked data, synthetic panels, committed fixtures) and the linter only.
# The real end-to-end verification is the local command `curtailmit-run` (docs/task14_design.md, section 4).
jobs:
  lint-and-unit-tests:
    name: lint + unit tests (integration tests excluded: local-data dependency)
    runs-on: ubuntu-latest
    env:
      # Empty on purpose: a unit test that needs real data must fail here, not read some default path.
      DATABASE_ROOT: ${{ runner.temp }}/empty_curtailmit_database
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
          cache-dependency-path: pyproject.toml
      - name: Install package with dev extras
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev]"
      - name: Lint
        run: ruff check src tests
      - name: Unit tests (integration tests deselected explicitly)
        run: pytest -v -m "not integration"
      - name: Entry-point smoke test (no data touched)
        run: curtailmit-run --dry-run
```

Notes: `-m "not integration"` is already the pytest default (`addopts` in `pyproject.toml`); it is repeated on the command line so the exclusion is visible in the workflow, and the marker description in `pyproject.toml` is corrected in Task 14 to "requires the local curtailmit_database and/or live network". `requirements.txt` stays for the Makefile `setup` target but CI no longer installs from it; Task 14 makes it a documented mirror (a unit test comparing the two lists is cheap and proposed). Only Python 3.11 is tested although `requires-python >= 3.10`.

**Is the orchestrator exercised in CI?** Recommendation: **yes, in two reduced forms, not as a data run.** (a) The unit tests of `pipeline.py` with mocked stage functions run inside the normal pytest step (call order, gate propagation, no-skip behaviour, section 4). (b) `curtailmit-run --dry-run` verifies the console script installs and resolves its plan without reading any data. A synthetic end-to-end run on fabricated data is **not** recommended: it would duplicate what the stage-level tests and the `@integration` regressions already cover, require maintaining a fake database, and invite the false impression that CI validated the science. CI = lint + unit + entry-point smoke; the real run is local.

## 4. Test plan

Unit tests (`tests/test_pipeline.py`, default suite, no data; stage functions replaced through an injectable `stages` mapping like `run_stage1(steps=...)`):

1. Call order: stages execute in the documented sequence with the documented arguments (`recalibrate`, `refresh=True` when Stage 1 ran; `use_cache` forwarded).
2. Gate propagation: each of `Stage1Error`, `LimitationError`, `ModelProvenanceError`, `SupportStatusConflictError`, `FinalResultsError` raised in its stage stops the run, later stages are **not** called, the failure JSON is written, the exception type reaches `main()` and the exit code is non-zero (2 for gates).
3. `check_provenance` is called on the Option E table and is not bypassable: a table with one `reference_national_curve` row aborts before `run_final_results`.
4. No silent skip: a stage returning `None` or a stage missing from the mapping is an error; `--skip-stage1` produces the "PARTIAL RUN" marker.
5. `pld.enabled: true` raises in preflight.
6. Retired references: an AST/source scan asserts `pipeline.py` does not import or reference `run_calibration`, `build_pte_curtailment_table`, `project_curtailment_two_curves`, `fit_regional_reference`.
7. Reference check: a doctored total raises `FAILED_REFERENCE`; within 1e-9 passes.
8. `--dry-run` prints the plan with the resolved database root and touches nothing (tmp `DATABASE_ROOT`); `--database-root` overrides the environment.
9. `pyproject` console script entry resolves to `curtailmit.pipeline:main`; `requirements.txt` and `pyproject.toml` dependency lists agree.
10. The one test that leaks (D32) is made synthetic and the full default suite is run with an empty `DATABASE_ROOT` as part of acceptance.

Local acceptance (not CI): with the real database, `curtailmit-run --skip-stage1` (and, once, the full run with `--use-cache`) must end with success and with `final_results.csv` equal to the current Task 13 output: 156 rows, the 12 reference totals within 1e-9, tCO2 = central x 1e6 x 2025 factor, 2050 rows `calibrated_label = False`, `central_inside_range` 120 True / 36 False. `git diff --stat` on the committed tables must show no change. The existing `pytest -m integration` suite (14 tests) is run as well.

## 5. Out of scope / follow-ups

Figures and the auto-generated limitations report (Task 13B), the aggregated `run_manifest_<timestamp>.json` (Task 15), pushing the 37 local commits and the first green CI run (user action), any change to model code or computed values.

## 6. Questions for approval

1. D31: scope as in 0.4 (Stage 1 -> calibration -> Option E -> final results; analysis scripts and references out)?
2. D32: fix the leaking test by making it synthetic (recommended) or mark it `integration`?
3. Console script `curtailmit-run` in `pipeline.py` with `scripts/run_pipeline.py` as a shim: accepted?
4. Full run always recalibrates (deterministic) instead of loading a frozen calibration: accepted? (A `--reuse-calibration` flag could be added, but the default would remain explicit recalibration.)
5. Reference check on by default, fixture `tests/fixtures/final_results/reference_totals.json`: accepted?
6. CI: lint + unit + `--dry-run` smoke only, `DATABASE_ROOT` empty, Python 3.11 only: accepted?
