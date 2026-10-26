# Task 11E3 - Extrapolation-distance calibration of the 2050 uncertainty, and decision closure for D24 / D25 / D26: decision-ready memo

Status: investigation / prototype, Brazil-only data. No file under `src/` was changed and no decision was adopted (D13-D22 untouched; D23, D24, D25, D26 `status: pending`).
Follows `docs/task11e2_findings.md` (committed as `a2f2ea7` before this task started), `docs/task11e_findings.md`, `docs/task11d_findings.md` (cross-linked, not edited).
Code (throwaway, outside the package): `analysis/task11e3_error_growth.py` (11E3-a), `analysis/task11e3_2050_calibration.py` (11E3-b); smoke tests `tests/test_analysis_task11e3.py`. Tables and figure: `DATABASE_ROOT/outputs/tables/task11e3_*`, `outputs/figures/task11e3_error_growth.png`.
Environment fix done first: `statsmodels>=0.14` is now declared in `pyproject.toml` (`[dev]` extras) and `requirements.txt`; after `pip install -e ".[dev]"` in the project `.venv` every 11E2 and 11E3 script runs without the system Python (checked). The data panel is 2022-01..2026-09 (the COFF curtailment series starts in 2022; 2021 has balance data only, so no 2021 curtailment exists to train or test on).
Pre-existing, unrelated to this task: one test (`tests/test_ons_solar_gap.py::test_schema_findings_reports_type_change_and_missing_columns`) fails in the `.venv` (pandas 3.0.6 / pyarrow 26 write `large_string` where the test expects `string`); it passes with the system Python (pandas 2.3.3). Not touched; flagged for a separate fix.

## 0. Summary

| Question | Answer |
|---|---|
| Can 2050 be reported as a data-calibrated quantitative range? | **No. 2050 must remain a qualitative / conditional range**, as recommended in Task 11E2. The extrapolation-distance calibration was run exactly as proposed and **fails the credibility rule fixed before the results** on every technology (section 3). |
| Does prediction error grow with extrapolation distance? | **Not in a way that supports calibration.** R2 of the error-growth relation is 0.03 (wind), 0.04 (solar), 0.07 (unified). Error is dominated by two things that are not distance: a level bias (the model under-predicts wind by about 20-30 % on quarter blocks even at zero distance) and a drift that grows with the lead time between training and test (corr with lead time -0.34, with distance -0.04). |
| Is 2050 inside the historical range of distances? | **On the share-of-curtailment metric yes, on the "how far" metric no.** E_out (share of predicted curtailment from beyond-support hours) of 2050 is 0.51-0.78, inside the historical wind splits (0 to 0.90) but 0.49-0.57 is the most the solar and unified splits ever reached. D_pp (mean excess of r beyond the support) of 2050 is 14-29 pp against a historical maximum of 8-11 pp: the historical splits never test conditions further than 11 pp beyond the training support, 2050 is 1.2-2.4 times beyond for wind and up to 3.7 times for solar. |
| Does the method pass its own sanity check at 2030 / 2040? | **No.** At 2030 (E_out 0.02-0.03, in-sample) the empirical neighbour band for wind is 17-86 TWh around a central of 21.6 (a factor 5); the method is not producing a narrow band where the horizon is in-sample. 6 of the 20 neighbour bands exceed the physical cap (curtailment cannot exceed PTE generation), e.g. 2050 wind 278-1128 TWh against 393 TWh of PTE wind. |
| What is reported instead? | For 2030 / 2040: an empirical **annual-backtest error band** of option E (wind truth/prediction 1.09-1.31, solar 0.87-1.13; descriptive, from section 4). For 2050: the Task 11E2 flexibility-conditional range with the in-support / beyond-support decomposition, no probability attached. |
| D24 / D25 / D26 | **All three decidable together.** Consolidated recommendation in section 6: D24 = option E reported by horizon; D25 = close with the stated wording; D26 = retire the PDE/PET extension with the stated limitation. D23 remains open and does not block them. |

