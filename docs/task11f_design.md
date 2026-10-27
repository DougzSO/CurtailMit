# Task 11F-1 - Design proposal: production migration of option E into `src/`

Status: ~~PROPOSAL, awaiting explicit approval.~~ **Update (Task 15 sync): approved and implemented in commit `bfd1e80` (Task 11F).** The text below is the design as proposed; the implemented behaviour is `docs/methodology.md` section 2.3j. No `src/` file has been changed. D23-D26 are all adopted (D25 locked in 11F-0, commit `0598e70`).

Existing production pieces this design must coexist with: `calibration.py` (monthly national-P logistic, D22: `fit_calibration`, `run_calibration`, `CalibrationResult`, bootstrap CI), `projection.py` (`project_curtailment_two_curves` -> table `pte_curtailment_two_curves.parquet`, consumed by `mitigation.compute_mitigation` through the columns `E_curt_twh[_low|_high]`, `E_curt_{wind,solar}_twh[_low|_high]`, `extrapolated_{wind,solar}`), `mitigation.py`, `results_writer.py`.

## 1. Where the hourly dose-response logic lives

**Proposal: a new module `src/curtailmit/hourly_model.py`; `calibration.py` stays as the (labeled) monthly national/regional reference.**

Why not extend `calibration.py`: it is organised around the monthly frame (`calibration_frame.parquet`, one row per month, `P` = national monthly penetration) and its `CalibrationResult` has fixed fields `wind/solar/combined_diagnostic`; the hourly model has a different input (hourly SIN panel), a different driver (r), a different support notion (populated bins, r_cap) and extra outputs (distance metrics). Folding it in would make that file mix two unrelated data models. `hourly_model.py` re-uses only `calibration.logistic`-style maths (re-implemented as `logistic_rate(x, L, k, x0)`, the same formula as `task11e_common.logistic_w`) and does not import the monthly code.

Contents (pure functions + small frozen dataclasses, no network, no global paths except the two I/O wrappers):

| Piece | Signature (sketch) | Replaces (analysis) |
|---|---|---|
| panel | `build_hourly_panel(balance, curtailment, solar_dispatched, load) -> DataFrame` (index hourly; cols `wind, curt_wind, solar_disp, curt_solar, load, r`) | `task11e_common.hourly_panel` / `sin_hourly` |
| bins | `MonthBins(h, real, curt, xcol="r", width=2.0)` with `.bins(w)` | `task11e2_common.MonthBins` |
| fit | `fit_hourly_curve(bins, min_hours=15, L_fixed=None) -> HourlyCurve` | `fit_logistic` / `fit_binned` |
| curve | `HourlyCurve(technology, L, k, x0, r_cap, n_months, n_hours, window)` with `.rate(r)` | tuple `(L,k,x0)` + `r_cap_of` |
| bootstrap | `bootstrap_hourly_params(mb, n, seed, L_fixed)` | `bootstrap_params` |
| distance | `extrapolation_metrics(r, pot, curve) -> dict(E_out, H_out, D_pp)` | `task11e3_error_growth.distance_metrics` |
| scaling | `scale_profile(base, pte_row, base_row, phi=1.0) -> r_h` ; `projected_rate(r, pot, curve, cap=False)` | `base_profile`, `scale_factors`, `projected_r`, `projected_rate` |
| I/O | `run_hourly_calibration(interim_dir, processed_dir) -> HourlyCalibration` (writes `hourly_curve_{wind,solar}.json`) | scripts |

Window and spec fixed as adopted: wind and solar fitted on their own populated samples (2022-01.. for wind, solar from its 30 months), bins of 2 pp, >=15 hours, potential-weighted bounded logistic, gross basis (D23), base-year profile 2025 scaled by PTE totals.

## 2. By-horizon reporting in `projection.py`

New entry point (the existing two-curve function is kept; see section 4):

```python
def project_curtailment_hourly(pte_table, hourly: HourlyCalibration, bands: HorizonBands,
                               years=PROJECTION_YEARS, phi_low=1.5) -> pd.DataFrame
```

`HorizonBands` (in `hourly_model.py` or a small `uncertainty.py`) holds the *calibrated inputs* of the uncertainty treatments, so `projection.py` is pure application:
- empirical annual-backtest band (Task 11E3): per technology and horizon, relative half-widths;
- conformal supplement (Task 11E4): finite-sample weighted split-conformal quantile function `conformal_interval(scores, weights, alpha)` (rule `ceil((n+1)(1-alpha)) <= n`, test weight 1; returns `inf` when infeasible - this is what makes 2050 unbounded);
- 2050 flexibility-conditional range parameters (phi 1.5 .. L=1).

