# Task 11D - Regional recalibration, time-confound test, pooled panel, documentation realignment

Status: investigation / prototype. No file under `src/` was changed, no decision was adopted (D13-D22 untouched; D23, D24, D25 remain `status: pending`).
Code (throwaway, not part of the package, no unit tests): `analysis/task11d_regional_recalibration.py` (11D-0, 11D-a), `analysis/task11d_time_confound.py` (11D-b),
`analysis/task11d_pooled_panel.py` (11D-c). Tables and figures: `DATABASE_ROOT/outputs/tables/task11d_*.csv|json` and `outputs/figures/task11d_*.png`.
Inputs: the Task 11C artifacts (ONS subsystem balance, dispatched solar, COFF curtailment by subsystem) and the Task 11B projection table. **No new data was acquired.**

## 0. Summary for a reader who has not seen the outputs

| Question | Answer |
|---|---|
| Does the PTE report give wind/solar by region? (11D-0) | **No.** Regional content is macroeconomic only. A labelled proxy (constant Northeast shares) is used, not an authoritative PTE number. |
| What does a Northeast-only wind curve look like? (11D-a) | A logistic fitted on P_NE = 49-84 % (57 months): L = 0.25, k = 0.16, P0 = 76. It saturates near 25 %, whereas the national curve (L = 1, P0 = 36) goes to ~100 % at P = 50 %. **But** its parameters are weakly identified (bootstrap L 95 % interval 0.12-1.00) and unstable across sub-samples. |
| Does it fix the 2040/2050 wind implausibility? (11D-a, proxy) | **In magnitude, yes**: 2050 wind curtailment 79-129 TWh (rate 21-22 %) instead of 322-568 TWh (rate 87-98 %). Conditional on the proxy, on a weakly identified asymptote, and on P_NE leaving the observed range (85-94 % vs max 83.6 %). |
| Does the same hold for solar? | **No.** There is no regional natural experiment for solar (30 months, 66-84 % P_NE, parameters at the bound). Solar stays on the national curve and then dominates the total (61-67 % of the 2050 total, 74-75 % of the 2040 total). **The total is not yet plausible.** |
| How much of the P effect is just time? (11D-b, D25) | In the Northeast, **almost all of it.** Time alone explains 73 % of the variance of C_wind; adding P_NE adds 0.5 percentage points (partial r = 0.14, p = 0.32). A rank-based partial (0.38, p = 0.004) and a last-30-month sub-sample (partial r = 0.43, p = 0.02) retain some association, which disappears when load and hydrology proxies are added (p = 0.97). |
| Pooled international panel (11D-c) | Qualified result only: 18 system-years, 7 systems, 4 international points from 3 systems. A pooled fractional logit gives C_wind = 5.6 % / 7.2 % / 10.2 % at P = 44 / 58 / 78 % (95 % CI up to 13.7 %). Northeast 2022-24 is in line with or below peers, **2025 (19.4 % at P = 78 %) is above them.** |

## 1. Sub-task 11D-0 - regional PTE data

Searched: the full text of the CEBRI PTE2 report already used in Task 11C (112 pp.) for "Nordeste", "subsistema", "regional", "transmiss" (14 hits for "Nordeste" in total) and
`config/scenarios.yaml`. The regional content is the TERM inter-regional general-equilibrium decomposition (GDP and per-capita income by macro-region, Grafico 22) and a
statement that the Northeast "continuara sendo um polo renovavel (eolica e solar)". The NEWAVE step applies supply criteria "no SIN e em cada subsistema" but publishes no
subsystem generation. **No wind or solar capacity or generation by region exists in the PTE sources; none was fabricated.**

**Proxy used (labelled as a methodological approximation, not a PTE number).** For each PTE scenario and year, with national wind W, solar S, total T (TWh):

- NE wind = s_w x W, with s_w held at its 2025 value (0.926); NE solar = s_s x S with s_s = 0.535 (2025); NE other generation (hydro + thermal + others) = 0.071 x (T - W - S).
- P_NE = (NE wind + NE solar) / (NE wind + NE solar + NE other).
- Non-NE wind keeps the observed 2025 non-NE curtailment rate (5.7 %).
- Stress variant: s_w = 0.80 (hypothetical diversification of wind away from the Northeast).

