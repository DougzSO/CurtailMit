# CurtailMit

Quantifying the curtailment-driven CO2 mitigation deficit under Brazil's PTE/EPE energy transition scenarios, with green-hydrogen valorization potential.

Target venue: DeCarbon.

**Model in one paragraph.** Wind and solar curtailment of the Brazilian interconnected system (SIN) is modelled hourly: the curtailment rate of each technology is a bounded logistic function of the hourly potential share of wind and solar in the load (Option E, decision D24), fitted on the ONS record 2022-2026 and applied to the 2025 hourly profile scaled to each PTE scenario (TB, TA, TG) and year (2025, 2030, 2040, 2050). Curtailed energy is converted to a mitigation deficit (average, OM and CM emission factors, never summed) and to green-hydrogen potential. Results are ranges implied by stated assumptions, not confidence intervals; the 2050 rows are conditional. Known limitation (D25): wind curtailment drifts upward over time, so central values are more likely low than high.

## Repositories

| | |
|---|---|
| `curtailmit` (this repository, public) | code, configuration, documentation, tests, committed fixtures |
| `curtailmit_database` (sibling directory, **local only**) | raw / interim / processed data, logs, output tables; never published here |

Set `DATABASE_ROOT` in `.env` (copy `.env.example`; default `../curtailmit_database`). The raw data are open ONS and MCTI downloads fetched by Stage 1; this repository publishes their identities (`data_snapshot_manifest.json`: URL, retrieval time, SHA-256, size), not the data. See `docs/reproducibility.md`.

## Setup

```
python -m venv .venv
.venv\Scripts\Activate.ps1            # Linux/macOS: . .venv/bin/activate
pip install -r requirements.lock.txt   # exact versions of the verified environment (Python 3.11)
pip install -e . --no-deps
copy .env.example .env                 # Linux/macOS: cp .env.example .env
```
`make setup-locked` does the same (Windows paths); `make setup` is the flexible development install. For development with the newest compatible releases instead: `pip install -e ".[dev]"` (floors in `requirements.txt` / `pyproject.toml`; CI tests both).

## Run

```
curtailmit-run                  # whole pipeline; same as: python -m curtailmit.pipeline
curtailmit-run --dry-run        # validate configuration and show what would run; writes nothing
curtailmit-run --use-cache      # reuse SHA-256-verified cached downloads
curtailmit-run --skip-stage1    # explicit partial run on the existing Stage 1 products
python -m curtailmit.data_ingestion   # Stage 1 alone (acquisition + data-quality report)
```
The stage sequence is in `docs/orchestration.md` (generated from the code). A stage is skipped only when its stamp verifies; otherwise it is recomputed. Output: `final_results.csv/.parquet` (156 rows, long format) under `DATABASE_ROOT/outputs/tables`. Hard gates stop the run with exit code 2. Details: `docs/orchestration.md`.

## Tests and checks

```
pytest -m "not integration"     # unit suite (what CI runs, with an empty DATABASE_ROOT)
pytest -m integration           # needs the local curtailmit_database (and some, the network)
ruff check src tests
python -m curtailmit.run_manifest verify   # local raw files vs data_snapshot_manifest.json
python -m curtailmit.doc_generation --check   # generated documentation blocks vs their sources
```

## Documentation (map)

| Document | Content |
|---|---|
| `docs/reproducibility.md` | start here to reproduce the numbers: environment, data, run, why Option E, decision register |
| `docs/methodology.md` | the model (section 2.3j, current) and results layer (2.3k); earlier sections are the historical record |
| `docs/orchestration.md` | the `curtailmit-run` command, skip logic, gates, CI |
| `docs/roadmap.md`, `docs/progress_log.md`, `docs/claude_commands.md` | plan, history by task, task prompts (append-only history, with update notes) |
| `docs/pre_submission_checklist.md` | open items to close by hand before submitting the article (ONS/MCTI licensing) |
| `docs/task13b_design.md`, `src/curtailmit/figures.py` | article figures F1, F2, F4, S1, S2 (`python scripts/generate_figures.py`; implemented; raster 1000 dpi and column widths follow the DeCarbon author guide; NOT yet accepted: final human look pending; automated checks: `python -m curtailmit.figure_checks`) |
| `docs/task17_design.md`, `src/curtailmit/{spatial,context_data,figures_context}.py` | context figures C1 / C1S (observed curtailment by state, `python scripts/build_context_data.py` then `python -m curtailmit.figures_context`) and C2 (dose-response curve); boundary geometry GADM 4.1 is local-only (D36); the projected regional map (D37) is pending and NOT implemented |
| `docs/limitations_summary.md` | the limitations of the production model by theme, generated from the decisions and the output table caveats |
| `docs/acceptance_criteria_status.md` | roadmap acceptance criteria against the production table |
| `docs/data_dictionary.md` | output columns and run records |
| `config/discovered_sources.yaml` | the adopted decisions D13 onward with their texts |

Reproducibility promise: same environment, inputs and machine give byte-identical products; elsewhere the results must match `tests/fixtures/final_results/reference_totals.json` within 1e-9 (checked on every run).

*Updated for Task 15.*
