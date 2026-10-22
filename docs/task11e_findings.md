# Task 11E - Intra-day solar, wind asymptote envelope, transmission-capacity confound test: decision-ready memo

Status: investigation / prototype, Brazil-only data. No file under `src/` was changed, no decision adopted (D13-D22 untouched; D23, D24, D25 remain `status: pending`; **D26 was not registered**, see 3.5).
Follows `docs/task11d_findings.md` (cross-linked, not edited) and `docs/task11c_investigation_report.md`.
Code (throwaway, outside the package): `analysis/task11e_solar_intraday.py` (11E-a), `analysis/task11e_wind_envelope.py` (11E-b), `analysis/task11e_transmission_confound.py` (11E-c),
shared loaders `analysis/task11e_common.py`. Tables and figures: `DATABASE_ROOT/outputs/tables/task11e_*` and `outputs/figures/task11e_overview.png`.
New data: ONS transmission registries and pairwise interchange, documented in `docs/ons_transmission_data_sources.md`.

## 0. Summary

| Question | Answer |
|---|---|
| Is the solar signal hidden in temporal aggregation? (11E-a) | **Yes.** Midday (10-14 h) potential VRE share of load explains the monthly solar curtailment rate with R2 = 0.78 (national P of Tasks 7-7D: 0.40); partial correlation given time 0.83 (P: 0.73). Hourly SIN-wide VRE share of load is a stable dose-response driver (60 % of solar curtailment falls in 10-14 h). Solar need not stay on the national annual curve. Caveat: 30 months only, one regime. |
| Is the same true for wind? (found while testing the "time effect") | **Yes, and it explains most of the Task 11D time confound.** NE wind curtailment as a function of the hourly SIN-wide potential VRE share of load r is stable over 2023-2026 and, as a FIXED curve, reproduces the national monthly wind rate with R2 = 0.76 without using time (time alone 0.73). Time still adds (R2 0.86; an under-prediction of +2 to +3 pp in 2025-26 remains). |
| Can the wind asymptote L be identified? (11E-b) | **No** (all L give the same RMSE, 0.068). L is therefore reported as an envelope: NE-regional wind 2050 curtailment 79-245 TWh over L = 0.25 / 0.5 / 1.0 (rates 22-42 % of PTE wind), plus a capacity-grounded floor that raises the low bound for TA 2050 to 162 TWh. |
| Is NE interchange capacity the structural driver? (11E-c) | **No, as a stock; partially, as a ratio; not as a binding constraint in the hourly data.** Capacity stocks are collinear with time (r = 0.92-0.99) and do not beat it. VRE potential / boundary capacity beats P_NE net of time (partial 0.60 vs 0.14) but time stays significant. Only 1-8 % of NE wind curtailment occurs when NE net export is >= 95 % of its trailing 12-month maximum; at curtailment the median export is 48-70 % of that maximum. The binding constraint is system-wide (energy balance), not NE export saturation. |
| Are 2040/2050 totals now plausible? | **They are bounded, not settled.** Under the options below 2050 totals range from 234 TWh (A, TG) to 810 TWh (national high). 2040 totals range 112-423. The hourly approach puts 2030 inside the observed regime (58-64 TWh), and every approach makes 2050 depend on flexibility (storage, interconnection, demand response) that no Brazilian data can calibrate. |

## 1. Sub-task 11E-a - intra-day solar

**Data (step 1).** No new acquisition was needed. Already in `raw/`: ONS balance by subsystem (hourly load, wind, solar), per-plant capacity-factor files (hourly dispatched solar, D20 basis) and COFF solar curtailment (half-hourly per plant, subsystem-tagged, from 2024-04).
`analysis/task11e_common.hourly_panel()` assembles one hourly subsystem panel (203,424 rows, 2021-01..2026-10-20; October 2026 is excluded from every statistic as incomplete).

