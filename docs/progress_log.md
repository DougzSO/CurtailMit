# CurtailMit — Progress Log

A chronological, append-only record of what has been completed, decided,
and discovered. This is a working log, not a source-of-truth spec — for
the authoritative methodology and task list, see `docs/methodology.md`,
`docs/roadmap.md`, and `docs/claude_commands.md`.

---

## Phase 0 — Project setup

- Repositories created: `curtailmit` (public, GitHub) and
  `curtailmit_database` (local only, sibling directory, never pushed).
- `docs/roadmap.md` and `docs/methodology.md` finalized (v3.1 FINAL),
  encoding decisions D1-D11.
- Full directory scaffolding generated via PowerShell for both repos.
- `config/scenarios.yaml` populated with final PTE/EPE Table 2 data
  (TB/TA/TG scenarios x 2025/2030/2040/2050).
- `config/paths.yaml`, `.gitignore`, `.env.example`, `LICENSE`, `README.md`,
  `Makefile`, `requirements.txt`, `pyproject.toml` created.
- Initial scaffolds: `schemas.py`, `ons_client.py`, `data_ingestion.py`,
  `test_schemas.py`, `test_ons_client.py`. `pytest -v` passed (2 passed).
- `git init` on both repos; venv created.

## Phase 1 — Pre-build via terminal (reducing Claude Code token spend)

Rationale: anything that is pure mechanical infrastructure, generic math
already fully specified in the methodology, or simple scaffolding was
built directly via terminal/local work instead of delegated to Claude
Code, to save tokens for genuinely novel/ambiguous work (API discovery,
schema reconciliation, orchestration logic).

Pre-built and committed:
- `src/curtailmit/schemas.py` — full rewrite, all Pydantic v2 models for
  the pipeline (RetrievalManifest, CoverageInfo, Baseline2020Generation,
  DataQualityReport, CalibrationParams, ProjectionRow, MitigationRow,
  HydrogenRow, plus original scenario/config models).
- `src/curtailmit/paths.py` — DATABASE_ROOT resolution + directory helpers.
- `src/curtailmit/acquisition.py` — `fetch_and_cache()` + manifest sidecar
  pattern (retrieval manifests for reproducibility).
- `src/curtailmit/manual_ingestion.py` — isolated manual-download fallback
  path with `ManualIngestionRequired` exception.
- `src/curtailmit/calibration.py` — generic logistic curtailment function
  fitting machinery (`fit_calibration`, `apply_calibration`,
  `validate_against_holdout`, save/load). Math complete; not yet wired to
  real historical ONS data.
- `src/curtailmit/mitigation.py` — `compute_mitigation()` COMPLETE,
  average vs marginal factor handling, classification-aware.
- `src/curtailmit/hydrogen.py` — `compute_hydrogen_potential()` COMPLETE,
  SEC range (50/52.5/55 kWh/kg) enforced via Pydantic validator.
- Test suite additions: test_calibration.py, test_mitigation.py,
  test_hydrogen.py, test_manual_ingestion.py, test_acquisition.py,
  test_paths.py.
- `scripts/discovery_probe.py` and `scripts/discovery_probe_2.py` —
  exploratory, non-pipeline scripts to probe real APIs/pages using the
  developer's own internet connection, avoiding blind trial-and-error by
  Claude Code.
- CI/tooling: `.github/workflows/ci.yml`, `Makefile` (`discover` target),
  `requirements.txt` additions (beautifulsoup4, lxml, pyarrow, responses),
  `pyproject.toml` pytest `integration` marker config.

**Bug encountered and fixed**: `pyproject.toml` was written with a UTF-8
BOM via PowerShell's `Set-Content -Encoding UTF8`, which Python's TOML
parser cannot read ("Invalid statement at line 1, column 1"). Fixed by
rewriting the file via `[System.IO.File]::WriteAllText(...)` with an
explicit no-BOM `UTF8Encoding`. Lesson: always use this method for TOML
files going forward, never `Set-Content -Encoding UTF8`.

**Test status**: 21/21 passing (`pytest -v -m "not integration"`) after
`pip install -e .` (package must be installed in editable mode — this
was missing initially and caused `ModuleNotFoundError: No module named
'curtailmit'`).

