# Task 11E2 - Validation and cross-technology unification of the hourly dose-response model: decision-ready memo

Status: investigation / prototype, Brazil-only data. No file under `src/` was changed and no decision was adopted (D13-D22 untouched; D23, D24, D25 and the new D26 are `status: pending`).
Follows `docs/task11e_findings.md` and `docs/task11d_findings.md` (cross-linked, not edited).
Code (throwaway, outside the package): `analysis/task11e2_insample_coverage.py` (a), `task11e2_backtest.py` (b), `task11e2_wind_hourly.py` (c), `task11e2_transmission_mechanism.py` (d), `task11e2_options_table.py` (e),
shared helpers `task11e2_common.py`; smoke tests `tests/test_analysis_task11e2.py`. Tables and figures: `DATABASE_ROOT/outputs/tables/task11e2_*`, `outputs/figures/task11e2_insample_coverage.png`, `task11e2_transmission_mechanism.png`.
No new data was acquired (the ONS curtailment files already hold the reason code, origin code and constraint description used in 11E2-d).

Notation: r = hourly SIN-wide potential VRE share of load (%) = (wind + solar + curtailed) / load; f(r) = logistic curtailment rate of a technology as a function of r (L, k, x0). "Populated support" = bins of 2 pp of r with at least 15 observed hours (r <= 63 %); the largest r ever observed is 75.8 %.
All 2030/2040/2050 numbers use the Task 11D-0 / 11E proxy (the 2025 hourly SIN shape scaled by the PTE annual totals of wind, solar and total generation) and the Task 11B gross formula (curtailed = PTE generation x rate; D23 pending).

## 0. Summary

| Question | Answer |
|---|---|
| Is 2040/2050 in-sample under the hourly driver? (11E2-a) | **2030 yes, 2040 mostly, 2050 no.** Share of projected hours inside the populated support: 2030 99.6-99.7 %; 2040 TB 96 / TG 93 / TA 86 %; 2050 TB 60 / TG 70 / TA 43 %. Share of the projected curtailed energy produced by hours **beyond** the support (wind): 2030 2-3 %; 2040 13 / 21 / 30 % (TB / TG / TA); 2050 62 / 51 / 77 %. The hourly formulation fixes the Task 11B extrapolation problem for 2030-2040, **not** for 2050. |
| Does the model backtest and hold out of sample? (11E2-b) | **Yes in the observed regime, with a visible downward bias in the latest years.** Wind 2025: -8 % in sample, -11 % leave-one-year-out, -19 % trained on 2022-24 (benchmarks: national P -45 %, time trend -43 %, Task 11D regional prototype -37 %). Solar: +1 to +15 % out of sample. Fails when the training support is far below the test regime (trained on 2022-23, r <= 39: -56 % in 2025). |
| Is the curve stable? (11E2-b) | **Stable across years 2023-2026 (gap <= 4.4 pp) and between wind and solar near r = 40; not stable across seasons or hours of day, and wind drifts upward ~2 pp per year.** 2022 (first COFF year) is an outlier (17.6 pp). Wet season / Q1 curve is up to 14 / 23 pp higher at the same r; night-time wind curve differs by 19 pp. |
| Does it survive the time control? (11E2-b, resolves D25?) | **Better than any monthly P, but time is not eliminated.** Partial correlation of national monthly wind C with the hourly-model rate given t: 0.70 (0.68 with the model trained without that year); national P 0.42; P_NE 0.14. Incremental R2 over time: 0.13 (hourly) vs 0.047 (national P) vs 0.005 (P_NE). Time still adds 0.10 R2 (p < 0.001; about +0.24 pp per month): a residual upward drift remains unexplained and is not absorbed by thermal / hydro shares. |
| Does the hourly approach work for wind? (11E2-c) | **Yes, same family as solar.** Wind L = 0.73 (bootstrap 0.68-0.78), x0 = 40.9, k = 0.143; solar L = 0.74 (0.62-0.87), x0 = 41.9, k = 0.101. Equal within sampling error near r = 40; wind is steeper above r = 50 (+6 to +8 pp, interval excludes 0). Technology-specific asymptotes are not distinguishable. |
| Does it narrow the wind envelope? | **It narrows the statistical band, not the structural uncertainty, and it moves the centre.** Wind 2050 (TB / TA / TG): hourly 239 / 387 / 208 TWh (bootstrap 227-248 / 363-406 / 199-215; L = 1 variant 295 / 498 / 250), against 11E envelope 86-145 / 162-245 / 79-127 and 11B national 361 / 568 / 322. The hourly curve sits above the top of the 11E envelope and inside the 11B range, and 30-58 % of its 2050 hours are beyond the support. |
| Can one unified curve replace the two? (11E2-c) | **For totals, yes.** One curve for total VRE curtailment (L 0.77, k 0.117, x0 42.2) gives monthly R2 0.61 (separate curves 0.63), annual totals within 0.1-1 pp of the separate curves and 2030-2050 projection totals within +-2.1 %. The wind/solar split it implies is less accurate for solar (2025: -9.2 % vs -6.7 %), so technology accounting stays separate for the OM/CM step of Task 13. |
| Is NE curtailment export-bound? (11E2-d) | **No, and the class data say more than that.** NE wind curtailment by ONS class (DEB energy / REB reliability / EUB external unavailability): DEB 8 % (2022) -> 61 % (2026); REB 33 % -> 28 %. In 2026 (descriptions complete) 61.5 % is system frequency / energy balance, 23 % NE-internal network limits, 15 % interchange-related (flow controls 9.8 %, SE-side network 5.3 %). Export capacity at its demonstrated maximum is reached in only 0.3-4.7 % of the curtailed energy of any class. See 4 for the correction to the "local / security dominates" reading. |
| Retire the PDE/PET extension? | **Recommended (with a stated limitation); registered as candidate D26, pending.** |
| Decidable now? | **D24 yes, D25 yes, D26 yes; D23 no** (needs the PTE/CEBRI authors). Section 7. |

