# Reproducing the CurtailMit results

Task 15 (decisions D33, D34). Written for a reader who **already has the local data repository `curtailmit_database` populated** (or who will populate it by running Stage 1 against the public sources). Companion documents: `docs/orchestration.md` (how the command decides what to recompute), `docs/methodology.md` section 2.3j/2.3k (the model), `docs/acceptance_criteria_status.md` (which acceptance criterion is met by which artifact).

## 1. Scope and limits

**What is reproduced.** The 156-row long-format table `final_results` (12 scenario-years x 13 quantity/component combinations), from the raw ONS and MCTI files, by one command.

**What is promised.**
- *Same environment, same inputs, same machine:* byte-identical products, whatever `PYTHONHASHSEED` or BLAS thread count is used. This is a standing test (`tests/test_determinism.py`; the only randomness in the production path is a bootstrap seeded with `default_rng(seed=0)`).
- *Any other machine, operating system or library version:* bitwise identity is **not** promised (parquet files embed the pyarrow version, `to_csv` follows the platform line ending, floating-point reductions can differ in the last bits). The promise there is the reference-value check that `curtailmit-run` enforces on every run: the 60 `total` rows of `final_results` must equal `tests/fixtures/final_results/reference_totals.json` within a relative tolerance of 1e-9 (a mismatch stops the run with exit code 2).

**Data availability (D33) - what this document does and does not promise.** This document assumes the raw data have already been acquired. It is **not** a promise that the data are bundled with, or hosted by, this repository: `curtailmit_database` is local-only and is not on GitHub. What the public repository provides instead is `data_snapshot_manifest.json` (repository root): relative path, source URL, retrieval time (UTC), SHA-256 and byte size of each of the 254 raw data files (525,601,319 bytes; 250 pipeline inputs plus, since Task 17, the 4 files of the GADM boundary layer of decision D36, which are local-only context-map inputs and not a pipeline input) that the production pipeline read, plus the code to re-download them (Stage 1) and to check them hash-by-hash (section 3). No copy of the data is hosted, because the redistribution terms of the ONS and MCTI datasets have not been verified; the manifest lists identities, not content. The publishers may revise or remove historical files, so a re-download can legitimately differ; the verification command reports every difference instead of hiding it. **Open item: the ONS and MCTI terms of use were not formally verified; this must be checked by hand before submission (`docs/pre_submission_checklist.md`, item 1).** *The article needs a data-availability statement that cites this manifest and the verification procedure (open item for the article-writing step; no article text is drafted here).*

**What is not covered.** Figures (Task 13B). The retired national/regional calibration and the analysis scripts of Tasks 7-11E5 are reference material, not part of the reproduction path.

## 2. Environment

