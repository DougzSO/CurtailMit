# Task 11E5 - The residual wind curtailment drift of the hourly model: characterisation, explanations, extended model, and the D25 recommendation

Status: investigation / prototype, Brazil-only data, **no new data**. No file under `src/` was changed and no decision was adopted (D25 `status: pending`; D23, D24, D26 are `adopted` since Task 11F0).
Follows `docs/task11e2_findings.md` (where the drift was first found), `docs/task11e3_findings.md`, `docs/task11e4_findings.md` (cross-linked, not edited).
Code (throwaway, outside the package): `analysis/task11e5_drift_characterization.py` (a), `task11e5_drift_hypotheses.py` (b), `task11e5_extended_model.py` (c); smoke tests `tests/test_analysis_task11e5.py` (5). Tables: `DATABASE_ROOT/outputs/tables/task11e5_*`.

## 0. Summary

| Question | Answer |
|---|---|
| How large is the drift, with a confidence interval? (a) | Pooled hourly curve, monthly residual of the wind curtailment rate: **+1.4 pp per year** (Newey-West 95 % interval 0.5 to 2.3; block bootstrap 0.6 to 2.9) over 2022-2026, +1.6 (0.6 to 2.7) from 2023. The binned-at-fixed-r measure of Task 11E2 (+2.0 to +2.3) is the same effect read at a different weighting; the honest range is **1.4 to 2.3 pp per year**. The drift is significant over the whole sample, not over the last 33 months alone (p = 0.06). |
| What does it compound to by 2050? (a) | Naive uncapped: 24 years x 1.6 = **+39 pp (14 to 64)**, not "about 50": the slope is 1.4-1.6, not 2. **That number is not physically available**: the central 2050 wind rate of option E is already 56-67 % against an asymptote of 73 %, i.e. only **7-17 pp of headroom**. Capped at the asymptote the additional wind curtailment in 2050 is +34 / +41 / +52 TWh (TA / TB / TG; linear), +15 to +20 TWh (saturating, 6-year time scale), about 0-4 % (step). The more defensible assumption is bounded (step or saturating), not linear. |
| Where does the drift sit? (a) | **At low-to-intermediate r, not at the plateau.** Observed rate by class of r, 2023 -> 2026: r 20-25 3.5 -> 9.8 %, 25-30 7.7 -> 14.4 %, 30-35 12.5 -> 19.9 %; but 45-50 50.3 -> 50.2 (2025 -> 2026) and above 60 75 -> 78 %. NE carries it (+1.4 / +1.6 pp per year); the rest of the system (3 % of the energy) is not distinguishable from zero. |
| Which explanation is supported? (b) | **A regime change in 2025, not vintage or composition.** The residual is better described by a **step of about +4.6 pp at 2025-01** than by a smooth trend (BIC lower by 4.9; permutation p = 0.07, borderline), a saturating curve does not beat the linear one, and the step coincides with the doubling of the energy-balance (ENE / DEB) class in the curtailment (29.5 % of the energy in 2024, 50.6 % in 2025, 60.8 % in 2026). At fixed r the energy-balance and external-unavailability classes rose in 2025; the reliability class did not. **Fleet vintage and state composition are rejected**: the composition effect is negative (-0.8 to -2.4 pp) and the within-group change is +5.5 to +8.9 pp: old plants drifted as much as or more than new ones. The drift sits in RN and BA, not in PI. The cause of the 2025 change (an operating or regulatory rule) cannot be tested with the data in hand. |
| Does an explicit trend term improve the model safely? (c) | **No; none of the five variants passes all pre-registered criteria.** The hourly driver does not collapse (partial correlation of the r-component with C given t stays at 0.69-0.70 in every variant): the confound safety criterion is met. But (i) the bootstrap widths of the curve parameters grow by 1.6 to 8.5 times (k or x0), (ii) out-of-sample the trend variants help on one validation split and hurt on the other (e.g. the saturating variant: -3 % instead of -17 % for 2025 when trained to 2024, but +11.5 % instead of -3.1 % for 2025 Jul-Dec when trained to 2025-06), (iii) the trend term cannot be extrapolated without an assumption that 4.75 years of data cannot identify: 2050 wind ranges from -33 % to +31 % across the variants. |
| Recommendation for D25 | **(ii) Accept the drift as a documented, quantified limitation**; do not add a trend term to option E. Recommended text in section 5. |