**Growth of the shares (checked, as requested)**: the NE share of national wind grew from 88.8 % (2021) to 92.6 % (2025); the NE share of dispatched solar *fell* from 69.7 % to
53.5 % (new solar in S and SE); the NE share of total generation grew from 20.8 % to 24.8 %, and its share of hydro + thermal fell from 10.6 % to 7.1 %. Holding the 2025 shares constant is therefore
a simplification in the direction of the observed trend for wind (a small upward drift is ignored) and against it for solar. Assumptions of the proxy that are unverifiable: that the PTE national
wind build-out is located in the same proportion in the NE, and that the NE's non-wind generation scales with the national residual. The proxy pushes P_NE to 85-94 % in 2040/2050, i.e. beyond
the observed 49-84 % (flagged `P_NE_extrapolated`).

## 2. Sub-task 11D-a - regional recalibration of C_wind(P_NE)

**Definitions.** Same operational definition as the national P of Tasks 7-7D with only the geographic scope changed: P_NE = (NE wind + NE dispatched solar) / (NE hydro + NE thermal +
NE wind + NE dispatched solar), realized generation, ONS balance by subsystem (solar on the D20 dispatched basis). C_wind = curtailed / (realized + curtailed) with NE curtailment from the COFF files. One
unavoidable difference, documented rather than reconciled: the NE exports and imports, so its local generation is not its load; P_NE is a generation share (a load-based variant
`P_vs_load` exists in the Task 11C table and was not used). Both P definitions use realized (post-curtailment) generation, so the regressor moves with the dependent variable
(endogeneity common to the national and regional versions).

**Fit** (same bounded logistic as `calibration.fit_calibration`, 57 months 2022-01..2026-09, P_NE 49.2-83.6, mean 71.5; C_wind 0.000-0.306):

| | L | k | P0 | observed P range | RMSE |
|---|---|---|---|---|---|
| National wind (Task 7D) | 1.000 | 0.167 | 35.6 | 10.3-29.4 | 0.061 |
| Northeast wind (this task) | 0.249 | 0.163 | 76.4 | 49.2-83.6 | 0.068 |
| NE bootstrap 95 % interval (1000 refits) | 0.12 - 1.00 | 0.09 - 112 | 67 - 99 | | |

The two curves have a similar steepness (k) but opposite positions: the national P0 is 40 points lower, which is exactly why the national curve extrapolates to ~100 % at P = 50 %. Curve values
(C_wind): at P = 50 %: national 0.92, NE 0.003; at 70 %: 0.997 vs 0.065 (NE 95 % interval 0.04-0.15); at 80 %: 0.999 vs 0.160 (0.12-0.18); at 90 %: 1.00 vs 0.225 (0.12-0.43). The full table is
`task11d_curve_comparison_national_vs_NE.csv`; the plot is `task11d_regional_recalibration.png`.

**Two caveats that limit how much weight the NE curve can carry.**
1. *Weak identification of the asymptote.* Fitting the first 28 and last 29 months separately gives L = 0.07 (C range 0-0.13) and L = 1.00 with k = 0.016, P0 = 180 (C range 0.04-0.31). The
   asymptote 0.25 is a feature of the window, not an established ceiling. The NE interval is wide at the top (C(90 %) up to 0.43, C(100 %) up to 0.74).
2. *Residual time structure.* The P-only fit overpredicts 2022-24 (residual -0.029, -0.047, -0.040) and underpredicts 2025-26 (+0.046, +0.088): the curve rises more slowly than curtailment actually did. This is the
   footprint of the time confound quantified in section 3.

**Projection prototype (Task 11B logic, wind only; `src/projection.py` untouched).** Formula unchanged: wind curtailed = wind generation x C (D23 gross reading, still pending). Central estimate with s_w = 0.926 and
bootstrap bounds of the NE curve (sampling uncertainty only):