**Metrics** (potential basis = realized + curtailed, so the regressor does not fall when curtailment rises): `mid_solar_share` = mean over 10:00-14:59 of solar potential / load (SIN); `mid_vre_share` = same with wind + solar; `r_p95`, `r_mean`, `r_max` of the hourly SIN potential VRE share of load r.
Dependent variable: national monthly C_solar (D20 basis), 30 months 2024-04..2026-09 (0.028-0.365).

| Driver (national, 30 months) | corr with C_solar | Spearman | corr with t | partial corr given t |
|---|---|---|---|---|
| P (Tasks 7-7D) | 0.63 | 0.67 | 0.14 | 0.73 |
| solar share of generation | 0.42 | 0.37 | 0.89 | -0.52 |
| midday solar share of load | 0.82 | 0.84 | 0.96 | 0.82 |
| **midday VRE share of load** | **0.88** | **0.88** | 0.56 | **0.83** |
| r_p95 | 0.88 | 0.87 | 0.62 | 0.79 |
| r_mean | 0.80 | 0.79 | 0.33 | 0.82 |

OLS with Newey-West errors (R2 / RMSE): P alone 0.40 / 0.068; midday VRE share 0.78 / 0.041; r_p95 0.77 / 0.042; time alone 0.45 / 0.065; midday VRE share + t 0.83 / 0.037 (t p = 0.04); P + t 0.74 / 0.044. Adding r_p95 to P leaves P with a **negative** coefficient (-0.0066, p = 0.05).
The signal of the annual/monthly national P is real (partial 0.73 over these 30 months, where P and t are almost uncorrelated, 0.14), but it is a coarse proxy of the intraday metric.

**Hourly dose-response.** Solar curtailment rate by r (% of potential): 20-25 % -> 4 / 11 / 8.5 (2024 / 2025 / 2026); 30-35 % -> 18.5 / 24.8 / 22.5; 40-45 % -> 37.6 / 37.9 / 35.6; 50-60 % -> n.a. / 57.6 / 56.9; > 60 % -> n.a. / 72.6 / 73.4. Stable across 2025-2026; 2024 is lower at low-to-mid r (about -6 pp). By hour of day: 29-32 % at 08-11 h, 0 at night. 60.1 % of curtailed solar energy falls in 10-14 h (54.1 % of potential).
A fixed hourly curve (logistic, L = 0.74, k = 0.10, x0 = 42) reproduces the monthly rate with R2 = 0.74 / RMSE 0.045 (in sample). Out of sample it degrades: trained on 2024-04..2025-06 and tested 2025-07.. R2 = 0.30 / RMSE 0.060 (under-predicts by 3 pp); trained on 2025-01.. and tested on 2024 R2 = -0.21 / RMSE 0.052.
Subsystem panel (NE and SE only; the South has no centralized solar in the dispatched series; n = 60): the within-subsystem relation with the intraday metric is positive (R2 0.41 with fixed effects, but its significance falls once t is added), while the subsystem solar share of generation does not explain anything (R2 0.03). This panel is weak evidence (2 subsystems).

**Outcome.** The temporal-aggregation hypothesis is supported. For solar, a driver based on the hourly SIN-wide VRE share of load is a better explanatory variable than annual/monthly P and is usable as a prototype (30 months, one regime, moderate out-of-sample skill). **Solar does not have to stay on the national annual curve**; the national curve remains the comparison line (option C). Limitation to flag: every use of the hourly curve for 2040/2050 holds today's flexibility fixed (section 4).

## 2. Sub-task 11E-b - wind asymptote L as a scenario envelope

**Why an envelope.** Fixing L at 0.25, 0.5 and 1.0 and refitting k and P0 on the 57 NE months gives the same RMSE (0.068) in all three cases; the half-sample fits disagree for every L (second-half k = 0.02-0.04). The data do not discriminate between L values, so L is reported as a range of structural uncertainty. Values: 0.25 = the free fit of Task 11D (point estimate), 1.0 = the physical ceiling used in D21/D22, 0.5 = mid-point (arbitrary, labelled so).

