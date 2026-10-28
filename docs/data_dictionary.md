# CurtailMit — Output Data Dictionary

## Purpose

This document describes every column in the final CurtailMit output dataset
(`results_writer.ResultsRow` / `RESULTS_COLUMNS`), produced by the mitigation-deficit
computation pipeline. For each column: name, unit, data type, and whether it is
**computed** (derived within the pipeline) or **sourced/published** (taken directly
from an external source, e.g. ONS or MCTI).

## Scope

This dictionary documents the schema defined in `src/curtailmit/results_writer.py`
(`ResultsRow` dataclass, `RESULTS_COLUMNS` tuple) — i.e. the final, publication-facing
output rows. It does not document intermediate pipeline artifacts (retrieval
manifests, calibration parameters, raw ONS/MCTI files) — those are documented inline
in their respective modules (`manifest.py`, `calibration.py`, `acquisition.py`).

## Column Reference

| Column | Type | Unit | Computed / Sourced | Description |
|---|---|---|---|---|
| `scenario` | string | categorical | Sourced (config) | PTE scenario identifier (e.g. TB, TA, TG per `config/scenarios.yaml`). Defines the penetration trajectory being evaluated. |
| `year` | int | calendar year | Sourced / Computed | One of the fixed year-grid points {2020, 2025, 2030, 2040, 2050} (headline anchors), or any intervening year when `is_interpolated=True`. 2020 is always sourced from real historical ONS data; 2025-2050 are sourced from PTE/EPE scenario projections (methodology.md Table 2). |
| `source` | string (enum) | - | Metadata | One of `historical_ons`, `pte_projection`, `interpolated`. Declares the provenance of the underlying penetration data for this row. Never `pte_projection` for `year=2020` (enforced in `projection.py` and `results_writer.py`). The value also indicates the generation-total basis (D16): `historical_ons` rows carry ONS/SIN-scope generation totals; `pte_projection` rows carry the PTE/BLUES model's own total-generation scope, which may differ in basis from ONS SIN (BEN 2021 cross-check: ONS SIN is ~89 % of the national total). This is documented and intentional, not an error; no rescaling is applied. |
| `is_interpolated` | bool | - | Metadata (computed) | True iff this row's year is not one of the 5 headline anchor years but was produced by linear interpolation between adjacent anchors (`projection.py::interpolate_series`). Headline tables show only `is_interpolated=False` rows (`projection.py::headline_table`). |
| `classification_available` | bool | - | Metadata (computed / propagated) | True iff ONS curtailment data for this (scenario, year) was available in classified form: DEB ("Razão Energética"), REB ("Confiabilidade"), EUB ("Indisponibilidade Externa", its own category, never merged with DEB/REB). False iff only the unclassified aggregate curtailment figure was available, in which case no DEB/REB breakdown is reported. Propagated end-to-end from `validation.py::ClassificationFlag` and must never silently disappear. |
| `E_curt_twh` | float | TWh (terawatt-hours) | Computed | Total curtailed wind+solar energy for the scenario/year. Represents the aggregate curtailment total (DEB+REB+EUB combined when classified, or the unclassified aggregate when not), derived from P(s,t) = solar_pct + wind_pct (computed in `data_ingestion.py` from ONS generation-by-source data) and the calibrated curtailment function (`calibration.py`), applied on top of PTE-projected generation volumes. |
| `mitigation_deficit_avg_tco2` | float | tCO2 (metric tonnes CO2) | Computed | Lost CO2-mitigation potential = `E_curt_twh` x average SIN emission factor (MCTI monthly "Fator Medio de Emissao de CO2 do SIN", annualized), after TWh->MWh unit conversion. Represents the mitigation that would have occurred if the curtailed renewable energy had displaced average-grid generation. |
| `mitigation_deficit_marginal_om_tco2` | float | tCO2 | Computed | Lost mitigation potential using the Operating Margin (OM) marginal emission factor, used as a **DEB proxy** (economic/"Razao Energetica" curtailment) = `E_curt_twh` x OM. OM = simple mean of MCTI's 12 published monthly OM values for the year (`emission_factors.py::derive_annual_om_from_monthly`). |
| `mitigation_deficit_marginal_cm_tco2` | float | tCO2 | Computed | Lost mitigation potential using the Combined Margin (CM) marginal emission factor, used as a **REB proxy** (reliability/"Confiabilidade" curtailment) = `E_curt_twh` x CM. CM = 0.5 x OM + 0.5 x BM per decision D12 (UNFCCC ACM0002 default weighting), computed in `emission_factors.py::compute_combined_margin` from MCTI's published annual Build Margin (BM) and the derived annual OM. Reported as its own column, never collapsed with `mitigation_deficit_marginal_om_tco2` into one undifferentiated "marginal" figure. |
| `marginal_proxy_note` | string | - | Metadata | Free-text note stating explicitly that OM/CM are used as DEB/REB *proxies* respectively (not official per-cause emission factors), and reflecting the row's `classification_available` state. Included to prevent the marginal figures from being misread as precise causal attributions. |
| `h2_potential_min_kg` | float | kg H2 | Computed | Hydrogen production potential from curtailed energy under the least-efficient electrolyzer case = `E_curt_twh` x 1e9 (TWh->kWh) / SEC_max (55 kWh/kg). Labeled "min" because the higher SEC (less efficient) yields the minimum kg of H2 for a given energy input. |
| `h2_potential_central_kg` | float | kg H2 | Computed | Central-estimate hydrogen production potential = `E_curt_twh` x 1e9 / SEC_central (52.5 kWh/kg). |
| `h2_potential_max_kg` | float | kg H2 | Computed | Hydrogen production potential under the most-efficient electrolyzer case = `E_curt_twh` x 1e9 / SEC_min (50 kWh/kg). Labeled "max" because the lower SEC yields the maximum kg of H2 for a given energy input. |