## 1. Sub-task 11E5-a - characterisation and quantification

### 1.1 Residual by year (pooled hourly wind curve fitted on all 57 months, L 0.733, k 0.143, x0 40.9; SIN)
| Year | Observed TWh | Predicted TWh | Residual TWh | Residual (pp of potential) |
|---|---|---|---|---|
| 2022 | 0.40 | 2.88 | -2.48 | -3.04 |
| 2023 | 3.41 | 4.83 | -1.42 | -1.44 |
| 2024 | 9.55 | 11.13 | -1.58 | -1.35 |
| 2025 | 26.22 | 24.01 | +2.20 | +1.56 |
| 2026 (Jan-Sep) | 19.67 | 16.92 | +2.74 | +2.79 |
The pattern (flat at about -1.4 in 2023-24, positive in 2025-26) already suggests a level change rather than a straight line.

### 1.2 Trend of the monthly residual (pp of rate per year)
| Window | Slope | Newey-West 95 % | Block-bootstrap 95 % |
|---|---|---|---|
| 2022-01..2026-09 (57 months) | 1.40 | 0.54 to 2.26 (p = 0.001) | 0.56 to 2.87 |
| 2023-01..2026-09 (45 months) | 1.62 | 0.58 to 2.65 (p = 0.002) | 0.37 to 3.58 |
| 2024-01..2026-09 (33 months) | 1.66 | -0.07 to 3.38 (p = 0.06) | -1.38 to 5.41 |
By subsystem group (own pooled curve): NE 1.43 (0.46 to 2.40) all months, 1.62 (0.38 to 2.85) from 2023; N + S + SE together (1.8 of 59 TWh) 1.09 (-0.72 to 2.91), 1.82 (-0.85 to 4.48): not distinguishable from zero or from the NE value.

### 1.3 Where it sits: observed curtailment rate (% of potential) by class of r
| r | 2023 | 2024 | 2025 | 2026 | slope 2023-26, pp per year (95 %) |
|---|---|---|---|---|---|
| 20-25 | 3.5 | 4.6 | 9.3 | 9.8 | 2.4 (-0.2 to 5.0) |
| 25-30 | 7.7 | 8.2 | 13.1 | 14.4 | 2.6 (-0.2 to 5.4) |
| 30-35 | 12.5 | 13.2 | 16.3 | 19.9 | 2.9 (0.9 to 4.9) |
| 35-40 | 26.0 | 26.5 | 26.2 | 31.4 | 2.6 (very wide) |
| 40-45 | - | 39.0 | 42.2 | 41.8 | 0.9 (very wide) |
| 45-50 | - | 44.5 | 50.3 | 50.2 | - |
| 50-60 | - | - | 62.2 | 62.9 | - |
| > 60 | - | - | 74.7 | 78.1 | - |
The classes with at least three years of data show +2.4 to +2.9 pp per year; the plateau shows none. The drift is a change of the curve at low-to-intermediate r (the curve flattens: k falls from 0.168 in 2023 to 0.118 in 2026 at an unchanged x0 of about 40-41), not a vertical shift of the whole curve.

### 1.4 Compounding to 2030 / 2040 / 2050
Naive scalar (additive, uncapped): 24 years x slope = +39 pp (central 1.62; 14 to 64 with the interval of the slope); 25 years from 2025: +40 pp. **Not defensible**, because the rate cannot exceed the asymptote: headroom of the central wind rate of option E to L = 0.733 in 2050 is 6.7 pp (TA, rate 66.7 %), 12.4 pp (TB, 60.9 %), 16.9 pp (TG, 56.4 %); in 2040 it is 26.5 / 44.8 / 36.8 pp.
Additional wind curtailment (TWh) of an additive drift of 1.62 pp per year from 2026, capped at L (central curve, PTE-scaled 2025 profile):
| Scenario, year | none | linear | saturating tau 12 | tau 6 | tau 3 |
|---|---|---|---|---|---|
| TB 2040 / 2050 | 0 | +31 / +41 | +19 / +25 | +13 / +17 | +7 / +10 |
| TA 2040 / 2050 | 0 | +37 / +34 | +25 / +22 | +18 / +15 | +10 / +10 |
| TG 2040 / 2050 | 0 | +39 / +52 | +24 / +31 | +17 / +20 | +9 / +12 |
(Relative to option E central totals, wind + solar: 2050 +6 / +12 / +15 % (TA / TB / TG) for linear, 3-6 % for tau 6.) **Which assumption is more defensible?** The shape evidence of 11E5-b favours a bounded change (a step) over a straight line, and the physical headroom is a hard cap; a linear compounding is the upper bound, a bounded one the more plausible. In every case the sign is upward: the central values of option E are more likely low than high.

