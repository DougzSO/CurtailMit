# Task 11E4 - Coverage figure, NE-hourly extension, sub-hourly feasibility, conformal prediction intervals: consolidated memo

Status: investigation / prototype, Brazil-only data. No file under `src/` was changed and no decision was adopted (D13-D22 untouched; D23, D24, D25, D26 `status: pending`; **D27 was not registered**, see section 3).
Follows `docs/task11e3_findings.md` (commit `fd3b5bd`), `docs/task11e2_findings.md`, `docs/task11e_findings.md` (cross-linked, not edited).
Code (throwaway, outside the package): `analysis/task11e4_coverage_figure.py` (a), `task11e4_ne_hourly.py` (b), `task11e4_subhourly_feasibility.py` (c), `task11e4_conformal_prediction.py` (d); smoke tests `tests/test_analysis_task11e4.py` (5).
Tables and figures: `DATABASE_ROOT/outputs/tables/task11e4_*`, `fig_insample_coverage_data.csv`; `DATABASE_ROOT/outputs/figures/fig_insample_coverage.{pdf,svg,png}` and `task11e4_*`.
New data: a 2025 sample of the ONS verified-load API (30-minute), documented in `docs/ons_subhourly_data_sources.md`.

## 0. Summary

| Workstream | Outcome | Changes the Task 11E3 conclusion? |
|---|---|---|
| (a) Coverage figure | Publication-ready figure (vector PDF / SVG, 600-dpi PNG), data table and caption text produced (section 1). | - |
| (b) NE-hourly | **Does not extend the support; it shrinks it.** 2050 hours inside the NE-hourly support: 48 / 32 / 59 % (TB / TA / TG) against 60 / 43 / 70 % with the SIN-wide hourly driver; curtailment from beyond-support hours 76 / 87 / 66 % against 62 / 77 / 51 %. The NE curve validates about as well as the SIN one (partial correlation given time 0.69 vs 0.68) but is not better. | No |
| (c) Sub-hourly data | **Exists (30 minutes, realized), tested on 2025: negative.** Maximum of r at 30 minutes is 1.006 times the hourly maximum (SIN) and 1.001 times (NE); the 30-minute driver explains 0.1-0.6 % more of the unexplained curtailment variance. **D27 not registered.** | No |
| (d) Conformal prediction | 2030 / 2040: finite 80 % intervals (and a finite 90 % one for wind), but **3-10 times wider** than the Task 11E3 empirical band; empirical coverage is right (LOQO 85-92 %). **2050: the guaranteed procedure returns no finite interval** (unbounded at 80 % and 90 %, every scenario and technology); the exchangeability assumption is clearly violated. An unguaranteed heuristic interval for wind is reported (91-630 TWh, TB). | No: it confirms that 2050 is not quantitatively defensible |

**Does any workstream move 2050 from "conditional" to "quantitatively defensible"? No, for any scenario or subset.** Details and the single updated D24 recommendation are in sections 5 and 6.

## 1. Sub-task 11E4-a - publication-ready in-sample coverage figure

Files (convention: `DATABASE_ROOT/outputs/figures/`, vector PDF for submission, SVG for editing, 600-dpi PNG for preview; underlying numbers in `DATABASE_ROOT/outputs/tables/fig_insample_coverage_data.csv`; caption text in `fig_insample_coverage_caption.txt`; colour-blind-safe palette, values printed on the bars so no colour is needed to read the panels; 7.4 x 3.3 inches, double column).
Panel (a): share of projected hours inside the observed support (bars) and inside the largest observed value (ticks), by year and scenario. Panel (b): share of the projected curtailed energy produced by supported hours, wind (solid) and solar (dashed).

| Year | TB | TA | TG | (hours inside the support, %) |
|---|---|---|---|---|
| 2025 (observed profile) | 99.8 | 99.8 | 99.8 | |
| 2030 | 99.6 | 99.6 | 99.7 | |
| 2040 | 96.4 | 85.5 | 92.6 | (inside the largest observed value: 99.4 / 94.5 / 98.4) |
| 2050 | 59.9 | 42.5 | 70.3 | (inside the largest observed value: 78.9 / 59.5 / 88.4) |