One row per (scenario, year); output schema = existing columns (so `compute_mitigation` is unchanged) plus:

| Column | Meaning |
|---|---|
| `model` = `"option_E_hourly"` | production model label |
| `horizon_treatment` | `"band_plus_conformal"` (2025, 2030, 2040) / `"decomposition_conditional"` (2050) |
| `E_curt_*_twh`, `_low`, `_high` | central; low/high = **empirical band** for 2025-2040; for 2050 low/high = **flexibility-conditional range** (phi=1.5 .. L=1), explicitly *not* a confidence interval |
| `conformal80_lo_twh`, `conformal80_hi_twh` | supplement, 2025-2040 per technology/total where certifiable; NaN otherwise; for 2050 always NaN |
| `conformal_available` (bool) | False for 2050 (exchangeability violated; procedure unbounded) |
| `in_support_fraction` | share of hourly potential energy with r <= r_cap |
| `curt_in_support_twh`, `curt_out_support_twh` | decomposition (reported for all years; headline for 2050) |
| `E_out`, `H_out`, `D_pp` | distance metrics (Task 11E3) |
| `partially_out_of_support` (bool) | True when out-of-support hours are material (TA 2040: 14.5% of hours, 30-45% of curtailment); same flag convention as `extrapolated_*` (kept, now defined on r_cap) |
| `calibrated_label` (bool) | False for 2050 - no "calibrated" label, no probability |
| `known_limitations` | see section 3 |
| `interpolated`/`classification_available` | untouched flags from existing tables; passed through where present |

Rules enforced in code (with tests): 2050 rows never carry a conformal value or `calibrated_label=True`; the total conformal interval is only emitted where the sum was certified in 11E4 (otherwise NaN).

## 3. Propagating the D25 limitation into outputs