## 1. Sub-task 11E3-a - error growth with extrapolation distance

### 1.1 Metrics and splits (defined before the results; `task11e3_error_growth.py` docstring)
Test unit: a calendar quarter of hourly data (13 quarters for wind 2023Q3-2026Q3, 10 for solar and the unified driver 2024Q2-2026Q3; blocks with less than 0.3 TWh observed curtailment, 0.5 TWh for unified, are dropped). Error: e = ln(predicted / observed); e < 0 means under-prediction.
Distance of a split (same curve that is being tested; support edge r_cap = largest 2-pp bin of r with at least 15 training hours):
- **E_out** (primary): share of the block's predicted curtailed energy produced by hours with r above r_cap. Unit-free, directly comparable with the 2050 shares of Task 11E2-a.
- H_out: share of hours above r_cap. **D_pp**: energy-weighted mean excess of r over r_cap in pp (how far, not only how much).
Split families (training months always exclude the test quarter): `expanding` (all earlier months), `rolling_12/18/24` (the previous W months), `trunc_past` (earlier months whose monthly r_p95 is at most a quantile theta of 0.25-0.85: deliberately low-penetration training), `trunc_any` (all other months at or below theta: covariate shift, "train on low penetration, predict higher"). Counts: wind 180 splits, solar 85, unified 85.

### 1.2 Results (error = (pred - obs) / obs on quarter blocks)
Wind (180 splits):
| E_out bin | n | mean error | median | 5th-95th percentile | mean absolute error |
|---|---|---|---|---|---|
| 0-0.02 | 50 | -28 % | -39 % | -70 % to +25 % | 35 % |
| 0.02-0.1 | 26 | -31 % | -29 % | -75 % to +23 % | 38 % |
| 0.1-0.25 | 36 | -19 % | -17 % | -80 % to +18 % | 27 % |
| 0.25-0.5 | 28 | -19 % | -21 % | -65 % to +20 % | 25 % |
| 0.5-1.0 | 40 | -47 % | -44 % | -76 % to -22 % | 47 % |

By family: expanding -30 % (mean, absolute 32 %), rolling_12 -16 % (24 %), rolling_18 -22 % (28 %), rolling_24 -20 % (25 %), trunc_any -23 % (34 %), trunc_past -41 % (42 %). Relation e = a + b E_out: a = -0.38, b = -0.29 (90 % cluster-bootstrap over test quarters: -0.62 to -0.03), R2 = 0.025; the fitted spread of the error does **not** widen with distance (d = -0.30, interval -0.53 to -0.003).
Solar (85 splits): mean error -0.6 % / +15 % / +5 % / +13 % across the four E_out bins up to 0.5 (one split above 0.5); slope b = 0.37 (interval -0.32 to 1.05), R2 = 0.04. Unified (85): slope 0.71 (-0.40 to 1.69), R2 = 0.07; no split above E_out 0.49.
Figure: `outputs/figures/task11e3_error_growth.png` (error versus E_out and versus D_pp, by family and technology, with the fitted relation and the 2050 range of E_out shaded).

### 1.3 What the error is made of
- At near-zero distance the wind error is already a mean -28 % (mean absolute 35 %) on quarter blocks. This is the level bias and the drift of Task 11E2 (+2 pp per year; wet-season / Q1 curve to the left), amplified by the quarter block (annual blocks, 11E2-b: -8 % to -23 % out of sample).
- **Lead time matters more than distance.** For the temporal splits (not `trunc_any`), the correlation of the error with the lead time between the last training month and the test quarter is -0.34 for wind (with E_out: -0.04); the regression of e on E_out and lead gives -0.066 per month of lead for wind (R2 0.22). The model under-predicts more the further in time the test is from the training: the drift, not the covariate range.
- The splits with large E_out are the deliberately truncated ones (training stops at low r). They test the **rising part** of the logistic, where an unidentified L and x0 matter; the 2050 hours are mostly on the **plateau** (r far above 63 %), where the question is whether the curve stays flat at L and whether flexibility stays at today's level. The historical record contains no hour in which that was tested.
- The error is mostly of one sign (under-prediction). This is informative for 2030-2040 (if the drift continues the central values are more likely low than high) and means a symmetric band around the central value would misrepresent it.

