# CurtailMit - Methodology - v3.1 FINAL

## 2.1. Positioning and modeling strategy

PTE/EPE scenarios do not model dispatch/curtailment; confirmed textually in the Relatorio
Tecnico (p.60-62), where curtailment appears only as a qualitative policy risk. Curtailment is
imposed externally, calibrated on ONS data, applied on top of PTE penetration trajectories.

This is not an hourly dispatch pipeline. Curtailment is an externally calibrated function
applied on top of PTE shares - a modeling choice reinforced, not weakened, by the PTE's own
silence on quantitative curtailment.

## 2.2. Data sources

### PTE/EPE - Table 2 (solar+wind penetration and generation): RESOLVED

The PTE publishes solar+wind share at a discrete set of years, not annually: 2025, 2030,
2040, 2050 for electricity generation composition (relevant for curtailment); 2025, 2030,
2035, 2040, 2045, 2050 for primary energy composition (finer grid, wrong denominator - kept
only as a robustness cross-check, D4).

Table 2 - P(s,t) = solar%+wind% of electricity generation, and implied solar+wind generation
(TWh):

| Scenario | Year | Solar % | Wind % | P(s,t) | Total generation (TWh) | Solar+wind generation (TWh) |
|---|---|---|---|---|---|---|
| TB | 2025 | 12% | 14% | 26% | 836 | 217.4 |
| TB | 2030 | 16% | 13% | 29% | 928 | 269.1 |
| TB | 2040 | 20% | 16% | 36% | 997 | 358.9 |
| TB | 2050 | 17% | 33% | 50% | 1191 | 595.5 |
| TA | 2025 | 12% | 14% | 26% | 834 | 216.8 |
| TA | 2030 | 16% | 13% | 29% | 911 | 264.2 |
| TA | 2040 | 21% | 23% | 44% | 1116 | 491.0 |
| TA | 2050 | 17% | 41% | 58% | 1417 | 821.9 |
| TG | 2025 | 12% | 14% | 26% | 836 | 217.4 |
| TG | 2030 | 15% | 13% | 28% | 929 | 260.1 |
| TG | 2040 | 20% | 19% | 39% | 1126 | 439.1 |
| TG | 2050 | 18% | 29% | 47% | 1274 | 598.8 |

solar_pct/wind_pct/total_generation_twh are stored in config/scenarios.yaml; P(s,t) and the
generation term are computed by data_ingestion.py, never hardcoded.

Closed decisions (D1-D4, see roadmap.md section 2 for full rationale):

- Year grid: {2020, 2025, 2030, 2040, 2050}. 2020 = real historical ONS generation-by-source
  data, tagged source: historical_ons - not a PTE projection (D1, D2).
- Interpolation (2031-39, 2041-49): linear, used only where a continuous curve is required.
  Headline tables report only the 5 anchor points; interpolated years are explicitly labeled
  (D3).
- Primary-energy 6-point grid: robustness cross-check only; never substitutes the
  electricity-generation P(s,t) series (D4).

### ONS curtailment and penetration data - RESOLVED OPERATIONALLY (empirical, Stage 1)

All ONS-side unknowns (exact CKAN dataset names, historical depth, whether the classified
monthly series - Razao Energetica/Confiabilidade/Indisponibilidade Externa - is exportable vs.
dashboard-only, and the DEB/REB/EUB mapping) are resolved empirically by Stage 1 at run time.
Requirements, enforced by explicit failure rather than silent assumption:
(a) historical depth covers at least Jan/2022-present;
(b) the classification field is present in the returned series;
(c) mapping to DEB/REB/EUB (D5) is programmatically confirmed, or the pipeline falls back to
    the unclassified aggregate with classification_available: false (D6).
Requirement (a) is applied per package (D14): wind from 2022-01, solar from its own published
start (2024-04).

Curtailed energy (wind and solar) is taken from ONS's own ascertained figure,
`val_geracaonaorealizadaapurada` (MW, integrated over the sampling interval to MWh), not derived
by subtracting realized from reference generation, because the reference column
(`val_geracaoreferenciafinal`) is sparsely populated (D13; verified equivalent on the 3,746
populated rows of the 2022-01 wind sample).