## 1. Sub-task 11E2-a - in-sample coverage of the hourly driver

Observed r (SIN, 41,616 hours 2022-01..2026-09): mean 21.6 %, p95 39.3, p99 50.0, p99.9 62.3, maximum 75.8. By year the distribution shifts upward: p95 26.5 / 28.9 / 36.0 / 45.6 / 47.0 % (2022-2026), maximum 38.2 / 39.2 / 48.8 / 71.3 / 75.8.
Populated support is the same for both technologies: bins up to r = 63.0 % have at least 15 hours (51.1 % with at least 100 hours).

Projected hourly r (2025 shape scaled by the PTE totals, phi = 1; the 2025 check reproduces the observed 2025 distribution, 99.8 % inside the support):

| Scenario, year | mean r | p95 | max | hours r <= 75.8 (observed max) | hours inside support (r <= 63) | wind curtailment from beyond support | solar curtailment from beyond support |
|---|---|---|---|---|---|---|---|
| TB 2030 | 27.6 | 49.0 | 75.5 | 100 % | 99.6 % | 2.8 % | 2.8 % |
| TB 2040 | 34.1 | 60.8 | 93.5 | 99.4 % | 96.4 % | 13.4 % | 15.8 % |
| TB 2050 | 58.0 | 93.8 | 146.7 | 78.9 % | 59.9 % | 62.2 % | 61.9 % |
| TA 2040 | 45.1 | 76.6 | 119.7 | 94.5 % | 85.5 % | 29.7 % | 45.4 % |
| TA 2050 | 69.9 | 112.8 | 174.4 | 59.5 % | 42.5 % | 77.5 % | 72.8 % |
| TG 2040 | 38.6 | 66.9 | 103.9 | 98.4 % | 92.6 % | 20.7 % | 28.6 % |
| TG 2050 | 52.5 | 85.8 | 134.7 | 88.4 % | 70.3 % | 50.7 % | 55.7 % |

(TA 2030 is identical to TB 2030; TG 2030 is within 1.5 pp of it on r, and has 99.7 % of hours inside the support and 2.1 % of the curtailment beyond it.) Figure: `outputs/figures/task11e2_insample_coverage.png` (observed vs projected histogram with the support shaded, exceedance curve, and the extrapolated share of curtailment).

**Reading.** The weight of the extrapolation falls on the 2050 hours with r above the support (TA: 57 % of hours have r above 63 %, and the p95 of r is 113 %, i.e. potential VRE output exceeds the load). Splitting the E central value (wind + solar) into curtailment produced by hours inside and beyond the support:
TB 2040 109 + 19, TB 2050 134 + 220; TA 2040 151 + 91, TA 2050 128 + 409; TG 2040 136 + 46, TG 2050 158 + 176 TWh (inside + beyond). The curve itself saturates (L <= 0.77), so capping r at the support changes the total by only 2-4 % (the "no curve extrapolation" low bound of section 6);
what is not tested is whether the **stationarity of the curve and of today's flexibility** survives r above 76 %. Flexibility sensitivity (r_eff = r / phi): TA 2050 536 -> 476 (phi 1.25) -> 406 (phi 1.5) TWh; TA 2040 242 -> 179 -> 127.
Northeast alone (r_NE = NE VRE potential / NE load, same proxy): the NE ratio is not the model driver (NE exports most of its VRE: mean 111 %, maximum 375 %); 0 % of 2030 hours, 0.4-5 % of 2040 and 15-48 % of 2050 hours exceed its observed maximum. Listed only to show the regional variable is far more extrapolated than the system-wide one.

## 2. Sub-task 11E2-b - backtest, out-of-sample validation, stability, time confound

### 2.1 Annual backtest (curtailed TWh, SIN; error = (predicted - observed) / observed)