## 2. Sub-task 11E3-b - 2050 distance and the credibility rule

Distance of the PTE-scaled hourly conditions (Task 11E2-a proxy) to the **full** 2022-2026 training sample (curve and support from all 57 months; wind curve L 0.733 / k 0.143 / x0 40.9; r_cap 63.0):
| Scenario, year | E_out (wind / solar / unified) | H_out | D_pp (wind) |
|---|---|---|---|
| 2030 (TB, TA) | 0.03 / 0.03 / 0.03 | 0.4 % | 4.3 |
| TB 2040 | 0.13 / 0.16 / 0.15 | 3.6 % | 7.2 |
| TA 2040 | 0.30 / 0.45 / 0.35 | 14.5 % | 12.7 |
| TG 2040 | 0.21 / 0.29 / 0.24 | 7.4 % | 9.0 |
| TB 2050 | 0.62 / 0.62 / 0.63 | 40 % | 17.4 |
| TA 2050 | 0.78 / 0.73 / 0.78 | 58 % | 27.1 |
| TG 2050 | 0.51 / 0.56 / 0.53 | 30 % | 13.7 |

**Credibility rule (fixed in the script before any result was seen):** (1) the error-growth relation must be distinguishable from flat; (2) the target distance must be inside, or at most 25 % beyond, the historical range on **both** E_out and D_pp; (3) at least 25 test blocks over at least 3 calendar years.
Outcome (`task11e3_credibility_rule.csv`): wind: (1) passes formally (slope interval excludes 0) but with the wrong sign for a widening band and R2 0.025; (2a) E_out passes for 2040 and 2050, (2b) D_pp fails for 2050 (27 pp against 11.3 x 1.25 = 14.2), passes narrowly for 2040 (12.7 against 14.2 for TA); (3) fails (13 quarters). Solar and unified: (1) fails, (2a) fails for 2050, (2b) fails for 2040 and 2050, (3) fails (10 quarters). **No technology passes in 2040 or 2050.**

Indicative empirical band (not calibrated: the rule failed). Take the historical splits whose E_out lies within +-0.15 of the target, at least 15 splits from at least 4 test quarters; obs = pred x exp(-e); band = central x exp(-q95) to central x exp(-q05) (TWh):
| | 2030 (central) | 2040 | 2050 |
|---|---|---|---|
| wind TB | 17-86 (21.6) | 37-181 (45.5) | 278-1128 (239) |
| wind TA | 17-84 (21.3) | 102-400 (120) | 510-1498 (387) |
| wind TG | 17-82 (20.6) | 66-318 (78) | 177-811 (208) |
| solar and unified, 2050 | | | insufficient evidence: 0-8 splits at the target E_out (TB 4, TA 0, TG 8) |

For 2050 the wind bands rise above the PTE wind generation itself (393 / 581 / 369 TWh), which a gross-basis curtailment cannot exceed; they are a symptom of calibrating on truncated-training splits whose predictions are extreme under-predictions, not a usable range. The 2030 band, 5 times wide at an in-sample horizon, fails the sanity check required by the task.

**Comparison asked for (wind 2050, TWh; TB / TA / TG):**
| Formulation | TB | TA | TG |
|---|---|---|---|
| 11B national extrapolation, low / central / high | 83 / 361 / 385 | 123 / 568 / 579 | 78 / 322 / 355 |
| 11D regional point estimate | 85 | 129 | 79 |
| 11E envelope (L 0.25 / 0.5 / 1.0, capacity-grounded low) | 86-145 | 162-245 | 79-127 |
| 11E2 option E central (bootstrap 5-95 %) | 239 (227-248) | 387 (363-406) | 208 (199-215) |
| 11E3 indicative empirical band (rule failed; uncapped) | 278-1128 | 510-1498 | 177-811 |
The indicative band is **wider** than the 11E envelope (width high/low 2.9-4.6 against 1.5-1.7) and covers the 11B central value. It is wider because it measures the model's real historical misses (level bias and drift) rather than a scenario choice of L, and it is not narrower or more informative than the envelope. The honest reading is that the data do not support narrowing the 2050 wind range below "plausible range spans the 11E envelope up to the 11B national value".

