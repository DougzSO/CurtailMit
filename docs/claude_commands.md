# CurtailMit — Claude Code Build Commands — v2.0

> Source of truth for everything in this document: `docs/roadmap.md` and
> `docs/methodology.md`. If anything here conflicts with those two files, the two
> files win — update this document, not the other way around.
> Full discovery provenance (every confirmed package_id, URL, decision D1-D14):
> `config/discovered_sources.yaml` and `config/acquisition_targets.yaml`.
> Chronology of how we got here: `docs/progress_log.md`.

## 0. How to use this document

- This is not one giant prompt. It is a **sequence of discrete tasks**, numbered.
- Paste **one task at a time** into Claude Code, let it finish, review the diff,
  run tests, commit, and only then move to the next task.
- Every task assumes Claude Code has read access to the full repository
  (`curtailmit/`) and should **start by reading `docs/roadmap.md` and
  `docs/methodology.md`** before writing any code.
- Never paste a task out of order — later tasks assume earlier ones are merged.
- **Section 1** (completed work) is for context only — do not paste it as a task.
  **Section 2** (remaining tasks) is what actually gets pasted, in order.

---

## 1. COMPLETED WORK — SUMMARY (context only, do not rebuild)

A significant portion of this project was pre-built locally (pure math/config/
validation logic, zero open methodological questions) to reduce Claude Code's
token usage, plus real Claude Code sessions (Tasks 2, 2B, 3, 4, 5, 6) that did live
API discovery and acquisition. Full test suite currently: **249 passed, 0 failed**
(`pytest -v -m "not integration"`).

### 1.1 Shared infrastructure (pre-built, tested)

| Module | Status | What it does |
|---|---|---|
| `acquisition.py` | ✅ | `fetch_and_cache()` — download + cache + manifest sidecar. |
| `manifest.py` | ✅ | `write_manifest()`, `load_manifest()`, `compute_sha256()`. Used internally by `acquisition.py`. |
| `paths.py` | ✅ | `get_database_root()`, `get_raw_dir()` — reads `.env` + `config/paths.yaml`. |
| `validation.py` | ✅ | Acceptance-criteria logic: `validate_penetration_ceiling()`, `resolve_ons_min_coverage()` (per-package coverage floors), `validate_mcti_factor_coverage()`, `ClassificationFlag`/`attach_classification_flag()`/`validate_classification_propagation()` (DEB/REB/EUB propagation rules). **Reuse this in Tasks 4 and 8 — do not rewrite classification/coverage logic.** |
| `emission_factors.py` | ✅ | `derive_annual_om_from_monthly()` (mean of 12 monthly OM values), `compute_combined_margin()` (CM = 0.5×OM + 0.5×BM, decision D12). **Reuse directly in Task 5.** |
| `calibration.py` | ✅ (generic logic only) | Logistic-fit machinery: `fit_calibration`, `apply_calibration`, `validate_against_holdout`, save/load. **Not yet wired to real data — Task 3's output now exists; the PTE/ONS basis question is settled in 1.3b (D16).** |
| `projection.py` | ✅ | P(s,t) interpolation, headline-table/anchor-point logic, enforces 2020 = `historical_ons` only. |
| `mitigation.py` | ✅ (partial) | `compute_mitigation()` works but currently emits only ONE marginal column (`om_factor`). **Needs enrichment to emit both OM and CM columns — folded into Task 13 below.** |
| `hydrogen.py` | ✅ | `compute_hydrogen_potential()` — SEC range 50/52.5/55 kWh/kg, min/central/max always reported together. |
| `results_writer.py` | ✅ | Final `ResultsRow` schema — already includes the OM/CM split (`mitigation_deficit_marginal_om_tco2`, `mitigation_deficit_marginal_cm_tco2`) and all provenance flags (`source`, `is_interpolated`, `classification_available`). CSV/JSON read-write. **This is the target schema Task 13 must populate — do not change it.** |
| `pld.py` | ✅ | CCEE PLD module stub. `pld.enabled: false` enforced by design (see 1.3). |
| `schemas.py` | ✅ | Extended with `RetrievalManifest`, `Baseline2020Generation`, `DataQualityReport`, `CalibrationParams`, `ProjectionRow`, `MitigationRow`, `HydrogenRow`. **`DataQualityReport` already exists — reuse/extend in Task 8, don't recreate.** |
| `config/acquisition_targets.yaml` | ✅ | Consolidated, machine-readable config of every confirmed source fact (package_ids, schemas, URLs, classification mapping, coverage floors). Read this before any discovery work. |
| `docs/data_dictionary.md` | ✅ | Documents every final output column (unit, type, computed vs. sourced). |