| Scenario | Year | P national | P_NE (proxy) | NE extrapolated? | Wind curtailed, 11B national curve (TWh) | Wind curtailed, NE-regional proxy (TWh) [bootstrap 95 %] | Wind rate: 11B -> regional |
|---|---|---|---|---|---|---|---|
| TB | 2025 | 26 | 78.7 | no | 19.7 | 16.4 [12.5, 19.8] | 16.8 % -> 14.1 % |
| TB | 2030 | 29 | 80.3 | no | 30.2 | 18.7 [14.2, 21.7] | 25.1 % -> 15.5 % |
| TB | 2040 | 36 | 84.9 | yes | 82.6 | 30.1 [18.9, 41.1] | 51.8 % -> 18.8 % |
| TB | 2050 | 50 | 91.8 | yes | 360.6 | 85.4 [46.5, 177.7] | 91.8 % -> 21.7 % |
| TA | 2040 | 44 | 89.1 | yes | 206.2 | 53.6 [30.4, 95.7] | 80.3 % -> 20.9 % |
| TA | 2050 | 58 | 94.0 | yes | 567.5 | 129.2 [68.8, 303.0] | 97.7 % -> 22.2 % |
| TG | 2040 | 39 | 86.7 | yes | 136.8 | 42.5 [25.3, 65.7] | 64.0 % -> 19.9 % |
| TG | 2050 | 47 | 90.6 | yes | 321.7 | 79.1 [43.7, 154.2] | 87.1 % -> 21.4 % |

(2030 TA/TG and 2025 TA/TG are in `task11d_projection_regional_proxy.csv`; the s_w = 0.80 stress variant lowers 2050 values by 9-11 %, e.g. TA 2050 115.5 TWh.) For reference the observed 2025 wind curtailment
(ONS) is 26.2 TWh against 16.4 TWh from this prototype (19.7 TWh from the 11B national curve): both underestimate the observed 2025 level, the regional one more, consistent with the
residuals above.

**Solar (limitation, as required).** The NE has 30 months with published solar curtailment (2024-04 onward), P_NE 66.5-83.6, C_solar 0.037-0.371. An exploratory logistic hits the bound (L = 1.0, k = 0.062, P0 = 96.8, i.e.
no information about the shape) and C_solar correlates with both P_NE (0.50) and time (0.55). There is no solar high-penetration natural experiment in the data; **no regional solar refit was forced**, and the
solar part of the totals below remains the national curve (an extrapolation, 70-86 % rates).

| Scenario | Year | Total curtailed 11B (TWh) | Total with NE-regional wind + national solar (TWh) | of which solar |
|---|---|---|---|---|
| TB | 2040 | 174.6 | 122.0 | 91.9 |
| TB | 2050 | 512.6 | 237.4 | 152.0 |
| TA | 2040 | 355.5 | 202.9 | 149.3 |
| TA | 2050 | 774.9 | 336.5 | 207.3 |
| TG | 2040 | 255.8 | 161.5 | 119.0 |
| TG | 2050 | 481.6 | 238.9 | 159.8 |

Even with the regional wind curve the 2050 totals (237-337 TWh) are dominated by solar (61-67 % of the total in 2050) that is still extrapolated
by the national curve (about 86 % of TA solar generation in 2050 is curtailed at the central estimate: 207 of 241 TWh).

## 3. Sub-task 11D-b - time-versus-P confound (the D25 question)

Unit: Northeast, monthly, 57 months; dependent variable C_wind; regressors P_NE, month index t, NE load (TWh/month, demand proxy), SIN hydro generation / SIN load (hydrology proxy), optional
month-of-year dummies. OLS with Newey-West standard errors (6 lags). Numbers from `task11d_time_confound_regressions.csv`.