Generation by source (P(t) history and the D1 2020 baseline) comes from ONS `balanco-energia-subsistema`
(`id_subsistema == "SIN"`, hourly average power in MW, integrated to MWh over the inferred 1 h interval;
`ons_generation.py`). Only years from 2016 are used: earlier resources have unusable gaps (wind blank 2000-2005
and partly 2006; 24 h missing in 2015). Blank `val_gersolar` (partial in 2016) is treated as 0, as documented; a
blank in any other source fails explicitly. The 2020 baseline requires every hour of 2020 to be present.
Observed 2020 values (retrieved 2026-10-21): total 554.35 TWh, wind 54.30 TWh, solar 5.23 TWh, i.e. 10.74 %
wind+solar penetration. This ONS SIN total is on a narrower footing than the PTE `total_generation_twh` figures in
config/scenarios.yaml (e.g. 836 TWh for 2025); this is intentional and left unreconciled (D16, see 2.4).

Classification (D5/D6, D17): the COFF series carries `cod_razaorestricao`, which the ONS data dictionary defines
as ENE (razao energetica), CNF (confiabilidade), REL (indisponibilidade externa) and PAR (parecer de acesso). The
code-to-label crosswalk is derived at run time from that dictionary and mapped by D5 to DEB / REB / EUB (EUB kept
separate). Over 2022-01..2026-10 the split of curtailed wind+solar energy was DEB 47.75 TWh, REB 27.81 TWh and EUB
10.35 TWh, with 0.0027 % of energy lacking a code. PAR is documented but unmapped and never forced into a category;
if the dictionary or code field were missing the pipeline would fall back to the unclassified aggregate with
`classification_available: false` (D6).

### Emission factor data - RESOLVED, same empirical discovery pattern (new in v3.1)

Implementation note (Task 5, D18): factors are scraped from the MCTI landing page and read from the workbooks by their labels. Years 2020-2025 are required; the average factor is the MCTI-published annual (and monthly) value, BM is MCTI-published, annual OM is the simple mean of the 12 published monthly values (derived) and CM = 0.5 OM + 0.5 BM (computed, D12). Factors exist only for completed years, so how they are applied to later projection years is a Task 13 choice.

- Average SIN factor (D8): MCTI's official monthly Fator Medio de Emissao de CO2 do SIN
  (gov.br/mcti). Stage 1 discovers the current publication format/endpoint, verifies coverage
  against the calibration window, fails explicitly if not met.
- Marginal factor, DEB/REB (D9): MCTI annual Operating Margin / Build Margin / Combined Margin
  (ACM0002-aligned methodology) used as DEB/REB proxies respectively. Explicit proxy, stated
  plainly in Results/Limitations, never presented as a precise marginal calculation.

## 2.3. Step 1 - Curtailment projection function

Three-layer structure: historical calibration (ONS, 2021-present) -> short-term validation
(ONS/EPE prospection 2026-2029, validation_data, never mixed with calibration_data) ->
extrapolation (PTE scenarios, 2020/2025/2030/2040/2050 per Table 2, interpolated only where a
continuous curve is needed).

**Solar basis in the calibration window (D20).** The ONS balance series `val_gersolar` includes an estimated non-dispatched
(MMGD-like) component from 2023-04-29 (measured in Task 6C: a step of about +2.5 to +3 GWmed on that day, absent from dispatched
solar; 2024 gap 45,789 GWh vs ONS's own MMGD estimate of 45,752 GWh). MMGD is never subject to COFF curtailment, so for the
calibration window (2021 onward) "solar generation" is the ONS-dispatched (centralized) series summed from the per-plant
capacity-factor dataset, used consistently in (a) the solar term of P(t) (numerator and the solar part of the total-generation
denominator) and (b) the potential-generation denominator (realized + curtailed) of the solar curtailment rate. Consequences:
(i) wind is unaffected (no step) and keeps `val_gereolica`; (ii) the 2020 baseline (554.35 TWh total, 54.30 wind, 5.23 solar,
10.74 %) is unaffected and was left untouched; (iii) raw `val_gersolar` is kept only as the diagnostic column
`solar_gen_ons_balance_raw_mwh`; (iv) projection years (PTE/BLUES, D16) are not rescaled. Limitation: a smaller gap (89-197 MWmed,
5-13 % of `val_gersolar`) already exists from 2021-03 to 2023-03, consistent with an earlier staged inclusion of non-dispatched
plants; it is documented and not material because ONS curtailment data (wind from 2022-01, solar from 2024-04) leaves this window
with no curtailment to be mis-scaled in the solar term, and the dispatched series is used there too.

**Two technology-specific curves (D22).** The curtailment function is split into C_wind(P) and C_solar(P). Both are logistic functions of the same
combined penetration P = solar_pct + wind_pct; they differ in the dependent variable (the technology's own curtailment rate, curtailed / (generation
+ curtailed), solar on the D20 dispatched basis) and in the fitting window (wind: all 57 complete months from 2022-01; solar: the 30 months with published
solar curtailment, 2024-04 onward). A single combined curve would mix a wind-only rate (27 months) with a wind+solar rate (30 months). For a scenario/year,
curtailed wind = wind_gen x C_wind(P) and curtailed solar = solar_gen x C_solar(P), summed. The earlier combined curve is kept only as a non-primary diagnostic.