### 1.2 ONS curtailment acquisition (Tasks 1, 2, 2B) — DONE

- Wind curtailment: package `restricao_coff_eolica_usi`, confirmed live, data from **2021-10**.
- Solar curtailment: package `restricao_coff_fotovoltaica`, confirmed live, data from **2024-04-01**.
- `data_ingestion.py` discovers both via `package_show()` at runtime (defensive re-confirmation, falls back to `package_search()` if a package_id ever goes stale), downloads via `fetch_and_cache()`, parses to `[date, usina, curtailed_energy_mwh, reason_category, source]`, writes `interim/ons_curtailment_raw.parquet`.
- **Coverage floors are per-package**, not global: wind requires ≥2022-01, solar requires ≥2024-04 (`validation.resolve_ons_min_coverage()`, config-driven). Raises `ValidationError`/`CoverageError` explicitly if a floor is missing or unmet.
- **D13**: curtailment energy sourced from `val_geracaonaorealizadaapurada` (ONS's own ascertained figure), not derived via reference-minus-realized subtraction (reference column mostly empty); verified equivalent on 2022-01 sample.
- **D14**: ANEEL probed (13 queries, 20 packages inspected) — no solar curtailment series exists there; nothing improves on ONS's 2024-04 floor. The 2020 baseline's solar curtailment is therefore a **documented zero, not a measurement** — flagged in the data-quality report (`solar_curtailment_2020_baseline: documented_zero_not_measured`), never silently assumed. SIGA capacity figures (2019: 2.5GW → 2024: 17.2GW, centralized/SIGA only, excludes MMGD) recorded as corroborating context only, not proof.
- Raw reason codes (`CNF`, `REL`, etc.) are stored as-is in `reason_category` — the DEB/REB/EUB mapping is applied by Task 4 (see 1.3c).
- 128→132 tests added across this work; one `@pytest.mark.integration` test confirmed live against real ONS (both packages resolve, no fallback triggered).
- Commits: `f32eac5` (Task 2), `d7b267e` (Task 2B), `bc5a0bb` (docs).

### 1.3 CCEE PLD (Task 7) — DONE, permanently closed

CCEE (`dadosabertos.ccee.org.br`) returns HTTP 403 (WAF-level block) on every probe, including with browser headers — confirmed twice, **do not re-probe**. `pld.py` stub built, tested, `pld.enabled: false` enforced. This is a closed limitation, not an open task.

### 1.3b ONS generation-by-source (Task 3) — DONE (commit `3f69554`; closeout D15, D16)

- Module `src/curtailmit/ons_generation.py` (package `balanco-energia-subsistema`, re-confirmed at runtime via `package_show`, `package_search` recovery path, yearly resources PARQUET > CSV > XLSX, `id_subsistema == "SIN"`, hourly MW integrated to MWh). Values are published as decimal *text* and are coerced explicitly. Blank `val_gersolar` -> 0 (documented); a blank in any other source fails explicitly.
- Outputs (under `DATABASE_ROOT`): `interim/ons_generation_by_source.parquet`, `processed/ons_penetration_monthly.parquet`, `processed/ons_penetration_annual.parquet`, `processed/baseline_2020_generation.json` (validated against `schemas.Baseline2020Generation`; requires every hour of 2020).
- **2020 baseline (observed, ONS SIN):** total **554.35 TWh**, wind **54.30 TWh**, solar **5.23 TWh**, wind+solar penetration **10.74 %**.
- **D15**: series usable only from `history_start_year: 2016` (`config/acquisition_targets.yaml`); wind blank 2000-2005 and partly 2006, 2015 has 24 h with no data. Does not affect the 2020 baseline or the 2021+ calibration window.
- **RESOLVED (D16) — PTE vs ONS generation basis:** historical/calibration data stay ONS-SIN-based (`historical_ons`); PTE years are used as published on their own basis (`pte_projection`), deliberately not rescaled (the PTE is the evaluated object). BEN 2021 (~621.2 TWh, ONS SIN ~89 %) only explains why the scopes differ. Remaining sub-questions are optional paper-discussion items, not pipeline blockers. See D16 in `config/discovered_sources.yaml` and `docs/pte_ons_basis_investigation.md` (kept as background).

### 1.3c ONS curtailment classification (Task 4) — DONE (D17)

- Module `src/curtailmit/ons_classification.py`; `data_ingestion.check_classification_availability` now delegates to it (stub replaced).
- Code crosswalk derived at run time from each package's JSON data dictionary (`classification.dictionary_keywords` in `acquisition_targets.yaml`) and mapped by D5: ENE -> DEB, CNF -> REB, REL -> EUB. PAR (documented, never observed) and code-less rows stay unclassified (`deb_reb_eub` null), kept in the aggregate.
- Outputs: `processed/ons_curtailment_classified.parquet` (adds `deb_reb_eub`, `classification_available`) and `processed/classification_available.json` (flag, reason, crosswalk, energy by category).
- Real run (2022-01..2026-10, 15.78M rows): `classification_available = true`; DEB 47.75 TWh, REB 27.81 TWh, EUB 10.35 TWh, 0.0027 % unclassified.
- Unavailable branch (no dictionary / field not described / no D5 match in any source) -> `classification_available = false`, no classified column; undocumented codes raise `ClassificationError`.
- `validation._CLASSIFIED_FIELDS` extended with `deb_reb_eub` so the leak guard covers the new column. Large-file loading is categorical/Arrow based (full file does not fit as object dtype).
- Magnitude sanity check done: curtailed energy matches ONS RT DGL 0189/2025 within ~1 %; the rate depends on the denominator convention (decide before Task 9). See `docs/curtailment_magnitude_sanity_check.md`.

### 1.3d MCTI emission factors (Task 5) — DONE (D18)

- Module `src/curtailmit/mcti_client.py`; `data_ingestion.discover_mcti_factors` now delegates to it (stub replaced); `fetch_and_cache` gained an optional `headers` argument and `manual_ingestion.load_manually_placed_file` an optional `read_kwargs`.
- Scrapes the landing page (BeautifulSoup), selects files by name pattern + year token (current domain beats legacy, ambiguity fails), parses margin workbooks by label (sheet names vary), verifies each download is a real spreadsheet.
- Outputs (`DATABASE_ROOT/processed`): `mcti_average_factor.parquet` (year, month, factor), `mcti_average_factor_annual.parquet` (MCTI-published annual), `mcti_margin_factors.parquet` (year, om, bm, cm + `om_is_derived`/`cm_is_derived`/`bm_is_published` flags, source URL, manual flag).
- Real run: average factor 2006-2025 complete (2026 partial, excluded); margins 2020-2025 (2026 skipped: BM not yet published, 9/12 months). Example: 2025 OM 0.4125, BM 0.0711, CM 0.2418 tCO2/MWh; average 0.0461.
- Required years are in config (`mcti.required_years: [2020, 2025]`); manual-ingestion fallback implemented and tested (declared in the result via `manual_ingestion_used`; Task 8 must surface it in the data-quality report).
- Open for Task 13: factors exist only for completed years, so the 2025+ grid points need an explicit, logged choice of which year's factor applies.

### 1.3e RESOLVED (D20) — curtailment-rate denominator

**RESOLVED by D20 (adopted 2026-10-23, `config/discovered_sources.yaml`):** for the calibration window (2021+) and every curtailment-rate calculation, solar generation is the directly measured ONS-dispatched (centralized) series (`interim/ons_solar_dispatched_monthly.parquet`), not `val_gersolar`, in both the solar term of P(s,t) (numerator and total-generation denominator) and the potential-generation denominator (realized + curtailed) of the solar curtailment rate. Wind and the 2020 baseline are unchanged; raw `val_gersolar` stays in the outputs as `solar_gen_ons_balance_raw_mwh`, diagnostic only. Wired in Task 9 (`ons_generation.py`, `calibration.py`); the recomputed rates are in `docs/task9_calibration_report.md`. The text below is the historical record of the question and the evidence.

*(Original pending text follows.)*

PENDING DECISION FOR TASK 9: our computed curtailment-rate percentages (0.43% / 2.40% / 6.61% / 15.23% for 2022-2025, partial 2026 figure unconfirmed) do not match ONS's own published rates (0.5% / 3.6% / 9.3% for 2022-2024; ~20.7% cited for 2025 via secondary source) despite the absolute MW/GWh curtailment figures matching almost exactly (see `docs/curtailment_magnitude_sanity_check.md`). The discrepancy is attributed to an undetermined difference in the "potential generation" denominator definition used by ONS vs. our computation (realized + curtailed generation). This denominator choice must be made explicitly, and recorded as a decision, before `calibration.py` (Task 9) is implemented — it changes the computed curtailment rate by up to ~25% relative. Reference `docs/curtailment_magnitude_sanity_check.md` for full detail.

**Evidence update (Task 6, still PENDING — nothing decided):** `docs/ons_solar_mmgd_capacity_crosscheck.md` shows ONS solar generation implying a ~21 % capacity factor vs. ANEEL centralized capacity in 2018-2022 but 52-58 % in 2023-2025 (wind shows no break), which suggests the ONS balance solar (and the total) includes estimated MMGD from 2023 (unconfirmed). The COFF curtailment numerator covers centralized plants only, so a centralized-scope denominator would land at ~8.7 % (2024) and ~19.9 % (2025), close to ONS's 9.3 % and ~20.7 %. **Task 6B verification (`docs/ons_solar_mmgd_verification.md`):** the balance dictionary is silent on MMGD, but ONS's `carga-energia` package states MMGD inclusion in load from 29/04/2023 and the balance solar steps up by +2.5 to +3 GWmed on exactly that day while ONS-dispatched (centralized) solar has no step; no decision recorded yet (proposed D20 text in that report). If confirmed, the Task 9 calibration series also has a definitional break in 2023 (solar term and total-generation denominator); the 2020 baseline is unaffected.

**Task 6C measurement (still PENDING - nothing decided):** `docs/ons_solar_mmgd_verification.md` (Task 6C section) measures the monthly gap `val_gersolar` minus ONS-dispatched solar for 2021-01..2026-10: step exactly on 2023-04-29, 2024 gap 45,789 GWh vs the RT's 45,752 GWh, small non-zero baseline (89-197 MWmed) before the step. A candidate D20 is logged in `config/discovered_sources.yaml` as "pending (not adopted)".

### 1.3f ANEEL fallback (Task 6) — DONE (D19)

- Module `src/curtailmit/aneel_client.py` (`fetch_generation_fallback(years, reason, ...)`): standalone fallback, NOT wired into `data_ingestion`/Stage 1 (a test enforces this); the caller must pass the documented ONS failure as `reason`, logged as a WARNING.
- Package discovery by `package_search` (3 candidate queries) with a documented score; every candidate and every rejection is logged and returned in `AneelFallbackChoice`; schema of the downloaded file is verified. Chosen: SIGA plant registry (`siga-sistema-de-informacoes-de-geracao-da-aneel`).
- Limitation (D19): ANEEL has no SIN generation-energy series, so the fallback returns installed capacity (MW) and shares by source, flagged `is_generation_energy = False`; it cannot replace the ONS P(t) without a capacity-factor decision.
- Side finding: ONS solar vs ANEEL capacity suggests MMGD is included in the ONS solar series from 2023 (see 1.3e evidence update).

### 1.3g RESOLVED (D21) — calibration curve identifiability

**RESOLVED by D21 (adopted 2026-10-23, Task 7C), structural part superseded by D22 (Task 7D: two curves, C_wind and C_solar):** `fit_calibration` bounds 0 < L <= 1 (the full-sample fit lands on L = 1.000, k = 0.1688, P0 = 34.8, RMSE 0.0612, unchanged); the 27 wind-only months are kept; `calibration.bootstrap_calibration_ci` quantifies the extrapolation uncertainty (see `docs/task9_calibration_report.md`). **Stage 3 must propagate that uncertainty (requirement below).** Historical record of the question follows.

Logged after Task 9. (Numbered 1.3g because 1.3f is the ANEEL fallback section.)

- The saved logistic fit on the D20 basis (57 monthly points 2022-01..2026-09, P 10.3-29.4 %) has L = 1.254, k = 0.164, P0 = 36.8: L > 1 means curtailment above 100 % at high P, which is physically impossible (C(60 %) = 1.23).
- Constraining L <= 1 does not worsen the in-sample RMSE (0.0612 in both cases): the data do not discriminate between the two, they only constrain the curve below P ~ 30 %.
- Including vs excluding the 27 wind-only months (2022-01..2024-03, no solar curtailment published) changes the extrapolated C(40 %) from 0.71 to 0.42 (L <= 1 bounded fits); the wind+solar-only unbounded fit degenerates (L = 2,236, P0 = 169).
- The PTE scenarios reach P (solar+wind, table values) of 26-29 % in 2025-2030 (inside the observed range) but 36-44 % in 2040 and 47-58 % in 2050, i.e. well outside it (see D21 in `config/discovered_sources.yaml` and `docs/task9_calibration_report.md`).
- **Must be resolved before Stage 3 (PTE scenario projection), not before Task 8.** Open sub-questions: (a) constrain L <= 1 in `fit_calibration`? (b) how to treat the wind-only months (include as-is, downweight, or fit separately from solar months)?

### 1.4 Discovery already resolved for not-yet-implemented tasks

These tasks still need real **implementation**, but discovery is fully closed —
do not re-discover, proceed straight to coding:

- **Task 3 (ONS generation-by-source)** — DONE, see 1.3b. Discovery notes kept for reference: package `balanco-energia-subsistema`, one CSV per year, confirmed schema (`id_subsistema, val_gerhidraulica, val_gertermica, val_gereolica, val_gersolar, val_carga, val_intercambio`). Filter `id_subsistema=="SIN"`. `val_gersolar` NaN/0 pre-2017 = expected, treat as 0. `geracao-usina-2` demoted to optional cross-check only.
- **Task 5 (MCTI emission factors)**: landing page confirmed, file-naming patterns confirmed (inconsistent per-year names, legacy domain for pre-2021), sheet names confirmed (`inventário-todos`, `MDL`, `Publicar`). Full mapping table in Task 5 below.
- **Task 6 (ANEEL fallback)**: CKAN base confirmed reachable. Note: the Task 2B probe already ruled out ANEEL for *curtailment* data specifically (20 packages checked, none are curtailment series — registries/capacity/auctions/tariffs only). Task 6's fallback role should therefore target **generation-by-source** data, not curtailment.

### 1.5 Still fully open (no discovery done yet)

- **Task 8** — Stage 1 finalization / full data-quality report (`DataQualityReport` schema exists, orchestration doesn't).
- **Task 13** — needs rewriting (see below) to reflect that `results_writer.py` already exists with a richer schema than originally scoped; remaining work is wiring `mitigation.py`'s OM/CM split + final assembly + figures/limitations doc.
- **Tasks 14, 15** — untouched.

---

## 2. Global operating rules (paste once, keep in context all session)

```
GLOBAL RULES FOR THIS PROJECT (CurtailMit):

1. Source of truth: docs/roadmap.md and docs/methodology.md. Read both before
   writing code in any task. If a task description below seems to conflict with
   them, follow the docs and flag the conflict to me instead of guessing.

2. API-first, always. The goal is a pipeline that acquires the maximum possible
   amount of data automatically, via public APIs or stable programmatic HTTP
   endpoints (CKAN, REST, direct file URLs discovered programmatically). Manual
   file downloads are the LAST RESORT ONLY, and if ever unavoidable, must be:
   (a) clearly logged as a manual-ingestion limitation in the data-quality report,
   (b) isolated in a clearly named function/module (e.g. `manual_ingestion.py`),
   never silently mixed into the automated path.

3. Never hardcode a resource_id, package_id, or direct file URL without first
   discovering/confirming it programmatically (package_search, package_show,
   HTML parsing of a known landing page, etc.) and logging what was found. If a
   URL must be fixed in config for performance reasons, it must be written there
   by code after a successful discovery run, with a comment showing when and how
   it was confirmed — never typed in from a web browser by a human. (Exception:
   facts already confirmed and logged in config/acquisition_targets.yaml or
   config/discovered_sources.yaml from a prior session — reuse those, but
   defensively re-confirm with package_show()/package_search() at runtime since
   sources can be renamed/retired.)

4. Fail explicitly, never silently. If a data source does not meet a minimum
   coverage/schema requirement, raise a clear, specific exception with a message
   that explains exactly what was expected vs. what was found. No silent
   fallbacks, no "assume zero", no swallowed exceptions.

5. Prefer the most current data available. Every data-acquisition function should
   fetch the latest available data by default (no silently reusing a stale local
   cache unless explicitly requested via a `use_cache=True` flag). However, every
   acquisition must also write a retrieval manifest (see Task 1) recording exactly
   what was fetched and when, for reproducibility of a specific pipeline run.

6. All raw/interim/processed data and logs are written under `DATABASE_ROOT`
   (from `.env`), i.e. the sibling `curtailmit_database/` repository — NEVER
   inside the `curtailmit/` code repository. Code repository stays data-free
   except for small, explicitly tracked example/test fixtures under `tests/fixtures/`.

7. Every new module gets unit tests. Network calls in tests must be mocked
   (use `responses` or `unittest.mock`) — tests must never require live internet
   access to pass. Add a separate, clearly marked integration test (skipped by
   default, e.g. `@pytest.mark.integration`) for the real live calls.

8. After each task: run `pytest -v -m "not integration"`, fix failures, then
   produce a git commit with a clear message. Do not move to the next task with
   failing tests.

9. Use type hints and Pydantic v2 models (extend schemas.py) for any new
   structured data crossing a module boundary.

10. Logging: use the `logging` module (already configured in data_ingestion.py),
    never bare `print()` for pipeline diagnostics. Log at INFO for normal
    discovery steps, WARNING for fallbacks, ERROR immediately before raising.

11. Before writing code, inspect what's already pre-built (see section 1 of
    docs/claude_commands.md, and config/acquisition_targets.yaml /
    config/discovered_sources.yaml) and reuse it. Do not reimplement equivalent
    logic. If something you need seems to be missing, say so explicitly rather
    than assuming it doesn't exist.
```

---

## 3. Task sequence overview

| # | Task | Module(s) | Status |
|---|---|---|---|
| 1 | Retrieval manifest + caching utility | `acquisition.py` | ✅ DONE |
| 2 | ONS curtailment discovery & acquisition (wind + solar) | `ons_client.py`, `data_ingestion.py` | ✅ DONE |
| 2B | ANEEL solar gap probe + per-package coverage floors | `validation.py`, config | ✅ DONE |
| 3 | ONS generation-by-source discovery & acquisition | `ons_generation.py` | ✅ DONE (D15; PTE/ONS basis RESOLVED as D16) |
| 4 | Curtailment classification (DEB/REB/EUB mapping) | `ons_classification.py` | ✅ DONE (D17) |
| 5 | MCTI emission factor discovery & acquisition | `mcti_client.py` | ✅ DONE (D18) |
| 6 | ANEEL fallback discovery (generation-by-source) | `aneel_client.py` | ✅ DONE (D19) |
| 7 | CCEE PLD discovery & acquisition (optional) | `ccee_client.py`, `pld.py` | ✅ DONE (closed) |
| 8 | Stage 1 finalization: `run_stage1` end to end + data-quality report | `data_ingestion.py`, `stage1_report.py` | ✅ DONE (`docs/stage1_data_quality_report.md`) |
| 9 | Stage 2: `calibration.py` + D20 solar basis | `calibration.py`, `ons_generation.py` | ✅ DONE (D20; report `docs/task9_calibration_report.md`; logistic identifiability open, see report) |
| 10 | Stage 3: `projection.py` | `projection.py` | ✅ DONE |
| 11 | Stage 4: `mitigation.py` | `mitigation.py` | 🔶 done, needs OM/CM split (folded into Task 13) |
| 12 | Stage 5: `hydrogen.py` | `hydrogen.py` | ✅ DONE |
| 13 | Stage 6: finalize `results_writer.py` wiring + reports/figures | `results_writer.py`, `mitigation.py` | ⬜ (rewritten below) |
| 14 | End-to-end orchestration + CI | `scripts/run_pipeline.py`, CI | ⬜ |
| 15 | Reproducibility pass + documentation sync | `docs/`, `README.md` | ⬜ |

---

## 4. REMAINING TASKS — paste sequentially from here

### TASK 3 — DONE (see section 1.3b; prompt removed)

---

### TASK 4 — DONE (see section 1.3c; prompt removed)

---

### TASK 5 — DONE (see section 1.3d; prompt removed)

---

### TASK 6 — DONE (see section 1.3f; prompt removed)

---

### TASK 8 — DONE (see `docs/stage1_data_quality_report.md`; prompt removed)

`run_stage1` runs, in order: config, ONS curtailment (D14 floors), capacity-factor files (D20), generation + P(t) on the dispatched basis (D15/D20), classification (D17), MCTI (D12/D18), validation_data, then writes `processed/data_quality_report.json`, `logs/stage1_data_quality_report_<ts>.json` and the Markdown report. Statuses: PASS / WARNING / NOT APPLICABLE / FAIL; any FAIL raises `Stage1Error`. It never runs calibration, mitigation or the secondary generation fallback. Calibration has its own entry point (`calibration.run_calibration`).

---

### STAGE 3 REQUIREMENT (from D21, updated by D22) - two curves, propagated uncertainty

Stage 3 (PTE scenario application, `projection.py` wiring; a future task) MUST use the two technology-specific curves of D22 separately, never a single combined curve:
(1) for each scenario/year, curtailed wind = `wind_gen` x `C_wind(P)` and curtailed solar = `solar_gen` x `C_solar(P)`, with each technology's own projected generation (PTE shares) and the scenario's combined P = solar_pct + wind_pct; the total is the sum, and the mitigation deficit is computed from it;
(2) each curve carries its own bootstrap 95 % interval (`calibration.bootstrap_calibration_ci`, 1000 resamples; stored in `processed/calibration_ci_wind.parquet` and `calibration_ci_solar.parquet`), and every 2040/2050 figure (P = 36-58 %, outside the calibration range 10.3-29.4 % for both curves) must be reported with lower/upper bounds instead of a point estimate alone;
(3) state that the intervals cover sampling uncertainty only, not the logistic functional form;
(4) the combined single curve (`calibration_params_combined_diagnostic.json`) is a non-primary diagnostic and must not feed Stage 3 deficits.
Reference: D21, D22, `docs/task9_calibration_report.md`. Not implemented yet by design.

---

### TASK 13 — Stage 6 finalization: wire mitigation.py's OM/CM split + assemble results_writer output

```
TASK 13 — Finish Stage 4/6 wiring and produce final outputs with full
provenance.

Read docs/roadmap.md §8 and docs/methodology.md §3.7 first. NOTE: this task
has been rewritten from its original scope because results_writer.py and its
ResultsRow schema ALREADY EXIST, fully built and tested, with a richer schema
than originally planned — it already separates
mitigation_deficit_marginal_om_tco2 and mitigation_deficit_marginal_cm_tco2
as two distinct columns (never one collapsed "marginal" figure). Do not
change this schema. The remaining real work is upstream of it.

PART A — Enrich mitigation.py:
mitigation.compute_mitigation() currently only computes one marginal deficit
using a single om_factor. Update it (or add a new function alongside it, your
call) to compute BOTH:
- mitigation_deficit_marginal_om_tco2 = E_curt x OM (DEB proxy)
- mitigation_deficit_marginal_cm_tco2 = E_curt x CM (REB proxy, CM from
  emission_factors.compute_combined_margin(), already built)
Both values must always be populated together — never report one without
the other. If classification_available is False for a given row, both OM
and CM proxies are still computed (they're proxies for curtailment CAUSE,
not dependent on whether cause classification succeeded) but
marginal_proxy_note must say so explicitly (matching results_writer's
ResultsRow.marginal_proxy_note field).

PART B — Assembly:
Write the orchestration logic (in results_writer.py or a thin new
assemble_results.py, your call) that:
1. Merges projection_results (Stage 3), the enriched mitigation output
   (Part A), and hydrogen_results (Stage 5) on [scenario, year].
2. Constructs one results_writer.ResultsRow per (scenario, year), populating
   every field including source, is_interpolated, classification_available
   (propagated end-to-end from Task 4's flag, via validation.py's existing
   helpers — do not reinvent propagation logic).
3. Calls results_writer.write_results_csv() and write_results_json()
   (already built) to produce DATABASE_ROOT/outputs/tables/final_results.csv
   and .json.

PART C — Reports and figures (as originally scoped):
1. DATABASE_ROOT/outputs/reports/limitations_summary.md — auto-generated
   from the actual flags present in the data (e.g. if
   classification_available is False for any scenario, this must appear
   here verbatim, matching language in docs/methodology.md §3.7 — pull from
   the flags, don't invent new wording). Must also surface the
   solar_curtailment_2020_baseline documented-zero note from D14.
2. Basic matplotlib figures (DATABASE_ROOT/outputs/figures/): E_curt by
   scenario/year, mitigation deficit (avg vs OM vs CM) by scenario/year, H2
   potential range by scenario/year. Each figure's filename/caption must
   indicate whether interpolated points are included.
3. Enforce at runtime: if classification_available is False, any
   column/figure referencing DEB/REB must instead be labeled "aggregate
   (unclassified)" — write a unit test that fails if this mislabeling ever
   occurs.

Tests:
- mitigation.py: synthetic fixtures confirming both OM and CM columns are
  always populated together and correctly traceable to their proxy source.
- assembly: synthetic merged fixture with classification_available=False;
  assert the output report contains "aggregate" and does NOT contain "DEB"
  or "REB" in that scenario's section.
- Full chain: a mocked end-to-end test producing a complete outputs/
  directory.

Acceptance:
- pytest -v -m "not integration" passes.
- No ResultsRow is ever written with only one marginal figure — both OM and
  CM columns populated on every row.
```

---

### TASK 14 — End-to-end orchestration + CI

```
TASK 14 — Wire everything into scripts/run_pipeline.py and add CI.

1. Rewrite scripts/run_pipeline.py to run Stages 1-6 in order, respecting:
   - pld.enabled flag from config (skip Stage/module if false, per D10 —
     currently always false, CCEE permanently closed).
   - A --use-cache CLI flag (argparse) controlling acquisition.py's
     use_cache behavior — default False, explicit opt-in to reuse cached
     raw files for faster iteration during development.
   - A --integration flag to also run the @pytest.mark.integration-style
     live calls as part of a manual full run (not part of default CI).

2. Each stage's output path and the final DataQualityReport +
   limitations_summary.md should be printed as a clear console summary at
   the end of the run.

3. Fill in .github/workflows/ci.yml:
   - Run on push/PR to main.
   - Set up Python 3.11, install requirements.txt + the package itself
     (pip install -e ".[dev]").
   - Run pytest -v -m "not integration" (never run live network calls in CI).
   - Run ruff check src tests.

4. Update Makefile with a run target calling scripts/run_pipeline.py.

Acceptance:
- python scripts/run_pipeline.py runs end-to-end against mocked/test
  configuration without crashing.
- CI workflow file is valid YAML and the job list matches the steps above.
```

---

### TASK 15 — Reproducibility pass + documentation sync

```
TASK 15 — Final reproducibility and documentation pass.

1. Add a DATABASE_ROOT/logs/run_manifest_{timestamp}.json at the end of
   every full pipeline run, aggregating all individual retrieval manifests
   (Task 1) used in that run.

2. Update docs/roadmap.md §8 ("Remaining open items") — replace with actual
   outcomes now that the pipeline has run at least once: which resource_ids
   were discovered, which fallback paths (if any) were triggered, final
   calibration parameters.

3. Update README.md with real, tested instructions: how to run Stage 1
   alone, how to run the full pipeline, how to interpret
   outputs/reports/limitations_summary.md.

4. Confirm every acceptance criterion in docs/roadmap.md §7 has a
   corresponding passing test — list them explicitly in a new
   docs/acceptance_criteria_status.md, one row per criterion, with the test
   name that verifies it.

5. Housekeeping: config/discovered_sources.yaml currently has decisions D13
   and D14 in a structured `decisions:` block, while earlier decisions
   (D10, D12) are inline comments. Normalize all decisions (D1-D14) into the
   structured block format for consistency.

Acceptance:
- All of the above files exist and are internally consistent with the
  actual code behavior (not aspirational).
- Full test suite (excluding integration-marked tests) passes.
```

---

## 5. Session restart checklist (paste if starting a new Claude Code session)

```
Before continuing: read docs/roadmap.md, docs/methodology.md, and
docs/claude_commands.md (sections 1 and 3) in full. Tell me which task number
we left off at (check the latest git log and which modules/tests already
exist) before writing any new code.
```