Wind (curve fitted on the training months only; benchmarks refitted on the same months: national-P logistic of the D22 family, and a linear time trend of the monthly rate):

| Scheme | Year | Observed | Hourly model | National P | Time trend |
|---|---|---|---|---|---|
| in sample | 2023 | 3.41 | 4.83 (+42 %) | 6.60 (+94 %) | 4.25 (+25 %) |
| in sample | 2024 | 9.55 | 11.13 (+17 %) | 13.85 (+45 %) | 11.42 (+20 %) |
| in sample | 2025 | 26.22 | 24.01 (-8 %) | 21.03 (-20 %) | 21.20 (-19 %) |
| in sample | 2026 Jan-Sep | 19.67 | 16.92 (-14 %) | 12.73 (-35 %) | 19.31 (-2 %) |
| train 2022-24 | 2025 | 26.22 | 21.23 (-19 %) | 14.44 (-45 %) | 14.86 (-43 %) |
| train 2022-24 | 2026 Jan-Sep | 19.67 | 15.06 (-23 %) | 8.21 (-58 %) | 13.30 (-32 %) |
| train 2023-24 (2022 left out) | 2025 | 26.22 | 22.22 (-15 %) | 14.63 (-44 %) | 18.19 (-31 %) |
| train 2023-24 (2022 left out) | 2026 Jan-Sep | 19.67 | 15.77 (-20 %) | 8.53 (-57 %) | 17.07 (-13 %) |
| leave-one-year-out | 2025 | 26.22 | 23.41 (-11 %) | 20.34 (-22 %) | 19.05 (-27 %) |
| train 2022-23 | 2024 / 2025 / 2026 | 9.55 / 26.22 / 19.67 | -35 % / -56 % / -61 % | -57 / -79 / -81 % | -28 / -54 / -46 % |

2022 (observed 0.40 TWh) is over-predicted by 2.5 TWh in sample (+619 %): the first COFF year sits well below the later curve at the same r (section 2.3). The Task 11D regional prototype for 2025 was 16.4 predicted vs 26.2 observed (-37 %): the hourly model **beats that benchmark in every scheme except the one trained on 2022-23**, where the training support ends at r = 39 and every method fails.
Monthly rate RMSE of the hourly model by year in sample: 3.2 / 2.9 / 1.5 / 6.6 / 5.1 pp (2022-2026). The error is not noise: the model **under-predicts 2025-2026 and over-predicts 2023-2024**, the signature of the upward drift in 2.3.

Solar (30 months):

| Scheme | Period | Observed | Hourly model | National P | Time trend |
|---|---|---|---|---|---|
| in sample | 2024 Apr-Dec / 2025 / 2026 Jan-Sep | 3.25 / 11.00 / 9.67 | +25 % / -7 % / +1 % | +69 % / -13 % / -19 % | +11 % / -15 % / +11 % |
| train 2024-04..2025-06 | 2025 Jul-Dec / 2026 Jan-Sep | 6.79 / 9.67 | +15 % / +10 % | -41 % / -36 % | -3 % / +46 % |
| leave-one-year-out | 2025 / 2026 | 11.00 / 9.67 | -12 % / +1 % | -22 % / -27 % | -25 % / +44 % |

### 2.2 Stability of the curve (L pinned at the pooled value; k and x0 refitted per group; gap = largest absolute difference from the pooled curve over r = 20-60 within the group's support)

| Dimension | Wind: x0 (gap, pp) | Solar: x0 (gap, pp) |
|---|---|---|
| Year | 2022 54.1 (17.6) / 2023 40.5 (2.1) / 2024 41.3 (2.1) / 2025 41.1 (2.8) / 2026 40.0 (4.4) | 2024 41.0 (4.2) / 2025 41.1 (2.5) / 2026 42.4 (1.9) |
| Season (dry May-Oct / wet Nov-Apr) | 41.7 (2.7) / 36.0 (13.9) | 42.7 (3.1) / 38.4 (7.0) |
| Quarter Q1 / Q2 / Q3 / Q4 | 32.7 (23.4) / 40.0 (3.7) / 42.2 (3.4) / 39.5 (4.8) | 37.5 (8.1) / 39.5 (7.1) / 43.2 (4.2) / 43.1 (2.4) |
| Hour of day (day 07-17 / rest) | 38.6 (6.3) / 53.9 (19.1) | 41.8 (0.2) / 44.5 (9.1; 0.3 TWh only) |

The weighted F tests reject equality in every dimension (p < 0.001; thousands of hours), so they carry no information; **effect size is the criterion.** Verdict: **years 2023-2026 are consistent within about 2-4 pp; seasons and hours of day are not.** The wet-season / first-quarter wind curve sits well to the left (x0 33 vs 41): at r = 30 % the wet-season wind curtailment rate is 20 % against 10 % in the dry season. A single curve therefore averages over a seasonal mixture whose weights are fixed by the 2025 hourly shape in the projection; that is acceptable for annual totals but should not be read as a stable physical law.
Month-bootstrap intervals of the pooled curve (5-95 %): wind L 0.68-0.78, x0 39.0-42.4, f(40) 0.32-0.37; solar L 0.61-0.87, x0 37.2-46.1, f(40) 0.31-0.36.

