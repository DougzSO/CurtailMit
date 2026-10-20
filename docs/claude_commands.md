# CurtailMit — Claude Code Build Commands — v1.0

> Source of truth for everything in this document: `docs/roadmap.md` and
> `docs/methodology.md`. If anything here conflicts with those two files, the two
> files win — update this document, not the other way around.

## 0. How to use this document

- This is not one giant prompt. It is a **sequence of discrete tasks**, numbered.
- Paste **one task at a time** into Claude Code, let it finish, review the diff,
  run tests, commit, and only then move to the next task.
- Every task assumes Claude Code has read access to the full repository
  (`curtailmit/`) and should **start by reading `docs/roadmap.md` and
  `docs/methodology.md`** before writing any code.
- Never paste a task out of order — later tasks assume earlier ones are merged.

---

## 1. Global operating rules (apply to every single task below)

Paste this block once, at the start of the first Claude Code session, so it stays
in context. Repeat it if you start a new session mid-project.

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
   it was confirmed — never typed in from a web browser by a human.

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

8. After each task: run `pytest -v`, fix failures, then produce a git commit with
   a clear message. Do not move to the next task with failing tests.

9. Use type hints and Pydantic v2 models (extend schemas.py) for any new
   structured data crossing a module boundary.

10. Logging: use the `logging` module (already configured in data_ingestion.py),
    never bare `print()` for pipeline diagnostics. Log at INFO for normal
    discovery steps, WARNING for fallbacks, ERROR immediately before raising.
```

---

## 2. Task sequence overview

| # | Task | Module(s) | Stage |
|---|---|---|---|
| 1 | Retrieval manifest + caching utility | `acquisition.py` | shared infra |
| 2 | ONS curtailment discovery & acquisition (wind + solar) | `ons_client.py`, `data_ingestion.py` | 1 |
| 3 | ONS generation-by-source discovery & acquisition | `ons_client.py`, `data_ingestion.py` | 1 |
| 4 | Curtailment classification availability + DEB/REB/EUB mapping | `data_ingestion.py` | 1 |
| 5 | MCTI emission factor discovery & acquisition (average + marginal) | `mcti_client.py`, `data_ingestion.py` | 1 |
| 6 | ANEEL fallback discovery (secondary source, if ONS insufficient) | `aneel_client.py` | 1 |
| 7 | CCEE PLD discovery & acquisition (optional module) | `ccee_client.py` | 1 (optional) |
| 8 | Stage 1 finalization: full data-quality report | `data_ingestion.py` | 1 |
| 9 | Stage 2: calibration.py | `calibration.py` | 2 |
| 10 | Stage 3: projection.py | `projection.py` | 3 |
| 11 | Stage 4: mitigation.py | `mitigation.py` | 4 |
| 12 | Stage 5: hydrogen.py | `hydrogen.py` | 5 |
| 13 | Stage 6: results_writer.py | `results_writer.py` | 6 |
| 14 | End-to-end orchestration + CI | `scripts/run_pipeline.py`, `.github/workflows/ci.yml` | all |
| 15 | Reproducibility pass + documentation sync | `docs/`, `README.md` | all |

---

## 3. TASK 1 — Retrieval manifest + caching utility

```
TASK 1 — Build a shared data-acquisition utility with retrieval manifests.

Read docs/roadmap.md and docs/methodology.md first.

Create src/curtailmit/acquisition.py with:

1. A function `fetch_and_cache(url: str, dest_path: Path, params: dict | None = None,
   method: str = "GET", use_cache: bool = False, timeout: int = 60) -> Path` that:
   - Downloads the resource (if use_cache=False or file missing).
   - Writes the raw response body to `dest_path`.
   - Writes a sidecar manifest file `dest_path.with_suffix(dest_path.suffix + ".manifest.json")`
     containing: source_url, http_status, retrieved_at_utc (ISO 8601), sha256 of the
     downloaded content, byte_size, and the request params used.
   - If use_cache=True and both dest_path and its manifest already exist, skip the
     network call and log that the cached version is being reused, including the
     original retrieved_at_utc from the manifest so it's never ambiguous which run
     the data belongs to.

2. A Pydantic model `RetrievalManifest` in schemas.py matching the JSON structure above.

3. A function `load_manifest(dest_path: Path) -> RetrievalManifest` to read it back.

4. Respect DATABASE_ROOT from .env (via python-dotenv) as the base path for all
   dest_path values used elsewhere in the pipeline — add a small `paths.py` helper
   with `get_database_root() -> Path` and `get_raw_dir(subdir: str) -> Path` that
   read config/paths.yaml + .env and create directories as needed.