**GitHub**: repo created at `https://github.com/DougzSO/CurtailMit`,
remote added, pushed successfully.

## Phase 2 — Real data source discovery (via local internet, not Claude Code)

### Round 1 (`discovery_probe.py`)

- **ONS wind curtailment**: CONFIRMED, `restricao_coff_eolica_usi`
  (already known), 185 resources, monthly CSV/XLSX/PARQUET.
- **ONS solar curtailment**: CONFIRMED via `package_search`,
  `restricao_coff_fotovoltaica`. Mirrors wind package structure.
- **ONS generation-by-source**: NOT resolved to a single package.
  Narrowed to two candidates: `geracao-usina-2` (per-plant hourly) and
  `balanco-energia-subsistema` (subsystem balance).
- **ANEEL**: CONFIRMED CKAN-based and reachable (`package_search`
  'geracao' returned 10 results). Secondary/fallback role only.
- **CCEE**: HTTP 403 "Acesso bloqueado" on both `package_list` and root
  URL, with default `requests` headers. Inconclusive — could be a simple
  User-Agent block.
- **MCTI**: SIRENE landing page reachable (HTTP 200), contains "fator" 7
  times in a naive substring search, but no `.xls/.xlsx/.csv` found.
  Guessed sub-paths returned 404.

### Round 2 (`discovery_probe_2.py`)

- **MCTI**: Proper `<a href>` extraction (BeautifulSoup) on the SIRENE
  page (609 total links) surfaced two strong real candidates:
    1. `.../sirene/dados-e-ferramentas/fatores-de-emissao`
       ("Fatores de emissão MDL/SIN") — primary candidate.
    2. `.../acompanhe-o-mcti/cgcl/#fatores`
       ("Fatores de emissão de CO2") — secondary/older candidate.
  Neither has been opened yet; next step is extracting actual file links
  from these two specific pages.
- **CCEE**: Retried with realistic browser `User-Agent` and
  `Accept-Language` headers. Still HTTP 403 "Acesso bloqueado" on both
  URLs. **Conclusion: CDN/WAF-level block, not a header issue. Closed as
  a permanent limitation** — no further automated probing planned.
  `pld.enabled: false` remains the permanent default.

All findings logged in `config/discovered_sources.yaml`, which is the
running source of truth for package/resource IDs until formally merged
into `config/scenarios.yaml`.

## Open items / next steps

1. Claude Code Task 2 (enriched): wire up ONS wind + solar curtailment
   acquisition using the two confirmed package IDs above.
2. Claude Code Task 3 (narrowed): inspect schemas of `geracao-usina-2`
   and `balanco-energia-subsistema` via `package_show` + one sample
   resource before writing acquisition code.
3. Claude Code Task 5 (narrowed): fetch the two MCTI candidate pages
   above, extract real downloadable file links, report back before
   writing acquisition code. If no usable file link is found, stop and
   report rather than guessing further.
4. Claude Code Task 6: ANEEL fallback module (confirmed CKAN-reachable,
   low risk).
5. Claude Code Task 7 (closed/reduced): CCEE is a documented, permanent
   limitation. Build only the minimal `pld.enabled: false` stub and a
   `docs/limitations.md` note; do not attempt further automated access.
6. Still fully pending (no pre-build possible, requires live decisions):
   Task 4 (classification mapping), Task 8 (DataQualityReport
   finalization), Task 10 (`projection.py`), Task 13 (`results_writer.py`),
   Task 14 (orchestration), Task 15 (reproducibility pass).
7. Content gaps in `config/scenarios.yaml` (not structural, just data
   entry): `validation_data` block (2026-2029 ONS/EPE prospection table),
   `primary_energy_crosscheck` 6-point grid, LICENSE copyright name/year.

---

## Task 11D (2026-10) - regional recalibration, time confound, pooled panel, documentation realignment

