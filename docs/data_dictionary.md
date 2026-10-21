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