| | All 57 months | Last 30 months (P and t nearly uncorrelated) |
|---|---|---|
| (i) corr(C, P_NE) Pearson / Spearman | 0.61 / 0.70 | 0.25 / 0.21 |
| (ii) corr(C, t) Pearson / Spearman | **0.85 / 0.90** | 0.65 / 0.66 |
| corr(P_NE, t) | 0.65 (VIF 1.74) | -0.11 |
| (iii) partial corr(C, P_NE given t) Pearson (p) | **0.14 (0.32)** | 0.43 (0.020) |
| partial Spearman (C, P given t) (p) | 0.38 (0.004) | 0.36 (0.053) |
| partial corr(C, t given P) | 0.76 (p < 0.001) | 0.70 (p < 0.001) |
| R2: P only / t only / P + t | 0.373 / 0.728 / 0.733 | 0.064 / 0.421 / 0.528 |
| Incremental R2 of P given t / of t given P | **0.005** / 0.361 | 0.107 / 0.464 |
| (iv) b_P, M0 (P only), p | 0.0066 per pp, p < 0.001 | 0.0040, p = 0.046 |
| b_P, M2 (P + t), p | **0.0010**, p = 0.36 (-85 % vs M0); b_t = 0.0042 per month, p < 0.001 | 0.0052, p < 0.001; b_t = 0.0057 |
| b_P, M3 (+ load + hydrology), p | -0.0006, p = 0.58 | -0.0001, p = 0.97 |
| b_P, M4 (M3 + month-of-year dummies), p | -0.0011, p = 0.54 | 0.0042, p = 0.087 |
| First difference dC ~ dP: b (p) | 0.0018 (0.099) | 0.0038 (0.098) |

Other checks: with year fixed effects (within-year variation only) b_P = 0.0032 per pp, p = 0.002, R2 = 0.77. For comparison the **national** wind frame over the same months: corr(C, P_nat) = 0.71, corr(C, t) = 0.86,
partial corr(C, P_nat given t) = 0.42 (p = 0.0015).

**Reading.** (a) In the Northeast, time alone accounts for 73 % of the variance of the wind curtailment rate; P_NE adds 0.5 percentage points once time is in the model, and its slope shrinks by 85 %. (b) A monotone
association survives in rank terms (partial Spearman 0.38) and, in the sub-sample where P and time are not collinear, partial r = 0.43; but it vanishes when load and hydrology are added (p = 0.97) and weakens with seasonal
dummies (p = 0.09). (c) The significant within-year association (year fixed effects) is most simply read as seasonality: windy months raise both realized wind (hence P) and curtailment; it is not evidence of a
structural P effect. (d) The national P survives time control better (partial 0.42) than the NE P (0.14); a plausible reason is that national P moves with the build-out of solar outside the NE, which the NE series does not see, but this was not tested.
**Quantitative answer to "how much of the regional P effect is just a time trend": about 85 % of the simple P slope in the full sample; in variance terms P adds only 0.5 percentage points of R2 beyond time (10.7 points in the last-30-month sub-sample), against 36-46 points added by time beyond P.** `t` is a catch-all (unobserved transmission outages, rule changes, new capacity connected to weak nodes, load growth) and nothing here is causal; the sample is 57 months in one regime. This is sufficient to register D25 as a candidate.

## 4. Sub-task 11D-c - pooled panel with international data

**Panel (annual, `task11d_pooled_panel.csv`).** 18 system-years, 7 systems, P = 1.7-78 %.
- Brazil: NE, S, SE, N subsystems, full years 2022-2025 (2026 excluded: 9 months, seasonal bias); SE has 2 usable years (no wind before 2024). P = subsystem generation share.
- International (every number from a primary document retrieved in Task 11C): Ireland + Northern Ireland 2024 (P = 35.0 % of demand; wind dispatch-down 14.0 %); South Australia FY2023-24 (wind 7 %; P = 55.9 % wind + large solar, or 74.2 % with rooftop PV) and FY2024-25 (11 %; 54.6 % / 77.0 %); Denmark 2023 (P = 64 % of consumption; rate carried
  as the interval 0-5.2 %, midpoint 2.6 %).
- Excluded for lack of a retrievable P: Ireland 2015-2023 (rates exist, a ten-year series: 5.1, 2.9, 4.0, 6.0, 7.7, 12.1, 7.4, 8.5, 10.7, 14.0 %, but the wind + solar share of demand by year was not found), South Australia FY2022-23 (8 %, solar share not retrieved), CAISO (rate and P not retrieved), Germany/ERCOT (not
  searched). Web searches for a year-by-year Irish/Danish/South-Australian series returned no clean series.
- **Definitions differ** (demand vs generation vs consumption; dispatch-down incl. economic offloading vs operator-imposed COFF restrictions) and the panel is annual, so P and C are only loosely comparable.

