# Task 13-1 - Design proposal: `results_writer.py` (OM/CM split and final output layer)

Status: PROPOSAL, awaiting explicit approval. Design only: no `src/` file and no test was changed in this task. Implementation is Task 13, contingent on approval of this document and on the three decisions in section 0.

Inputs read for this design: `src/curtailmit/results_writer.py` (existing), `mitigation.py`, `projection.py` (Task 11F), `limitations.py`, `emission_factors.py`, `hydrogen.py`, `schemas.py`, `docs/data_dictionary.md`, `tests/test_results_writer.py`, `tests/test_data_dictionary.py`, `docs/claude_commands.md` (Task 13 text), D12, D18, D23-D26, and the real table `processed/pte_curtailment_option_E.parquet` (12 rows).

## 0. STOP-AND-REPORT items (decisions for the user; nothing was assumed)

### 0.1 A legacy `results_writer.py` already exists (commit `62d5189`, Task pre-crisis; `9818fa6` only lint)

- **What it is:** a pure schema + I/O layer. Frozen dataclass `ResultsRow` (one row per scenario x year: `scenario, year, source, is_interpolated, classification_available, E_curt_twh, mitigation_deficit_avg_tco2, mitigation_deficit_marginal_om_tco2, mitigation_deficit_marginal_cm_tco2, marginal_proxy_note, h2_potential_{min,central,max}_kg`), `RESULTS_COLUMNS`, `write_results_csv/json`, `load_results_csv/json`. It computes nothing.
- **What consumes it:** only `tests/test_results_writer.py` and `tests/test_data_dictionary.py` (which checks that every `RESULTS_COLUMNS` name appears in `docs/data_dictionary.md`). `scripts/run_pipeline.py` has only a comment ("Stage 6 ... to be added incrementally"). It is **not reachable from any active entry point and has never produced an output file**; no article table or figure currently depends on it.
- **Conflict assessment:** it produces no figures, so it does not contradict any Option E number. It conflicts **structurally** with the Task 13-1 requirements: one scalar `E_curt_twh` (no central/range, no horizon treatment), no `known_limitations`/`calibrated_label`/`support_status`, `year` documented as the grid {2020, 2025, ..., 2050}, a validator that raises if `source == "historical_ons"` is flagged interpolated and so on, and the older Task 13 text in `docs/claude_commands.md` says "do not change this schema". That sentence predates D23-D26 and the 2050 conditional range.
- **Options (user decision, registered as pending decision candidate `D27` in `config/discovered_sources.yaml`):**
  - **A (recommended): supersede inside the same module.** Keep the file name `results_writer.py` (README, roadmap and data dictionary all name it). Add the new long-format schema and writer below the legacy code; mark `ResultsRow`, `RESULTS_COLUMNS` and the four legacy I/O functions `Deprecated (superseded by FinalResultsRow, Task 13)` in docstrings, keep them importable and tested so nothing breaks, and annex a legacy-to-new mapping in the data dictionary. No second module with a near-identical name.
  - **B: coexist.** Keep `ResultsRow` as the 2020 historical-baseline row format and use the new schema for projections. Justification would be that the 2020 baseline (`source="historical_ons"`) is not in the Option E table. Cost: two final-output schemas in the repo; risk that a legacy-format file reaches the article.
  - **C: freeze and put the new writer in a differently named module** (for example `final_results.py`). Same coexistence cost as B plus a misleading name.
  - Until decided, the legacy code is untouched.

### 0.2 OM/CM split versus the horizon-dependent range (decision candidate `D28`)

Arithmetically there is no ambiguity: mitigation is `E x factor(year)` with a deterministic scalar factor per year, so the map is linear and monotone, and "apply the range, then split" equals "split, then apply the range" to floating-point precision (the design proposes a test for this). The real questions, registered as pending rather than assumed:

1. **The 2050 range is conditional on a flexibility assumption on the energy side only** (phi = 1.5 lower bound, L = 1 upper bound). The emission factors are not conditioned on the same assumption (a more flexible 2050 system would also have a different marginal mix). Proposal: pass the energy range through the same factor and label it so (`range_basis` states that the factor is held at one MCTI year and is not part of the range).
2. **OM and CM are alternative proxies for the marginal factor (D12), not components.** They must never be summed or shown as a stacked total. Proposal: separate `quantity` rows, each with its own central value and range.
3. **The conformal supplement (2025-2040) maps through the factor unchanged** (monotone transformation keeps the coverage statement), but it is a different object from the empirical band and must stay in its own columns.
4. **Factor uncertainty is not in any range** (MCTI factors treated as exact). Declared in `range_basis`.

Recommended handling: as above, applied after the split, each of avg, OM and CM with its own range from the same energy endpoints. If the user prefers a different convention this changes only the writer, not the model.

### 0.3 MCTI factor-year for projection years (decision candidate `D29`; already flagged as a Task 13 duty in D18's `caveat` and in the roadmap)

MCTI margins exist only for completed years (2020-2025 in config); the projection grid is 2025/2030/2040/2050. A rule is needed for 2030-2050. Options: (a) hold the latest complete year (2025) constant (recommended default, simplest, sign of bias unknown); (b) multi-year mean of 2021-2025 (smooths hydrology-driven swings: average factor ranges 0.0385-0.1263 over 2021-2025); (c) a sensitivity set reporting both. Whatever is chosen is logged per row in `emission_factor_basis`. This design uses (a) as a placeholder in examples only.

### 0.4 Vocabulary note (no decision needed, flagged for confirmation)

The task text gives `"empirical_band"`, `"conformal_supplement"`, `"conditional_range"` as example `horizon_treatment` values. The production table (Task 11F) carries two values: `band_plus_conformal` (2025/2030/2040) and `decomposition_conditional` (2050). The design **inherits the production values verbatim** (never renames a value across the pipeline), and expresses the finer distinction in `range_basis` and in the separate supplement columns. If the user prefers the three-term vocabulary, the mapping would live in `projection.py`, not in the writer.

### 0.5 Scope note

The Option E table has no 2020 row (the 2020 baseline of D1 is historical, `source="historical_ons"`). Proposal: the final table covers the projection grid 2025/2030/2040/2050 x {TB, TA, TG}; 2020 appears only if the user wants a historical reference row (then with `horizon_treatment="historical_observed"`, `model="historical_ons"`, `range` columns empty and `calibrated_label` not applicable). Default: not included.

## 1. Module placement and public API

Placement (assuming option A of 0.1): `src/curtailmit/results_writer.py`, layered, **no new numeric computation** beyond calling existing functions:

```
processed/pte_curtailment_option_E.parquet
        |  load_option_e_table()            (checks sidecar present, reads limitations payload)
        v
mitigation.compute_mitigation(..., require_model=True)     <- hard guard, section 5
        |  (+ OM and CM columns, section 3)
        v
hydrogen.compute_hydrogen_potential(...)
        v
results_writer.build_final_results()  ->  long DataFrame (section 2)
        v
results_writer.write_final_results()  ->  CSV + parquet + sidecar JSON + data-dictionary check
```

Public functions:

```python
FINAL_RESULTS_FILENAME = "final_results"              # -> .csv, .parquet, .limitations.json
class ModelProvenanceError(ValueError): ...           # defined in mitigation.py, re-exported here

def load_option_e_table(processed_dir: Path | None = None) -> pd.DataFrame
def build_final_results(
    option_e: pd.DataFrame,
    average_factors: pd.DataFrame,      # [year, factor_tco2_per_mwh]
    marginal_factors: pd.DataFrame,     # [year, om_factor, cm_factor]
    factor_year_rule: FactorYearRule,   # D29, logged in emission_factor_basis
    classification_available: bool,
    sec: tuple[float, float, float],    # kWh/kg H2 min/central/max
) -> pd.DataFrame
def validate_final_results(df: pd.DataFrame) -> None      # schema, forbidden words, per-row caveats, ordering
def write_final_results(df: pd.DataFrame, out_dir: Path | None = None) -> dict[str, Path]
def read_final_results(path: Path) -> pd.DataFrame        # re-validates on load
```