## Notes on Units and Conventions

- All energy flows are expressed in TWh unless otherwise noted; conversion to kWh
  (x1e9) occurs only inside `hydrogen.py` for the SEC division, and conversion to MWh
  (x1e6) occurs only inside `mitigation.py` before applying tCO2/MWh emission factors.
- All emissions are expressed in tCO2, consistent with MCTI's published emission
  factor units (tCO2/MWh).
- Electrolyzer specific energy consumption (SEC) is always reported as a three-point
  range (min/central/max = 50/52.5/55 kWh/kg H2), never collapsed to a single point
  estimate.
- The mitigation deficit is always computed and reported twice per scenario/year row:
  once using the average SIN factor (`mitigation_deficit_avg_tco2`) and once using the
  marginal factor, which is itself split into two proxy columns (OM for DEB, CM for
  REB) rather than one undifferentiated "marginal" figure. This is a deliberate schema
  decision to keep the DEB/REB proxy distinction visible in the final output.
- `source="pte_projection"` rows derive their underlying penetration shares from
  methodology.md Table 2 (PTE/EPE scenario trajectories: TB/TA/TG), not from any live
  data call.
- `source="historical_ons"` rows (`year=2020` only) derive all inputs (P(s,t),
  curtailment, emission factors) from real published ONS/MCTI historical data, never
  from scenario projection.
- `source="interpolated"` rows are produced only for continuous-curve figures (never
  headline tables) via linear interpolation between adjacent anchor points
  (`projection.py::interpolate_series`) and always carry `is_interpolated=True`.
- EUB ("Indisponibilidade Externa") is tracked upstream as its own curtailment-cause
  category, distinct from DEB and REB, and is never merged into either. It is included
  in the `E_curt_twh` aggregate total but has no dedicated marginal-proxy column, since
  OM/CM proxies map only to DEB/REB respectively.

## Upstream / Intermediate Artifacts (Not Part of This Dictionary)

For completeness, the following intermediate artifacts exist upstream of `ResultsRow`
but are documented in their own modules, not here:

- Raw ONS/MCTI source files and their retrieval manifests
  (`manifest.py`, `config/acquisition_targets.yaml`)
- Calibration parameters for the curtailment function (`calibration.py`)
- Classification flags and validation acceptance criteria (`validation.py`)
- Scenario configuration tables (`config/scenarios.yaml`)