**Model.** Fractional logit (GLM, binomial family, logit link): C = 1 / (1 + exp(-(a + b P))), equivalent to a logistic with L fixed at 1, chosen because the 3-parameter form is not identifiable on so few points;
standard errors clustered by system (7 clusters, few).

| Model | Result |
|---|---|
| A: pooled, no fixed effects | b = 0.0193 per pp (p < 0.001); C = 3.6 / 4.7 / 5.6 / 7.2 / 10.2 % at P = 20 / 35 / 44 / 58 / 78 % (95 % CI at 58: 5.3-9.6 %; at 78: 7.5-13.7 %) |
| B: + Brazil intercept | b = 0.0178 (p = 0.001); Brazil intercept -0.47 (p = 0.27, not significant); predicted C at 44/58/78: Brazil 4.8/6.1/8.5 %, international 7.4/9.4/12.8 % |
| C: system fixed effects | **Not credible.** Only 5 systems with >= 2 observations identify the slope; Ireland and Denmark (1 observation each) are absorbed. The slope (0.26 per pp) comes from within-system growth over time (NE intercept -22), i.e. from the same time trend as in 11D-b. Reported as a diagnostic, not as a result. |
| International points only | 4 points, 3 systems, correlation (P, C) = -0.90: no curve can be identified |
| Bounded 3-parameter logistic (production form) | Brazil subsystems only: L = 1, k = 0.32, P0 = 82 (C = 0.0 at 44-58 %, 0.31 at 80 %); pooled Brazil + international: L = 1, k = 0.019, P0 = 192 (C = 5.6 / 7.1 / 10.5 % at 44 / 58 / 80 %) |

**Where does Brazil-NE sit?** Observed NE annual wind rates: 0.5 % (P = 62.5 %, 2022), 3.7 % (71.2 %, 2023), 8.7 % (75.5 %, 2024), 19.4 % (78.0 %, 2025). Comparable international points: South Australia 7 % and 11 % at P = 74-77 % (rooftop-inclusive definition, closest to the NE
share definition), Denmark 0-5 % at 64 %, Ireland 14 % at 35 % (the latter is largely a network-outage and must-run effect in Northern Ireland: 29.6 % there). NE 2022-24 is in line with or below those peers; **NE 2025 is above the pooled
prediction (10.2 %, CI 7.5-13.7 %) and about 1.8x the South Australian 11 %**; the NE is "in line, trending to worse". The Brazilian subsystems at very low P show the opposite pattern of the national-P hypothesis: in 2025 the
North had 9.5 % curtailment at P = 2.1 % and the South 4.7 % at 6.9 %, far above the pooled prediction at that P (3.6 % at P = 20 %), consistent with local network restrictions (Task 11C, c). **Against all of this the national curve's
80-98 % at P = 44-58 % is an order of magnitude outside every system in the panel.**

**Qualifications.** n = 18; only 4 international points from 3 systems; heterogeneous definitions; the NE dominates the high-P end (all Brazilian points above P = 8 % are NE); the pooled slope is partly the NE time trend; the pooled model is a plausibility band, not a
calibrated predictor for Brazil.

## 5. Recommendation: does the regional/pooled approach resolve the Task 11B implausibility?

1. **Wind: largely yes in magnitude, with strong conditions.** The regional curve takes 2050 wind curtailment from 322-568 TWh (87-98 % of wind) to 79-129 TWh (21-22 %), which sits inside the international envelope (Northern Ireland 29.6 %, Ireland all-island 14 %, South Australia 11 %). The residual
   problems: the NE asymptote (0.25) is not identified (L 95 % interval 0.12-1.0; unstable between halves of the sample); P_NE for 2040/2050 relies on the labelled proxy and is itself extrapolated (85-94 % vs 84 % maximum observed); the 2025 fit underestimates observed curtailment; and the P effect itself is mostly time (D25).
   So the regional wind numbers are a defensible *scenario envelope*, not a calibrated forecast, and should carry the wide bound (up to 303 TWh in TA 2050) together with the stress variant.