- Investigation / prototype only; no `src/` change; D13-D22 untouched; D23, D24, D25 recorded as `pending`.
- Added `analysis/task11d_regional_recalibration.py`, `task11d_time_confound.py`, `task11d_pooled_panel.py` and `docs/task11d_findings.md`.
- Findings (preliminary): no regional wind/solar in the PTE sources (labelled constant-share proxy); Northeast wind logistic L = 0.25, P0 = 76 (weakly identified) gives 2050 wind curtailment 79-129 TWh instead of 322-568; in the Northeast time explains 73 % of the
  variance of C_wind and P_NE adds 0.5 points; pooled plausibility band 5.6-10.2 % at P = 44-78 %; solar has no regional sample, so totals remain implausible.
- Documentation realigned (roadmap, methodology 2.3b, claude_commands transition note and 1.11D entry, task table, discovered_sources). Task 13 blocked.

---

## Task 11E (2026-10) - intra-day solar, wind asymptote envelope, transmission-capacity test

- Investigation / prototype only; no `src/` change; D13-D22 untouched; D23, D24, D25 `pending`; D26 not registered (criterion not met).
- Added `analysis/task11e_*.py`, `docs/task11e_findings.md`, `docs/ons_transmission_data_sources.md`; new ONS data under `raw/ons/interchange/` (lines, transformers, pairwise interchange).
- Findings (preliminary): midday VRE share of load explains monthly solar curtailment (R2 0.78 vs 0.40); the hourly SIN-wide VRE share of load is a stable dose-response driver for wind and solar and reproduces most of the monthly time effect; wind L not identifiable (envelope); capacity stocks collinear with time, NE export not saturated in most curtailed hours.
- Documentation realigned (roadmap, methodology 2.3c, claude_commands 1.11E and task table, discovered_sources). Production migration renumbered 11F. Task 13 blocked.

## Task 11E2 (2026-10) - validation and unification of the hourly dose-response model

- Investigation / prototype only; no `src/` change; no new data; D13-D22 untouched; D23, D24, D25 and the new D26 `pending`.
- Added `analysis/task11e2_*.py`, `tests/test_analysis_task11e2.py`, `docs/task11e2_findings.md`.
- Findings (preliminary): the projected hourly conditions are in-sample for 2030, mostly for 2040, not for 2050; the wind backtest beats the national-P, time-trend and Task 11D regional benchmarks out of sample (-11 to -19 percent on 2025 vs -22 to -45 percent); the curve is stable across years but not across seasons or hours of day, and wind drifts about +2 pp per year; wind follows the solar curve family and one unified curve gives the same totals; NE curtailment is increasingly an energy-balance phenomenon and interchange-related constraints are a minority (D26 candidate: retire the PDE / PET extension).
- Documentation realigned (roadmap, methodology 2.3d, claude_commands 1.11E2 and task table, discovered_sources D23-D26). Task 11F and Task 13 blocked.

## Task 11E3 (2026-10) - extrapolation-distance calibration and decision closure

- Investigation / prototype only; no `src/` change; no new data; D13-D22 untouched; D23, D24, D25, D26 `pending`. Task 11E2 committed first as `a2f2ea7`.
- Added `analysis/task11e3_*.py`, `tests/test_analysis_task11e3.py`, `docs/task11e3_findings.md`; `statsmodels` declared in `pyproject.toml` and `requirements.txt` (the 11E2 / 11E3 scripts run in `.venv`).
- Findings (preliminary): error does not grow with extrapolation distance in a calibratable way (R2 0.03-0.07; lead-time drift dominates); credibility rule failed; 2050 stays a flexibility-conditional range; 2030 / 2040 reported with an empirical annual-backtest band. Consolidated recommendation: D24 = E by horizon, D25 closed with the stated sentence, D26 retire. Task 11F and Task 13 blocked.
- Known unrelated issue: `tests/test_ons_solar_gap.py::test_schema_findings_reports_type_change_and_missing_columns` fails in `.venv` (pandas 3 / pyarrow `large_string`), passes with the system Python.

## Task 11E4 (2026-10) - coverage figure, NE-hourly, sub-hourly feasibility, conformal prediction