| NE-regional wind curtailment (TWh; proxy of 11D, NE wind share 0.93) | L = 0.25 | L = 0.5 | L = 1.0 |
|---|---|---|---|
| TB 2040 / 2050 | 30 / 86 | 35 / 121 | 36 / 145 |
| TA 2040 / 2050 | 54 / 130 | 70 / 195 | 80 / 245 |
| TG 2040 / 2050 | 43 / 79 | 52 / 109 | 56 / 127 |

(wind rate as % of PTE wind in 2050: TB 22 / 31 / 37, TA 22 / 34 / 42, TG 22 / 30 / 34.) The 2030 values (15-19 TWh) do not depend on L. P_NE is outside the observed range (>83.6 %) in 2040 and 2050 for all scenarios.

**Capacity-grounded refinement (from 11E-c).** A necessary-curtailment floor, floor = max(0, NE wind + solar potential - NE load - 8.76 x K), with K the NE export capacity (GW; trailing 12-month maximum of observed export = 15.3 GW in 2026-09), O = 0 (no must-run generation kept), NE load scaled with PTE total generation. K grows linearly with the registry boundary stock (+0.64 GW/yr) in the central path; constant (no expansion) and 2x-growth paths are also computed.
Back-test: the floor is 0 in 2022-2025 although 0.4-31 TWh were curtailed (annual energy balance does not bind today; the hourly profile and system-wide constraints do), so the floor is a lower bound that only starts to matter when NE VRE potential far exceeds NE load plus export capacity.

| Floor on NE VRE curtailment, TWh (wind share pro rata) | K constant | K linear trend (central) | K 2x trend |
|---|---|---|---|
| TA 2050 | 335 (wind 270) | 201 (wind 162) | 66 (wind 53) |
| TB 2050 | 173 (133) | 38 (29) | 0 |
| TG 2050 | 154 (113) | 19 (14) | 0 |
| TA 2040 | 73 (48) | 0 | 0 |

Only TA 2050 exceeds the L = 0.25 curve: its low bound rises from 130 to 162 TWh (statistical bound -> **capacity-grounded bound**; the label matters: the first is arbitrary, the second depends on the NE-share proxy, load scaling and the K path). It is not an upper bound and cannot narrow L from above.

## 3. Sub-task 11E-c - transmission interchange capacity and the time confound

### 3.1 Data (acquired; see `docs/ons_transmission_data_sources.md`)
ONS operational data, cc-by, accessed 2026-10-22: `Linha_Transmissao` (2,343 lines >= 230 kV: terminals, kV, long-duration operating current, entry / deactivation dates), `Capacidade_Transformacao` (2,045 basic-network transformers: MVA, dates), `Intercambio_Nacional` 2021-2026 (hourly pairwise flows). Planning documents (PDE/PET) were not used.
**Caveats:** the capacity series are stocks **reconstructed from the current registry and its commissioning dates**, not published transfer limits (those are not in the open data); line MVA = sqrt(3) x kV x long-duration operating current (thermal rating, summed over lines: it is not a coincident transfer capacity); the "revealed capacity" (trailing 12-month maximum of the observed NE net export) is a lower bound of what the network can carry. Reconciliation: NE net export of the ONS balance equals the pairwise interchange (correlation 1.0000, identical annual means) and equals generation minus load in every year 2021-2025.

Series (NE, 2022-01 -> 2026-09): boundary line rating 34.8 -> 44.1 GVA (17 -> 21 lines; steps 2022-07, 2023-01, 2025-02, 2025-12, 2026-02; CAGR 5.2 %/yr); km of >= 230 kV lines 37.6 -> 43.6 thousand; NE transformer capacity 89.6 -> 109.8 GVA; revealed export capacity 9.7 -> 15.3 GW.