Subsystems (own fits, free L): wind in the NE (57.5 of 59.2 TWh) reproduces the SIN curve (L 0.74, k 0.144, x0 40.5; monthly R2 0.75), while N + S + SE together (1.8 TWh) differ (x0 53.6, R2 0.47) but carry 3 % of the energy. Driving NE wind with the SIN-wide r (R2 0.75) is slightly better than with the NE-only ratio r_NE (0.72): the system-wide variable is the right one.
Solar NE vs SE: x0 37.5 vs 50.1, L 0.62 vs 1.0; monthly R2 0.75 vs 0.55 (SE is weaker): the solar curve is less homogeneous across subsystems than the wind curve (two subsystems; indicative).

### 2.3 Drift
Weighted regression of the yearly binned rate minus the pooled curve on year (r 25-55): wind **+2.3 pp per year (p < 0.001)**, +2.0 pp per year excluding 2022 (p < 0.001); solar +0.2 pp per year (p = 0.74).

### 2.4 Time-confound test (Task 11D-b style; monthly C, OLS, Newey-West 6 lags)

| Sample, driver | corr(C, driver) | partial corr given t | incremental R2 of driver over t | R2 of t over driver | p of t given driver |
|---|---|---|---|---|---|
| wind national, 57 months, hourly model in sample | 0.87 | **0.70** | 0.130 | 0.099 | < 0.001 |
| same, hourly model trained without the evaluated year | 0.85 | **0.68** | 0.124 | 0.128 | < 0.001 |
| same, r_p95 (no fitting) | 0.90 | 0.63 | 0.107 | 0.033 | 0.001 |
| same, national P (Task 7-7D) | 0.71 | 0.42 | 0.047 | 0.271 | < 0.001 |
| wind NE, 57 months, hourly model (NE curve on SIN r) | 0.87 | 0.68 | 0.124 | 0.101 | < 0.001 |
| same, P_NE (Task 11D) | 0.61 | **0.14** | 0.005 | 0.361 | < 0.001 |
| wind national, last 30 months, hourly model | 0.77 | 0.69 | 0.267 | 0.112 | < 0.001 |
| solar national, 30 months, hourly model | 0.88 | **0.82** | 0.372 | 0.044 | 0.019 |
| solar, national P | 0.63 | 0.73 | 0.293 | 0.348 | < 0.001 |

The hourly driver survives the time control far better than P_NE and national P (partial 0.68-0.70 against 0.14 and 0.42; the leave-year-out version rules out that the result is an in-sample artefact). It does **not** eliminate time: adding t to the wind model raises R2 from 0.76 to 0.86, with a time coefficient of about +0.24 pp per month. Thermal and hydro shares of generation do not absorb it (t stays at p < 0.001; thermal share p = 0.18 once t is in). Interpretation: the monthly "time effect" of Task 11D is mostly the upward shift of the hourly distribution of r (D25 mechanism of Task 11E), plus a residual drift of unknown origin that the hourly model does not explain. A hypothesis, not tested here: the composition of the ONS classes shifts toward system energy balance (section 4), which changes the shape of the pooled curve over time.

## 3. Sub-task 11E2-c - the hourly model for wind, and a unified driver

### 3.1 Wind versus solar curves (month-bootstrap 5-95 %)
| Curve | L | k | x0 | f(30) | f(40) | f(50) | f(60) | r at 50 % of L / at 90 % of L |
|---|---|---|---|---|---|---|---|---|
| wind 2022-01..2026-09 | 0.73 (0.68-0.78) | 0.143 (0.128-0.161) | 40.9 (39.0-42.4) | 0.128 | 0.343 | 0.576 | 0.688 | 40.9 / 56.3 |
| wind 2024-04..2026-09 (solar window) | 0.80 (0.73-0.87) | 0.122 | 42.5 | 0.142 | 0.338 | 0.571 | 0.715 | 42.5 / 60.5 |
| solar 2024-04..2026-09 | 0.74 (0.62-0.86) | 0.101 (0.086-0.124) | 41.9 (37.6-46.1) | 0.170 | 0.333 | 0.512 | 0.635 | 41.9 / 63.6 |

Paired difference wind - solar on the common window: -2.8 pp at r = 30 (interval -4.3 to -1.3), +0.5 pp at r = 40 (-1.6 to +2.8), +5.9 at r = 50 (3.9 to 8.5), +8.1 at r = 60 (4.7 to 12.8); L +0.06 (-0.04 to +0.16), x0 +0.7 (-3.2 to +4.1). **Same threshold and asymptote within sampling error; wind is steeper and higher above r = 50; solar is higher below r = 30.** No evidence for technology-specific asymptotes.