## 2. Sub-task 11E5-b - candidate explanations

### 2.1 Regime break versus smooth trend (monthly residual, 57 months; BIC; lower is better)
| Model | parameters | RSS | BIC | vs linear |
|---|---|---|---|---|
| constant | 1 | 994.7 | 167.0 | +9.5 |
| linear trend | 2 | 783.7 | 157.5 | 0 |
| **step at 2025-01 (+4.56 pp)** | 2 | 719.3 | 152.6 | **-4.9** |
| linear + step at 2025-01 | 3 | 717.9 | 156.5 | -1.0 |
| saturating (tau 5 years) | 2 | 795.0 | 158.3 | +0.8 |
A single step at **January 2025** beats the straight line, and the step-plus-trend model adds nothing over the step. The permutation test of the step against a constant (block shuffles of 6 months, 500 permutations) gives p = 0.07: suggestive, not conclusive. A saturating learning curve (tau up to 5 years) does not beat the linear trend, so a "one-time learning effect" reading is not supported.
In-data markers: the energy-balance (ENE, DEB) class share of the wind curtailment goes 8.5 % (2022), 26.9 % (2023), 29.5 % (2024), **50.6 % (2025)**, 60.8 % (2026): the doubling in 2025 coincides with the step. The first month in which the 'system frequency control' description appears is 2025-09 (descriptions are incomplete before 2026); the ONS data hold **no machine-readable log of operational or regulatory rule changes**, so a documented rule cannot be matched to January 2025 with the data in hand.

### 2.2 Class composition
Observed rates by class at fixed r (hours-weighted over r 20-40; % of potential): ENE 1.6 (2023), 2.4 (2024), 5.7 (2025), 7.0 (2026); CNF 3.0, 6.3, 6.6, 7.0; REL 1.1, 0.7, 2.6, 2.9. From 2024 to 2025 the total rises 9.4 -> 14.9 %: ENE explains +3.3 pp, REL +1.9, CNF +0.3. Within r 35-40, CNF falls from 15 to 8.5-9.8 % while ENE rises from 6-8.5 to 15-20 %. Class-by-class residual trends of separate pooled curves are small and not individually significant (ENE +0.4 to +0.5 pp per year, CNF + REL + other +0.4 to +0.5; all intervals include zero), because splitting the series removes the power to see a step. **Suggestive**: the 2025 change is a rise of energy-balance and external-unavailability curtailment at a given r.

### 2.3 Fleet vintage and state composition (plant level, 200 COFF wind plants, 6.3 million plant-hours; vintage = share of installed capacity added since 2021-12 from the plant-level capacity files, 99 % of COFF plants matched)
The fleet changed massively: the potential share of plants with more than half of their capacity added since 2021-12 goes from 7 % (2022) to 29 % (2023), 43, 56 and 60 % (2026). Shift-share of the standardised curtailment rate at r 20-40 (fixed distribution of r), percentage points:
| Grouping | Period | Total | Within groups | Composition |
|---|---|---|---|---|
| vintage cohort | 2023 -> 2025 | +4.7 | +5.5 | **-0.8** |
| vintage cohort | 2023 -> 2026 | +6.6 | +8.9 | **-2.4** |
| state (BA, RN, PI, CE, other) | 2023 -> 2025 | +4.8 | +5.0 | -0.2 |
| state | 2023 -> 2026 | +6.6 | +7.2 | -0.6 |
Standardised rates 2023 -> 2026: old plants 9.6 -> 21.2 %, new plants 9.6 -> 13.0 %; RN 15.0 -> 29.1 %, BA 6.6 -> 12.2 %, CE 21.6 -> 20.0 %, PI 5.5 -> 6.5 %. **The vintage hypothesis is rejected**: the arrival of new wind capacity did not cause the drift (new plants curtail less than old ones at the same r, and the composition effect is negative). The drift is within groups and concentrated in RN and BA (and old plants), which points to a change in the network or operating conditions of those areas, not to who is generating.

