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
token usage, plus three real Claude Code sessions (Task 2, Task 2B, Task 3) that did live
API discovery and acquisition. Full test suite currently: **149 passed, 0 failed**
(`pytest -v -m "not integration"`).

### 1.1 Shared infrastructure (pre-built, tested)

| Module | Status | What it does |
|---|---|---|
| `acquisition.py` | ✅ | `fetch_and_cache()` — download + cache + manifest sidecar. |
| `manifest.py` | ✅ | `write_manifest()`, `load_manifest()`, `compute_sha256()`. Used internally by `acquisition.py`. |
| `paths.py` | ✅ | `get_database_root()`, `get_raw_dir()` — reads `.env` + `config/paths.yaml`. |
| `validation.py` | ✅ | Acceptance-criteria logic: `validate_penetration_ceiling()`, `resolve_ons_min_coverage()` (per-package coverage floors), `validate_mcti_factor_coverage()`, `ClassificationFlag`/`attach_classification_flag()`/`validate_classification_propagation()` (DEB/REB/EUB propagation rules). **Reuse this in Tasks 4 and 8 — do not rewrite classification/coverage logic.** |
| `emission_factors.py` | ✅ | `derive_annual_om_from_monthly()` (mean of 12 monthly OM values), `compute_combined_margin()` (CM = 0.5×OM + 0.5×BM, decision D12). **Reuse directly in Task 5.** |
| `calibration.py` | ✅ (generic logic only) | Logistic-fit machinery: `fit_calibration`, `apply_calibration`, `validate_against_holdout`, save/load. **Not yet wired to real data — Task 3's output now exists; see the open PTE/ONS basis question in 1.3b.** |
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
- Raw reason codes (`CNF`, `REL`, etc.) are stored as-is in `reason_category` — DEB/REB/EUB mapping is Task 4's job, not done yet.
- 128→132 tests added across this work; one `@pytest.mark.integration` test confirmed live against real ONS (both packages resolve, no fallback triggered).
- Commits: `f32eac5` (Task 2), `d7b267e` (Task 2B), `bc5a0bb` (docs).

### 1.3 CCEE PLD (Task 7) — DONE, permanently closed

CCEE (`dadosabertos.ccee.org.br`) returns HTTP 403 (WAF-level block) on every probe, including with browser headers — confirmed twice, **do not re-probe**. `pld.py` stub built, tested, `pld.enabled: false` enforced. This is a closed limitation, not an open task.

### 1.3b ONS generation-by-source (Task 3) — DONE (commit `3f69554`; closeout D15 + basis investigation)

- Module `src/curtailmit/ons_generation.py` (package `balanco-energia-subsistema`, re-confirmed at runtime via `package_show`, `package_search` recovery path, yearly resources PARQUET > CSV > XLSX, `id_subsistema == "SIN"`, hourly MW integrated to MWh). Values are published as decimal *text* and are coerced explicitly. Blank `val_gersolar` -> 0 (documented); a blank in any other source fails explicitly.
- Outputs (under `DATABASE_ROOT`): `interim/ons_generation_by_source.parquet`, `processed/ons_penetration_monthly.parquet`, `processed/ons_penetration_annual.parquet`, `processed/baseline_2020_generation.json` (validated against `schemas.Baseline2020Generation`; requires every hour of 2020).
- **2020 baseline (observed, ONS SIN):** total **554.35 TWh**, wind **54.30 TWh**, solar **5.23 TWh**, wind+solar penetration **10.74 %**.
- **D15**: series usable only from `history_start_year: 2016` (`config/acquisition_targets.yaml`); wind blank 2000-2005 and partly 2006, 2015 has 24 h with no data. Does not affect the 2020 baseline or the 2021+ calibration window.
- **OPEN — PTE vs ONS generation basis (pending our decision, NOT resolved):** ONS SIN total (554 TWh in 2020, 700 TWh in 2025) is on a different, narrower basis than the PTE `total_generation_twh` (836 TWh in 2025). Evidence and unconfirmed items: `docs/pte_ons_basis_investigation.md`. Decide how to reconcile P(t)'s denominator basis between calibration and projection **before Task 9**.

### 1.4 Discovery already resolved for not-yet-implemented tasks

These tasks still need real **implementation**, but discovery is fully closed —
do not re-discover, proceed straight to coding:

- **Task 3 (ONS generation-by-source)** — DONE, see 1.3b. Discovery notes kept for reference: package `balanco-energia-subsistema`, one CSV per year, confirmed schema (`id_subsistema, val_gerhidraulica, val_gertermica, val_gereolica, val_gersolar, val_carga, val_intercambio`). Filter `id_subsistema=="SIN"`. `val_gersolar` NaN/0 pre-2017 = expected, treat as 0. `geracao-usina-2` demoted to optional cross-check only.
- **Task 5 (MCTI emission factors)**: landing page confirmed, file-naming patterns confirmed (inconsistent per-year names, legacy domain for pre-2021), sheet names confirmed (`inventário-todos`, `MDL`, `Publicar`). Full mapping table in Task 5 below.
- **Task 6 (ANEEL fallback)**: CKAN base confirmed reachable. Note: the Task 2B probe already ruled out ANEEL for *curtailment* data specifically (20 packages checked, none are curtailment series — registries/capacity/auctions/tariffs only). Task 6's fallback role should therefore target **generation-by-source** data, not curtailment.

### 1.5 Still fully open (no discovery done yet)

- **Task 4** — DEB/REB/EUB classification mapping (logic exists in `validation.py`, not yet applied to real parsed ONS data).
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
| 3 | ONS generation-by-source discovery & acquisition | `ons_generation.py` | ✅ DONE (D15; PTE/ONS basis question OPEN) |
| 4 | Curtailment classification (DEB/REB/EUB mapping) | `data_ingestion.py` | ⬜ NEXT |
| 5 | MCTI emission factor discovery & acquisition | `mcti_client.py`, `data_ingestion.py` | ⬜ |
| 6 | ANEEL fallback discovery (generation-by-source) | `aneel_client.py` | ⬜ |
| 7 | CCEE PLD discovery & acquisition (optional) | `ccee_client.py`, `pld.py` | ✅ DONE (closed) |
| 8 | Stage 1 finalization: full data-quality report | `data_ingestion.py` | ⬜ |
| 9 | Stage 2: `calibration.py` | `calibration.py` | 🔶 logic done, needs real-data wiring (Task 3 done; resolve the PTE/ONS basis question first) |
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

### TASK 4 — Curtailment classification availability + DEB/REB/EUB mapping

```
TASK 4 — Implement the classification availability check and mapping logic
(Decisions D5/D6).

Read docs/roadmap.md §2 (D5, D6) and §6/§7 (acceptance criteria) first.
IMPORTANT: the mapping logic and propagation rules already exist and are
TESTED in src/curtailmit/validation.py — reuse them, do not rewrite:
- validation.ClassificationFlag (dataclass: classification_available, reason)
- validation.attach_classification_flag(record, flag) -> new dict
- validation.validate_classification_propagation(records)
The mapping itself (reason-string -> DEB/REB/EUB) is already defined in
config/acquisition_targets.yaml under classification.mapping:
  "Razão Energética" -> DEB, "Confiabilidade" -> REB,
  "Indisponibilidade Externa" -> EUB (own category, never merged).
classification.fallback_on_missing_classification: true is also already set.

Implement check_classification_availability() for real (replacing the current
stub) in data_ingestion.py, applied to the REAL parsed ONS curtailment data
from Task 2 (interim/ons_curtailment_raw.parquet, column reason_category,
currently holding raw codes like "CNF", "REL"):

1. Inspect the distinct values actually present in reason_category. Check
   whether they correspond (directly, or via a documented code->label
   crosswalk you derive by inspecting the ONS resource's accompanying
   documentation/dictionary if available) to the three categories in
   config/acquisition_targets.yaml's classification.mapping. Log the exact
   distinct values found and your crosswalk reasoning.

2. If a usable mapping is found: apply it to produce a `deb_reb_eub` column
   (values: DEB/REB/EUB). Use validation.attach_classification_flag with
   ClassificationFlag(classification_available=True) for each record. Log a
   value_counts() summary.

3. If not found, or only an aggregate series is available: set
   classification_available = False with a specific reason via
   ClassificationFlag, apply attach_classification_flag accordingly (this
   enforces, per validation.py's existing rules, that no classified
   DEB/REB/EUB fields leak into records marked unavailable), log a clear
   WARNING explaining exactly what was checked and why it failed. The
   aggregate (unclassified) series must remain fully usable downstream.

4. Persist the result to
   DATABASE_ROOT/processed/ons_curtailment_classified.parquet, plus a
   top-level flag file DATABASE_ROOT/processed/classification_available.json
   = {"classification_available": bool, "checked_at_utc": ..., "reason": "..."}.

5. Run validation.validate_classification_propagation() over the final
   records as a hard check before writing output — if it raises, treat that
   as a real bug, not something to catch and suppress.

6. Tests: one fixture simulating real-looking CNF/REL-style raw codes with a
   documented crosswalk (passes through mapping correctly), one fixture
   simulating an aggregate-only resource (correctly sets
   classification_available: false, validate_classification_propagation
   still passes, no classified fields leak through).

Acceptance:
- pytest -v -m "not integration" passes.
- classification_available.json is produced with a clear, human-readable
  reason field in both branches.
- No scenario silently defaults to a specific DEB/REB/EUB value without the
  flag being correctly set to False first.
```