`compute_mitigation` changes (additive, Part A of the old Task 13 text): compute `mitigation_deficit_marginal_om_tco2` and `mitigation_deficit_marginal_cm_tco2` (and `_low`/`_high`, wind/solar) from `om_factor` and `cm_factor`; keep the existing single `marginal` columns for backward compatibility with `MitigationRow`. `marginal_proxy_used` text says OM is the DEB proxy and CM the REB proxy and that they are proxies of curtailment cause, not official per-cause factors (D12), reflecting `classification_available`.

## 2. Output schema (long format: one row per scenario x year x quantity x component)

Long format is needed because the required names `central_value`, `conditional_range_low`, `conditional_range_high` are single columns applying to several quantities (TWh, tCO2, kg H2). Every row repeats the caveat columns, so any filtered subset or spreadsheet copy still carries them.

| Column | Type | Meaning |
|---|---|---|
| `scenario` | str | TB / TA / TG |
| `year` | int | 2025, 2030, 2040, 2050 |
| `quantity` | str | `curtailed_energy`, `mitigation_deficit_avg`, `mitigation_deficit_marginal_om`, `mitigation_deficit_marginal_cm`, `h2_potential` |
| `component` | str | `total`, `wind`, `solar` (`h2_potential` only `total`) |
| `unit` | str | `TWh`, `tCO2`, `kg_H2` |
| `central_value` | float | model central value (Option E, D23 gross basis) |
| `conditional_range_low` / `conditional_range_high` | float | end points of the range described by `range_basis`; **not a statistical interval** |
| `range_basis` | str | free text, mandatory, never empty (examples below) |
| `supplement_low` / `supplement_high` | float | split-conformal 80 percent supplement; **NaN for 2050 and for components without one**; see `supplement_basis` |
| `supplement_basis` | str | `split_conformal_nominal_80_finite_sample_rule` or `not_available_2050_exchangeability_not_certifiable` |
| `horizon_treatment` | str | inherited verbatim: `band_plus_conformal` or `decomposition_conditional` |
| `in_support_fraction` | float | share of the curtailed energy from hours with an historical analogue |
| `support_status` | str | `within_support`, `partially_out_of_support`, `mostly_out_of_support` (rule in `projection.support_status`) |
| `partially_out_of_support` | bool | True for TA 2040 and for every 2050 row |
| `calibrated_label` | bool | True only where the 2025-2040 backtest/conformal treatment applies; **False for all 2050 rows** |
| `known_limitations` | str | ids, `D25;SOLAR_SHORT_RECORD` (from the table, which got them from `limitations.py`) |
| `known_limitations_text` | str | one fixed human-readable sentence (section 4) so a copy-pasted row is self-explaining |
| `drift_direction` | str | `upward` (central values more likely low than high, D25) |
| `model`, `role` | str | `option_E_hourly`, `production` |
| `emission_factor_basis` | str | quantity-specific: factor name (average, OM, CM), MCTI source year used and the D29 rule; `not_applicable` for TWh and kg H2 |
| `marginal_proxy_note` | str | OM = DEB proxy, CM = REB proxy; "aggregate (unclassified)" wording when `classification_available` is False (no DEB/REB labels then) |
| `classification_available` | bool | propagated |
| `source`, `is_interpolated` | str, bool | `pte_projection`, False (headline anchors) |

Forbidden anywhere in this file (columns, `range_basis`, docstrings, sidecar, data dictionary entries for 2050): names or descriptions using `ci_low`, `ci_high`, `confidence*`, `credible`, "interval" for the conditional range. The conformal supplement is described as "nominal 80 percent split-conformal prediction interval, finite-sample rule", and only for 2025-2040.