- A module constant `KNOWN_LIMITATIONS = {"D25": {...}}` in a new `src/curtailmit/limitations.py`, loaded **from `config/discovered_sources.yaml`** (D25 `decided` text, verbatim) rather than duplicated, with a loader that fails loudly if D25 is not `adopted`. This ties the output to the adopted text (single source of truth).
- Every wind-containing row (wind and total columns) carries `known_limitations = "D25"` (short id) and `known_limitations_text` is NOT repeated per row; instead the parquet/CSV is written with sidecar metadata `*.limitations.json` (id, adopted date, full text, quantified bounded additions: 2030 +10-14% of wind curtailment; 2050 +1-4% step / +15-20 TWh saturating / <=34-52 TWh capped; direction = upward) and the parquet file-level metadata stores the same JSON. Solar-only columns carry `known_limitations` empty, plus the separate solar note (30 months) as `"SOLAR_SHORT_RECORD"`.
- Extra column `drift_direction = "upward"` (central more likely low than high) so downstream tables/figures can annotate without parsing text.
- `results_writer.py` gets one small addition: write the sidecar next to any table that has a `known_limitations` column (no change to existing writers' outputs).

## 4. Retaining the national and regional formulations as labeled references

- `calibration.py` and `project_curtailment_two_curves` are **not modified in behaviour**. Their outputs get a `model` column: `"reference_national_curve"` (Tasks 7/11B), and the regional-only (Task 11D, NE logistic on P_NE) is added as `calibration.fit_regional_reference(...)` / `project_curtailment_regional_reference(...)` with `model = "reference_regional_NE"`.
- File names make the role explicit: production -> `pte_curtailment_option_E.parquet`; references -> existing `pte_curtailment_two_curves.parquet` (unchanged name for backward compatibility; gains `model` and `role="reference"` columns) and `pte_curtailment_regional_reference.parquet`.
- Every reference row carries `role="reference"` and `known_limitations="REFERENCE_NOT_PRODUCTION"`; `mitigation.compute_mitigation` gets a required keyword `model_role` defaulting to the production table only when it is given the Option E table (guard: refuses to silently run on a table lacking `model`). Reference mitigation outputs are written to separate files and prefixed `reference_` so they cannot be mistaken for headline results.
- The D26 caveat (38% of NE wind curtailment from network-element limits in 2026, 23% internal to NE) is stored as a documented sensitivity note in the sidecar of the production table.

## 5. Regression-testing strategy

Three layers; none uses the network.

1. **Unit tests on synthetic panels** (new `tests/test_hourly_model.py`, `test_projection_hourly.py`): bin construction equals direct groupby; `MonthBins.bins(ones)` equals binning the hours directly; recovery of known (L,k,x0) from synthetic hours; `r_cap` is the last bin with >=15 hours; bounded rate <= L; decomposition sums to the total; 2050 never has conformal fields; conformal infeasibility returns inf; schema and flags; D25 loader fails when status != adopted.
2. **Golden-value regression against the validated prototypes.** Reference values are frozen in `tests/fixtures/option_e/golden.json`, extracted *once* by a documented script (`analysis/task11f_extract_golden.py`) from the committed analysis artifacts in `outputs/tables/` (`task11e2_wind_solar_curves.csv`, `task11e2_unified_projection.csv`, `task11e2_backtest_annual.csv`, `task11e3_annual_backtest_band.csv`, `task11e3_target_distance.csv`, `task11e4_conformal_intervals_2030_2040.csv`, `task11e4_conformal_2050.csv`, `task11e5_compounding.csv`) plus the hand-checkable intermediate values (curve parameters, r_cap, E_out/H_out/D_pp per scenario/year, annual TWh). The fixture also stores a **small deterministic hourly sample** (a few thousand rows, committed) with the prototype's outputs on it, so the production functions are compared to the prototype functions on identical input. Tolerances: parameters 1e-6 relative (same optimiser settings), TWh 1e-6 relative, intervals exact within float rounding.
3. **Opt-in end-to-end check** (`pytest -m e2e`, skipped when the database root lacks the parquet panel): rebuilds the full hourly panel, refits, and asserts the production table equals `task11e2_unified_projection.csv` / conformal tables to the stated tolerance. Not in the default suite because it needs the multi-GB local data; run once by me at the end of 11F-3 and the result recorded in the memo.

Order of work after approval: 11F-2 (`hourly_model.py` + tests + golden, references labelled), 11F-3 (`projection.py`, `limitations.py`, writer sidecar, tests), 11F-4 (docs), 11F-5 (full suite, `ruff check src tests`, commit).

## 6. Decisions I need from you

1. New module `hourly_model.py` (recommended) vs. extending `calibration.py`.
2. Sidecar JSON + per-row `known_limitations` id (recommended) vs. full D25 text repeated per row.
3. Keep the old file name `pte_curtailment_two_curves.parquet` for the reference table (recommended, backward compatible) vs. rename it to `..._reference`.
4. Confirm that the conformal 80% supplement and the empirical band are computed from **frozen calibration inputs** (the `HorizonBands` object built from the 11E3/11E4 procedures, refreshed only by re-running the calibration) rather than recomputed on every projection call.

---

## Implementation notes (Task 11F-2 / 11F-3, after approval of this design)

All four decisions of section 6 were approved as recommended (new module; sidecar JSON with a per-row id; old file name kept for the national reference; frozen `HorizonBands`). Differences and precisions relative to the proposal:

- The default suite uses synthetic data and a committed 4,344-hour sample of the real 2025 panel; the full-sample regression tests use the existing `integration` marker (`pytest -m integration`) instead of a new `e2e` marker. Both were run: the production code reproduces the committed Task 11E2-11E4 tables to a relative difference of 1e-9 or less (curves, r_cap, bands, conformal log-quantiles, projections, distance metrics, decomposition, flexibility and L = 1 scenarios).
- `HourlyCalibration` (free-L curves, L = 1 curves, 2025 profile, `HorizonBands`) and `run_hourly_calibration` / `load_hourly_calibration` live in `hourly_model.py`; the files written to `processed/` are `hourly_curve_{wind,solar,wind_L1,solar_L1}.json`, `hourly_base_profile.parquet`, `hourly_horizon_bands.json`.
- Support status rule (fixed here, not in the earlier memos): `mostly_out_of_support` if E_out >= 0.50; `partially_out_of_support` if E_out >= 0.30 or H_out >= 0.10; otherwise `within_support`. It reproduces the earlier statement (2040 TA partially out of support; TB and TG 2040 within support); all 2050 rows are mostly out of support.
- The total's conformal 80 % interval uses the unified-calibration log-quantile applied to the sum of the wind and solar centrals (the prototype computed it around the unified curve's own central, which differs by under 10 %); the per-technology intervals are exactly those of Task 11E4.
- Regional reference: only the curve fit (`fit_regional_reference`) is in `src/`; the Task 11D proxy projection stays in `analysis/task11d_regional_recalibration.py` (it needs the subsystem monthly panel of Task 11C, which is an analysis artifact).
- `mitigation.compute_mitigation(..., require_model=False)` keeps its old behaviour by default; `require_model=True` is the guard for the option-E workflow.