### 2.4 What can and cannot be tested with the data in hand
- Supported (circumstantially): an operating-regime change around January 2025 raising energy-balance (and external-unavailability) curtailment at low-to-intermediate r, concentrated in RN / BA.
- Rejected: fleet vintage, state composition (as drivers of the drift); smooth saturating learning curve (as better than linear or step).
- **Untestable for now**: documented ONS dispatch or ANEEL regulatory changes (no log in the data); plant technology (turbine type, hub height) and siting beyond state; local grid reinforcements or outages in RN / BA (the constraint descriptions exist only for 2025-26); the contribution of demand changes not captured by r. Each would need documents or data not in hand and is not pursued here.

## 3. Sub-task 11E5-c - extended model with an explicit trend term

Models (wind, SIN; month x 2-pp-bin cells weighted by potential): base (option E); linear left shift of the curve (+beta t); saturating shift (tau chosen in {1, 2, 3, 5} years); step at 2025-01; slope change of the curve (k + kappa t). Pre-registered criteria are in the script docstring: S1 r-component keeps its explanatory power (partial correlation >= 0.5 and incremental R2 >= 0.08), S2 no confound (bootstrap widths of k and x0 at most 1.5 times the base), S3 worth (absolute held-out error falls by at least 5 pp in at least 2 held-out periods), S4 bounded extrapolation.

| Model | In-sample monthly R2 / RMSE (pp) | Residual trend left (pp per year) | S1 partial corr / incr. R2 | S2 width ratio k / x0 | Held-out error % (S1: 2025, 2026; S2: 2025 Jul-Dec, 2026) |
|---|---|---|---|---|---|
| base | 0.761 / 4.18 | 1.46 (0.61 to 2.30) | 0.695 / 0.130 | 1.00 / 1.00 | -17.3, -21.5; -3.1, -17.1 |
| linear | 0.815 / 3.68 | 0.70 (-0.13 to 1.54) | 0.695 / 0.130 | 0.85 / **1.57** | +10.7, +24.5; +15.9, +20.3 |
| step | 0.810 / 3.73 | 0.93 (0.13 to 1.73) | 0.694 / 0.130 | 1.06 / **1.59** | -17.3, -21.5 (step unseen); +6.7, -7.2 |
| k trend | 0.824 / 3.59 | 0.44 (-0.33 to 1.21) | 0.697 / 0.131 | **1.88** / 1.07 | +1.0, +8.3; +15.6, +19.8 |
| saturating | 0.833 / 3.49 | 0.31 (-0.40 to 1.02) | 0.694 / 0.130 | 0.89 / **8.47** | -3.1, -5.0; +11.5, +1.5 |

- **S1 passes for all**: adding a trend term does not erode the hourly driver (the partial correlation of the r-component with C given t stays at 0.69-0.70; incremental R2 0.13): the confound problem of Task 11D-b does not return. This is the safe part of the result.
- **S2 fails for every variant** (x0 interval 1.6 times wider for linear and step; k 1.9 times for the slope-change model; x0 8.5 times for the saturating model, whose tau sits at the boundary of the grid and whose x0 of 79 is an artefact). The trend term and the r-curve compete for the same information.
- **S3 is mixed**: trained to 2024, the saturating and k-trend variants cut the 2025 / 2026 errors from -17 / -22 % to -3 / -5 % and +1 / +8 %; but trained to 2025-06 (where the step is already in the data) they overshoot (+11.5 to +19.8 %) while the base model is already within -3 % for 2025 Jul-Dec; the linear model overshoots in all four. The step model cannot be tested out of sample before the step.
- **S4 fails** for the linear (unbounded) and k-trend (clipped, flat) models.
Projections (wind curtailment, TWh; base / step / saturating / linear; model spread, %): 2040 TA 116 / 118 / 125 / 175, TB 44 / 46 / 49 / 102, TG 76 / 78 / 82 / 142; 2050 TA 371 / 374 / 409 / 414, TB 230 / 232 / 251 / 280, TG 201 / 202 / 217 / 263. The k-trend model gives 2050 values 21-33 % below base (artefact of the clip) and 2030 values 90 % above base. **Across variants the 2050 wind curtailment spans -33 % to +31 % around the base: the model-choice uncertainty about the trend term exceeds the effect it is meant to correct.** The bounded step model is the safest variant (+1 to +4 % in 2040-2050, +10 % in 2030) and can be offered as a sensitivity.
Conclusion of 11E5-c: the explicit trend term does not meet the safety and worth criteria; **adopting it is not recommended**.