## Final results layer (Task 13, decision D27) - long-format production table

`results_writer.build_final_results` / `final_results.csv` supersedes the wide `ResultsRow` above (kept for backward compatibility, DEPRECATED). One row per scenario x year x quantity x component. Columns: `scenario`, `year`, `quantity` (`curtailed_energy`, `mitigation_deficit_avg`, `mitigation_deficit_marginal_om`, `mitigation_deficit_marginal_cm`, `h2_potential`), `component` (`total`, `wind`, `solar`), `unit` (TWh, tCO2, kg_H2), `central_value`, `conditional_range_low`, `conditional_range_high` (a range implied by stated assumptions, not a probabilistic statement), `range_basis` (mandatory text), `central_inside_range`, `supplement_low`, `supplement_high`, `supplement_basis` (nominal 80 percent split-conformal supplement, 2025-2040 only), `sec_sensitivity_low`, `sec_sensitivity_high` (hydrogen, SEC 55 / 50 kWh/kg), `horizon_treatment` (`band_plus_conformal`, `decomposition_conditional`), `in_support_fraction`, `support_status`, `partially_out_of_support`, `calibrated_label` (False for every 2050 row), `known_limitations` (ids, D25 on every row), `known_limitations_text`, `drift_direction`, `model`, `role`, `source`, `is_interpolated`, `mcti_factor_year` (`2025` central, `mean_2021_2025` in the companion sensitivity table), `emission_factor_basis`, `marginal_proxy_note` (OM = DEB proxy, CM = REB proxy; never summed), `classification_available`, `mcti_sensitivity_avg_2021_2025_central_value`. 2050 ranges are conditional on a flexibility assumption on the energy side; the emission factor is a fixed point value outside the range (D28). See `docs/methodology.md` section 2.3k.

Column notes added in Task 13-2: `central_inside_range` (bool, first-class column of `final_results`) is True when `conditional_range_low <= central_value <= conditional_range_high`; it is False for the wind component in 2025-2040 by construction of the empirical band (backtest errors one-sided, band above the central value), an expected consequence of D25 and not a model error; the total band contains the central value. `sec_sensitivity_low` / `sec_sensitivity_high` (hydrogen only) hold the SEC 55 / 50 kWh/kg bounds outside the conditional range (D30, extension of D28).

## Pipeline stamps and run records (Task 14-15)

Written by `curtailmit-run` under `DATABASE_ROOT`; not part of `final_results`.

**`processed/pipeline_stamps/<stage>.json`** (stage = `stage1`, `calibration`, `projection`, `results`): `schema`, `stage`, `created_utc`, `fingerprint` {`inputs`, `decisions`, `code`, `params`: name -> SHA-256 or value}, `outputs` (name -> SHA-256), `extra`. A stage is skipped only if everything recorded still matches the disk.

**`logs/pipeline_run_<UTC>.json`** (every run, including failures): `started_utc`, `database_root`, `args`, `partial`, `status` (`SUCCESS`, `SUCCESS_PARTIAL`, `DRY_RUN`, `FAILED`), `precheck`, `stages` [{`stage`, `status` SKIPPED/RAN, `kind`, `detail`, `seconds`}], `reference_check`, `outputs`, `failure` {`stage`, `error_type`, `reason`, `gate`, `diagnostics`}.

**`logs/run_manifest_<UTC>.json`** (only `SUCCESS` and `SUCCESS_PARTIAL` runs; see `docs/reproducibility.md` section 9): `schema`, `created_utc`, `status`, `partial`, `run_started_utc`, `code` {`commit`, `dirty`, `branch`}, `environment` {`python`, `platform`, `lock_file`, `lock_file_sha256`, `packages` {name: {`locked`, `installed`}}, `environment_matches_lock`, `mismatches`}, `end_exclusive`, `config_sha256`, `decisions_sha256`, `stages`, `reference_check`, `raw_inputs` {`n_files`, `total_bytes`, `verified_against_retrieval_manifests`, `committed_snapshot`, `files` [{`path`, `source_url`, `retrieved_at_utc`, `http_status`, `sha256`, `byte_size`}]}, `artifacts_sha256`.