---

### TASK 5 — MCTI emission factor discovery & acquisition

```
TASK 5 — Implement MCTI average and marginal emission factor acquisition.

Read docs/roadmap.md (D8, D9, D12) and docs/methodology.md §2.2 first.
Discovery for this task is ALREADY CLOSED — do not search for new URLs. Use
these confirmed facts directly (full detail in config/acquisition_targets.yaml,
mcti section):

- Landing page:
  https://www.gov.br/mcti/pt-br/acompanhe-o-mcti/sirene/dados-e-ferramentas/fatores-de-emissao

| Concept | File pattern | Granularity | Sheet |
|---|---|---|---|
| Average SIN factor (D8) | `Inventario_{year_range}.xlsx` — ONE consolidated file, 2006->present | Monthly + annual | `inventário-todos` |
| Build Margin (BM) | `Despacho_{YYYY}_*.xlsx` OR `Margemdeconstruo_{YYYY}*.xlsx` — ONE FILE PER YEAR, inconsistent naming, legacy domain antigo.mctic.gov.br for pre-2021 | Annual (direct) | `MDL` |
| Operating Margin (OM), DEB proxy (D9) | Same per-year file as BM | Monthly only (12 values; no official annual figure) | `MDL` |
| Combined Margin (CM), REB proxy (D9) | NOT PUBLISHED | — | — |
| Simple Adjusted OM (secondary/fallback only) | `FE_simplesajustado_{year}_web.xlsx` — ONE consolidated file, 2006->present | Annual | `Publicar` |

CRITICAL: per-year BM/OM file naming is inconsistent across years and CANNOT
be guessed from a fixed URL pattern. Your acquisition code must:
1. Fetch the landing page above.
2. Parse all <a href> tags ending in .xlsx/.xls (BeautifulSoup).
3. Match the target year as a substring in the href or link text to select
   the correct file for that year.
4. Log every discovered URL via acquisition.fetch_and_cache's manifest
   sidecar (already built — reuse it, do not write new HTTP logic).
5. If no file matches a required year, FAIL EXPLICITLY — do not guess a URL.

Create src/curtailmit/mcti_client.py:

1. `discover_average_factor_file(landing_url) -> dict`: find and download the
   single consolidated Inventario_*.xlsx file into
   get_raw_dir("mcti/average_emission_factor"), parse sheet
   "inventário-todos" into [year, month, factor_tco2_per_mwh].

2. `discover_margin_factor_file(landing_url, year) -> dict`: find the correct
   per-year Despacho_*/Margemdeconstruo_* file for the given year via the
   substring-match rule above, download into
   get_raw_dir("mcti/margin_factors"), parse sheet "MDL" into BM (single
   annual value) and OM (12 monthly values).

3. Use emission_factors.derive_annual_om_from_monthly() (already built,
   tested — do not reimplement) to get annual OM.

4. Use emission_factors.compute_combined_margin() (already built, tested) to
   compute CM = 0.5*OM + 0.5*BM. Flag CM and derived-annual-OM explicitly as
   computed/derived in all output metadata — never presented as an
   MCTI-published figure.

5. Validate coverage: average factor series must cover the full calibration
   window from Tasks 2/3 (2021-present at minimum) — raise a specific
   exception if not.

6. If the MCTI page/file structure cannot be parsed at all (layout changed,
   access blocked), this IS a legitimate manual-ingestion case: implement
   manual_ingestion.py with load_manually_placed_file(expected_path) ->
   pd.DataFrame, raising a clear instructional error naming exactly which
   file to place where. Log this fallback prominently as a declared
   limitation in Task 8's data-quality report — never silently.

7. Persist to DATABASE_ROOT/processed/mcti_average_factor.parquet and
   DATABASE_ROOT/processed/mcti_margin_factors.parquet (columns: year, om,
   bm, cm — all three, with a note that om/cm are derived).

8. Tests: mock the HTML landing page + file downloads; one test for correct
   parsing, one for the explicit coverage-exception path, one confirming
   manual_ingestion.py raises a clear actionable error when invoked without
   a pre-placed file.

Acceptance:
- pytest -v -m "not integration" passes without live network access.
- If the confirmed landing page structure has changed since discovery (i.e.
  it no longer matches what's documented in acquisition_targets.yaml), STOP
  and report back exactly what changed instead of guessing a fix.
```