5. Unit tests in tests/test_acquisition.py using `responses` (add to requirements.txt)
   to mock HTTP calls — no live network access in the default test run.

Acceptance:
- pytest -v passes.
- Running fetch_and_cache twice with use_cache=True only performs one real HTTP call
  (assert via mock call count in the test).
- Manifest JSON is valid and round-trips through RetrievalManifest.
```

---

## 4. TASK 2 — ONS curtailment discovery & acquisition (wind + solar)

```
TASK 2 — Implement real ONS curtailment discovery and data acquisition.

Read docs/roadmap.md §6 and docs/methodology.md §2.2 first. Reuse acquisition.py
and ons_client.py from previous work — do not duplicate HTTP logic.

Goal: fully automated discovery (no hardcoded resource_id beyond the package name
already in config/scenarios.yaml) of:
(a) wind curtailment: package "restricao_coff_eolica_usi" (already known, confirm it
    still resolves — ONS can rename/retire datasets).
(b) solar/photovoltaic curtailment: package id NOT known yet. Discover it via
    CkanClient.package_search using multiple candidate queries (try at least:
    "restricao fotovoltaica", "corte geracao fotovoltaica", "curtailment solar",
    "restricao geracao eolica fotovoltaica"). Log every candidate result found,
    then apply a disambiguation heuristic (prefer exact/near-exact name match to
    the wind package naming pattern, e.g. "restricao_coff_fotovoltaica_usi" or
    similar) and log the final choice with justification.

Implement in data_ingestion.py (replacing the current discover_ons_resources TODO):

1. For each package (wind, solar):
   - list_resources() via CkanClient.
   - Identify the resource(s) actually containing the monthly/time-series data
     (not documentation PDFs) — prefer CSV/XLSX/JSON formats, log all formats seen.
   - Download the most recent resource via acquisition.fetch_and_cache into
     get_raw_dir("ons/curtailment_wind") / get_raw_dir("ons/curtailment_solar").
   - Parse the downloaded file into a pandas DataFrame with at least columns:
     [date, installation/usina, curtailed_energy_mwh, reason_category (if present)].
   - Determine the true earliest available date in the parsed data.
   - Call CkanClient.enforce_min_coverage(earliest_date, date(2022,1,1)) — let it
     raise CoverageError if insufficient; do not catch and suppress it.

2. Update config/scenarios.yaml automatically is NOT required by this task — just
   log the discovered package/resource ids clearly (they will be documented
   manually by me afterward if I want to pin them). Do not silently overwrite the
   YAML file from code.

3. Write parsed, concatenated (wind+solar) interim data to
   DATABASE_ROOT/interim/ons_curtailment_raw.parquet, with a `source` column
   ("wind"/"solar") preserved.

4. Unit tests with mocked CKAN responses + a small fixture CSV/XLSX under
   tests/fixtures/ons/ simulating a realistic resource payload (few rows is enough).
   Add one @pytest.mark.integration test that performs the real discovery against
   the live ONS CKAN API (skipped by default, run manually with
   `pytest -m integration`).

Acceptance:
- pytest -v (unit tests) passes without network access.
- Explicit CoverageError raised (demonstrated in a unit test with a mocked
  short-coverage fixture) rather than silently proceeding.
- Clear INFO/WARNING logs showing the discovery trail (candidates considered,
  final choice, coverage found).
```

---

## 5. TASK 3 — ONS generation-by-source discovery & acquisition

```
TASK 3 — Implement ONS generation-by-source discovery and acquisition (for P(t)
calibration input and the 2020 historical baseline, per Decision D1).

Read docs/roadmap.md §2 (D1, D2) and §6 (item 8) first.

Goal: automatically find the correct CKAN package for monthly (or finer) generation
by source (solar, wind, hydro, thermal, nuclear, etc.) and subsystem/national total,
sufficient to:
(a) compute historical P(t) = (solar+wind generation) / total generation, 2021-present,
    for calibration against the curtailment series from Task 2;
(b) provide the real 2020 historical generation-by-source figures needed for the
    `baseline_2020` anchor point in config/scenarios.yaml (D1).

Implement in data_ingestion.py / a new ons_generation.py submodule if cleaner:

1. Use CkanClient.package_search with candidate queries: "geracao usina",
   "geracao fonte", "balanco energia subsistema", "geracao energia mensal". Log
   every candidate, pick the best match using a documented heuristic (prefer
   datasets whose resource schema includes a fuel/source-type column and monthly
   granularity), log the final choice and why alternatives were rejected.