Range semantics per horizon (the only difference between rows):

| Horizon | `conditional_range_*` source | `range_basis` | supplement |
|---|---|---|---|
| 2025, 2030, 2040 | `E_curt_*_twh_low/high` (empirical annual-backtest band, Task 11E3) | `empirical_annual_backtest_band_task11e3_not_a_coverage_guarantee` | conformal 80 |
| 2050 | `E_curt_*_twh_low/high` = flexibility-conditional (phi 1.5 lower, L = 1 upper) | `flexibility_assumption_phi_1.5_to_L1_conditional_not_statistical` | NaN |

For tCO2 and kg H2 the same endpoints are passed through the factor or SEC; `range_basis` is extended with `; emission_factor_held_at_<year>_not_in_range` (D29) or `; SEC_central_52.5`. The SEC sensitivity (50 / 52.5 / 55 kWh/kg) is a separate axis: for `h2_potential` it is carried in two extra columns `sec_sensitivity_low/high` (NaN for other quantities), never mixed into the energy range.

Example rows (values from the real table; tCO2 uses the 2025 average factor 0.0461 tCO2/MWh and a placeholder OM/CM for illustration only):

| scenario | year | quantity | component | central_value | conditional_range_low | conditional_range_high | horizon_treatment | support_status | calibrated_label | supplement (low, high) |
|---|---|---|---|---|---|---|---|---|---|---|
| TB | 2025 | curtailed_energy | total | 43.78 TWh | 42.50 | 53.02 | band_plus_conformal | within_support | True | 14.78, 129.67 |
| TB | 2030 | curtailed_energy | total | 64.27 TWh | 60.72 | 76.53 | band_plus_conformal | within_support | True | 21.70, 190.34 |
| TA | 2040 | curtailed_energy | total | 242.37 TWh | 237.50 | 295.29 | band_plus_conformal | **partially_out_of_support** | True | 81.83, 717.83 |
| TB | 2050 | curtailed_energy | total | 354.77 TWh | 230.90 | 432.13 | decomposition_conditional | mostly_out_of_support | **False** | NaN, NaN |
| TB | 2050 | mitigation_deficit_avg | total | 354.77e6 x f | 230.90e6 x f | 432.13e6 x f | decomposition_conditional | mostly_out_of_support | False | NaN, NaN |

Every row also carries `known_limitations = "D25;SOLAR_SHORT_RECORD"`, `drift_direction = "upward"`, `model = "option_E_hourly"`.

Note: the conformal supplement for the total is an approximation (unified logq applied to the sum of the central values, documented in methodology 2.3j); the per-technology supplements are exact. The writer keeps this and says so in `supplement_basis` for `component == "total"`.

## 3. OM/CM split

- OM: `E x om_factor(year)`, labelled **DEB proxy**. CM: `E x cm_factor(year)`, labelled **REB proxy**, `cm_factor = 0.5 OM + 0.5 BM` from `emission_factors.compute_combined_margin` (D12; `cm_is_derived` flagged, never presented as an MCTI-published figure). Average: `E x factor_tco2_per_mwh(year)`.
- `compute_mitigation` is the **only** place where `TWh x 1e6 x factor` is evaluated; the writer never re-implements the arithmetic. The conformal supplement is scaled by calling `compute_mitigation` on a derived frame whose `E_curt_twh` is the supplement end point, so no second formula exists.
- Both OM and CM rows exist for every scenario/year/component; the validator fails if one is missing.
- Factor year per 0.3; factor coverage checked by `validation.validate_mcti_factor_coverage`.

## 4. `known_limitations` and `calibrated_label`: source and serialization

