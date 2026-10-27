# Orchestration and staleness logic (Task 14; decisions D31, D32)

Design: `docs/task14_design.md` (commit `e1287eb`). Implementation: `src/curtailmit/pipeline.py` (orchestrator) and `src/curtailmit/provenance.py` (stamps). Entry points: `curtailmit-run` (console script), `python -m curtailmit.pipeline`, `scripts/run_pipeline.py` (three-line shim; `make run`).

## What the command runs (D31)

<!-- GENERATED:BEGIN id=pipeline-sequence sources=pipeline.py
     do not edit by hand; regenerate with: python -m curtailmit.doc_generation --write -->

`pre-check -> Stage 1 -> hourly calibration -> Option E projection -> final results -> reference-value check -> run manifest -> summary`

(Generated from `curtailmit.pipeline.PIPELINE_SEQUENCE`; each stage is skipped only when its stamp verifies.)

<!-- GENERATED:END id=pipeline-sequence -->

*Task 16 update: the sequence above is generated from `pipeline.PIPELINE_SEQUENCE`; the hand-typed line it replaced ended at "reference-value check -> summary" and omitted the run-manifest step (added in Task 15).*

Out of scope: analysis and reference scripts (the retired national/regional calibration is never imported or called by the orchestrator; a test scans `pipeline.py` and the production-path functions for it), PLD (D10: `pld.enabled: true` is an error, not a silent skip), figures (Task 13B), ~~the reproducibility manifest (Task 15)~~ (Task 16 update: the run manifest is part of the run, see the sequence above).

The database root comes from `curtailmit.paths` (`--database-root` > `DATABASE_ROOT` > `.env` > `../curtailmit_database`, resolved against the project root) and is printed at the start. `--dry-run` resolves everything without creating directories.

## Skip logic: a stage is reused only if its stamp verifies

After each stage runs, the orchestrator writes `processed/pipeline_stamps/<stage>.json` with SHA-256 of: the input files, the adopted decision entries the stage depends on (`config/discovered_sources.yaml`), the source files of the modules involved (newline-normalised; any edit, even a comment, invalidates), the stage parameters, and the produced artifacts. Next run, the decision is evaluated just before the stage (so it sees what upstream stages just wrote). **Default when in doubt: re-run.** No stamp, unreadable stamp, any changed item, a missing or modified output -> `RAN`.

| Stage | Inputs fingerprinted | Decisions | Outputs verified |
|---|---|---|---|
| Stage 1 | every file under `raw/` (data + retrieval manifests), `config/*.yaml`, Stage 1 modules | D14 D15 D17 D18 D20 D22 | classification flag, MCTI factor tables, penetration monthly, classified curtailment, quality report |
| Hourly calibration | `raw/ons/{generation_by_source,capacity_factor,curtailment_wind,curtailment_solar}/*.parquet` | D24 D25 | 4 curve JSON, base profile, horizon bands |
| Option E projection | the calibration outputs, `scenarios.yaml` | D24 D25 D26 | `pte_curtailment_option_E.parquet` + limitations sidecar |
| Final results | option E table + sidecar, MCTI factor tables, classification flag, `scenarios.yaml` | D18 D23 D24 D25 D27-D30 | `final_results.{csv,parquet,limitations.json}`, sensitivity companion |

Stage 1 special case (documented gap closed in this task): its inputs are remote, and freshness cannot be verified offline, so **without `--use-cache` Stage 1 is always re-run**; with `--use-cache` it is skipped only if its stamp verifies. The pre-existing `acquisition.fetch_and_cache(use_cache=True)` trusted a cached file merely because it and its manifest existed; it now re-verifies SHA-256 and size against the manifest and fetches again on any mismatch (all 250 raw files of the local database verified).

The hourly panel cache in `interim/` is never reused by the orchestrator (`load_sin_panel(refresh=True)` when the calibration stage runs).

## Console and run record

Every stage prints `SKIPPED (cached, <reason>)` or `RAN (missing | stale | forced: <reason>)`; the same lines are stored in `logs/pipeline_run_<UTC>.json` together with the pre-check, the reference check, the output paths and, on failure, `{stage, error_type, reason, gate, diagnostics}`.

Flags: `--force-stage1 --force-calibration --force-projection --force-results --force-all`, `--use-cache`, `--skip-stage1` (explicit **partial** run: Stage 1 products must exist; the summary says `SUCCESS_PARTIAL` and whether the products were verified by a stamp; cannot be combined with `--force-stage1/--force-all`), `--dry-run`, `--database-root`. No flag disables a gate or changes the model.

## Gates and exit codes

Exit code 2: `Stage1Error`, `LimitationError` (D25 not adopted), `ModelProvenanceError`, `SupportStatusConflictError`, `FinalResultsError`, `ReferenceMismatchError`. Exit code 1: any other exception (`PipelineError`: PLD enabled, missing products, a stage that did not write its outputs, ...). Nothing is caught and continued.

## Reference-value check (safety net)

After the final results, always (also when every stage was skipped): `final_results.parquet` is compared with `tests/fixtures/final_results/reference_totals.json` (156 rows; central value of the 60 `total` rows; relative tolerance 1e-9), generated by `analysis/task14_extract_reference.py` from the validated Task 13 output (curtailed energy equals Task 11F: TB 43.8 / 64.3 / 127.6 / 354.8 TWh, TA 2040 242.4, TA 2050 536.1, TG 2040 181.4, 2050 333.9). A change in any of them is a conscious re-baseline, never automatic.

## CI