### 3.2 Does capacity explain the "time effect"? (monthly NE wind rate, 57 months, OLS, Newey-West 6 lags)

| Model | R2 | RMSE | Comment |
|---|---|---|---|
| t | 0.728 | 0.046 | reference |
| P_NE | 0.373 | 0.070 | Task 11D |
| log boundary MVA | 0.611 | 0.055 | corr(stock, t) = 0.92 |
| log NE km | 0.720 | 0.047 | corr(stock, t) = 0.99: equal to time, not better |
| log NE transformer MVA | 0.693 | 0.049 | corr 0.98 |
| log revealed export capacity | 0.428 | 0.067 | |
| R_boundary = VRE potential / boundary MVA | 0.612 | 0.055 | beats P_NE |
| R_revealed = VRE potential / revealed capacity | 0.602 | 0.056 | |
| R_boundary + t | 0.827 | 0.037 | |
| R_revealed + t | 0.843 | 0.035 | |

Partial correlations given time: R_boundary 0.60, R_revealed 0.65 (P_NE: 0.14); partial correlation of t given R: 0.74-0.78 (still large). Bounded logistics on the ratio: RMSE 0.054 (R_boundary), 0.052 (R_revealed), P_NE 0.068, linear in t 0.046.
**Result:** capacity stocks do **not** explain the time effect as well as time itself (they are time in disguise). The ratio of VRE potential to capacity is a better driver than P_NE net of time, but it does not replace time: this is a mixed, mostly negative result for "transmission capacity is the structural driver".

### 3.3 Is NE export saturated when curtailment happens? (hourly, 2022-2026)
Saturated = NE net export >= 95 % of its trailing 12-month maximum. Share of NE wind curtailment in saturated hours: 3.8 / 0.7 / 7.6 / 1.2 / 0.9 % (2022-2026); saturated hours are 0.4-3.1 % of hours. Export / revealed capacity at curtailment: median 0.58 (deciles 0.25-0.85). By ONS reason class (shares of NE wind curtailment): ENE (energy) 49 %, energy-weighted median export / cap 0.48, only 0.3 % in saturated hours, 53 % in hours with export below half the capacity; CNF (reliability) 39 %, median 0.70, 4.7 % saturated; REL (external unavailability) 12 %, median 0.56, 1.0 % saturated.
**Result (negative for the simple transmission-bottleneck story):** curtailment happens mostly when NE export is far from its demonstrated maximum. Caveat: the dynamic limit can be lower than the maximum ever observed (N-1 security, topology, SE absorption), which this data cannot separate; the ENE share (energy balance of the whole system) and the next result point the same way.

### 3.4 The hourly SIN-wide VRE share of load explains most of the time effect
NE wind curtailment rate (% of potential) by hourly SIN potential-VRE share of load r (2022 / 2023 / 2024 / 2025 / 2026): r 25-30 % -> 1.0 / 8.2 / 8.6 / 13.7 / 14.5; 30-35 % -> 3.5 / 13.1 / 13.9 / 17.1 / 19.8; 35-40 % -> 4.2 / 27.2 / 27.7 / 27.4 / 31.6; 40-45 % -> n.a. / n.a. / 40.3 / 43.9 / 42.5; 45-50 % -> 45.8 / 52.4 / 50.9 (2024-26); 50-60 % -> 63.7 / 63.2 (2025-26); > 60 % -> 75.2 / 77.3. Pooled 2022-2026: 0.5 % (r < 15), 5.7 % (20-25), 16 % (30-35), 29 % (35-40), 43 % (40-45), 63 % (50-60), 76 % (> 60). The top decile of r (mean 41 %) holds 53 % of NE wind curtailment; observed hourly r reaches 75.8 % (p99 50 %).
The curve is stable from 2023 on (2022, the first year of the COFF series, sits lower at the same r), so the monthly "time trend" is largely the upward shift of the hourly distribution of r (p95 of r: 26 -> 29 -> 36 -> 46 -> 47 % in 2022-2026).
A fixed hourly wind curve (L = 0.73, k = 0.14, x0 = 41) predicts the **national** monthly wind rate with R2 = 0.76 (RMSE 0.042), against 0.73 for time alone; with t added R2 = 0.86 and t stays significant (b = 0.002/month, p < 0.001; partial corr(C, t | curve) 0.65): an under-prediction of about +2 to +3 pp in 2025-26 remains unexplained. Fitted on 2022-24 only, the curve under-predicts 2025-26 by 4-5 pp (RMSE 0.070).