| Item | Value |
|---|---|
| Interpreter used for every verified result | Python 3.11.9 (Windows 10, local `.venv`); CI uses Python 3.11 on Ubuntu (3.11.x) |
| Declared floor | `requires-python >= 3.10` in `pyproject.toml` - **never tested**; the floor is stated, not silently changed |
| Pinned environment | `requirements.lock.txt`: exact `==` pins of every direct and transitive dependency, from `pip freeze` of the `.venv` in which the test suite and `curtailmit-run` passed (47 lines, key versions: pandas 3.0.6, numpy 2.4.6, scipy 1.17.1, pyarrow 26.0.0, statsmodels 0.15.0) |
| Human-readable floors | `requirements.txt`, `pyproject.toml` (what CI's floors job resolves to the newest releases) |

```
python -m venv .venv && . .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.lock.txt
pip install -e . --no-deps
```

CI runs both: the floors resolution (`unit-tests`, catches new releases that break the code) and the pinned environment (`unit-tests-locked`, the environment of the results). A test checks that every pin satisfies the floor in `pyproject.toml`. `make setup` is the flexible development install (floors, `requirements.txt`); `make setup-locked` is the exact-pin reproducibility install (`requirements.lock.txt` + `pip install -e . --no-deps`). Where the lock cannot be installed (another platform, another Python), the reference check above is the criterion that the numbers still hold.

## 3. Data

**Sources** (all open data, downloaded by Stage 1; URLs and retrieval times in `data_snapshot_manifest.json`):

| Folder under `raw/` | Files | Source | Used by |
|---|---:|---|---|
| `ons/generation_by_source` | 13 | ONS open-data S3 bucket (energy balance by subsystem) | hourly panel (generation, load) |
| `ons/capacity_factor` | 59 | ONS open-data S3 bucket | hourly panel (potential generation) |
| `ons/curtailment_wind`, `ons/curtailment_solar` | 60, 33 | ONS open-data S3 bucket (constrained-off wind / solar) | hourly panel (curtailment), classification |
| `ons/mmgd`, `ons/interchange`, `ons/carga_energia` | 68, 11, 1 | ONS load API and open-data bucket | Stage 1 checks (D20) and probes; not model inputs |
| `mcti/*` | 8 | MCTI / gov.br (emission-factor workbooks) | OM/CM/average factors (D18, D29) |

The PTE/EPE scenario table is in the repository (`config/scenarios.yaml`); there is nothing to download for it.

**Acquiring and checking the data.**
```
curtailmit-run                          # Stage 1 downloads every file again (without --use-cache) and writes a retrieval manifest next to each
python -m curtailmit.run_manifest verify   # compare the local raw files with data_snapshot_manifest.json
```
`verify` prints `N matching, N differing, N missing, N extra` and lists the differing files (exit code 1 on any difference). A *differing* file means the publisher changed it since the snapshot; the model panel is cut at `END_EXCLUSIVE` (below), so a revision of an old month can change the results while a new month cannot. To regenerate the manifest from a populated database: `python -m curtailmit.run_manifest snapshot`.

**Cutoff.** `END_EXCLUSIVE = "2026-10-01"` in `src/curtailmit/hourly_model.py`: the hourly panel excludes everything from that date because October 2026 is incomplete in the raw files. It is deliberately fixed; advancing it changes the calibration and every total, so the reference check fails by design until `reference_totals.json` is consciously regenerated (`docs/orchestration.md`, maintenance watchpoints).

## 4. Running

```
curtailmit-run                  # also: python -m curtailmit.pipeline
curtailmit-run --dry-run        # configuration, imports, gate wiring and the skip/run plan; writes nothing
curtailmit-run --use-cache      # Stage 1 reuses SHA-256-verified cached raw files and may be skipped
curtailmit-run --skip-stage1    # explicit PARTIAL run (SUCCESS_PARTIAL): existing Stage 1 products reused
curtailmit-run --force-all      # recompute every stage
```
The stage sequence is in `docs/orchestration.md` (generated from the code). Each stage prints `SKIPPED (cached, ...)` or `RAN (missing | stale | forced: ...)`; a stage is skipped only if its stamp (`processed/pipeline_stamps/<stage>.json`: SHA-256 of inputs, adopted decisions, module source, parameters, outputs) verifies; whenever that cannot be established it is recomputed. Exit code 0 = success, 2 = a hard gate (Stage 1 quality FAIL, D25 not adopted, a non-Option-E row, a support-status conflict, an invalid final table, a reference mismatch, a raw file whose provenance cannot be stated), 1 = any other error. Details: `docs/orchestration.md`.

Outputs (under `DATABASE_ROOT/outputs/tables`): `final_results.csv`/`.parquet` (+ `.limitations.json`), `final_results_mcti_sensitivity.csv`/`.parquet`. Intermediate products are in `processed/`. Two records per run, in `DATABASE_ROOT/logs`: `pipeline_run_<UTC>.json` (every run, success or failure; on failure it holds the stage, error type, reason and diagnostics) and `run_manifest_<UTC>.json` (section 9).

Notes: Windows and Linux are both supported (paths come from `curtailmit.paths`; CSV line endings follow the platform). The database root is `--database-root` > `DATABASE_ROOT` > `.env` > `../curtailmit_database`.

## 5. Why Option E is the production model

The question is how much wind and solar energy the Brazilian grid will curtail in the PTE scenarios and what CO2 mitigation that costs. The model that answers it is **Option E** (D24): the curtailment rate of each technology is a bounded logistic function of the *hourly* potential share of wind and solar in the system load (r), fitted on the 2022-2026 ONS hourly record of the whole interconnected system (SIN) and applied to the 2025 hourly profile scaled to each PTE scenario-year. Full description: `docs/methodology.md` section 2.3j.

The history needed to trust that choice is short:
- Tasks 7-11B fitted a *monthly national penetration* curve C(P). Task 11D showed that the monthly penetration is a time-confounded proxy of the true driver (D25 text).
- Tasks 11E-11E4 replaced it by the hourly driver and tested the alternatives: a Northeast-only driver, transmission capacity, sub-hourly data (negative), conformal prediction. D26 retires the transmission-expansion extension.
- D23 fixes the basis (PTE generation treated as gross/potential), D24 adopts the hourly formulation and the by-horizon reporting (2025-2040: empirical backtest band plus a supplementary conformal 80 % interval; 2050: central value plus a flexibility-conditional range, never a confidence interval), D25 records the one limitation that could not be removed: a residual upward drift of wind curtailment at fixed r, so central values are more likely low than high (upward only, 3-15 % of the 2050 total).
- Task 11F migrated Option E to production; the earlier curves survive only as labelled reference formulations (`model = "reference_*"`), never in `final_results`.

Per-task evidence: `docs/task11c_investigation_report.md` ... `docs/task11e5_findings.md`, `docs/roadmap.md` updates. A reader who trusts D24/D25 does not need them.

## 6. Reading the output

`final_results` is long format: one row per scenario x year x quantity x component. `central_value` is the model value; `conditional_range_low/high` is a range implied by stated assumptions (`range_basis` says which), **never a confidence interval**. OM and CM emission factors are alternative proxies of the marginal factor and are never summed (D28). The emission-factor year is 2025 (D29); the 2021-2025 mean is a labelled sensitivity. Hydrogen uses a fixed SEC of 52.5 kWh/kg with 50-55 as a separate sensitivity (D30). Every row carries `known_limitations` (D25 on every row) and `drift_direction = "upward"`. The 2050 rows are not calibrated and carry only the conditional range; their emission-side figures compose an energy-side range with point-value factors (a partial uncertainty composition that any article text must state). Column definitions: `docs/data_dictionary.md`.

## 7. Decision register

Generated from `docs/roadmap.md` (D1-D12) and `config/discovered_sources.yaml` (D13 onward); `python -m curtailmit.doc_generation --write` regenerates it and a test fails if this table disagrees with the sources or a number is reused. D1-D12 were not rewritten into the YAML (the adopted texts are the audit trail).

<!-- GENERATED:BEGIN id=decision-register sources=roadmap.md,discovered_sources.yaml
     do not edit by hand; regenerate with: python -m curtailmit.doc_generation --write -->

| # | Decision | Status | Decided in | Implemented in |
|---|---|---|---|---|
| D1 | 2020 baseline | adopted | roadmap, table | - |
| D2 | Year grid | adopted | roadmap, table | - |
| D3 | Interpolation (2031-39, 2041-49) | adopted | roadmap, table | - |
| D4 | Primary-energy 6-point grid (+2035, +2045) | adopted | roadmap, table | - |
| D5 | ONS classification mapping default | adopted | roadmap, table | - |
| D6 | Classification fallback | adopted | roadmap, table | - |
| D7 | Electrolyzer SEC | adopted | roadmap, table | - |
| D8 | Average SIN emission factor (OQ-3, part 1) | adopted | roadmap, table | - |
| D9 | Marginal emission factor (OQ-3, part 2) | adopted | roadmap, table | - |
| D10 | PLD (OQ-4) | adopted | roadmap, table | - |
| D11 | OQ-1 | adopted | roadmap, table | - |
| D12 | Combined Margin (CM) weighting formula | adopted | roadmap, own section | - |
| D13 | Curtailment energy column (wind and solar) | adopted | YAML, 2026-10-21 | curtailmit.data_ingestion.parse_curtailment_frame (Task 2) |
| D14 | Per-package ONS coverage floors; solar 2020 baseline = documented zero | adopted | YAML, 2026-10-21 | - |
| D15 | ONS generation-by-source: usable history starts 2016 | adopted | YAML, 2026-10-21 | curtailmit.ons_generation (Task 3, commit 3f69554) |
| D16 | Generation basis: ONS SIN (historical) vs PTE/BLUES (projection) - not reconciled by design | adopted | YAML, 2026-10-21 | documentation only |
| D17 | Curtailment classification: ONS reason codes -> DEB / REB / EUB | adopted | YAML, 2026-10-21 | curtailmit.ons_classification (Task 4) |
| D18 | MCTI emission factors: scraping rules, required years, derived OM/CM | adopted | YAML, 2026-10-21 | curtailmit.mcti_client (Task 5) |
| D19 | ANEEL fallback for generation-by-source: capacity only, explicit invocation | adopted | YAML, 2026-10-22 | curtailmit.aneel_client (Task 6) |
| D20 | ONS balance val_gersolar includes a non-dispatched (MMGD-like) component from 2023-04-29 onward; centralized-... | adopted | YAML, Task 6B | commit 224ad96 (Task 9: ons_generation.py P(t) tables, ons_solar_gap.py, calibration.py w... |
| D21 | Calibration curve: L bounded to (0, 1]; wind-only months kept; bootstrap uncertainty mandatory for Stage 3 | adopted (superseded in practice by D24) | YAML, Task 9 | Task 7C: calibration.fit_calibration (bounds), calibration.bootstrap_calibration_ci |
| D22 | Two technology-specific curtailment curves, C_wind(P) and C_solar(P), on the shared driver P = solar_pct + wi... | adopted (superseded in practice by D24) | YAML, Task 7D | Task 7D: calibration.build_technology_frames, TechnologyCurve, CalibrationResult, run_cal... |
| D23 | Gross (potential) vs net (delivered) basis of the PTE/BLUES generation, and the E_curt formula | adopted | YAML, Task 11C | working assumption in operational use since Task 7 / Task 11B (curtailed = PTE generation... |
| D24 | Adopt the regional / pooled formulation as the project's driver of the curtailment rate, replacing or augment... | adopted | YAML, Task 11C | adoption recorded in the Task 11F0 commit ('Task 11F0: formal adoption of D23, D24, D26') |
| D25 | Time confound: the P -> C_wind relation in the Northeast is mostly a time trend | adopted | YAML, Task 11D | adoption recorded in the Task 11F-0 commit ('Task 11F-0: formal adoption of D25 |
| D26 | Retire the deferred EPE PDE / PET transmission-expansion extension on the basis of the Task 11E / 11E2 negati... | adopted | YAML, Task 11E2 | adoption recorded in the Task 11F0 commit ('Task 11F0: formal adoption of D23, D24, D26') |
| D27 | Fate of the pre-existing results_writer.ResultsRow schema (supersede, coexist or freeze) when the Option E fi... | adopted | YAML, Task 13-1 | curtailmit.results_writer (build_final_results, write_final_results, FinalResultsRow supe... |
| D28 | How the OM/CM split interacts with the horizon-dependent range of option E (2050 flexibility-conditional rang... | adopted | YAML, Task 13-1 | curtailmit.results_writer (build_final_results, write_final_results, FinalResultsRow supe... |
| D29 | MCTI emission-factor year applied to the projection years 2030, 2040 and 2050 (open duty recorded in the D18... | adopted | YAML, Task 13-1 | curtailmit.results_writer (build_final_results, write_final_results, FinalResultsRow supe... |
| D30 | Hydrogen SEC treatment: scoped extension of the D28 principle (energy-side range kept separate from a fixed p... | adopted | YAML, Task 13-2 | commits 57d9488 and cb58ba4 (Task 13): results_writer.build_final_results (h2_potential q... |
| D31 | Scope of 'end to end' for the orchestration command (Task 14) | adopted | YAML, Task 14-1 | curtailmit.pipeline (orchestrator: Stage 1 -> hourly calibration -> Option E projection -... |
| D32 | CI test isolation: a default test depends on the local database | adopted | YAML, Task 14-1 | tests/test_analysis_task11e5.py::test_compounding_never_exceeds_the_asymptote (synthetic... |
| D33 | Data-availability promise of the project (curtailmit_database is local-only) | adopted | YAML, Task 15-1 | data_snapshot_manifest.json |
| D34 | Task 15 scope split, environment lock mechanism, handling of D1-D12 in the YAML | adopted | YAML, Task 15-1 | tests/test_determinism.py |
| D35 | Acceptance criterion 5 (2020 historical anchor, source historical_ons) is superseded by the Task 11E2 backtes... | adopted | YAML, Task 15-3 | docs/acceptance_criteria_status.md (criterion 5 restated as superseded by D35) |
| D36 | Boundary geometry source and vintage for the context maps (C1) | adopted | YAML, Task 17-1 | src/curtailmit/spatial.py |
| D37 | Rule for spatially disaggregating the national Option E projection (projected regional risk map, Map 2) | pending | YAML, Task 17-1 | - |

37 decisions: 36 adopted, 1 pending.

**Numbering note.** `D27` in older documents (Task 11E4, `docs/task11e4_findings.md`) denotes the sub-hourly feasibility candidate of Task 11E4 (negative result, never adopted); it is written `D27-candidate` there and is NOT the adopted `D27` of this table.

<!-- GENERATED:END id=decision-register -->

## 8. Verification

- `tests/fixtures/final_results/reference_totals.json` (60 totals, rtol 1e-9) is checked on every `curtailmit-run`.
- `pytest` (default `-m "not integration"`): unit suite with synthetic and committed fixtures; runs in CI with an empty `DATABASE_ROOT`. `pytest -m integration` needs the local database (and, for a few tests, the network); it includes the real-pipeline determinism comparison (`tests/test_determinism.py`).
- Re-baselining on purpose (for example after advancing `END_EXCLUSIVE`): run `analysis/task14_extract_reference.py` on the validated output and commit the new `reference_totals.json` as an explicit, documented decision. Never edit it to make a run pass.

## 9. Run manifest

`logs/run_manifest_<UTC>.json` is written only by runs that end in `SUCCESS` or `SUCCESS_PARTIAL` (a failed run leaves only `pipeline_run_<UTC>.json`). Fields: `status`, `partial`, `run_started_utc`; `code` (git commit, dirty flag, branch); `environment` (Python, platform, lock-file hash, every locked package with `locked` and `installed` version, `environment_matches_lock`, `mismatches`); `end_exclusive`; `config_sha256`; `decisions_sha256` (the adopted decisions the stages depend on); `stages` (status and reason of each); `reference_check`; `raw_inputs` (every raw file with source URL, retrieval time, SHA-256, size - each verified against the file's own retrieval manifest when the manifest is written - plus a comparison with the committed `data_snapshot_manifest.json`); `artifacts_sha256` (stage products and final tables). A raw file with no retrieval manifest, or whose bytes differ from it, stops the run (exit code 2): its provenance cannot be stated. A run outside the lock is valid but shows `environment_matches_lock: false`.