### 3.2 Wind projection under the hourly model (TWh; phi = 1)
| Scenario, year | PTE wind | beyond-support hours | hourly low / central / high (L = 1) | bootstrap 5-95 % | 11B national low / central / high | 11D regional point (lo-hi) | 11E envelope low / central / high |
|---|---|---|---|---|---|---|---|
| TB 2030 | 120.6 | 0 % | 21.6 / 21.6 / 22.3 | 20.5-23.1 | 22.5 / 30.2 / 36.3 | 18.7 (14-22) | 18.7 / 19.1 / 19.1 |
| TB 2040 | 159.5 | 4 % | 45.4 / 45.5 / 48.7 | 43.9-47.5 | 33.2 / 82.6 / 107.1 | 30.1 (19-41) | 30.1 / 34.6 / 36.3 |
| TB 2050 | 393.0 | 40 % | 234.6 / 239.4 / 295.2 | 227.3-248.2 | 82.9 / 360.6 / 385.1 | 85.4 (47-178) | 85.7 / 121.3 / 144.8 |
| TA 2040 | 256.7 | 15 % | 119.1 / 120.1 / 136.4 | 116.6-123.3 | 54.1 / 206.2 / 237.4 | 53.6 (30-96) | 53.7 / 70.4 / 79.5 |
| TA 2050 | 581.0 | 58 % | 376.6 / 387.2 / 497.6 | 363.0-405.6 | 122.5 / 567.5 / 579.1 | 129.2 (69-303) | 161.8 / 194.8 / 244.5 |
| TG 2040 | 213.9 | 7 % | 77.8 / 78.2 / 85.0 | 76.0-80.7 | 44.9 / 136.8 / 171.4 | 42.5 (25-66) | 42.6 / 51.8 / 56.0 |
| TG 2050 | 369.5 | 30 % | 205.4 / 208.4 / 249.5 | 199.3-215.3 | 77.9 / 321.7 / 354.9 | 79.1 (44-154) | 79.3 / 108.8 / 126.7 |

Width of the 2050 range (high / low): 11B 4.6-4.7x; 11E envelope 1.5-1.7x; hourly 1.2-1.3x; hourly bootstrap p95 / p05 1.08-1.12x. **It does narrow the range, but the tight statistical band is conditional on stationarity**: it measures sampling error of a curve whose 2050 operating points are 30-58 % beyond the observed hours, and it does not contain the 11E envelope (the hourly low bound for 2050 is 1.5-1.6 times the top of the 11E envelope for the same scenario). The wind curve of the regional approach and that of the hourly approach are different statements about the same future: the regional one caps the rate at a function of P_NE that tops out at 22-42 % of PTE wind, the hourly one lets the system-wide share r reach 60-170 % of load and applies today's absorption capability. Neither can be checked against data beyond r = 76 %.
Flexibility (TA 2050 wind, r / phi): 387 (phi 1) -> 347 (1.25) -> 298 (1.5) TWh; the 2040 and 2050 totals move by 25-35 % for a 25 % improvement in effective absorption.

### 3.3 Unified driver (one curve for total VRE curtailment, 2024-04..2026-09)
Parameters L 0.771, k 0.117, x0 42.2 (separate wind curve on the same window L 0.80, k 0.122, x0 42.5; solar L 0.74, k 0.101, x0 41.9).
Monthly total rate: R2 0.609 / RMSE 4.51 pp (unified) against 0.625 / 4.42 pp (two curves). Annual total error: in sample 2025 -4.4 % (unified) vs -4.5 % (two curves), 2026 -5.9 vs -6.0, 2024 +28 vs +28; leave-one-year-out 2025 -7.3 vs -7.1, 2026 -8.3 vs -8.2. Split of the unified rate by technology potential: wind 2025 -2.4 % (two curves -3.6 %), solar -9.2 % (-6.7 %); 2024 solar +12 % (+25 %).
Projection totals (wind + solar, TWh), two curves vs unified: TB 2040 129 vs 132, TB 2050 368 vs 365; TA 2040 246 vs 249, TA 2050 563 vs 556; TG 2040 184 vs 187, TG 2050 343 vs 343 (differences -1.3 to +2.1 %).
**A unified driver is defensible for totals** (it is simpler and equally accurate); the technology split of curtailed energy (needed for the OM/CM emission-factor step in Task 13) should still come from the technology-specific curves, since the unified split is not systematically better on either technology.

## 4. Sub-task 11E2-d - the transmission negative result (paper-ready subsection) and the ONS reason classes

### 4.1 Subsection text (for the paper)