2. **Solar: no.** No regional natural experiment exists, the national solar curve still gives 70-86 %, and solar is 61-67 % of the 2050 total in the prototype. Until solar has an independent treatment (for example a documented external envelope such as South Australia's 22-32 % grid-scale solar offloading
   used as a labelled assumption, or a new data source), **the 2040/2050 total does not become physically plausible.**
3. **The driver itself.** Given D25 (time explains most of the NE relation) and 11C (c) (curtailment occurs at low local P in the S, SE and N), a formulation in which P is the sole driver is not supported structurally; the regional version only relocates the extrapolation to a regime (P_NE 85-94 %) where the data are
   silent. The pooled panel gives a plausibility band (5-10 % at P = 44-78 %), not a model.
4. **Suggestion (for your decision):** treat the regional wind curve as an *alternative scenario* alongside the national one rather than a replacement; define Task 11E as a prototype in `src` only after a decision on solar; do not unblock Task 13 until D24 and the solar treatment are decided.

## 6. Candidate decisions (all `pending`, none adopted) - text recorded in `config/discovered_sources.yaml`

- **D23** (gross vs net PTE basis): unchanged in substance; added that every number in this task keeps the 11B "gross" formula, so they would all shift if D23 is decided otherwise.
- **D24** (rewritten): "Adopt the regional / pooled formulation as the project's driver of C, replacing or augmenting national P." Options: (A) adopt for wind as the primary, national curve retained as sensitivity; (B) adopt as an alternative scenario only; (C) reject, keep the national P curve with caveats; (D) defer pending solar treatment
  and transmission data. My reading: (B) or (D); (A) is not supported for solar.
- **D25** (new): "In the Northeast sample, the apparent P -> C_wind relation is mostly a time trend; P_NE is not retained as a causal driver without a time/load/hydrology control, and any use of P_NE must carry this caveat." Quantitative basis in section 3.

## 7. Documentation touched by Task 11D (for your review)

| File | Change |
|---|---|
| `docs/task11d_findings.md` | **New.** This report. |
| `docs/roadmap.md` | Added "Update (Task 11D)": the calibration stage branches into regional recalibration, time-confound control, international pooling and a deferred transmission-capacity extension as formal parts of Stages 2-3; Task 13 blocked pending 11D/11E; annotation under the pipeline-stages table and next steps. Prior text untouched. |
| `docs/methodology.md` | Added section "2.3b Update (Task 11D)": why the purely national P -> C formulation was found insufficient (extrapolation), regional/pooled driver concept, time-confound result, preliminary findings labelled as not adopted; one-line annotation under the D21/D22 paragraph and one limitation bullet in 3.7. Prior text kept. |
| `docs/claude_commands.md` | Transition note (why the project pivoted) and the section 1.11D entry inserted before section 1.4; task-table rows updated (11 note, 13 blocked, new 11C/11D/11E rows); a "BLOCKED" annotation line before the Task 13 prompt. Earlier entries not edited. |
| `config/discovered_sources.yaml` | D23 note added; D24 rewritten as the adopt/reject framing of the regional/pooled formulation; D25 added (all `status: pending`). |
| `docs/progress_log.md` | Appended a Task 11D entry (append-only log). |
| `docs/task11c_investigation_report.md` | One pointer line to this report at the stop point (history otherwise intact). |

## 8. Reproducibility and limits of this investigation

- Re-run: `python analysis/task11d_regional_recalibration.py`, then `task11d_time_confound.py`, then `task11d_pooled_panel.py` (they reuse `outputs/tables/task11c_subsystem_monthly.csv`, regenerated by `analysis/task11c_diagnostics.py region` if missing).
- Bootstrap: 1000 resamples, seed 0, i.i.d. over months (ignores autocorrelation, so intervals are optimistic); sampling uncertainty only.
- The international inputs are transcribed from the documents listed in `docs/task11c_investigation_report.md` (b) and in the header of `analysis/task11d_pooled_panel.py`; the Danish rate is an interval derived from a qualitative statement and the 19.4 TWh denominator comes from a secondary source.
- Nothing here is causal, and nothing here has been validated out of sample (`validation_data` in `config/scenarios.yaml` is still empty).