Wind curtailment from supported hours (%): 2030 97.2 / 97.2 / 97.9; 2040 86.6 / 70.3 / 79.3; 2050 37.8 / 22.5 / 49.3. Solar: 2040 84.2 / 54.6 / 71.4; 2050 38.1 / 27.2 / 44.3 (TB / TA / TG).

**Caption (ready to adapt).** *Where the hourly dose-response model is anchored in observation. For each PTE scenario (TB, TA, TG) the 2025 hourly profile of the system-wide variable-renewable share of load is scaled to the projected annual wind, solar and load, and compared with the hourly values actually observed in Brazil in 2022-2026 (41,616 hours, maximum 75.8 %). (a) Share of projected hours that fall inside the range supported by at least 15 observed hours per 2-percentage-point class (bars) and inside the largest value ever observed (ticks); (b) share of the projected curtailed energy that is produced by hours inside the supported range. Observation essentially covers 2025 and 2030 (99.6-99.8 % of hours), covers 86-96 % of the 2040 hours and 43-70 % of the 2050 hours; in 2050, 51-77 % of the projected wind curtailment comes from hours with no historical analogue. We report this boundary explicitly and treat 2050 as a conditional range rather than a calibrated estimate: quantifying where the evidence ends is part of the method.*
Framing note for the text: present the figure in Methods or the start of Results as the method's own diagnostic (the model states, hour by hour, where it is evidence-based), and cite it every time a 2040 or 2050 number is used.

## 2. Sub-task 11E4-b - combined Northeast + hourly extension

Data: the Task 11E hourly subsystem panel (NE rows, 2022-01..2026-09, 41,616 hours); nothing re-acquired. r_NE = NE (wind + solar + curtailed) / NE load. NE exports most of its VRE, so r_NE is routinely above 100 % (median 108 %) and its level cannot be compared with the SIN-wide r; only its position within its own range matters.

### 2.1 Distribution
| | SIN r (%) | NE r_NE (%) |
|---|---|---|
| median / p95 / p99 / p99.9 | 20.5 / 39.3 / 50.0 / 62.3 | 108 / 194 / 247 / 304 |
| maximum | 75.8 | 375 |
| maximum / median; p99.9 / median | 3.70; 3.04 | 3.47; 2.81 |
| 2025 p95 / maximum | 45.6 / 71.3 | 226 / 358 |
**NE-hourly does reach higher absolute values (375 against 75.8 %, about 4.9 times), but not a more extreme tail**: relative to its median the NE maximum is 3.5 times, the SIN one 3.7 times.

### 2.2 Refit and validation (NE wind 2022+, NE solar 2024-04+, r_NE in 10-pp bins, populated support to r_NE = 295 %)
- Curves: wind L 0.75, k 0.029, x0 206 (SIN-r curve on the same NE targets: L 0.74, x0 40.5); solar L 0.64, x0 186.
- Annual backtest on NE targets (error of r_NE / error of the SIN-r curve): wind 2025 in sample -9.9 / -9.5 %; leave-one-year-out 2025 -12.8 / -12.6 %; trained on 2022-24: 2025 -27.1 / -19.4 %, 2026 -35.4 / -21.3 %. Solar: in sample 2024 +15.4 / +3.9 %, 2025 -0.9 / -1.4 %; trained to 2025-06: 2025 +3.0 / +6.3 %, 2026 -1.3 / +10.0 %. **For wind r_NE is equal in sample and worse out of sample; for solar it is mixed.**
- Stability by year (L pinned): wind gap to the pooled curve 2.5 / 4.3 / 2.9 / 5.9 pp for 2023-2026 (2022: 21.9 pp, the same outlier year as before); solar 0.9-4.9 pp. Same conclusion as the SIN-wide driver.
- Time-confound test (NE wind, 57 months): partial correlation of monthly C with the hourly-model rate given t = 0.69 (r_NE; 0.67 leave-year-out) against 0.68 (0.66) with the SIN-wide r; incremental R2 over time 0.131 / 0.124. **No gain.** (Reference: P_NE 0.14.)