> **Curtailment of Northeast wind is not primarily bound by export capacity.** We test the hypothesis that NE wind curtailment is driven by the limits of the NE-to-rest-of-grid interchange, using ONS operational data. (i) Reconstructed capacity of the NE boundary lines (thermal rating of lines with one NE terminal, registry-based), of NE transformers and of the line length stock are collinear with calendar time (r = 0.92-0.99) and explain the monthly wind curtailment rate no better than time itself (R2 0.61-0.72 vs 0.73); the ratio of potential VRE output to boundary capacity improves on the regional penetration P_NE (partial correlation given time 0.60 vs 0.14) but does not replace time. (ii) Net NE export reaches 95 % of its trailing 12-month maximum in only 0.4-3.1 % of the hours of 2022-2026, and only 1-8 % of NE wind curtailment occurs in such hours (median export at curtailment = 48-70 % of that maximum, by constraint class). (iii) ONS classifies curtailed energy by reason (energy balance, reliability, external unavailability) and by constraint description. In 2026 (full description coverage), 61.5 % of NE wind curtailment is attributed to system frequency control / energy balance, 23.1 % to limits of NE-internal network elements, and 15.1 % to interchange-related elements (flow controls on the NE-SE corridors 9.8 %, SE-side network elements 5.3 %). The share attributed to energy balance rose from 8 % (2022) to 61 % (2026). The binding constraint on NE wind is therefore predominantly a system-wide balance between VRE output and the load the rest of the system can absorb, for which the hourly system-wide VRE share of load is the natural driver, with explicit export-limit constraints a minority (about 5 % of NE wind curtailment over 2025-2026 for flow controls alone; 12-15 % including SE-side elements) that is growing. The demonstrated export maximum is a lower bound of the dynamic limit, so these tests cannot exclude contingency-dependent limits; the constraint descriptions are the direct evidence.

### 4.2 ONS classes (D5 mapping: ENE -> DEB energy surplus, CNF -> REB reliability, REL -> EUB external unavailability; origin SIS = system, LOC = local)
NE wind curtailed energy (TWh; shares of the year):
| Year | TWh | DEB (energy) | REB (reliability) | EUB (ext. unavail.) | origin SIS | origin LOC |
|---|---|---|---|---|---|---|
| 2022 | 0.4 | 8.1 % | 32.8 % | 59.1 % | 58 % | 42 % |
| 2023 | 3.4 | 26.0 % | 54.9 % | 19.0 % | 74 % | 26 % |
| 2024 | 9.4 | 28.5 % | 61.8 % | 9.7 % | 62 % | 38 % |
| 2025 | 25.7 | 49.8 % | 37.1 % | 13.1 % | 81 % | 19 % |
| 2026 (Jan-Sep) | 18.6 | 61.5 % | 27.7 % | 10.8 % | 76 % | 24 % |
| 2022-2026 | 57.5 | 48.4 % | 39.1 % | 12.5 % | | |

Every DEB (ENE) row is of system origin; REB (reliability) is 57.6 % local origin; EUB is 85 % system origin. By subsystem (all years, wind): N 90 % DEB, S 57 % DEB / 43 % EUB, SE 85 % DEB (small volumes, 1.8 TWh together). **Solar** (NE + SE): DEB 48 % (2024) -> 61 % (2025) -> 86 % (2026); REB 43 % -> 26 % -> 7 %: solar curtailment is already almost entirely an energy-balance phenomenon, consistent with the midday duck-curve driver of Task 11E.

### 4.3 Constrained element (keyword classification of `dsc_restricao`; approximate; descriptions exist only for 2025-26: 48 % of 2025 energy and 100 % of 2026 energy)
| Share of NE wind curtailment | 2025 (described part: 48 %) | 2026 (100 %) |
|---|---|---|
| system frequency control (all DEB) | 25.8 % | 61.5 % |
| NE-internal network (500 kV Acu III / Jaguaruana / Quixada / Milagres, etc.) | 10.0 % | 23.1 % |
| SE-side network (Rio Novo do Sul 500/345 kV, Itabira, Campos) | 11.6 % | 5.3 % |
| interchange flow controls (FNESE, FNS, FPOTPPA) | 0.9 % | 9.8 % |
| other / outage | 0.0 % | 0.3 % |
| no description | 51.7 % | 0 % |

Share of each element in hours with NE export >= 95 % of its trailing maximum: NE-internal 3.1 %, SE-side 1.8 %, flow controls 2.1 %, system frequency 0.4 %; by class DEB 0.3 %, EUB 0.9 %, REB 4.7 %. Median export / maximum at curtailment: 0.49 (frequency), 0.64 (flow controls), 0.69 (SE-side), 0.71 (NE-internal). The explicit flow controls bind at 64 % of the historical maximum, which shows that dynamic limits sit well below the demonstrated maximum: **the saturation test (11E-c) understates export limitation, and the descriptions are the better evidence.**