**Bounds and uncertainty (D21).** Each upper asymptote is bounded to 0 < L <= 1 in `fit_calibration` (a curtailment fraction cannot exceed 100 %).
The calibration range is P = 10.3-29.4 %; PTE 2040/2050 lie outside it for both curves, so C(P) there is an extrapolation. A percentile bootstrap of each fit
(`bootstrap_calibration_ci`) quantifies its sampling uncertainty (not the functional-form uncertainty), and Stage 3 must carry both intervals into the reported
mitigation-deficit figures.

> Note (Task 11D): the national-P formulation described in this section (D20-D22) is the original approach. It was later found insufficient for extrapolation to the PTE 2040/2050
> penetration levels; see section 2.3b below. This section is kept unchanged as the record of the approach.

## 2.3b. Update (Task 11D) - regional and pooled driver concept (preliminary findings, not adopted decisions)

**Why a purely national curve was found insufficient.** The curves of section 2.3 are calibrated on 57 complete months (2022-01 to 2026-09) in which national wind + solar penetration
ranges over 10.3-29.4 %. The PTE scenarios place 2040 and 2050 at 36-44 % and 47-58 %, outside that range for both technologies, so the projected curtailment depends entirely on the
functional form beyond the data. A bounded logistic (D21) with its midpoint just above the observed range gives C_wind of 0.87-0.98 and C_solar of 0.70-0.86 at those levels, i.e. 70-98 % of
the technology's potential generation curtailed (512-775 TWh in 2050). Three independent checks (Task 11C) show that this is not credible as a prediction, whatever its in-sample fit: (i) the highest
annual curtailment or dispatch-down rates found for any system with a comparable or higher wind + solar share (Ireland and Northern Ireland, South Australia, Denmark) are 11-30 % for wind and about 32 % for grid-scale
solar; (ii) the Brazilian Northeast subsystem already operates at a local wind + solar generation share of 49-84 % - the range the whole country is only projected to reach in 2040-2050 - with annual
wind curtailment of 0.5-19 %; (iii) curtailment in Brazil occurs at very low local penetration in other subsystems (South, Southeast, North), so national penetration is not what locates it. The common thread
is that the national aggregate P mixes regions with very different constraints, and that its relation with curtailment, observed over a short and fast-changing period, is entangled with time.

**Regional driver.** The same operational definition of P (wind + dispatched solar over total generation, realized basis) is applied at the subsystem level. A logistic C_wind(P_NE) fitted on the
Northeast alone covers P_NE = 49-84 % within the sample and yields L = 0.25, k = 0.16, P0 = 76 (national: L = 1, k = 0.17, P0 = 36). Applied to the PTE scenarios through a labelled proxy (the PTE sources give no regional
generation; the Northeast shares of national wind, solar and residual generation are held at their 2025 values) it gives 2050 wind curtailment of 79-129 TWh (21-22 % of wind) instead of 322-568 TWh. Preliminary
caveats: the asymptote is weakly identified (bootstrap 95 % interval of L: 0.12-1.0; unstable between sub-samples), the proxy places P_NE at 85-94 % in 2040/2050 (beyond the observed maximum of 83.6 %), solar has no regional
high-penetration sample (30 months) and stays on the national curve, so the total remains dominated by an extrapolated solar term.

