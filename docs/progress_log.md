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