`.github/workflows/ci.yml`: `lint` (`ruff check src tests`), `unit-tests` (`pytest -m "not integration"`, `DATABASE_ROOT` an empty directory), `smoke-test` (`curtailmit-run --dry-run` and `python -m curtailmit.pipeline --dry-run`), Python 3.11. Integration tests are excluded because they need the local `curtailmit_database`; CI does not validate the scientific output. D32: the one default test that read the local database (`test_compounding_never_exceeds_the_asymptote`) now uses a synthetic table.

## Changelog: cache trust semantics changed during Task 14

Found while investigating the orchestrator's skip logic (Task 14), not a planned Task 14 goal: `acquisition.fetch_and_cache(use_cache=True)` used to trust a cached file whenever it existed next to its manifest. It now verifies the file's SHA-256 and byte size against the manifest before trusting it, and a mismatch (or a missing manifest) triggers a fresh download. This affects every Stage 1 acquisition made with `--use-cache` (commit `a6093c8`); earlier Stage 1 runs with `use_cache=True` relied on existence only. At the time of the change all 250 raw files of the local database verified against their manifests.

## Hash pre-filter for large files (Task 16)

`curtailmit-run` hashes the large data files that enter the stamps (the raw tree, the processed products) through a cache, `processed/pipeline_stamps/hash_cache.json` (`curtailmit.hash_cache`; design: `docs/task16_design.md` part B). **The content hash stays authoritative: a stage is skipped only when the hashes in its stamp equal the hashes of the files now.** The cache only decides whether a file has to be read again to get its hash: a recorded hash is reused when the file has the same size, `mtime_ns` and inode as when it was hashed, is at least 1 MiB, had been quiet for 5 s when it was hashed (racy guard) and does not carry a modification time in the future; in every other case the file is read and hashed in full. Code, configuration, decision entries and files under 1 MiB are always hashed in full, the stamp format is unchanged (deleting the cache is always safe), and the run manifest keeps hashing the raw files in full.

Measured on the real raw tree (500 files, 509 MB): 16.75 s cold, 1.21 s with the operating-system cache warm, 0.05 s for the metadata alone, so the gain is small on a warm cache and real on a cold disk.

**Residual risk.** Content that changes while size, `mtime_ns` and inode stay equal to the recorded values keeps its stale hash (the weakness of every metadata quick-check, such as git's index or rsync's default). It protects against accidental staleness (edits, replaced or restored files, partial writes), not against forged timestamps. `curtailmit-run --no-hash-cache` hashes everything in full and neither reads nor writes the cache: use it on network shares (clock differences can defeat the guard) and for the run that produces the numbers submitted for publication. The accepted risk is a named test, `tests/test_hash_cache.py::test_forged_metadata_is_the_documented_residual_risk`.

## Maintenance watchpoints

- **`END_EXCLUSIVE` in `src/curtailmit/hourly_model.py` (currently `"2026-10-01"`).** The hourly panel excludes everything from this date on because October 2026 is incomplete in the raw files; the value is intentionally fixed (Task 14-3) until the user explicitly decides to advance it. Newer months downloaded by Stage 1 do not enter the model while the cutoff stays put (verified in the Task 14-2 live run: new October data, `final_results` byte-identical). Advancing the cutoff changes the calibration and every downstream total, and **the reference-value check is expected to fail with exit code 2** (`ReferenceMismatchError`, failure record in `logs/pipeline_run_*.json`). That failure is correct behavior, not a bug: it requires an explicit user decision before `tests/fixtures/final_results/reference_totals.json` is regenerated (`analysis/task14_extract_reference.py`), because numbers in article drafts would shift. See "Gates and exit codes" and "Reference-value check" above.
- Editing `hourly_model.py` (even this comment) changes the code fingerprint, so the next run recalculates calibration, projection and results once; the outputs are deterministic and the reference check confirms they are unchanged.

## Reproducibility records (Task 15)

After the reference-value check, a run that ends in `SUCCESS` or `SUCCESS_PARTIAL` writes `logs/run_manifest_<UTC>.json` (`curtailmit.run_manifest`): git commit, locked vs installed package versions, `END_EXCLUSIVE`, configuration and decision hashes, every raw input file verified against its own retrieval manifest and compared with the committed `data_snapshot_manifest.json`, and the hashes of the produced artifacts. A raw file without a retrieval manifest, or whose bytes differ from it, raises `RunManifestError`, a hard gate (exit code 2, stage `run-manifest` in the failure record). Failed runs write only `pipeline_run_<UTC>.json`. `--dry-run` writes neither. See `docs/reproducibility.md` for the full procedure, the pinned environment (`requirements.lock.txt`, CI job `unit-tests-locked`) and the determinism guarantee (`tests/test_determinism.py`).

## Corrected defect: the Makefile (Task 15-3)

**Makefile targets were non-functional (missing TAB indentation) until Task 15-2; prior references to `make run` in documentation describe intended, not verified, behavior up to that point.** Facts established in Task 15-3: the Makefile was committed on 2026-10-19 (`cb803d5`, again in `dbf547b`) and every revision up to Task 15-2 had recipe lines without the TAB that make requires, so GNU make rejects such a file ("missing separator") before running any target: `make setup`, `make run`, `make stage1`, `make test`, `make lint` and `make discover` could not have succeeded from the repository as committed. No log, progress note or commit in the repository records a successful `make` run, and `make` is not installed on the development machine. The statements that `make run` calls `scripts/run_pipeline.py` (`docs/task14_design.md`, the docstring of `scripts/run_pipeline.py`, the Task 14 text) described the intended wiring; the supported, verified entry points are `curtailmit-run` and `python -m curtailmit.pipeline`. Task 15-2 added the TABs and the `setup-locked` target; the new Makefile still has not been executed with `make` (a test checks its structure only), so run `make setup-locked` once on a machine that has make before relying on it. This is a factual correction; nothing else changed.
