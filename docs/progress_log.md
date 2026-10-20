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