## 4. Quantified limitation to carry in the paper
Option E under-predicts wind curtailment by about 1.4-1.6 pp of the rate per year over 2022-2026 (95 % interval 0.5-2.7), of which the largest part is a step of about +4.6 pp in January 2025 coinciding with the rise of energy-balance curtailment; it sits at r between 20 and 40 % and in RN / BA, and is not explained by the new wind fleet. For 2030 (mostly low-to-intermediate r) the effect is of the order of +10 to +14 % of wind curtailment (step and saturating variants); for 2040-2050 it is bounded by the asymptote and amounts to +1 to +4 % (step), +15 to +20 TWh (saturating, 6 years), up to +34 to +52 TWh (linear, capped) in 2050, i.e. 3-15 % of the 2050 total, always upward. This is a bounded, one-sided, quantified limitation, not an unbounded compounding.

## 5. Recommended text for D25 (reading, not a decision)
> **D25 - Time confound.** Monthly penetration P (national or regional) is a time-confounded coarse proxy of the hourly system-wide potential VRE share of load r: the hourly driver is not just time (partial correlation of the monthly wind curtailment rate with the hourly-model rate given time 0.68-0.70, against 0.14 for P_NE and 0.42 for national P), and adding an explicit trend term does not erode it (0.69-0.70). A residual upward shift of wind curtailment at fixed r remains, of about +1.4 to +1.6 pp of the rate per year over 2022-2026 (95 % interval 0.5 to 2.7; 1.4-2.3 depending on the measure), better described as a step of about +4.6 pp in January 2025 (coinciding with a doubling of the energy-balance share of curtailment) than as a smooth trend, concentrated at r between 20 and 40 % and in RN and BA, and not explained by fleet vintage or state composition; its cause is not identified with the data available. Naively compounded to 2050 it would add about 39 pp (14 to 64), but this is bounded by the asymptote of the curve: the 2050 wind rate of option E has only 7-17 pp of headroom, and the additional 2050 wind curtailment is +1-4 % (step), +15-20 TWh (saturating) and at most +34-52 TWh (linear, capped), i.e. 3-15 % of the 2050 wind + solar total, upward only; for 2030, +10-14 % of wind curtailment. The drift is not corrected in the adopted specification: an explicit trend term was tested and rejected (parameter uncertainty grows 1.6-8.5 times, out-of-sample benefit inconsistent, extrapolation not identified). The central values of option E should be read as more likely low than high.

Alternative (i), adopting the extended model, is not recommended; if you wish to keep a sensitivity, the bounded **step** variant is the only one that is safe (+0.7 to +4.3 % in 2040-2050, +10 % in 2030). D25 is decidable now; once decided, Task 11F (production migration of option E) can start with your confirmation.

## 6. Documentation touched; data acquired
| File | Change |
|---|---|
| `docs/task11e5_findings.md` | New. This memo. |
| `docs/roadmap.md` | Appended "Update (Task 11E5)". |
| `docs/methodology.md` | Appended section "2.3h Update (Task 11E5)". |
| `docs/claude_commands.md` | Appended section 1.11E5; task table: new 11E5 row. |
| `docs/progress_log.md` | Appended a Task 11E5 entry. |
| `config/discovered_sources.yaml` | D25: `task11e5_update` with the recommended final text; **still `pending`**. |
| `analysis/task11e5_*.py`, `tests/test_analysis_task11e5.py` | New throwaway analysis code and smoke tests (5). |
New data: none (plant-level hourly wind and capacity caches, regenerable, in `DATABASE_ROOT/interim/task11e5_*`).

## 7. Reproducibility and limits
Run in the project `.venv`, after the Task 11E / 11E2 scripts: `task11e5_drift_characterization.py`, `task11e5_drift_hypotheses.py`, `task11e5_extended_model.py`. Intervals: Newey-West (6 lags) and moving-block bootstrap (blocks of 6 months, 2000 resamples); the permutation test uses 500 block shuffles; the extended-model bootstrap 150 month resamples. The step date was selected from the data (a scan over break months), so its significance is the permutation p-value, 0.07. One Brazilian sample of 4.75 years.