### 4.4 Corroboration check (what the classification does and does not support)
- Supported: curtailment is not primarily export-bound. Interchange-related elements are 3.6 % of NE wind curtailment over all years (flow controls only; 10.5 % with SE-side elements), 15 % in 2026.
- Supported: the dominant and growing class is system-wide energy balance (DEB, system origin, frequency control), not local and not transmission.
- **Not supported as stated**: that "constraint reasons are predominantly local / security". Local / reliability reasons (REB + EUB) were 70-90 % of NE wind curtailment in 2022-2024 but only 38 % in 2026; the largest class today is energy balance. Network-element limits (NE-internal + SE-side + flow controls) total 38 % of the 2026 energy, 23 % of it NE-internal, so local transmission reinforcement can still matter for about a fifth of NE wind curtailment, which is a different statement from export capacity.
- Caveat: classification of descriptions is by keywords; 2022-2024 have no descriptions (only the code classes); code classes are ONS's own.

### 4.5 Should the PDE/PET extension be retired? - **Recommendation: yes, with a stated limitation (registered as candidate D26, pending).**
Reasons: (1) the project's driver is system-wide and hourly; transmission expansion enters it only through the absorption capability held fixed in phi, and the sensitivity to phi already brackets the effect (TA 2050 536 -> 476 -> 406 TWh); (2) capacity stocks do not outperform time (11E-c) and ONS has no published coincident transfer limits, so PDE/PET figures could not be mapped to curtailment without an unsupported hypothesis; (3) interchange-related constraints are a minority of the energy (4-15 %), and NE-internal network limits (23 % in 2026) are not what PDE/PET interchange assumptions describe; (4) the extension is the costliest open item and would not change the decision structure of D24.
Limitation to state if retired: the 2026 data show 38 % of NE wind curtailment in network-element classes, a share that expansion could reduce; it is covered only as a flexibility sensitivity (phi), not as a calibrated pathway. If you prefer to keep the thread open, the minimal alternative is to leave it deferred with this limitation noted.

## 5. Sub-task 11E2-e - decision table, options A-E (wind + solar curtailed TWh; central with range)

Numbers for C and A are those of `docs/task11e_findings.md` (unchanged). E is re-estimated here and reproduces the 11E values exactly (central). For E the range shown is "no curve extrapolation (r capped at the support) to L = 1", and the bootstrap band (sampling error only, 5-95 %) in brackets.

| Option | What it is | 2040 TB / TA / TG | 2050 TB / TA / TG |
|---|---|---|---|
| **A** | regional (NE) wind curve as primary, as the envelope L = 0.25 / 0.5 / 1.0 (capacity-grounded low) + hourly solar | 117 (112-123) / 193 (172-218) / 155 (144-168) | 237 (195-282) / 344 (301-427) / 234 (200-273) |
| **B** | A reported alongside C as an alternative scenario | no number of its own: it reports the A line and the C line side by side | no number of its own: A line and C line side by side |
| **C** | reject: keep the national P curves (Task 11B) | 175 (87-221) / 356 (117-423) / 256 (105-321) | 513 (138-566) / 775 (188-810) / 482 (140-550) |
| **D** | defer | no number by nature (nothing adopted). Bracket across A, C, E for reference: 87-221 / 117-423 / 105-321 | no number by nature. Bracket: 138-566 / 188-810 / 140-550 |
| **E** | hourly dose-response, wind + solar (this task: validated for 2030-2040) | 128 (127-135; boot 124-131) / 242 (238-275; 232-252) / 181 (179-197; 175-187) | 355 (344-432; 332-371) / 536 (516-680; 498-565) / 334 (326-396; 315-348) |
| E, in-support part of the central value | curtailment from hours inside the observed support | 109 / 151 / 136 | 134 / 128 / 158 |
| E, beyond-support part | from hours with r above 63 % | 19 / 91 / 46 | 220 / 409 / 176 |
| E, flexibility sensitivity phi = 1.25 / 1.5 | r_eff = r / phi | 84 / 56; 179 / 127; 125 / 85 | 294 / 231; 476 / 406; 264 / 198 |

2030 (for reference; in-sample): E gives 64 / 63 / 58 TWh (TB / TA / TG; range 58-65). The 2025 total observed by ONS is 37 TWh (potential basis differs, see D23).
For the three scenarios the 2050 totals under E (334-536) exceed A (234-344) and are below C (482-775) in all three scenarios. The ordering E > A in 2050 reflects stationarity of the system-wide curve against a saturating regional one, not a measurable difference, and it is where the beyond-support share is largest.
**D23 sensitivity under E.** The net reading (PTE generation = delivered) cannot be implemented with the hourly curve: inverting realized -> potential through f(r) has no stable fixed point in steep parts of the curve, and applied to the **observed 2025 realized profile** it returns 113 TWh curtailed against 37 TWh observed. So under E only the gross reading is operational. Direction only: if the PTE generation were delivered energy, true potential and hence r would be higher than in the gross computation, and the E numbers would then be a lower bound of what the same curve implies.

## 6. Recommendation on D24 (reading, not a decision)