### 2.3 In-sample coverage with the NE-hourly reference (PTE constant-share proxy of Task 11D-0 / 11E, NE scaled like the SIN hours)
| Wind | TB 2040 | TA 2040 | TG 2040 | TB 2050 | TA 2050 | TG 2050 |
|---|---|---|---|---|---|---|
| hours inside the support, NE-hourly | 95.9 % | 80.6 % | 91.2 % | 47.9 % | 31.9 % | 59.1 % |
| hours inside the support, SIN-wide hourly | 96.4 % | 85.5 % | 92.6 % | 59.9 % | 42.5 % | 70.3 % |
| curtailment from beyond-support hours, NE | 16 % | 38 % | 24 % | 76 % | 87 % | 66 % |
| curtailment from beyond-support hours, SIN | 13 % | 30 % | 21 % | 62 % | 77 % | 51 % |
| p95 of projected r over the support edge, NE / SIN | 0.97 / 0.97 | 1.28 / 1.22 | 1.10 / 1.06 | 1.65 / 1.49 | 2.00 / 1.79 | 1.49 / 1.36 |
Solar gives the same ranking. **The NE-hourly reference does not improve the coverage of 2040 or 2050; it lowers it by 1-15 points of hours and raises the beyond-support share of curtailment by 3-13 points.** The reason is arithmetic: both references are scaled from the same 2025 profile by the same PTE factors, and the NE hourly range tops out in relative terms at the same point (the NE hours are slightly more volatile, so its supported band is narrower in relative terms). Combining the regional and hourly dimensions therefore adds no support; the regional information would have to come from a different (non-proxy) NE projection, which the PTE does not publish.

## 3. Sub-task 11E4-c - sub-hourly feasibility check (D27)