---

### TASK 6 — ANEEL fallback discovery (generation-by-source)

```
TASK 6 — Implement ANEEL open data as a secondary/fallback source for
generation-by-source data, used only if ONS (Task 3) coverage or schema turns
out to be insufficient for any specific scenario/year.

Read docs/roadmap.md and docs/methodology.md first. ANEEL's CKAN base
(https://dadosabertos.aneel.gov.br/api/3/action/) is CONFIRMED reachable — no
further reachability check needed.

IMPORTANT CONTEXT: a prior probe (Task 2B) already searched ANEEL specifically
for CURTAILMENT data across 13 queries and found none (20 packages inspected,
all registries/capacity/auctions/tariffs). Do not re-probe ANEEL for
curtailment — this task's fallback role is GENERATION-BY-SOURCE data only,
not curtailment.

Create src/curtailmit/aneel_client.py, reusing CkanClient against ANEEL's CKAN
base URL. Discover the correct generation-by-source package via
package_search (candidate queries: "geracao usina", "geracao fonte",
"capacidade instalada geracao"), log every candidate, pick the best match
using a documented heuristic, log final choice and why alternatives were
rejected.

This task should NOT be wired into the default Stage 1 pipeline — implement
as a standalone, tested module with a clear docstring explaining it's a
fallback path, callable explicitly (e.g.
aneel_client.fetch_generation_fallback(...)) but not invoked automatically
unless data_ingestion.py explicitly calls it after a documented ONS failure
in Task 3/8.

Tests: same mocked-fixture pattern as previous tasks.

Acceptance:
- pytest -v -m "not integration" passes.
- Module is self-contained, documented as "fallback, not default path" in its
  module docstring and in a short note added to docs/roadmap.md §8 under
  "Remaining open items".
```

---

### TASK 8 — Stage 1 finalization: full data-quality report

```
TASK 8 — Consolidate Stage 1 into a single, complete data-quality report.

Read docs/roadmap.md §6 and §7 (acceptance criteria) first — this task
enforces those criteria in code. schemas.DataQualityReport ALREADY EXISTS —
extend it if a field is missing, do not recreate it from scratch.

Rewrite run_stage1() in data_ingestion.py to orchestrate, in order:
1. load_config().
2. ONS curtailment discovery (Task 2/2B) for wind + solar, respecting the
   per-package coverage floors in validation.resolve_ons_min_coverage().
3. ONS generation-by-source discovery (Task 3), including baseline_2020
   extraction.
4. Classification availability check (Task 4).
5. MCTI emission factor discovery (Task 5), with manual_ingestion.py fallback
   if needed.
6. Load validation_data (2026-2029 prospection) from config/scenarios.yaml,
   explicitly kept out of any calibration-data variable used later.
7. ANEEL fallback (Task 6) — invoked only if an ONS step raised a
   CoverageError/ValidationError or schema mismatch; must be clearly logged
   as "fallback invoked" with the specific reason, never used silently as the
   primary path.

Populate schemas.DataQualityReport with at minimum:
- timestamp_utc
- ons_wind_coverage / ons_solar_coverage: {earliest_date, latest_date, n_records}
- solar_curtailment_2020_baseline: "documented_zero_not_measured" (per D14 —
  already decided, just needs to be surfaced in this report)
- classification_available: bool, reason: str
- mcti_average_factor_coverage / mcti_marginal_factor_coverage
- fallback_sources_used: list[str] (empty if none)
- validation_data_loaded: bool
- overall_status: "ok" | "degraded" | "failed"

Write as JSON (DATABASE_ROOT/logs/stage1_data_quality_report_{timestamp}.json)
and print a human-readable summary table to stdout.

Stage 1 must raise (not just log) if overall_status would be "failed" per
roadmap §7 acceptance criteria.

Acceptance:
- pytest -v -m "not integration" passes (fully mocked).
- A dedicated integration-style test using all mocked fixtures together
  produces a valid DataQualityReport JSON.
- Commit message should reference "Stage 1 complete".
```

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