**Time confound.** In the Northeast, time alone explains 73 % of the variance of the monthly wind curtailment rate; adding P_NE raises R2 by only 0.5 percentage points (partial correlation 0.14, p = 0.32 after controlling
for a linear time trend), and a last-30-month association (partial r = 0.43) vanishes when load and a hydrology proxy are added. The relation between penetration and curtailment is therefore not established as causal within the
sample; unobserved time-varying factors (network outages and reinforcements, dispatch rules, load, hydrology, connection of new capacity to weak nodes) are absorbed by the time trend.

**Pooled international panel.** A pooled annual fractional-logit over 18 system-years (Brazilian subsystems plus Ireland + Northern Ireland, South Australia and Denmark) gives a plausibility band of about 5.6-10.2 % wind curtailment at
P = 44-78 % (95 % interval up to 13.7 %). The Northeast is in line with or below its peers in 2022-24 and above them in 2025. The panel is thin (four international points from three systems; definitions of P and of curtailment differ), so it is
reported as a band for plausibility and not as a calibrated model.

**Consequence for the method (proposed, pending the user's decision on D24/D25).** The paper's contribution is positioned as methodological: curtailment at high penetration is characterized from real within-sample regional and
international experience, with explicit identification limits, rather than extrapolating a national curve. A mechanism-aware formulation (separating the systemic energy-balance component from the network components) and transmission-expansion
assumptions are the natural extension, but are deferred and need new data. Full evidence: `docs/task11d_findings.md`.

## 2.3c. Update (Task 11E) - hourly driver, envelope for the asymptote, transmission capacity (preliminary findings, not adopted decisions)

**Where the signal was hidden.** Section 2.3b showed that national or regional penetration, aggregated by month, is confounded with time. The same hourly data used by ONS give a different picture. Define r as the hourly
system-wide potential variable-renewable share of load, r = (wind + dispatched solar + curtailed wind + curtailed solar) / load, summed over the four subsystems (the potential basis keeps the regressor from falling when curtailment
rises). The curtailment rate of wind and of solar is a steep, monotone function of r: wind curtailment is 0.5 % of potential for r < 15 %, 16 % for r = 30-35 %, 43 % for 40-45 % and 76 % above 60 %; solar curtailment concentrates in the midday hours
(60 % of curtailed solar energy falls between 10:00 and 15:00). From 2023 (wind) and 2025 (solar) onward this hourly relation is stable across years, so a large part of the monthly "time trend" is the upward shift of the hourly distribution of r.
A fixed hourly curve reproduces the national monthly wind rate with R2 = 0.76 without using time (time alone: 0.73) and the monthly solar rate with R2 = 0.78 for the midday metric (national P: 0.40). A residual under-prediction of 2-3 percentage points in
2025-26 remains and is not attributed.

**The asymptote as an envelope.** In the regional wind curve the upper asymptote L is not identified (fixing L at 0.25, 0.5 or 1.0 leaves the fit error unchanged), so the 2040/2050 wind projection is reported as an envelope over L rather than as a point estimate;
an energy-balance floor (NE potential VRE minus NE load minus export capacity) acts as a capacity-grounded lower bound only where it binds (TA 2050). The hourly curve moves the unidentified part from a monthly asymptote (0.25 to 1.0) to the tail of the
hourly distribution (r above the observed maximum of 76 %), where the curve is bounded by L between 0.73 and 1.

**Transmission capacity is not the structural driver in the open data.** Stocks of NE transmission capacity reconstructed from the ONS registries (boundary line rating, km of lines, transformer MVA) are collinear with time (r = 0.92-0.99) and do not explain
the wind curtailment rate better than time; their ratio to potential VRE is a better regressor than P_NE net of time but does not replace it. In the hourly data NE net export is within 5 % of its trailing 12-month maximum in only 0.4-3 % of hours and in 1-8 % of
the curtailed energy; 49 % of NE wind curtailment carries the ONS energy reason (ENE). The binding constraint is therefore the system-wide energy balance, not saturation of the NE export corridor (with the caveat that the true dynamic limit may be below the maximum observed).

**Consequence (proposed, pending the user's decisions).** A defensible 2030-2040 estimate can use a stationary hourly dose-response curve applied to the scenario-scaled hourly profile; for 2050 the mean hourly VRE share of load implied by the PTE (53-70 %) is
outside the Brazilian experience and the result depends on flexibility (storage, interconnection, demand response) that is not calibrated by any Brazilian data, so it is reported as a flexibility-conditional range. Full evidence and the numbers for each decision
option: `docs/task11e_findings.md`; data provenance: `docs/ons_transmission_data_sources.md`.

## 2.3d. Update (Task 11E2) - validation of the hourly driver, wind extension, transmission mechanism (preliminary findings, not adopted decisions)

Details and numbers: `docs/task11e2_findings.md` (cross-linked; sections 2.3b and 2.3c above are not edited).

- **Coverage of the driver.** r is the hourly SIN potential VRE share of load. The PTE-scaled 2025 hourly profile falls inside the observed populated support (r <= 63 percent, 15 or more hours per 2-pp bin; maximum observed 75.8) for 99.6 percent of 2030 hours, 86-96 percent of 2040 hours and 43-70 percent of 2050 hours; the share of projected curtailment produced by hours beyond the support is 2-3 / 13-30 / 51-77 percent (wind, 2030 / 2040 / 2050).
- **Validation.** Annual backtest and leave-one-year-out against two refitted benchmarks (national-P logistic, linear time trend); stability of (k, x0) across years, seasons, hours of day and subsystems with the asymptote pinned (effect size, not p-values, because hourly samples reject every equality test); month-resampling bootstrap; partial correlation with monthly C given time (national P 0.42, P_NE 0.14, hourly model 0.70). Unexplained residual: wind drifts about +2 pp per year.
- **Wind and unified driver.** The same logistic family fits wind (L 0.73, x0 41) and solar (L 0.74, x0 42); a single curve for total VRE curtailment reproduces the two-curve totals within 2 percent, while the technology split for the OM / CM step stays technology-specific.
- **Transmission mechanism.** ONS reason classes (D5: ENE -> DEB, CNF -> REB, REL -> EUB), origin (SIS / LOC) and a keyword classification of the constraint description show that NE wind curtailment is increasingly an energy-balance phenomenon (DEB 8 percent in 2022, 61 percent in 2026); explicit interchange-related constraints are a minority; network-element limits (NE-internal, SE-side, flow controls) total 38 percent of 2026. The saturation test of Task 11E understates export limitation because dynamic limits sit below the demonstrated maximum.
- **Gross vs net (D23).** Under the hourly driver only the gross reading is operational; the net inversion overstates observed 2025 curtailment three-fold.

## 2.3e. Update (Task 11E3) - error growth with extrapolation distance (preliminary findings, not adopted decisions)

Details and numbers: `docs/task11e3_findings.md` (cross-linked; sections 2.3b-2.3d are not edited).

- **Method.** Hourly dose-response curves refitted on many training windows (expanding, rolling 12 / 18 / 24 months, and windows truncated to low-penetration months), tested on calendar-quarter blocks; extrapolation distance = share of the predicted curtailment from hours with r above the training support (E_out) and mean excess of r beyond it (D_pp); error = ln(predicted / observed).
- **Finding.** The error does not grow with distance in a way that supports calibration (R2 0.03-0.07); it is mostly a level bias and a drift that grows with the lead time between training and test (wind). The 2050 conditions (E_out 0.51-0.78, D_pp 14-29 pp) are beyond what any historical split tested on the "how far" metric (8-11 pp). A credibility rule fixed before the results (significant relation; distance within 1.25 x the historical range on both metrics; at least 25 test blocks over 3 years) fails for wind, solar and the unified driver, so no calibrated 2050 band is produced.
- **Reporting rule that follows.** 2030 / 2040: option E central with the empirical annual-backtest error band (descriptive, mostly one-sided: truth more likely above the central value). 2050: flexibility-conditional range with the in-support / beyond-support decomposition, no probability attached.

## 2.3f. Update (Task 11E4) - coverage figure, NE-hourly driver, sub-hourly check, conformal prediction (preliminary findings, not adopted decisions)

Details and numbers: `docs/task11e4_findings.md` (cross-linked; sections 2.3b-2.3e are not edited).

- **Coverage as a method diagnostic.** The share of projected hours (and of projected curtailed energy) inside the range supported by at least 15 observed hours per 2-pp class of r is reported for every horizon and scenario in one figure; it is part of the method, not a limitation disclosure.
- **NE-hourly driver.** r_NE = NE wind + solar potential over NE load (routinely above 100 percent because NE exports) was refitted and validated like the SIN-wide driver; it gives no validation gain and, under the PTE constant-share proxy, a smaller in-sample share in 2040-2050.
- **Sub-hourly resolution.** The 30-minute r of 2025 (COFF generation and curtailment plus verified load by area) has the same extremes as its hourly aggregation (ratio 1.006) and explains no more curtailment; hourly resolution does not hide extreme system-level conditions.
- **Conformal prediction.** Weighted split conformal on the signed log error of forecast-type splits (quarter blocks; each quarter weight 1) gives finite 80 percent intervals for 2030-2040 (90 percent only for wind), with right empirical coverage, but its exchangeability is violated by the multi-year horizon and, at 2050, by the extrapolation distance; a correctly applied 2050 procedure returns no finite interval. The result is reported rather than suppressed.

## 2.3g. Update (Task 11F0) - adopted decisions D23, D24, D26

The modelling choices below are now ADOPTED (`config/discovered_sources.yaml`); the preliminary sections 2.3b-2.3f above are kept as the record of how they were reached and are not edited. Evidence: `docs/task11d_findings.md` to `docs/task11e4_findings.md`.

- **Basis of the PTE generation (D23):** gross, pre-curtailment potential; curtailed energy = PTE generation x curtailment rate. Adopted as a working assumption by user decision; the PTE / CEBRI documentation does not settle it and the cross-checks against ONS are weak and mixed. The net-basis sensitivity remains documented (not usable with national curves; under the hourly driver its inversion overstates observed 2025 curtailment about three-fold) and is not blocking. State it as an assumption in the paper.
- **Curtailment driver (D24):** the hourly dose-response model (rate of each technology as a logistic function of the hourly system-wide potential VRE share of load; 2025 hourly shape scaled to the PTE annual totals) replaces the national-P curves of D21 / D22 for projections (those curves remain a documented reference). Reporting by horizon: 2025-2030 central value with the empirical annual-backtest band and the conformal 80 percent interval as supplement; 2040 the same, TA flagged as partly beyond the observed support; 2050 central value with the in-support / out-of-support decomposition, the flexibility-conditional range (phi 1.5 to L = 1), the coverage figure and the statement that no valid conformal interval exists; no probability or "calibrated" label for 2050.
- **Transmission (D26):** no transmission-expansion refinement is part of the method (extension retired); network-element limits (38 percent of NE wind curtailment in 2026, 23 percent NE-internal) are acknowledged in the limitations and enter only through the flexibility sensitivity.
- Open: D25 (time confound; Task 11E5). Production implementation (Task 11F) is not started.

## 2.3h. Update (Task 11E5) - residual drift of the hourly wind model (preliminary findings, not an adopted decision)

Details and numbers: `docs/task11e5_findings.md` (cross-linked; sections 2.3b-2.3g are not edited).

- **Quantification.** The monthly residual of the pooled hourly wind curve (observed minus predicted rate) trends upward by 1.4-1.6 pp per year (Newey-West and block-bootstrap 95 percent intervals 0.4-2.9); a single step of about +4.6 pp at 2025-01 fits better than a straight line (BIC), a saturating curve does not; the shift is concentrated at r between 20 and 40 percent (the curve flattens: k from 0.168 to 0.118) and is absent on the plateau.
- **Explanations.** Rejected: fleet vintage and state composition (shift-share: composition effect negative, within-group change +5.5 to +8.9 pp; old plants drift as much as new ones; RN and BA carry it). Supported circumstantially: an operating-regime change in 2025 raising energy-balance and external-unavailability curtailment at a given r. Untestable with the data in hand: documented ONS / ANEEL rule changes, turbine technology, local grid events.
- **Bounded compounding.** The asymptote of the curve caps the drift: in 2050 the central wind rate has only 7-17 pp of headroom, so the additional wind curtailment is +1-4 percent (step), +15-20 TWh (saturating), at most +34-52 TWh (linear, capped), always upward.
- **Extended model.** Linear, saturating, step and slope-change trend terms keep the hourly driver intact (partial correlation 0.69-0.70) but inflate the parameter uncertainty (1.6-8.5 times), validate inconsistently out of sample and cannot be extrapolated (2050 wind -33 percent to +31 percent across variants); not adopted in the specification of D24.

## 2.3i. Update (Task 11F-0) - decisions D23-D26 all adopted

D25 (residual wind drift accepted as a documented, quantified limitation, not corrected in the model; section 2.3h and `docs/task11e5_findings.md`) was adopted on 2026-10-26. D23 (gross basis), D24 (option E by horizon) and D26 (transmission extension retired) were adopted in Task 11F0. The consolidated description of the adopted production model will be written in Task 11F-4.

## 2.4. Step 2 - Applying the function to PTE scenarios

For each scenario s in {TB, TA, TG} and year t in {2020, 2025, 2030, 2040, 2050}
(2020 = ONS historical actual, tagged accordingly - D1):

- P(s,t) - from Table 2, or linearly interpolated (D3) if needed.
- C_hat(s,t) = C(P(s,t)) - from the calibrated logistic function (2.3), produced by Stage 2.
- E_curt(s,t) = Solar+wind generation(s,t) [Table 2] x C_hat(s,t).

**Denominator basis of P (D16).** P differs in accounting scope between the two domains: in the
historical/calibration domain (2020, 2021+) it is wind+solar over ONS SIN-reported total generation
(`source: historical_ons`); in the projection domain (2025-2050) it is the PTE/BLUES model's own
published shares and total generation (`source: pte_projection`), likely inclusive of MMGD,
self-production and isolated systems according to the BEN 2021 cross-check. This is a deliberate
methodological choice, not an inconsistency: the PTE scenarios are the object being evaluated, not a
dataset to be reconciled with ONS accounting, so no rescaling is performed. The calibrated function
C_hat(P), fit on real ONS SIN data, is applied to the PTE's own-scope P(s,t) under the assumption that
curtailment risk scales with wind+solar penetration share regardless of the exact accounting scope of
total generation. This is an assumption, not a proven equivalence.

## 2.5. Step 3 - Mitigation deficit (Stage 4)

Mitigation_deficit(s,t) = E_curt(s,t) x EF(t), computed twice per scenario/year: once with the
average SIN emission factor (D8) and once with the marginal DEB/REB proxy factor (D9) -
reported side by side as a sensitivity band, never collapsed into a single number without
labeling which factor was used.

## 2.6. Step 4 - Green hydrogen valorization potential (Stage 5)

H2_potential(s,t) = E_curt(s,t) / SEC, with SEC in [50, 55] kWh/kg H2 (D7), central estimate
52.5 kWh/kg H2. Reported as a range, not a single point.

## 2.7. Step 5 - Robustness cross-check (primary energy grid)

Using the 6-point primary-energy PTE grid (2025/2030/2035/2040/2045/2050) solely to check that
the electricity-generation-based P(s,t) trend (Table 2) is not an artifact of the coarser
4-point grid. Reported separately, never substitutes Table 2 (D4).

## 2.8. Step 6 - PLD (optional, non-blocking)

Optional secondary analysis using CCEE published PLD to translate curtailed/mitigated energy
into a financial proxy. Explicitly excluded from the core modules; absence does not block any
other stage (D10).

## 3. Results

### 3.7 Limitations (final)

- P(s,t) is observed at 5 anchor points per scenario (2020 historical + 2025/2030/2040/2050
  PTE-published); intermediate years shown in continuous curves are linearly interpolated.
- The 2020 baseline mixes one observed/historical point with three scenario-projected points
  from 2025 onward - stated explicitly per D1.
- ONS-side unknowns are resolved empirically by the pipeline at run time and logged. If the
  pipeline falls back to an unclassified aggregate curtailment series, this is stated as a
  limitation, never silently absorbed into the DEB/REB split.
- The marginal emission factor (DEB/REB) uses MCTI's OM/BM/CM margin methodology as a proxy,
  not a bespoke grid-dispatch marginal estimate - a methodological limitation, stated
  explicitly.
- Utility-scale solar curtailment in Brazil's SIN is not published by ONS before 2024-04 (earliest
  observed record 2024-04-01; wind is available from 2021-10), and no ANEEL dataset provides an
  alternative series (D14). ANEEL's SIGA registry shows ~3.3 GW of centralized utility-scale PV in
  operation at end-2020 versus ~17.2 GW at end-2024 (~19% of the later level), which is consistent
  with, but does NOT prove, negligible solar curtailment in 2020. The 2020 baseline's solar
  curtailment is therefore a documented zero, not a measured value; this is reported explicitly in
  the data-quality report (`solar_curtailment_2020_baseline`) and is never silently assumed.
- Residual gap to ONS-published curtailment rates (permanent limitation, Task 9). After D20 our scope-consistent annual rates (0.49 / 3.45 / 9.03 / 20.16 %
  for 2022-2025) stay 0.01 / 0.15 / 0.27 / 0.54 percentage points below ONS's published 0.5 / 3.6 / 9.3 / ~20.7 % (about 3-4 % relative for 2023-2025). The
  numerators match ONS (absolute MWmed within ~1 %), so the residual is in the potential-generation denominator, whose exact ONS definition (plant set,
  interval) was not reconstructed. The 2025 reference (~20.7 %) is a secondary-source citation (Ensaio Energetico, attributed to IEA/ONS), not an ONS primary
  publication, so the 2025 residual cannot be fully attributed. The rates are therefore reported as "close to, not equal to" ONS's.
- Solar basis and MMGD (D20). The calibration uses ONS-dispatched (centralized) solar, not `val_gersolar`, because the latter includes an
  estimated MMGD component from 2023-04-29. This is a project-level methodological choice backed by measurement (Task 6C), not an
  ONS-confirmed statement for that field. A smaller non-zero gap (89-197 MWmed) exists from 2021-03 to 2023-03; it is documented
  as a non-blocking limitation (the dispatched series is used throughout, and the curtailment series that calibrate C(P) begin
  in 2022 for wind and 2024-04 for solar). The 2020 baseline and wind are unaffected.
- Two-curve structure (D22, supersedes the single combined curve of D21). C_wind(P) and C_solar(P) are fitted separately on the shared P; the wind-only months are no
  longer blended into a combined series, so the earlier left-censoring concern for them does not arise. Remaining limitations: both curves end at the same observed
  maximum P (29.4 %) with P0 beyond it, so every PTE point above 29.4 % is an extrapolation for both; the solar curve rests on 30 monthly points from a short,
  fast-growing period (2024-04..2026-09); bootstrap intervals cover sampling uncertainty only.
- Generation-basis difference between calibration and projection (D16). Calibration and the 2020 baseline use
  ONS SIN-reported generation (2020: 554.35 TWh), while PTE projection years use the PTE/BLUES model's own
  total generation (e.g. 836 TWh in 2025). BEN 2021 reports a national total of ~621.2 TWh for 2020, of which
  ONS SIN is ~89 %; the remainder is plausibly MMGD, self-production and isolated systems outside the SIN
  balance. This supports, but does not prove, that the PTE total is on a broader national-style basis, and
  about 5 % of the 2025 gap stays unexplained even after that adjustment. The PTE report does not define its
  total. No reconciliation is applied by design (the PTE is the evaluated object); applying C_hat(P) across
  the two bases assumes penetration share governs curtailment risk irrespective of accounting scope.
  Full detail: docs/pte_ons_basis_investigation.md.
- Regional / pooled evidence (Task 11D, preliminary, not adopted): the Northeast wind curve is weakly identified (L 95 % interval 0.12-1.0), P_NE for the PTE years rests on a constant-share proxy and exceeds the observed range,
  the P effect in the Northeast is mostly a time trend (section 2.3b), and the international panel has four points from three systems with non-identical definitions. See `docs/task11d_findings.md`.
- The financial estimate (2.8, optional) excludes externality costs.
- Electrolyzer SEC is a literature-range assumption (50-55 kWh/kg H2), not a measured value.


---

## Addendum: Combined Margin (CM) computation (D12)

Per decision D12, the Combined Margin used as the REB proxy (D9) is
computed as:

    CM(y) = 0.5 * OM(y) + 0.5 * BM(y)

where:
- `OM(y)` is the annual Operating Margin (dispatch-analysis method) for
  year `y`, derived as the simple arithmetic mean of the 12 officially
  published monthly OM values for that year (MCTI publishes OM only at
  monthly granularity; no official annual OM figure exists).
- `BM(y)` is the annual Build Margin for year `y`, published directly by
  MCTI as a single annual value.
- The 0.5/0.5 weighting follows the UNFCCC CDM default convention for
  low-carbon, intermittent generation sources (consistent with ACM0002),
  adopted here in the absence of an MCTI-published CM figure.

Both the OM annual derivation and the CM computation itself must be
flagged as **derived/computed quantities** in all output metadata
(`DataQualityReport`, results tables) — never presented as directly
MCTI-published values. This mirrors the existing `classification_available`
flag pattern (D6): a boolean-style provenance flag that propagates
through all pipeline stages to `results_writer.py`.