## 3. Why 2050 stays conditional (decision for 11E3-b step 5)
1. The error-growth relation is too weak: R2 0.03-0.07, and in solar and unified its slope is not distinguishable from zero.
2. The historical splits cannot reach the 2050 distance on D_pp (11 pp against 14-29 pp) and the solar and unified splits cannot reach it on E_out either; calibrating 2050 would extrapolate the error curve itself.
3. The error that is observed is dominated by drift and by quarter-level seasonal heterogeneity, neither of which scales with r-distance; the neighbour method therefore returns bands that are unphysical at 2050 and 5 times wide at 2030.
4. The risk that matters in 2050 (does the dose-response plateau hold at r of 80-170 % with today's flexibility?) has no historical analogue; it is a scenario question, and the Task 11E2 phi sensitivity is the appropriate treatment.
Recommendation (as in Task 11E2): report 2050 as a flexibility-conditional range with the in-support / beyond-support decomposition; do not attach a probability or a "calibrated" label.

## 4. What can be quantified: the empirical error of option E in the observed regime (2030, 2040)
From the annual backtests of Task 11E2-b in the regime closest to the projections (test years 2025-2026; in-sample, leave-one-year-out and trained-on-2022-24 / 2023-24 schemes; the 2022-23-trained split is excluded as a support failure): wind error -8 % to -23 % (n = 7), solar -12 % to +15 % (n = 6). With err = (pred - obs) / obs, truth = pred / (1 + err): wind truth is 1.09-1.31 times the prediction, solar 0.87-1.13 times. Applied to the option E central values (wind and solar summed, errors treated as perfectly correlated, i.e. conservative):
| Scenario | 2030 central (band) | 2040 central (band) |
|---|---|---|
| TB | 64 (61-77) | 128 (121-152) |
| TA | 63 (60-75) | 242 (238-295) |
| TG | 58 (55-70) | 181 (175-219) |
This is a **descriptive** error band of the backtests (seven wind and six solar annual comparisons, one Brazilian sample), not a prediction interval, and it is only meaningful where the horizon is in-sample: for TA 2040 (E_out 0.30-0.45, 15 percent of hours beyond the support) it is likely too narrow.

## 5. Updated D24 decision table (wind + solar curtailed TWh; central and range)
Columns A, C are unchanged from `docs/task11e2_findings.md`; E now has a row per horizon with its reporting rule.
| Option | 2040 TB / TA / TG | 2050 TB / TA / TG |
|---|---|---|
| **A** regional wind envelope + hourly solar | 117 (112-123) / 193 (172-218) / 155 (144-168) | 237 (195-282) / 344 (301-427) / 234 (200-273) |
| **B** A and C reported side by side | no number of its own | no number of its own |
| **C** national P curves (11B) | 175 (87-221) / 356 (117-423) / 256 (105-321) | 513 (138-566) / 775 (188-810) / 482 (140-550) |
| **D** defer | no number by nature | no number by nature |
| **E**, central | 128 / 242 / 181 | 355 / 536 / 334 |
| **E**, reported range | **empirical annual-backtest band**: 121-152 / 238-295 / 175-219 | **flexibility-conditional range, not calibrated** (E central with phi 1 to 1.5 as the lower scenario and L = 1 as the upper): 231-432 / 406-680 / 198-396 |
| E, in-support / beyond-support part of the central | 109 + 19 / 151 + 91 / 136 + 46 | 134 + 220 / 128 + 409 / 158 + 176 |
| E 2030 for reference | 64 (61-77) / 63 (60-75) / 58 (55-70) | |
Read-across: the 2050 E range does not replace the 11E envelope with a data-derived band; it is a scenario range. If a single headline number is needed, it should be presented as the E central with the sentence "conditional on today's flexibility and on the stationarity of the dose-response beyond r = 76 %; 51-78 % of the energy comes from hours with no historical analogue".

## 6. Consolidated recommendation for D24, D25 and D26 (reading, not a decision)
**Adopt the three together as one confirmation:**
1. **D24 - adopt option E** (hourly dose-response driver, wind and solar, replacing the national-P curves of D21/D22 for projections; D13-D22 otherwise untouched), reported by horizon:
   - **2030 and 2040:** E central values with the empirical annual-backtest band of section 4, stated as descriptive and with the known under-prediction bias (truth more likely above the central value); 2040 TA to be flagged as partly beyond the support.
   - **2050:** E central with the in-support / beyond-support decomposition and the flexibility-conditional range of section 5; no calibrated or probabilistic band; the C line (national extrapolation) shown as a labelled reference (B-style).
   - Keep A out as primary (dominated by E on time control, backtest and coverage); available as a lower-side sensitivity. D remains an option only if you prefer to wait for flexibility data that no Brazilian source currently provides.
2. **D25 - close** with the sentence: "monthly P (national or regional) is a time-confounded coarse proxy of the hourly system-wide potential VRE share of load; the hourly driver is not just time (partial correlation 0.68-0.70 vs 0.14 and 0.42), but an unexplained upward drift of about 2 pp per year in wind remains." Task 11E3 **strengthens** the caveat: the error of the model grows with lead time (-0.066 in ln-ratio per month for wind), not with covariate distance.
3. **D26 - retire the PDE / PET extension**, with the limitation stated in `docs/task11e2_findings.md` section 4.5 (38 % of 2026 NE wind curtailment is attributed to network elements; covered only as the flexibility sensitivity). No new transmission evidence arises in Task 11E3; the recommendation is **confirmed unchanged**.
**D23 stays open** and does not block the three (gross formula used throughout; under option E only the gross reading is operational).
Is everything decidable? Yes: D24, D25 and D26 are decidable now. Gaps that remain, none blocking: (i) no Brazilian data calibrate 2050 flexibility; (ii) the wind drift is unexplained; (iii) the calibration of 2050 cannot be improved with the 4.75 years available, only by external information (other systems, storage and interconnection pathways), which is outside the Brazil-only scope; (iv) solar has 30 months.

## 7. Documentation touched and data acquired
| File | Change |
|---|---|
| `pyproject.toml`, `requirements.txt` | `statsmodels>=0.14` declared (`[dev]` extras and requirements). |
| `docs/task11e3_findings.md` | New. This memo. |
| `docs/roadmap.md` | Appended "Update (Task 11E3)". |
| `docs/methodology.md` | Appended section "2.3e Update (Task 11E3)". |
| `docs/claude_commands.md` | Appended section 1.11E3 after 1.11E2; task table: new 11E3 row. |
| `docs/progress_log.md` | Appended a Task 11E3 entry. |
| `config/discovered_sources.yaml` | D24, D25, D26 candidate text updated (`task11e3_update`, consolidated recommendation); D23 note. All `pending`. |
| `analysis/task11e3_*.py`, `tests/test_analysis_task11e3.py` | New throwaway analysis code and smoke tests (4 tests). |
New data: none.

## 8. Reproducibility and limits
Re-run in the project `.venv` (after the 11E and 11E2 scripts): `task11e3_error_growth.py`, then `task11e3_2050_calibration.py`. Bootstrap: 400 resamples of test quarters (seed fixed). Quarter blocks add seasonal noise (conservative for annual projections). The splits overlap strongly (the same test quarter appears in many splits), so the effective sample size is the number of test quarters (13 / 10 / 10), not the number of splits; hence the cluster bootstrap and rule (3). Out-of-sample means held-out periods of the same Brazilian sample.