2. Download, parse, and cache via acquisition.fetch_and_cache, same pattern as
   Task 2. Produce a tidy DataFrame: [date, source_type, generation_mwh,
   subsystem_or_national].

3. Aggregate to national monthly totals by source_type; compute P(t) series.

4. Extract the 2020 annual total (sum of monthly) by source_type specifically for
   the baseline_2020 use case; store as
   DATABASE_ROOT/processed/baseline_2020_generation.json with clear units (TWh)
   and a `source: historical_ons` tag matching schemas.BaselineConfig.

5. Write the full historical series to
   DATABASE_ROOT/interim/ons_generation_by_source.parquet.

6. Tests: same mocked-fixture + integration-marked pattern as Task 2.

Acceptance:
- pytest -v passes without network.
- baseline_2020_generation.json is produced in a mocked test run and validates
  against a Pydantic schema (extend schemas.py with a Baseline2020Generation model).
- Logs clearly show which dataset was chosen and why.
```

---

## 6. TASK 4 — Curtailment classification availability + DEB/REB/EUB mapping

```
TASK 4 — Implement the classification availability check and mapping logic
(Decisions D5/D6).

Read docs/roadmap.md §2 (D5, D6) and §6/§7 (acceptance criteria) first.

Implement check_classification_availability() for real (replacing the current
stub) in data_ingestion.py:

1. Inspect the schema of the resource(s) downloaded in Task 2. Check whether a
   reason/classification column exists (e.g. "razao_restricao", "motivo",
   "classificacao") with values matching or resembling: "Razão Energética",
   "Confiabilidade", "Indisponibilidade Externa" (accept reasonable
   variations/typos/casing — log the exact distinct values found).

2. If found: apply the mapping from config/scenarios.yaml
   (ons.classification_mapping) to produce a `deb_reb_eub` column
   (values: DEB/REB/EUB). Log a value_counts() summary.

3. If not found, or if the CKAN resource only exposes an aggregate series (no
   reason breakdown) while the ONS dashboard visually shows one: set
   classification_available = False, log a clear WARNING explaining exactly what
   was checked and why it failed, and ensure the aggregate (unclassified) series
   is still usable downstream.

4. Persist the result (classified or not) to
   DATABASE_ROOT/processed/ons_curtailment_classified.parquet (with the
   `deb_reb_eub` column present but possibly all-null + a top-level flag file
   DATABASE_ROOT/processed/classification_available.json = {"classification_available": bool,
   "checked_at_utc": ..., "reason": "..."}).

5. Tests: one fixture simulating a classified resource (passes through mapping
   correctly), one fixture simulating an aggregate-only resource (correctly sets
   classification_available: false and does not raise).

Acceptance:
- pytest -v passes.
- classification_available.json is produced with a clear, human-readable `reason`
  field in both branches (available / fallback).
- No scenario silently defaults to a specific DEB/REB/EUB value without the flag
  being correctly set to False first.
```

---

## 7. TASK 5 — MCTI emission factor discovery & acquisition

```
TASK 5 — Implement MCTI average and marginal emission factor discovery/acquisition.

Read docs/roadmap.md (D8, D9) and docs/methodology.md §2.2 ("Emission factor data")
first.

MCTI does not expose a CKAN API like ONS — the average SIN emission factor and the
annual OM/BM/CM margins are typically published as spreadsheet files linked from a
gov.br landing page (page URL and exact file names change over time/month). Treat
this as a structured web-scraping discovery task, not a hardcoded file URL:

Create src/curtailmit/mcti_client.py:

1. `discover_average_factor_page(landing_url: str) -> list[dict]`:
   - Fetch the known MCTI landing page for "Fator médio de emissão de CO2 do SIN"
     (use the current gov.br/mcti URL you can find; if you cannot verify a stable
     URL, implement a Google/Bing-independent fallback: try the most likely
     gov.br/mcti path pattern and log clearly if the page structure doesn't match
     what's expected — fail explicitly, do not guess silently).
   - Parse the HTML (BeautifulSoup) to find all linked spreadsheet files
     (.xls/.xlsx/.csv), extract visible link text (often contains the month/year),
     and return them sorted by apparent recency.
   - Pick the most recent file, download via acquisition.fetch_and_cache into
     get_raw_dir("mcti/average_emission_factor").

2. `discover_margin_factors_page(landing_url: str) -> list[dict]`: same pattern for
   the annual Operating Margin / Build Margin / Combined Margin publication.

3. Parse both downloaded files into tidy DataFrames:
   - average factor: [year, month, factor_tco2_per_mwh]
   - margin factors: [year, om_factor, bm_factor, cm_factor] (units tCO2/MWh)

4. Validate coverage: average factor series must cover the full calibration window
   used in Task 2/3 (2021-present at minimum) — raise a clear, specific exception
   if not, per global rule #4. If the MCTI page/file structure cannot be parsed at
   all (e.g. layout changed, access blocked), this IS the one legitimate case for
   a manual-ingestion fallback: implement `manual_ingestion.py` with a documented
   function `load_manually_placed_file(expected_path: Path) -> pd.DataFrame` that
   raises a clear instructional error telling me exactly which file to place where
   and in what format, if the automated path fails. Log this fallback usage
   prominently in the data-quality report (Task 8) as a declared limitation —
   never silently.

5. Persist parsed results to DATABASE_ROOT/processed/mcti_average_factor.parquet
   and DATABASE_ROOT/processed/mcti_margin_factors.parquet.

6. Tests: mock the HTML landing page and the file downloads; one test confirming
   correct parsing, one confirming the explicit exception path when coverage is
   insufficient, one confirming the manual_ingestion.py path raises a clear,
   actionable error message when invoked without a pre-placed file.

Acceptance:
- pytest -v passes without live network access.
- If you (Claude Code) cannot find a reliably parseable MCTI URL during this task,
  STOP and report back exactly what you tried and what you found, instead of
  shipping a brittle guess — this is the one task in the project where I expect a
  back-and-forth before it's considered done.
```

---

## 8. TASK 6 — ANEEL fallback discovery (secondary source)

```
TASK 6 — Implement ANEEL open data (dadosabertos.aneel.gov.br, also CKAN-based) as
a secondary/fallback source for generation-by-source and/or curtailment-adjacent
data, used only if ONS (Task 2/3) coverage or schema turns out to be insufficient
for any specific scenario/year during later stages.

Read docs/roadmap.md and docs/methodology.md first.

Create src/curtailmit/aneel_client.py, reusing CkanClient against ANEEL's CKAN base
URL (discover it the same way — package_search, log candidates, no hardcoded
resource_id without confirmation).

This task should NOT be wired into the default Stage 1 pipeline yet — implement it
as a standalone, tested module with a clear docstring explaining it's a fallback
path, callable explicitly (e.g. `aneel_client.fetch_generation_fallback(...)`) but
not invoked automatically unless ONS data_ingestion.py explicitly calls it after a
documented ONS failure.

Tests: same mocked-fixture pattern as previous tasks.

Acceptance:
- pytest -v passes.
- Module is self-contained, documented as "fallback, not default path" in its
  module docstring and in a short note added to docs/roadmap.md §8 under
  "Remaining open items" (add it as a new logged capability, not a new open
  question).
```

---

## 9. TASK 7 — CCEE PLD discovery & acquisition (optional module)

```
TASK 7 — Implement the optional PLD module (Decision D10), non-blocking.

Read docs/roadmap.md (D10) and docs/methodology.md §2.8 first.

CCEE publishes open data at dadosabertos.ccee.org.br (check whether it's CKAN-based
or a different API — discover and document which it is, do not assume it mirrors
ONS's CKAN structure).

Create src/curtailmit/ccee_client.py:

1. Discover the correct dataset/endpoint for historical PLD (Preço de Liquidação
   das Diferenças), log the discovery trail same as previous tasks.
2. Download and parse into a tidy DataFrame: [date, subsystem, pld_r_per_mwh].
3. Persist to DATABASE_ROOT/processed/ccee_pld.parquet.
4. Respect config/scenarios.yaml `pld.enabled: false` — this module must be
   fully functional but NOT invoked by the default pipeline run unless
   pld.enabled is set to true. Wire this check into scripts/run_pipeline.py
   later (Task 14), not now.

Tests: mocked-fixture pattern, consistent with previous tasks.

Acceptance:
- pytest -v passes.
- Running the module standalone (python -m curtailmit.ccee_client) works against
  mocked data in tests, and is documented as optional/non-blocking in its
  docstring.
```

---

## 10. TASK 8 — Stage 1 finalization: full data-quality report

```
TASK 8 — Consolidate Stage 1 into a single, complete data-quality report.

Read docs/roadmap.md §6 and §7 (acceptance criteria) first — this task is where
those acceptance criteria get enforced in code, not just described.

Rewrite run_stage1() in data_ingestion.py to orchestrate, in order:
1. load_config() — unchanged.
2. ONS curtailment discovery (Task 2) for wind + solar.
3. ONS generation-by-source discovery (Task 3), including baseline_2020 extraction.
4. Classification availability check (Task 4).
5. MCTI emission factor discovery (Task 5), with manual_ingestion.py fallback if
   needed.
6. Load validation_data (2026-2029 prospection) from config/scenarios.yaml,
   explicitly kept out of any calibration-data variable/dataframe used later.
7. ANEEL fallback (Task 6) — invoked only if any ONS step above raised a
   CoverageError or schema mismatch; must be clearly logged as "fallback
   invoked" with the specific reason, never used silently as the primary path.

Produce a single structured report (Pydantic model `DataQualityReport` in
schemas.py) with at minimum:
- timestamp_utc
- ons_wind_coverage: {earliest_date, latest_date, n_records}
- ons_solar_coverage: {earliest_date, latest_date, n_records}
- classification_available: bool, reason: str
- mcti_average_factor_coverage: {earliest, latest}
- mcti_marginal_factor_coverage: {years covered}
- fallback_sources_used: list[str] (empty if none)
- validation_data_loaded: bool
- overall_status: "ok" | "degraded" | "failed"

Write this report both as JSON (DATABASE_ROOT/logs/stage1_data_quality_report_{timestamp}.json)
and print a human-readable summary table to stdout.

Stage 1 must raise (not just log) if overall_status would be "failed" per the
acceptance criteria in docs/roadmap.md §7 (e.g. ONS coverage < Jan/2022, or MCTI
average factor coverage insufficient with no usable manual fallback either).

Acceptance:
- pytest -v passes (fully mocked).
- Running `python -m curtailmit.data_ingestion` end-to-end against mocks (via a
  dedicated integration-style test using all mocked fixtures together) produces a
  valid DataQualityReport JSON.
- Commit message should reference "Stage 1 complete".
```

---

## 11. TASK 9 — Stage 2: `calibration.py`

```
TASK 9 — Implement curtailment calibration function C(P).

Read docs/methodology.md §2.3 first.

Implement src/curtailmit/calibration.py:

1. Input: the merged historical series combining ons_generation_by_source.parquet
   (to compute historical P(t) = (solar+wind)/total generation, monthly or
   annualized) and ons_curtailment_classified.parquet (curtailed energy, with or
   without DEB/REB/EUB split depending on classification_available).

2. Fit a calibration function C(P) — use a logistic/sigmoid functional form per
   methodology (document the exact functional form and fitting method — e.g.
   scipy.optimize.curve_fit — in a docstring and in a short addition to
   docs/methodology.md §2.3 if the final form differs from a simple logistic).

3. Validate against the 2026-2029 validation_data (loaded separately, per D-series
   decisions) — report fit error (RMSE or similar) on this held-out validation set
   explicitly, never blended into the calibration fit itself.

4. Persist fitted parameters to DATABASE_ROOT/processed/calibration_params.json
   with the functional form name, parameters, fit date, and validation error.

5. Provide `def apply_calibration(P: float, params: dict) -> float` as the
   reusable function consumed by Stage 3.

Tests: fit against a small synthetic fixture dataset with known structure;
assert recovered parameters are reasonable; assert validation error is computed
and reported separately.

Acceptance:
- pytest -v passes.
- calibration_params.json includes both fit parameters and out-of-sample
  validation error, clearly separated.
```

---

## 12. TASK 10 — Stage 3: `projection.py`

```
TASK 10 — Apply C(P) to PTE scenarios.

Read docs/methodology.md §2.4 first.

Implement src/curtailmit/projection.py:

1. Load config/scenarios.yaml PTE table (via schemas.PipelineConfig) and
   calibration_params.json from Stage 2.

2. For each scenario s in {TB, TA, TG} and year t in year_grid
   {2020, 2025, 2030, 2040, 2050}:
   - P(s,t): from Table 2 (PTE config) for 2025/2030/2040/2050; from
     baseline_2020_generation.json (tagged source: historical_ons) for 2020.
   - Ĉ(s,t) = apply_calibration(P(s,t), params).
   - E_curt(s,t) = solar_wind_generation_twh(s,t) × Ĉ(s,t).

3. Implement linear interpolation (per D3) for any additional intermediate year
   requested via a function parameter, clearly tagging interpolated rows with
   `interpolated: true` in the output — never silently blended with the 5
   anchor-point rows.

4. Output a tidy DataFrame/parquet: DATABASE_ROOT/processed/projection_results.parquet
   with columns [scenario, year, P, C_hat, E_curt_twh, source (historical_ons/
   pte_published/interpolated)].

5. Implement the §2.7 robustness cross-check using primary_energy_crosscheck from
   config/scenarios.yaml IF enabled: true — if still enabled: false (because the
   YAML TODO wasn't filled in), log a clear WARNING and skip the cross-check
   without failing the pipeline (this one is non-blocking by design, per D4).

Tests: synthetic calibration params + a small PTE fixture table; assert output
schema and source tagging are correct, especially that 2020 is tagged
historical_ons and interpolated years are tagged interpolated.

Acceptance:
- pytest -v passes.
- Acceptance criterion from roadmap §7 enforced: 2020 is never tagged
  pte_projection.
```

---

## 13. TASK 11 — Stage 4: `mitigation.py`

```
TASK 11 — Compute the mitigation deficit, average vs. marginal sensitivity.

Read docs/methodology.md §2.5 first.

Implement src/curtailmit/mitigation.py:

1. Load projection_results.parquet (Stage 3), mcti_average_factor.parquet, and
   mcti_margin_factors.parquet (Stage 1/Task 5).

2. For each (scenario, year) row:
   - Mitigation_deficit_avg(s,t) = E_curt(s,t) × average_factor(t)
   - Mitigation_deficit_marginal(s,t) = E_curt(s,t) × marginal_factor_proxy(t)
     (document which of OM/BM/CM maps to which, per config
     emission_factors.marginal.deb_proxy/reb_proxy, and whether
     classification_available affects which proxy applies — if
     classification_available is false, use a clearly documented default proxy
     and flag it in the output row, e.g. `marginal_proxy_used: "OM_default_no_classification"`).

3. Output DATABASE_ROOT/processed/mitigation_results.parquet with columns
   [scenario, year, E_curt_twh, mitigation_deficit_avg_tco2,
   mitigation_deficit_marginal_tco2, marginal_proxy_used, classification_available].

4. Never report a single collapsed number without the two values + which factor
   was used, per methodology §2.5 — enforce this in the schema (both columns are
   required, not optional).

Tests: synthetic projection + factor fixtures; assert both average and marginal
columns are always populated and correctly traceable to their proxy source.

Acceptance:
- pytest -v passes.
```

---

## 14. TASK 12 — Stage 5: `hydrogen.py`

```
TASK 12 — Compute green-H2 valorization potential.

Read docs/methodology.md §2.6 first.

Implement src/curtailmit/hydrogen.py:

1. Load mitigation_results.parquet (for E_curt) and
   config.electrolyzer.sec_kwh_per_kg_h2 (min/max/central_estimate).

2. For each row: H2_potential_min/central/max(s,t) = E_curt(s,t)_TWh × 1e9 (kWh) / SEC.

3. Output DATABASE_ROOT/processed/hydrogen_results.parquet with columns
   [scenario, year, h2_potential_min_kg, h2_potential_central_kg, h2_potential_max_kg].

4. Never report only the central estimate in any downstream table without the
   min/max range alongside it, per methodology §2.6.

Tests: unit conversion correctness (TWh → kWh), range ordering (min <= central <= max).

Acceptance:
- pytest -v passes.
```

---

## 15. TASK 13 — Stage 6: `results_writer.py`

```
TASK 13 — Persist final tables/figures/reports with all data-quality flags
propagated.

Read docs/roadmap.md §8 (acceptance criteria) and docs/methodology.md §3.7
(Limitations) first.

Implement src/curtailmit/results_writer.py:

1. Merge projection_results, mitigation_results, hydrogen_results into one final
   tidy table, joined on [scenario, year].

2. Propagate `classification_available`, `source` (historical_ons/pte_published/
   interpolated), and `marginal_proxy_used` flags into this final table — every
   row must carry its full provenance.

3. Write:
   - DATABASE_ROOT/outputs/tables/final_results.csv and .parquet
   - DATABASE_ROOT/outputs/reports/limitations_summary.md — auto-generated from
     the actual flags present in the data (e.g. if classification_available is
     False for any scenario, this must appear here verbatim, matching the
     language already in docs/methodology.md §3.7 — do not invent new wording,
     pull from the flags).
   - Basic matplotlib figures (DATABASE_ROOT/outputs/figures/): E_curt by
     scenario/year, mitigation deficit (avg vs marginal) by scenario/year,
     H2 potential range by scenario/year. Each figure's filename and caption
     must indicate whether interpolated points are included.

4. The acceptance criterion from roadmap §7 — "classification_available: false
   must never appear in the paper as DEB/REB" — must be enforced here as a
   runtime check: if classification_available is False, any column/figure
   referencing DEB/REB must instead be labeled "aggregate (unclassified)" —
   write a unit test that fails if this mislabeling ever occurs.

Tests: synthetic merged fixture with classification_available=False; assert the
output report contains the word "aggregate" and does NOT contain "DEB" or "REB"
in that scenario's section.

Acceptance:
- pytest -v passes.
- Running the full mocked pipeline end-to-end (Tasks 8-13 chained) produces a
  complete outputs/ directory.
```

---

## 16. TASK 14 — End-to-end orchestration + CI

```
TASK 14 — Wire everything into scripts/run_pipeline.py and add CI.

1. Rewrite scripts/run_pipeline.py to run Stages 1-6 in order, respecting:
   - pld.enabled flag from config (skip Stage/module if false, per D10).
   - A `--use-cache` CLI flag (argparse) controlling acquisition.py's use_cache
     behavior — default False (always fetch freshest data), explicit opt-in to
     reuse cached raw files for faster iteration during development.
   - A `--integration` flag to also run the @pytest.mark.integration-style live
     calls as part of a manual full run (not part of default CI).

2. Each stage's output path and the final DataQualityReport + limitations_summary.md
   should be printed as a clear console summary at the end of the run.

3. Fill in .github/workflows/ci.yml:
   - Run on push/PR to main.
   - Set up Python 3.11, install requirements.txt + the package itself (pip install -e .).
   - Run `pytest -v -m "not integration"` (never run live network calls in CI).
   - Run `ruff check src tests`.

4. Update Makefile with a `run` target calling scripts/run_pipeline.py.

Acceptance:
- `python scripts/run_pipeline.py` runs end-to-end against mocked/test
  configuration without crashing (document how to run it against a small
  synthetic config for a smoke test, vs. the real one that requires live network).
- CI workflow file is valid YAML and the job list matches the steps above.
```

---

## 17. TASK 15 — Reproducibility pass + documentation sync

```
TASK 15 — Final reproducibility and documentation pass.

1. Add a DATABASE_ROOT/logs/run_manifest_{timestamp}.json at the end of every full
   pipeline run (scripts/run_pipeline.py), aggregating all individual retrieval
   manifests (Task 1) used in that run — this is the single file that lets us say,
   in the paper's methods section, exactly which data vintage produced a given
   result.

2. Update docs/roadmap.md §8 ("Remaining open items") — replace it with actual
   outcomes now that the pipeline has run at least once: which resource_ids were
   discovered, which fallback paths (if any) were triggered, what the final
   calibration parameters were. This section becomes a record of execution
   outcomes, not speculation.

3. Update README.md with real, tested instructions: how to run Stage 1 alone,
   how to run the full pipeline, how to interpret outputs/reports/limitations_summary.md.

4. Confirm every acceptance criterion listed in docs/roadmap.md §7 has a
   corresponding passing test — list them explicitly in a new
   docs/acceptance_criteria_status.md, one row per criterion, with the test
   name that verifies it.

Acceptance:
- All of the above files exist and are internally consistent with the actual
  code behavior (not aspirational).
- Full test suite (excluding integration-marked tests) passes.
```

---

## Appendix — Candidate API/data endpoints to try first (starting points, not final)

These are **starting points for discovery**, not confirmed final URLs — every task
above requires Claude Code to verify them programmatically before relying on them,
per Global Rule #3.

| Source | Base / landing point | Notes |
|---|---|---|
| ONS Dados Abertos | `https://dados.ons.org.br/api/3/action/` | CKAN API. Known package: `restricao_coff_eolica_usi` (wind curtailment). Solar/PV and generation-by-source packages: discover via `package_search`. |
| ANEEL Dados Abertos | `https://dadosabertos.aneel.gov.br/api/3/action/` | Also CKAN-based. Fallback source only (Task 6). |
| MCTI | `gov.br/mcti` — search for "Fator médio de emissão de CO2 do SIN" and "Fatores de Emissão / Margem Operacional, Margem de Construção" | No CKAN API confirmed — requires HTML discovery (Task 5). Confirm current URL before coding against it. |
| CCEE Dados Abertos | `https://dadosabertos.ccee.org.br/` | Confirm whether CKAN or custom REST API (Task 7). Optional module, non-blocking. |

---

## Session restart checklist (paste if starting a new Claude Code session)

```
Before continuing: read docs/roadmap.md, docs/methodology.md, and
docs/claude_commands.md in full. Tell me which Task number we left off at
(check the latest git log and which modules/tests already exist) before writing
any new code.
```
```

---

---
---

# STATUS ADDENDUM (supersedes the tasks listed below where noted)

This section was added after a round of local pre-building and real API
discovery probing, done outside of Claude Code to save tokens. Read this
addendum before starting any of the tasks it references. See also
`docs/progress_log.md` and `config/discovered_sources.yaml` for full detail.

## Tasks marked DONE (pre-built and tested locally; review only, do not rebuild)

- **Task 1** (Retrieval manifest + caching utility): DONE.
  `src/curtailmit/acquisition.py` and `src/curtailmit/paths.py` exist,
  fully tested. Only verify/extend if a real acquisition task surfaces a
  gap in the manifest schema.
- **Task 9** (Stage 2 calibration.py): PARTIALLY DONE. Generic logistic
  fitting machinery (`fit_calibration`, `apply_calibration`,
  `validate_against_holdout`, save/load) is complete and tested in
  `src/curtailmit/calibration.py`. Remaining work: wire in real historical
  ONS curtailment + generation data once Tasks 2 and 3 are complete.
- **Task 11** (Stage 4 mitigation.py): DONE. `compute_mitigation()` is
  complete and tested in `src/curtailmit/mitigation.py`. Review only.
- **Task 12** (Stage 5 hydrogen.py): DONE. `compute_hydrogen_potential()`
  is complete and tested in `src/curtailmit/hydrogen.py`. Review only.

## Task 2 (ONS curtailment acquisition) — enriched with confirmed IDs

Use these CONFIRMED package IDs (discovered via live `package_search` /
`package_show`, not guessed):

- Wind curtailment: `restricao_coff_eolica_usi`
- Solar curtailment: `restricao_coff_fotovoltaica`

Both follow the same resource naming pattern:
`Restricoes_coff_eolicas-YYYY-MM` (and equivalent for fotovoltaica),
available in CSV, XLSX, and (from ~2023 onward) PARQUET formats. Prefer
PARQUET where available for a given month, falling back to CSV.

Do not search for these again. Proceed directly to `package_show` on
each to confirm current resource lists, then implement acquisition.

## Task 3 (ONS generation-by-source) — narrowed, not resolved

No single clean package was found. Two real candidates were identified
via `package_search` (not guessed):

- `geracao-usina-2` ("Geração por Usina em Base Horária") — per-plant
  hourly generation, would require joining against plant metadata to
  aggregate by source type (solar/wind/hydro/thermal).
- `balanco-energia-subsistema` ("Balanço de Energia nos Subsistemas") —
  subsystem-level energy balance, unclear if broken down by source type.

**Your task**: run `package_show` on both, inspect one sample resource's
actual column schema from each, and report back (column names, units,
granularity) before writing any acquisition or aggregation code. Do not
guess the schema or assume which one is correct.

## Task 5 (MCTI emission factor discovery) — narrowed, not resolved

Two real candidate pages were found via actual link extraction on the
SIRENE landing page (not guessed):

1. `https://www.gov.br/mcti/pt-br/acompanhe-o-mcti/sirene/dados-e-ferramentas/fatores-de-emissao`
   (link text: "Fatores de emissão MDL/SIN") — primary candidate.
2. `https://www.gov.br/mcti/pt-br/acompanhe-o-mcti/cgcl/#fatores`
   (link text: "Fatores de emissão de CO2") — secondary candidate.

**Your task**: fetch both pages, extract all `<a href>` links ending in
`.xls`/`.xlsx`/`.csv`/`.zip` or containing "fator"/"emissao"/"margem" in
the href or link text, and report the exact file URLs found. If neither
page yields a usable file link after this, STOP and report back with
what you found rather than guessing further sub-paths or inventing a URL.

## Task 6 (ANEEL fallback) — confirmed reachable

ANEEL Dados Abertos is CONFIRMED CKAN-based and reachable at
`https://dadosabertos.aneel.gov.br/api/3/action/` (`package_search` for
"geracao" returned 10 real results). Proceed with building the fallback
module as originally scoped; no further discovery needed before starting.

## Task 7 (CCEE PLD) — closed as a permanent limitation

CCEE (`https://dadosabertos.ccee.org.br/`) was probed twice, including
once with realistic browser `User-Agent`/`Accept-Language` headers, and
returned HTTP 403 "Acesso bloqueado" both times. This is a CDN/WAF-level
block, not a CKAN or header issue, and will not be resolved by code
changes.

**Your task is reduced to**: build only the minimal `pld.enabled: false`
stub/module boundary as originally scoped (so the pipeline architecture
supports PLD if it's ever unblocked), and add a short note to
`docs/methodology.md` or a new `docs/limitations.md` documenting that
CCEE is not accessible via automated means as of this writing. Do NOT
attempt further automated discovery against CCEE — this has already been
tried twice and is considered closed.