- **Source of truth:** the text of D25 is loaded from `config/discovered_sources.yaml` by `limitations.d25_limitation()` (fails if D25 is not `adopted`). The Option E table already carries per-row ids (`known_limitations`, `drift_direction`) and `calibrated_label` (Task 11F). The writer **reads these from the table rows, never from constants**, and fails if a row lacks them or if `D25` is not in `known_limitations` for a production row.
- **Per row:** `known_limitations` (ids), `known_limitations_text` (a fixed one-sentence summary built from `limitations.D25_QUANTIFIED` and `SOLAR_NOTE`: "Central values are more likely low than high (residual upward drift of the wind curtailment rate, D25: +1.4 to +1.6 pp per year 2022-2026); solar fitted on 30 months; 2050 figures are conditional on a flexibility assumption, not a calibrated forecast."). The 2050 clause is added only for 2050 rows. Summary length is capped (about 300 characters) and a test pins the figures to `D25_QUANTIFIED`, so it cannot drift from the YAML.
- **File level:** the full D25 text and the D26 sensitivity note go into `final_results.limitations.json` and into the parquet metadata key `curtailmit_limitations` (reuse `limitations.write_table_with_limitations`); the CSV has the row-level columns, plus a header comment is **not** used (it would break readers); the sidecar sits next to it.
- **`calibrated_label`:** copied from the table (True 2025-2040, False 2050); the validator rejects any 2050 row with True and any `decomposition_conditional` row with True.
- The article figure data inherit the same long table, so a plotted 2050 point can be styled by `calibrated_label` and `range_basis` without a lookup.

## 5. `require_model=True` guard

Today the guard only checks that a `model` column exists. Design: strengthen it to the requested behaviour.

```python
class ModelProvenanceError(ValueError):
    """Raised by mitigation.compute_mitigation(require_model=True) when the projection table is not entirely option_E_hourly."""

REQUIRED_MODEL = "option_E_hourly"
if require_model:
    if "model" not in df.columns: raise ModelProvenanceError("... no 'model' column ...")
    bad = sorted(set(df["model"].dropna().astype(str)) - {REQUIRED_MODEL}) or df["model"].isna().any()
    if bad: raise ModelProvenanceError(f"require_model=True: expected every row model == 'option_E_hourly', found {bad}. Reference tables (reference_*) must not feed headline results; use require_model=False and the 'reference_' output prefix.")
```

It is an **exception** (subclass of `ValueError`, so existing callers and tests that catch `ValueError` still work), raised before any arithmetic; never a log line or warning. NaN or missing `model` values also raise. The reference tables from Task 11F keep working with `require_model=False` and the existing `output_prefix`. The guard also verifies `role == "production"` when the column exists. One existing 11F test (`tests/test_projection_hourly.py:213-214`, accepts a labelled reference table with `require_model=True`) is updated for the stricter semantics.

## 6. Support-status propagation (TA / 2040)

`projection.support_status` (E_out >= 0.50 mostly; E_out >= 0.30 or H_out >= 0.10 partially; else within) already produces `support_status` and `partially_out_of_support` in the table (TA 2040 = partially; 2050 all = mostly). The writer copies both **unchanged per row**, plus `in_support_fraction`, to every quantity and component row of that scenario-year, so TA 2040 tCO2 and H2 rows also carry "partially_out_of_support". `validate_final_results` recomputes the rule from the `E_out` column kept in the sidecar-free intermediate and fails on a mismatch. Rule thresholds are not re-implemented in the writer; it imports `projection.support_status`.

## 7. Test plan