- Investigation / prototype only; no `src/` change; D13-D22 untouched; D23, D24, D25, D26 `pending`; D27 not registered (negative sub-hourly result). New data: 2025 verified-load sample (30-minute, 37 MB).
- Added `analysis/task11e4_*.py`, `tests/test_analysis_task11e4.py`, `docs/task11e4_findings.md`, `docs/ons_subhourly_data_sources.md`, the figure `fig_insample_coverage.*`.
- Findings (preliminary): NE-hourly does not extend the support; 30-minute r has the same extremes as the hourly one; conformal intervals are finite but wide for 2030-2040 and cannot be certified for 2050 (exchangeability violated). 2050 stays conditional. Recommendation unchanged in substance (D24 = E by horizon, D25 closed, D26 retire); Task 11F and Task 13 blocked.

## Task 11F0 (2026-10) - formal adoption of D23, D24, D26

- Decision locking only: `config/discovered_sources.yaml` D23, D24, D26 `adopted` (specifications recorded in full, `implemented_in` populated); D25 `pending` (Task 11E5). No new analysis, no code under `src/` or `analysis/`.
- Documentation (append-only): roadmap update (the PDE / PET extension is retired, not deferred), methodology 2.3g, claude_commands 1.11F0 and task table.
- Task 11F is unblocked in principle but waits for D25; Task 13 blocked.

## Task 11E5 (2026-10) - residual wind drift of option E; D25 recommendation

- Investigation / prototype only; no `src/` change; no new data; D25 `pending` (recommendation only). Added `analysis/task11e5_*.py`, `tests/test_analysis_task11e5.py`, `docs/task11e5_findings.md`.
- Findings (preliminary): drift +1.4-1.6 pp per year, better described as a step at 2025-01; vintage and state composition rejected; bounded by the asymptote at 2050; trend term not safe. Recommendation: accept as quantified limitation. Task 11F awaits the D25 decision and your confirmation; Task 13 blocked.

## Task 11F-0 (2026-10) - D25 adopted

- `config/discovered_sources.yaml`: D25 `adopted` (text verbatim from the Task 11E5 recommendation); D23-D26 all adopted. Documentation only; no `src/` change. Next: design proposal `docs/task11f_design.md` (11F-1), awaiting approval.

## Task 11F (2026-10) - option E in production

- `src/` migration complete (hourly_model, hourly_uncertainty, limitations, projection.project_curtailment_hourly, labelled references, mitigation guard); regression against the validated prototypes to 1e-9; D25 propagated as `known_limitations`; consolidated methods text in docs/methodology.md 2.3j. Task 13 unblocked, awaiting confirmation.

## Task 13_pre (2026-10) - pandas 3 dtype test fix

- Test-only: `tests/test_ons_solar_gap.py` treats `large_string` and `string` as the same logical type. No `src/` change. Commit `6362db0`.

## Task 13-1 (2026-10) - design of the final output layer

- Design only: `docs/task13_design.md`. Legacy `results_writer.py` investigated (unused, never produced output, structural conflict with the new schema). Pending decisions D27, D28, D29 registered in `config/discovered_sources.yaml`. No `src/` or test change; Task 13 not started.

## Task 13 (2026-10) - final results layer

- `config/discovered_sources.yaml`: D27, D28, D29 adopted. `src/curtailmit/results_writer.py` extended (legacy `ResultsRow` kept, DEPRECATED); `mitigation.py` gains `ModelProvenanceError`, `check_provenance`, `split_margins` (OM and CM families); `tests/test_final_results.py` (21 default tests + 1 integration), `tests/test_projection_hourly.py` guard test updated. Outputs written to DATABASE_ROOT/outputs/tables (`final_results.*`, `final_results_mcti_sensitivity.*`). Docs: methodology 2.3k, data dictionary, roadmap, claude_commands (D27 supersession note). No figures, no matplotlib.

## Task 13-2 (2026-10) - closeout

- Documentation, visibility and decision registration only; no computed value changed. `central_inside_range` confirmed as a first-class column of `final_results`; methodology 2.3k addenda (wind 2025-2040 effect, D30); D30 adopted (hydrogen SEC, scoped extension of D28); data dictionary notes. Task 13_pre confirmed already done (commit `6362db0`), test passing.