**`data_snapshot_manifest.json`** (repository root, committed; D33): `schema`, `description`, `generated_utc`, `n_files`, `total_bytes`, `files` (same per-file fields as `raw_inputs.files`). Written by `python -m curtailmit.run_manifest snapshot`, checked by `... verify`.

**`processed/pipeline_stamps/hash_cache.json`** (Task 16; optional, safe to delete): `schema` 1, `written_utc`, `guard_ns` (5 s), `entries` {path relative to `DATABASE_ROOT` -> `size`, `mtime_ns`, `ino`, `sha256`, `hashed_at_ns`}. A metadata pre-filter for the SHA-256 of files of at least 1 MiB; the stamps do not depend on it and their format is unchanged. `curtailmit-run --no-hash-cache` neither reads nor writes it. See `docs/orchestration.md`.

**`outputs/figures/`** (main figures only; exploratory analysis figures are in `outputs/figures_exploratory/`; Task 13B; local only, D33; written by `python -m curtailmit.figures`): per figure `F1_mitigation_deficit`, `F2_support`, `S1_band_vs_supplement`, `S2_backtest` (since the review of 2026-10-28; the earlier curtailed-energy F1 was dropped and the earlier F4 became F1) a `.png` (1000 dpi; PNG only since the Task 17 housekeeping, `figures.OUTPUT_FORMATS`; no PDF / SVG, the DeCarbon line-art minimum applied to every figure; updated from 600 dpi in Task 13B-finalize), `_data.csv` (the exact frame plotted) and `_caption.txt` (numbers generated from the frame); `figures_manifest.json` records the SHA-256 of the input tables and of every output file, the matplotlib version, `confirmed_decarbon_standards` (dpi, column width), `provisional_decarbon_standards` (font size, palette: the project's own choices) and `figure_width_mm`. S2 is analysis-derived (committed fixture `tests/fixtures/figures/backtest_annual.csv`), not production pipeline output.


**`raw/boundaries/gadm/gadm41_BRA_1.{shp,dbf,prj,cpg}`** (Task 17, decision D36; local-only, never committed): GADM 4.1 level 1, Brazilian states (27 features, WGS 84). Each file has a retrieval manifest (`*.manifest.json`) with `source_url`, `http_status` (null: copied, not fetched), `retrieved_at_utc` (time of the copy), `sha256`, `byte_size`, `original_file_date` (2022-07-18) and a `note`; the four files are in `data_snapshot_manifest.json`. `raw/boundaries` is excluded from the Stage 1 stamp (`pipeline.NON_PIPELINE_RAW`): it is an input of the context figures only.

**`interim/curtailment_by_state_year.parquet`** and **`outputs/tables/curtailment_by_state_year.csv`** (Task 17; built by `python scripts/build_context_data.py [--force]`, not a pipeline stage): observed curtailment by the state of the plant (ONS `id_estado`), technology and calendar year. Columns: `id_estado`, `nom_estado`, `technology` (`wind` / `solar`), `year`, `curtailed_energy_mwh`, `curtailed_energy_twh`, `national_total_mwh` (the classified-table total of that technology-year), `share_of_national_pct` (shares of a technology-year sum to 100), `months_covered`, `is_partial_year`. Built from `processed/ons_curtailment_classified.parquet`; the sum over states reconciles with the national total at rtol 1e-9 (hard gate); a plant name mapping to more than one state stops the build.

**`outputs/figures/C1_*`, `C1S_*`, `C2_*`** (Task 17; `python -m curtailmit.figures_context`): context figures, PNG (1000 dpi) + `_data.csv` + `_caption.txt`, entries in the same `figures_manifest.json` (inputs include the SHA-256 of the boundary shapefile and of the state-year table). C1 / C1S: observed curtailment by state (share of the national total, `cividis`); C2: dose-response curve with the observed-support boundary. Observed data and calibration outputs only: not a projection (the projected regional map, decision D37, is not implemented).