Unit (mocked inputs, default suite, no DATABASE_ROOT):
1. Guard: a frame with `model` missing / one row `reference_national_curve` / NaN model / `role == reference` raises `ModelProvenanceError` (and is a `ValueError`); a clean frame passes; an exception, not a log record (assert via `caplog` that no substitute warning is used).
2. OM/CM: both populated on every row; `OM = E x om_factor`, `CM = E x cm_factor`, `CM = 0.5 OM_f + 0.5 BM_f` traceable; OM and CM never summed (no column equals their sum); linearity test: range-then-split equals split-then-range to 1e-12.
3. Schema: exactly the required column names present (`central_value`, `conditional_range_low`, `conditional_range_high`, `range_basis`, `horizon_treatment`, `known_limitations`, `calibrated_label`); `range_basis` never empty; ordering `low <= central <= high`.
4. Forbidden language: no column or `range_basis` matches `ci_|confidence|credible`; the module docstrings and the data dictionary section for 2050 contain none of them (regex over source text).
5. Per-row caveats: after filtering any subset (e.g. `year == 2050`, `quantity == mitigation_deficit_marginal_cm`) and after a CSV round trip, `known_limitations`, `calibrated_label`, `support_status`, `drift_direction` are present and non-null on every row.
6. 2050: `calibrated_label` False, supplement NaN, `supplement_basis` explanatory; 2025-2040: supplement present and `calibrated_label` True; a 2050 row with True fails validation.
7. TA 2040 `partially_out_of_support` True and propagated to every quantity row; recomputation mismatch fails.
8. D25 not adopted (temp YAML with `status: pending`) -> `LimitationError`; summary sentence figures match `D25_QUANTIFIED`.
9. `classification_available=False`: notes and column text say "aggregate (unclassified)" and do not contain "DEB"/"REB" (the existing Task 13 acceptance test).
10. Legacy compatibility (if option A): `ResultsRow` tests keep passing; deprecation noted in docstring (test the docstring marker).
11. Factor coverage missing for a year -> explicit error; D29 rule recorded in `emission_factor_basis`.

Integration (`pytest -m integration`, real `processed/pte_curtailment_option_E.parquet`):
- Reads the real 12-row table; `build_final_results` + `write_final_results` run end to end with the real MCTI factors in `processed/`.
- Row count equals 12 scenario-years x the defined quantity/component grid; every row has `model == "option_E_hourly"`.
- Energy central values equal the table (TB 2050 354.77, TA 2040 242.37, ...) to 1e-9; tCO2 equals `central x 1e6 x factor`.
- All 2050 rows: `calibrated_label` False, `horizon_treatment == "decomposition_conditional"`, supplement NaN, `range_basis` contains `flexibility_assumption`; no forbidden column name.
- TA 2040 rows: `partially_out_of_support` True; the other 2040 rows False.
- Every row: `known_limitations` contains `D25`; sidecar JSON and parquet metadata hold the verbatim adopted D25 text (equal to `limitations.d25_limitation()["text"]`).
- A round trip (write, read, validate) reproduces the frame exactly; filtering to a single row keeps the caveats.

Also: update `docs/data_dictionary.md` (new section; legacy mapping), `tests/test_data_dictionary.py` extended to the new schema's column names, ruff clean, one commit.

## 8. What Task 13 would deliver after approval

Items 1-11 above, `compute_mitigation` OM/CM extension, `ModelProvenanceError`, final long table (CSV, parquet, sidecar), data-dictionary and methodology section (an "Output layer" paragraph in 2.3j, append-only), limitations summary generated from the flags, and the three figure data frames (E_curt, avg vs OM vs CM, H2 with SEC axis) with filenames stating whether interpolated points are included. Figures themselves (matplotlib) follow the old Task 13 Part C scope, to be confirmed at approval.

## 9. Questions to answer at approval

1. Legacy `ResultsRow`: A (supersede in the same module, recommended), B or C? (D27)
2. OM/CM versus range handling as in 0.2: approve? (D28)
3. Factor-year rule for 2030-2050: (a) hold 2025, (b) 2021-2025 mean, (c) both as sensitivity? (D29)
4. Keep inherited `horizon_treatment` vocabulary (recommended) or rename to the three-term set?
5. Include a 2020 historical reference row? (default no)
6. Figures in Task 13 (Part C) or a follow-up task?