### 3.5 D26 - not triggered
The task asked for D26 only if interchange capacity were a strong explanator. It is not (3.2, 3.3), so **no D26 was registered** and no driver based on interchange capacity is proposed. The new driver found in 3.4 (hourly SIN-wide VRE share of load) is added as **option E inside the D24 candidate text** instead of minting a new decision number; if you prefer it registered separately (D26), say so.

## 4. Numeric 2040 / 2050 totals (wind + solar curtailed, TWh) under each D24 option

All numbers use the Task 11B gross formula (curtailed = PTE generation x rate; D23 pending), the Task 11D proxy for NE shares where a regional wind curve is used, and are central (low - high). PTE wind + solar potential for reference: TB 2040 359 / 2050 596; TA 491 / 822; TG 439 / 599.

| Scenario, year | **C**: reject, national curves (Task 11B) | **A**: regional wind envelope (L 0.25 / 0.5 / 1.0, capacity floor on low) + hourly solar curve | **E**: hourly dose-response for wind and solar (no regional proxy) | **D**: defer (bracket across all computed approaches) |
|---|---|---|---|---|
| TB 2040 | 175 (87 - 221) | 117 (112 - 123) | 128 (127 - 135) | 87 - 221 |
| TB 2050 | 513 (138 - 566) | 237 (195 - 282) | 355 (344 - 432) | 138 - 566 |
| TA 2040 | 356 (117 - 423) | 193 (172 - 218) | 242 (238 - 275) | 117 - 423 |
| TA 2050 | 775 (188 - 810) | 344 (301 - 427) | 536 (516 - 680) | 188 - 810 |
| TG 2040 | 256 (105 - 321) | 155 (144 - 168) | 181 (179 - 197) | 105 - 321 |
| TG 2050 | 482 (140 - 550) | 234 (200 - 273) | 334 (326 - 396) | 140 - 550 |

**B** (alternative scenario reported alongside the national one) reports the A column and the C column as two labelled lines; it has no number of its own. Components of A: wind TB 2050 86 / 121 / 145, TA 162 / 195 / 245, TG 79 / 109 / 127 (solar 110-183); solar rate of the hourly curve 41 - 62 % in 2040-2050 central against 46 - 86 % of the national solar curve (Task 11B, 2040-2050).
Components of E (central, rates): wind TB 2040 29 %, 2050 61 %; TA 47 %, 67 %; TG 37 %, 56 %; solar 41 - 62 %. 2030 under E is 58 - 64 TWh (rates 17 - 18 % wind, 27 - 29 % solar), inside the observed range.

**How to read E.** The curve is stationary: it holds the 2025 hourly shape, today's flexibility (hydro operation, thermal must-run, interconnection, no storage) and the 2025 weather year. The PTE shares imply a mean hourly VRE share of load of 34 / 45 / 39 % (TB / TA / TG) in 2040 and **58 / 70 / 53 % in 2050**, against 26.5 % in 2025 and a maximum of 75.8 % ever observed; 12-40 % of 2050 hours fall beyond the observed range, where the logistic is an extrapolation (L = 0.73, and the high bound forces L = 1). Sensitivity to flexibility (r_eff = r / phi): TA 2050 central falls from 536 TWh (phi = 1) to 476 (phi = 1.25) and 406 (phi = 1.5).
**How to read A.** It rests on the proxy (constant NE shares) and an unidentified L; its solar part is the same hourly solar curve (the national solar curve is not used). The A-versus-E gap in 2050 (344 vs 536 for TA) is a difference between a regional monthly driver that saturates at L <= 1 on a 49-84 % P_NE range and a SIN-wide hourly driver that extrapolates over hours of 76-110 % r; neither can be validated.