### 3.1 What exists (full inventory in `docs/ons_subhourly_data_sources.md`)
ONS publishes 30-minute realized data for **load** (verified load API, per area) and **curtailment / generation of the COFF plants** (already in the project's `raw/`, only summed to the hour by Task 11E), 30-minute programmed (DESSEM) balances since 2025-05-23, and half-hour restriction-period files. **Nothing finer than 30 minutes with generation or load was found.** So the finest instantaneous VRE-share-of-load that open data allow is the 30-minute one, and its generation side was already local; only the load needed acquisition.

### 3.2 Sample acquired and test (2025, SIN = N + NE + S + SE)
Acquired: verified load 2025, four areas (37 MB, 60 requests, seconds each; found: the SE area is published as `SECO` from 2025-05, area `SIN` returns zeros). Quality check: the COFF-plant realized VRE share of load, aggregated to the hour, correlates 0.9965 with the main hourly panel.
| 2025 | 30-minute r | hourly r (same data) | ratio |
|---|---|---|---|
| SIN p99.9 / maximum | 61.1 / 66.4 | 61.1 / 66.0 | 1.000 / 1.006 |
| NE p99.9 / maximum | 296.8 / 322.7 | 295.0 / 322.4 | 1.006 / 1.001 |
Within-hour spread of the SIN r (difference between the two half-hours): median 0.67 pp, p99 5.7 pp, maximum 27 pp (isolated events). Dose-response: the unexplained share of 30-minute curtailment variance is 0.500 with the 30-minute driver against 0.504 with the hourly one for wind (0.6 % relative reduction), 0.486 against 0.486 for solar (0.1 %).
**D27 rule (fixed before the test): register only if the 30-minute p99.9 or maximum exceeds the hourly by at least 10 % and the 30-minute driver reduces the unexplained variance by at least 15 %.** Both conditions fail (ratio 1.006 and reduction 0.6 %). **D27 is not registered. Result: negative.** Hourly aggregation does not hide extreme instantaneous VRE shares of load at the system level; the fleet and the load average out within the hour. Limits of this finding: one year, 30 minutes is the finest resolution available, and plant-level or sub-30-minute events (the intra-half-hour restriction files) are not a system-level driver.
(The 2025 SIN maximum here, 66.4 %, is below the 71.3 % of the main panel because COFF plants carry 96.3 % of the balance wind and the verified load is 2.3 % higher than the balance load.)

## 4. Sub-task 11E4-d - conformal prediction intervals

### 4.1 Procedure
Split conformal on the signed log error e = ln(predicted / observed) of the out-of-sample forecasts of Task 11E3 that mimic real use: model refitted on earlier months (expanding, or the previous 12 / 18 / 24 months) and evaluated on the next calendar quarter (wind 13 test quarters 2023Q3-2026Q3; solar and the unified driver 7). Truncated-training stress splits are excluded from this calibration set. Conformity score |e|; splits that share a test quarter are dependent, so each quarter carries total weight 1 and the test point weight 1 (weighted split conformal, Tibshirani et al. 2019). Finite-sample rule: n blocks give a finite (1 - alpha) interval only if ceil((n + 1)(1 - alpha)) <= n: 80 % needs n >= 4, 90 % needs n >= 9. Interval for the truth: central x exp(-q) to central x exp(+q). A bias-adjusted variant (score |e - median|) gives the same upper end and a slightly higher lower end. The guarantee is **per quarter block, under exchangeability**.

### 4.2 Does the calibration behave? (`task11e4_conformal_coverage_checks.csv`)
Leave-one-quarter-out coverage: wind 84.6 % (nominal 80 %) and 92.3 % (nominal 90 %); solar and unified 85.7 % at 80 %. Forward test (calibrate to 2025Q2, test 2025Q3-2026Q3): wind 5 of 5 inside both levels. With 7 blocks the 90 % interval is unbounded for solar and the unified driver.
Exchangeability caveats **even at 2030 / 2040**: every calibration block is the quarter immediately after its training window (0-3 months ahead); a 2030 projection is about 4 years beyond the end of the data and 2040 about 14. Task 11E3 showed that the error of the model depends on lead time (corr -0.34), so the calibration blocks are not exchangeable with a multi-year-ahead projection. The calibration scores are also dominated by the early quarters (2023-2024, trained on 12-24 months, tiny curtailment base): the largest scores are these, not the recent ones.

### 4.3 Results, 2030 and 2040 (TWh; central of option E; wind and solar calibrated separately, total with the unified-driver calibration)
80 % intervals, quarter blocks, symmetric:
| | Wind 2030 | Wind 2040 | Solar 2030 | Solar 2040 | Total 2030 | Total 2040 |
|---|---|---|---|---|---|---|
| TB | 21.6 (7.0-67.4) | 45.5 (14.6-141.7) | 42.6 (17.7-102.4) | 82.1 (34.2-197.2) | 58.9 (19.9-174.5) | 119.6 (40.4-354.2) |
| TA | 21.3 (6.8-66.2) | 120.1 (38.6-373.8) | 41.8 (17.4-100.5) | 122.3 (50.9-293.8) | 57.9 (19.5-171.4) | 239.8 (81.0-710.3) |
| TG | 20.6 (6.6-64.2) | 78.2 (25.1-243.5) | 37.6 (15.6-90.3) | 103.2 (43.0-248.0) | 53.6 (18.1-158.9) | 174.8 (59.0-517.7) |
90 % (wind only; unbounded for solar and total): wind 2030 5.5-86.0 (TB), 2040 11.5-180.8 (TB), 30.2-476.8 (TA), 19.7-310.6 (TG). Calibrating only on the 2025-2026 quarters (7 blocks) changes the 80 % interval by less than 5 %. Annual blocks (calendar years, expanding window; wind n = 4, solar n = 2): the 80 % interval exists for wind only (TB 2030 4.1-114.1) and is driven by one block (2023, trained on one year, ln-error -1.66); for solar and the total it is unbounded.
**Comparison with the Task 11E3 empirical annual-backtest band** (wind TB 2030 23.6-28.3; solar 37.1-48.3; total 60.7-76.5; 2040 total 121-152 / 238-295 / 175-219): the conformal intervals are 3-10 times wider and centred on a wider, symmetric log range; the empirical band is one-sided (truth above the central value) and narrow because it comes from seven annual comparisons in the best-trained regime.
Which is more defensible for the paper: **neither as a standalone claim.** The conformal interval has a stated guarantee (for a quarter block, if exchangeable) that is empirically confirmed by the leave-one-quarter-out check, but it is conservative for annual totals (quarterly noise is not averaged out), driven by early weak-training quarters, and its exchangeability is violated by the horizon. The empirical band is closer to the annual quantity but has no guarantee and rests on 6-7 points. Recommendation: report the empirical annual band as the headline for 2030-2040, labelled descriptive, and give the conformal 80 % interval in the supplement as the formal conservative bound with the finite-sample and exchangeability caveats, including that no 90 % interval can be certified for solar or the total.

### 4.4 The 2050 attempt (reported as obtained)
**Exchangeability assessment** (evidence of Task 11E3-a): the calibration blocks are 0-3 months ahead and have extrapolation distance E_out up to 0.37 (wind) / 0.24 (solar); the 2050 targets have E_out 0.51-0.78 and D_pp 13.7-29.4 pp, against a calibration maximum D_pp of 6.3 pp for the forecast-type splits and 11.3 pp even when all truncated stress splits are included; none of the forecast-type calibration blocks has E_out above 0.8 times the 2050 target. The error at the 2050 conditions depends on the plateau of the curve and on flexibility, which no calibration block tests. **The assumption (calibration and test drawn from similar conditions) is not credible at 2050.**
**Attempt with covariate-shift weights** (localised weighted conformal on all 180 / 85 / 85 splits, kernel on E_out, bandwidth 0.1, and a 2-D kernel with D_pp, bandwidth 5 pp): effective number of independent calibration quarters 6.9-10.7 for wind (1-D; 3.0-7.4 in 2-D) and 1.9-3.1 for solar and unified. Because the weights are below 1, the finite-sample rule is not met: **the interval is unbounded at 80 % and at 90 % for every scenario and technology.** The procedure, applied correctly, declines to produce a 2050 interval.
**Unguaranteed heuristic, shown so that the outcome is visible** (plain weighted quantile of |ln(pred / obs)| of the E_out-localised splits, no test-point mass; upper end capped at the PTE generation of the technology): wind central / 80 % interval / 90 % interval, TWh:
| | central | 80 % | 90 % | generation cap |
|---|---|---|---|---|
| TB wind 2050 | 239 | 91 - 393 (uncapped 630) | 59 - 393 (977) | 393 |
| TA wind 2050 | 387 | 147 - 581 (1019) | 136 - 581 (1106) | 581 |
| TG wind 2050 | 208 | 96 - 369 (455) | 72 - 369 (601) | 369.5 |
The upper end hits the physical cap in every scenario and the lower end is far below the option E range; the symmetric score also puts half of the mass below the central value although the historical errors at large extrapolation distance are overwhelmingly under-predictions (mean -47 % for E_out 0.5-1.0, Task 11E3), so the lower half is an artefact of the symmetric score. For solar and the unified driver the heuristic intervals (narrow, e.g. TG solar 110-143) rest on fewer than 3 effective quarters and are **not meaningful**. **Outcome: unbounded when done correctly, implausibly wide when forced, with an assumption violation that cannot be repaired with the data available.** The intervals are not integrated into the 2050 reporting as a quantitative range; they are cited as the explicit result of the method.

## 5. Does any workstream change the Task 11E3 conclusion about 2050?
**No.** (b) NE-hourly lowers, not raises, the in-sample share; (c) sub-hourly data add nothing at the system level; (d) conformal prediction, the most rigorous tool tried, refuses to give a 2050 interval and, when forced, produces one that hits the physical cap. 2050 stays a **flexibility-conditional range** (Task 11E3 / 11E2), with the coverage figure (a) as the main transparency exhibit: of every 2050 curtailed TWh, 51-77 % comes from hours without a historical analogue. This is a quantitative statement the paper can make, and it is a stronger one than an arbitrary band.
No scenario or technology subset is defensible quantitatively in 2050. The closest is TG wind (E_out 0.51, D_pp 13.7, effective quarters 10.7 in 1-D) but its D_pp is still 1.2 times the largest D_pp ever tested.

## 6. Updated D24 recommendation (reading, not a decision)
Adopt option E reported by horizon, as in Task 11E3, with these changes of emphasis from Task 11E4:
1. **2030 and 2040:** E central values with the Task 11E3 empirical annual band as the headline uncertainty (descriptive), and the conformal 80 % interval in the supplement as the conservative formal bound (wind and solar separately; no 90 % bound certifiable for solar or the total). TA 2040 is partly beyond the support (14.5 % of hours, 30-45 % of the curtailment): flag it.
2. **2050:** E central, the in-support / beyond-support decomposition, the flexibility-conditional range (phi 1.5 to L = 1), the coverage figure (a), and an explicit sentence that a conformal interval could not be produced because the calibration and projection conditions are not exchangeable. No probability, no "calibrated" label.
3. No change to D25 (close with the wording of Task 11E3) and D26 (retire with the stated limitation); no D27.
4. The paper can present the two uncertainty treatments side by side (empirical band and conformal interval for 2030-2040; conditional range and "no valid interval" for 2050) and let the reader see where they agree (both say the central value is more likely low than high, and both widen as the horizon grows) and disagree (conformal is 3-10 times wider because it counts quarter-level noise and early-training errors).
Decidable now: D24, D25, D26 (yes); D23 remains open and does not block them.

## 7. Note on international hourly data (intentionally excluded)
Per the user's decision for this task, **international hourly peak data (for example South Australia or Denmark) were intentionally not used** as a sanity anchor for the 2050 conditions. The reasons recorded are: cross-country comparability of sub-annual VRE-share-of-load and curtailment definitions is weak, Brazil's system (hydro-dominated, large reservoirs, NE export constraints, ONS reason codes) is specific enough that each country's conditions would need their own explanation, and the narrative cost outweighs the benefit. This is a scope decision, not an oversight, and is not revisited in this task. (The annual pooled international panel of Task 11D remains in the project history as a separate, earlier exercise.)

## 8. Documentation touched and data acquired
| File | Change |
|---|---|
| `docs/task11e4_findings.md` | New. This memo. |
| `docs/ons_subhourly_data_sources.md` | New. Inventory of sub-hourly ONS resources; provenance, access date, license and caveats of the 2025 verified-load sample. |
| `docs/roadmap.md` | Appended "Update (Task 11E4)". |
| `docs/methodology.md` | Appended section "2.3f Update (Task 11E4)". |
| `docs/claude_commands.md` | Appended section 1.11E4 after 1.11E3; task table: new 11E4 row. |
| `docs/progress_log.md` | Appended a Task 11E4 entry. |
| `config/discovered_sources.yaml` | D24 `task11e4_update` (pending); D27 not registered. |
| `analysis/task11e4_*.py`, `tests/test_analysis_task11e4.py` | New throwaway analysis code and smoke tests. |
| `DATABASE_ROOT/raw/ons/mmgd/cargaverificada_*_2025-*.json` (+ manifests) | New data: 2025 verified load, 30-minute, 37 MB. |
| `DATABASE_ROOT/interim/task11e4_subhourly_2025.parquet` | Regenerable analysis cache. |
| `DATABASE_ROOT/outputs/figures/fig_insample_coverage.{pdf,svg,png}`, `_caption.txt`; `outputs/tables/fig_insample_coverage_data.csv` | The publication figure, caption and data. |

## 9. Reproducibility and limits
Run in the project `.venv`, after the 11E / 11E2 / 11E3 scripts: `task11e4_coverage_figure.py`, `task11e4_ne_hourly.py`, `task11e4_subhourly_feasibility.py` (needs network on the first run; cached afterwards), `task11e4_conformal_prediction.py`. Conformal calibration uses the splits written by `task11e3_error_growth.py`. All statistics descriptive; one Brazilian sample of 4.75 years; the sub-hourly test covers 2025 only.