1. **Adopt E as the primary formulation of the curtailment-rate driver** (replacing the national-P curves of D21/D22 for projections, with D13-D22 otherwise untouched), reported **by horizon**: 2030 and 2040 as validated central values (E 64 / 63 / 58 TWh in 2030; 128 / 242 / 181 TWh in 2040; the 2040 values are 86-96 % in-sample by hours, 13-30 % of the energy from beyond-support hours, and carry the known bias below), and **2050 as a conditional range, never a single number**: E with the in-support / beyond-support decomposition and the flexibility sensitivity (phi = 1 / 1.25 / 1.5), plus C as the labelled national-extrapolation reference. In option language: E, with the 2050 results presented in B-style (E and C lines side by side).
2. **Do not adopt A as primary.** It is dominated by E on every test that could be run: time-confound (P_NE partial 0.14 vs 0.70), backtest (the regional prototype -37 % vs -11 to -19 % out of sample), in-sample coverage (P_NE is outside its observed range in all 2040/2050 scenarios, and the proxy of constant NE shares is untested), and it needs an unidentified L. It can stay as a lower-side sensitivity.
3. **Why not simply adopt E for 2050:** the in-sample coverage test says the problem is only solved at its root up to 2040. For 2050, 51-77 % of the E energy comes from hours that no Brazilian data cover, and the central result depends on flexibility staying at today's level. Option E is a coherent mechanism and a validated one inside the observed regime; it is not a forecast of 2050.
4. Known biases to carry in the text: (a) E under-predicted 2025-2026 annual wind curtailment by 8-23 % and over-predicted 2023-2024 (drift +2 pp per year); if the drift continues the 2030-2040 values are more likely low than high; (b) the curve averages a seasonal mixture (wet-season / Q1 curve is far to the left); (c) solar has 30 months in one regime; (d) the gross reading (D23).

## 7. Are the pending decisions decidable now?

- **D24 - decidable.** Options A-E have numbers or an explicit statement of why not (section 5), the validation evidence is in sections 1-3, the recommendation is in section 6.
- **D25 - decidable.** The question "is P (national / regional) a time trend?" has a complete answer: monthly P, national or regional, is a time-confounded proxy of the hourly system-wide VRE share of load; the hourly driver survives the time control (partial 0.68-0.70 vs 0.14 and 0.42), leaving an upward drift of +2 pp per year (wind) that is unexplained. The candidate text can be closed with that sentence.
- **D26 - decidable** (retire the PDE/PET extension on the basis of the Task 11E / 11E2 negative result): yes, with the limitation of 4.5.
- **D23 - not decidable from the data.** Gross vs net remains a question for the PTE / CEBRI authors. It does not block D24, D25 or D26; under E only the gross formula is operational (section 5).
- Gaps that remain, none blocking: (i) flexibility in 2050 (storage, interconnection, demand response) is not calibrated by any Brazilian data; the phi sensitivity is the only treatment; (ii) the unexplained wind drift; (iii) seasonal and diurnal heterogeneity of the curve; (iv) solar sample length; (v) description of constraints exists only for 2025-26.

## 8. Documentation touched and data acquired

| File | Change |
|---|---|
| `docs/task11e2_findings.md` | New. This memo. |
| `docs/roadmap.md` | Appended "Update (Task 11E2)": validation outcome, PDE/PET extension proposed for retirement (D26 pending), blocked items unchanged. Prior text untouched. |
| `docs/methodology.md` | Appended section "2.3d Update (Task 11E2)": validation of the hourly driver, coverage test, unified driver, transmission mechanism. Prior text kept. |
| `docs/claude_commands.md` | Appended section 1.11E2 after 1.11E; task table: new 11E2 row. |
| `docs/progress_log.md` | Appended a Task 11E2 entry. |
| `config/discovered_sources.yaml` | D24 (`task11e2_update`: validation, options A-E numbers, recommendation), D25 (`task11e2_update`), D23 (`task11e2_note`), new D26 `pending`. No status changed. |
| `analysis/task11e2_*.py`, `tests/test_analysis_task11e2.py` | New throwaway analysis code and smoke tests (6 tests). |

New data: none. Analysis cache `interim/task11e_hourly_subsystem.parquet` reused.

## 9. Reproducibility and limits
Re-run in order: `task11e_transmission_confound.py`, `task11e_solar_intraday.py`, `task11e_wind_envelope.py` (Task 11E), then `task11e2_insample_coverage.py`, `task11e2_backtest.py`, `task11e2_wind_hourly.py`, `task11e2_transmission_mechanism.py`, `task11e2_options_table.py` (they use the system Python that has `statsmodels`; the project `.venv` does not). Bootstrap draws resample months (300 draws, fixed seeds); a draw that fails to fit is skipped. Statistics are descriptive; Newey-West errors (6 lags); the hourly curves are weighted logistic fits to 2-pp bins of r with at least 15 hours. Out-of-sample means held-out years of the same Brazilian sample (4.75 years in total), not an independent system.