## 5. Are D23 / D24 / D25 decidable now?

- **D25 - decidable.** The question "how much of the P effect is a time trend" has a quantitative answer (11D-b) and 11E adds its mechanism: the time trend is largely the growth of the hourly distribution of VRE share of load; stocks of transmission capacity are not a better explanation. Candidate text updated.
- **D24 - decidable, with an added option.** The numbers for A / B / C / D are in section 4. Option E (hourly dose-response) is new and materially changes the picture (2050 totals between A and C). My reading, not a decision: E for 2030-2040 (inside or near the observed regime) and a reported envelope A-E-C for 2050, labelled as flexibility-conditional.
- **D23 - not decidable from the data.** Gross vs net remains a question for the PTE/CEBRI authors; every number above shifts with it. (It does not block D24/D25.)
- **Gaps that remain** (none blocks the decisions, all limit what is claimed): (i) no calibration of flexibility (storage, interconnection, demand response) for 2050, so the 2050 range is scenario-conditional; (ii) the NE export capacity is a reconstructed stock and revealed maximum, not a published limit; real interchange limits or EPE expansion plans (PDE/PET) would be needed to say anything on transmission, and remain the deferred extension; (iii) a residual upward drift (curve under-predicts by 2-3 pp in 2025-26, 4-5 pp when fitted on 2022-24 only) is not explained by any driver tested; (iv) solar has 30 months in one regime.

## 6. Documentation touched and data acquired

| File | Change |
|---|---|
| `docs/task11e_findings.md` | New. This memo. |
| `docs/ons_transmission_data_sources.md` | New. Provenance, access date, license, caveats of the three newly acquired ONS datasets (operational vs planning distinction stated). |
| `docs/roadmap.md` | Appended "Update (Task 11E)": the production migration of the old plan is renumbered 11F; Task 13 still blocked; prior text untouched. |
| `docs/methodology.md` | Appended section 2.3c "Update (Task 11E)": the intraday / hourly driver concept, the envelope treatment of L, the negative result on transmission capacity, preliminary and not adopted. Prior text kept. |
| `docs/claude_commands.md` | Appended section 1.11E entry before section 1.4; task table: new 11E row, former 11E renamed 11F. |
| `docs/progress_log.md` | Appended a Task 11E entry. |
| `config/discovered_sources.yaml` | D24 (option E, numeric ranges, status of the evidence) and D25 (final answer) updated; D23 note added. All `pending`. D26 not registered. |
| `analysis/task11e_*.py`, `tests/test_analysis_task11e.py` | New throwaway analysis code and smoke tests. |

New data (all under `DATABASE_ROOT/raw/ons/interchange/`, each with a retrieval manifest): `Intercambio_Nacional-2021..2026` (CSV for 2021-22, Parquet for 2023-26), `Linha_Transmissao.parquet`, `Capacidade_Transformacao.parquet`, three data dictionaries (JSON). Cache (regenerable): `interim/task11e_hourly_subsystem.parquet`.

## 7. Reproducibility and limits

Re-run in order: `task11e_transmission_confound.py` (writes the floor table), `task11e_solar_intraday.py`, `task11e_wind_envelope.py`. Statistics are descriptive; Newey-West errors (4-6 lags); the hourly curves are weighted logistic fits to 2-point-wide bins of r with at least 15 hours; nothing is validated out of sample beyond the splits reported; `validation_data` in `config/scenarios.yaml` is still empty.
