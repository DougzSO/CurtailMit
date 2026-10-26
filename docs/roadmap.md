# CurtailMit - Master Roadmap: Curtailment x CO2 Mitigation Pipeline (PTE/EPE Scenarios) - v3.1 FINAL

## 0. Project identity
- Package name: curtailmit
- Working title: "CurtailMit: Quantifying the Curtailment-Driven Mitigation Deficit under
  Brazil's PTE/EPE Energy Transition Scenarios"
- Target venue: DeCarbon
- Code repository (public, GitHub): curtailmit
- Local data repository (not published, sibling directory): curtailmit_database
- Geographic scope: v1 = national (SIN), no regional/subsystem breakdown (OQ-1, closed).

## 1. Objective

Given (a) the solar+wind penetration trajectories of the 3 PTE/EPE scenarios and (b) the ONS
historical curtailment series, compute the "mitigation deficit" per scenario/year, with
sensitivity analysis (average vs. marginal emission factor) and green-H2 valorization
potential.

This is not an hourly dispatch pipeline. Curtailment is an externally calibrated function
applied on top of PTE shares. Confirmed in both official PDFs: PTE does not quantitatively
model curtailment - it appears only as a qualitative policy risk (Relatorio Tecnico, p.60-62).
This reinforces, rather than weakens, the paper's methodological position.

## 2. Decisions closed since v3 (changelog)

| # | Topic | Decision taken |
|---|---|---|
| D1 | 2020 baseline | Use real historical ONS generation-by-source data as the 2020 anchor point. 2020 is explicitly labeled historical/observed, never conflated with a PTE projection. |
| D2 | Year grid | Official scenario grid becomes {2020(historical anchor), 2025, 2030, 2040, 2050}. |
| D3 | Interpolation (2031-39, 2041-49) | Linear interpolation adopted as default for continuous-curve figures. Headline tables report only the 5 anchor points; any interpolated year is explicitly labeled "interpolated, not PTE-published". |
| D4 | Primary-energy 6-point grid (+2035, +2045) | Kept strictly as a robustness cross-check. Never substitutes the electricity-generation P(s,t) series. |
| D5 | ONS classification mapping default | Razao Energetica ~ DEB; Confiabilidade ~ REB; Indisponibilidade Externa = own category, labeled EUB. Adjustable in config/scenarios.yaml. |
| D6 | Classification fallback | If the classified series is not exportable via API, Stage 1 falls back to the unclassified aggregate and sets classification_available: false, propagated to results_writer.py as a declared limitation. |
| D7 | Electrolyzer SEC | Sensitivity band 50-55 kWh/kg H2; central point estimate = 52.5 kWh/kg H2, explicitly a mid-point assumption. |
| D8 | Average SIN emission factor (OQ-3, part 1) | Source = MCTI's official monthly Fator Medio de Emissao de CO2 do SIN. Resolved as a Stage-1 discovery task. |
| D9 | Marginal emission factor (OQ-3, part 2) | Source = MCTI annual Operating Margin (OM) / Build Margin (BM) / Combined Margin (CM), used as DEB/REB marginal proxies. Documented explicitly as a proxy, not a bespoke dispatch estimate. |
| D10 | PLD (OQ-4) | Kept optional. Implemented as a secondary module (CCEE PLD). Does not block the core pipeline. |
| D11 | OQ-1 | Maintained: v1 is national scope only. |

## 3. Input data - final status

1. PTE/EPE structured table - resolved, hardwired in config/scenarios.yaml (pte_scenarios).
   P(s,t) = solar_pct + wind_pct; solar_wind_generation_twh = P(s,t)/100 x total_generation_twh,
   computed by data_ingestion.py, never hardcoded.
2. ONS curtailment, historical + classification - resolved operationally; verification is a
   Stage-1 discovery/validation task (see section 6).
3. Average SIN emission factor - resolved operationally (D8); Stage-1 discovery task.
4. Marginal emission factor (DEB/REB) - resolved operationally (D9); Stage-1 discovery task;
   results must state the proxy nature explicitly.
5. PLD - optional, non-blocking (D10).
6. Electrolyzer SEC - resolved (D7): 50-55 kWh/kg range, 52.5 central estimate.
7. Official ONS/EPE 2026-2029 short-term prospection - loaded as validation_data, kept
   strictly separate from calibration_data in every stage.
8. Monthly generation-by-source history, P(t) for calibration - resolved operationally,
   same CKAN-discovery pattern as item 2.

## 4. Repository layout

Two repositories, never merged:

curtailmit/              # public, GitHub - code, config, docs, tests, small tracked figures
curtailmit_database/     # local only - raw/interim/processed data, logs, large outputs

## 5. Pipeline stages

| Stage | Module | Responsibility |
|---|---|---|
| 1 | data_ingestion.py | Load config, discover/validate ONS + MCTI sources, build data-quality report |
| 2 | calibration.py | Fit curtailment function C(P) on historical ONS data |
| 3 | projection.py | Apply C(P) to PTE scenario P(s,t), interpolate where needed |
| 4 | mitigation.py | Compute mitigation deficit per scenario/year, average vs marginal sensitivity |
| 5 | hydrogen.py | Green-H2 valorization potential from curtailed energy |
| 6 | results_writer.py | Persist tables/figures/reports, propagate all data-quality flags |

> Note (Task 11D): Stages 2-3 are no longer a single national-P calibration followed by a projection. They now include a regional / time-controlled / pooled branch
> (see "Update (Task 11D)" at the end of this file). Stage 6 / Task 13 is blocked until that branch is decided.

## 6. Stage 1 (data_ingestion.py) - final spec

1. Load config/scenarios.yaml, validate against schemas.py (Pydantic v2):
   solar_pct + wind_pct <= 100 for every (s,t).
2. ONS discovery via CKAN: list all resources for wind and solar curtailment packages,
   determine real temporal coverage; fail explicitly if coverage does not reach Jan/2022.
   Check whether the classified series is exportable via CKAN resource, not just the
   dashboard; inspect schema, do not assume. Apply mapping D5 if available, else fallback D6.
   Use package_search (q=geracao) to confirm the correct generation-by-source dataset before
   fixing any URL in code.
3. MCTI discovery: locate the official monthly average SIN emission factor publication and the
   annual OM/BM/CM margin publication; log source, URL/resource used, coverage dates; fail
   explicitly if coverage window is insufficient.
4. Load 2026-2029 official prospection as validation_data, kept separate from
   calibration_data through all later stages.
5. Produce a data-quality report before any computation.

## 7. Acceptance criteria

- P(s,t) = solar_pct(s,t) + wind_pct(s,t) <= 100 for every s,t in the PTE table.
- If Stage 1 falls back to the unclassified aggregate series, data/processed/ carries an
  explicit classification_available: false flag, propagated by every subsequent stage.
- If Stage 1 cannot confirm MCTI average/margin factor sources against a minimum coverage
  window, it fails explicitly rather than silently substituting a placeholder value.
- Every interpolated year used in a figure/table is labeled as such in output metadata.
- 2020 is tagged source: historical_ons, never source: pte_projection.

## 8. Remaining open items (execution outputs, not decisions)

- Exact ONS/MCTI resource_ids and coverage windows - produced by Stage 1 at run time, logged.
- Calibrated C(P) function parameters - produced by Stage 2 at run time.
- Confirmation that MCTI margin (OM/BM/CM) publication has a stable public endpoint vs.
  PDF-only release (if PDF-only, flag as a manual-ingestion limitation).
- ANEEL (`aneel_client.py`, Task 6) is a FALLBACK, not the default path: standalone, never invoked automatically, and it can only
  provide installed capacity by source (ANEEL has no SIN generation-energy series), so it cannot replace the ONS generation-based P(t)
  without a new decision (D19).

## 9. Next steps

1. Build the local skeleton (done via terminal).
2. Implement Stage 1 (data_ingestion.py + ons_client.py + schemas.py) - first Claude Code task.
3. Iterate stage by stage, always gated by the acceptance criteria in section 7.

> Note (Task 11D): steps 1-3 above are historical. The current next step is the user's decision on D23, D24 and D25 (`config/discovered_sources.yaml`), then Task 11E (if approved), then Task 13.


---

## Decision D12 (added after MCTI discovery closure)

**D12: Combined Margin (CM) weighting formula.**

MCTI does not publish a Combined Margin (CM) value. CM must be computed
internally from Operating Margin (OM) and Build Margin (BM) using the
standard UNFCCC CDM default weighting for low-carbon/intermittent
sources (per ACM0002 convention):

    CM = 0.5 * OM + 0.5 * BM

This is a methodological assumption, not a published MCTI figure, and
must be explicitly logged as such in output metadata (never presented as
an MCTI-sourced number). See `src/curtailmit/emission_factors.py` for
the implementation and `config/discovered_sources.yaml` (mcti section)
for the full data provenance trail.

Additionally, per the same discovery round:

- MCTI's dispatch-analysis OM is published **monthly only**, with no
  official annual figure. The annual OM value used as the DEB proxy
  (D9) must be derived as the simple arithmetic mean of the 12 monthly
  values for that year, and this derivation must also be flagged as
  computed, not published, in output metadata.
- BM is published directly as a single annual value — no derivation
  needed.


---

## Update (Task 11D) - calibration / modeling stage branched into regional, time-controlled and pooled work

Context. Task 11B applied the nationally calibrated C_wind(P) / C_solar(P) curves (fitted on observed national penetration P = 10.3-29.4 %) to PTE scenarios reaching P = 58 %
nationally by 2050 and produced physically implausible values (87-98 % wind curtailment, 512-775 TWh in 2050). Task 11C (investigation, no code change) found that (a) the PTE
generation basis (gross vs net) is not stated, (b) international systems at similar penetration show curtailment an order of magnitude lower, and (c) the Northeast already operates
at local penetration of 49-84 % with annual curtailment of 9-19 %, and curtailment correlates more with time than with national P. The project thesis was revised (approved by the user):
high-penetration curtailment is primarily a regional / structural phenomenon (transmission-, load- and flexibility-bound), not a simple function of national aggregate penetration; the
contribution is methodological (using real within-sample regional and international experience instead of blind extrapolation of a national curve).

New branch of work, now a formal part of the calibration / modeling stage (Stages 2-3), not a lateral detour:

| Item | Content | Status |
|---|---|---|
| Task 11C | Investigation: PTE basis, international benchmarks, regional / DEB-REB-EUB diagnostic | DONE (`docs/task11c_investigation_report.md`) |
| Task 11D | Prototype / investigation: regional recalibration of C_wind (Northeast), time-confound test (D25), pooled international panel, documentation realignment. No `src/` change | DONE, findings pending user review (`docs/task11d_findings.md`) |
| Task 11E | Production migration of the driver (regional and/or pooled formulation) into `calibration.py` / `projection.py`, if the user adopts D24 | NOT started; contingent on D23, D24, D25 and on a solar treatment |
| Deferred extension | Transmission-capacity / expansion assumptions as an explicit regional driver (mechanism-aware formulation); needs a data-acquisition task | NOT started, not authorized |

Task 13 (OM/CM split, `results_writer` wiring, MCTI factor-year choice) **remains blocked** pending the outcome of Task 11D / 11E: its inputs (the curtailed-energy trajectories) are
the quantity in question. Decisions D13-D22 are untouched; D23, D24, D25 are candidates (`status: pending`).


---

## Update (Task 11E) - hourly driver, wind-asymptote envelope, transmission-capacity test

Task 11E (investigation / prototype, Brazil-only, no `src/` change; `docs/task11e_findings.md`) closes the three problems left open by Task 11D:

- Solar: the signal is not hidden by geography but by temporal aggregation. The midday potential VRE share of load explains monthly solar curtailment (R2 0.78 vs 0.40 for national P); an hourly SIN-wide dose-response curve is stable across 2025-2026.
- Wind asymptote L: not identifiable (same RMSE for L = 0.25 / 0.5 / 1.0), so the regional wind projection is reported as an envelope (79-245 TWh in 2050), with an energy-balance floor as a capacity-grounded low bound.
- Transmission: ONS operational capacity stocks are collinear with time and do not replace it; NE export is saturated in only 1-8 % of curtailed energy. The structural driver that emerges is the hourly SIN-wide VRE share of load (system energy balance), not NE export capacity.

Plan changes (the earlier table of the Task 11D update is annotated, not rewritten): the **production migration of the driver, previously called Task 11E, is renumbered Task 11F**; it remains NOT started and contingent on the user's decisions on D23, D24 (now with option E, hourly dose-response) and D25. Task 13 remains **blocked**. The deferred extension (EPE PDE / PET transmission-expansion assumptions) is unchanged and still not authorized. D26 (interchange-capacity driver) was not triggered and not registered.

---

## Update (Task 11E2) - validation of the hourly driver, wind extension, transmission mechanism

Task 11E2 (investigation / prototype, Brazil-only, no `src/` change; `docs/task11e2_findings.md`) validates the hourly dose-response driver (D24 option E) and extends it to wind:

- Coverage: the projected hourly conditions are inside the observed range for 2030 (99.6 percent of hours) and mostly for 2040 (86-96 percent of hours; 13-30 percent of the wind curtailment from hours beyond the support), but not for 2050 (43-70 percent of hours inside; 51-77 percent of the curtailment from beyond the support). The extrapolation problem is solved at its root only up to 2040.
- Validation: wind 2025 backtest -8 percent in sample and -11 to -19 percent out of sample (benchmarks -22 to -45 percent); stable across years 2023-2026 and between wind and solar near r = 40, not across seasons or hours of day; wind drifts about +2 pp per year; partial correlation with monthly C given time 0.70 (national P 0.42, P_NE 0.14).
- Wind and a unified driver: same family as solar; one curve for total VRE curtailment matches the two-curve total within 2 percent.
- Transmission: NE wind curtailment by ONS class is increasingly energy balance (DEB 8 to 61 percent, 2022-2026); interchange-related constraints are a minority. New candidate **D26** (status pending): retire the deferred EPE PDE / PET extension, with a stated limitation.
- Pending decisions: D24 (recommendation in the memo: E, reported by horizon, 2050 only as a conditional range), D25 and D26 are decidable; D23 is not. Task 11F (production migration) and Task 13 remain **blocked** until the user decides. The deferred extension is unchanged until D26 is decided.

---

## Update (Task 11E3) - extrapolation-distance calibration, decision closure

Task 11E3 (investigation / prototype, Brazil-only, no `src/` change; `docs/task11e3_findings.md`) tested whether the 2050 uncertainty of option E can be calibrated from how the model's error grew with extrapolation distance in 2022-2026 (350 train/test splits (wind 180, solar 85, unified 85), quarter blocks):

- Result: **no.** The error-growth relation explains 3-7 percent of the variance; the error is dominated by a level bias and a drift that grows with lead time (corr -0.34), not by covariate distance; the historical splits reach at most 8-11 pp beyond the training support while 2050 is 14-29 pp beyond; the pre-registered credibility rule fails for every technology and the method fails its own 2030 sanity check. **2050 stays a flexibility-conditional range**, not a calibrated band.
- What is quantified instead: an empirical annual-backtest error band of option E for 2030 and 2040 (wind truth / prediction 1.09-1.31, solar 0.87-1.13; descriptive).
- Consolidated recommendation for the next step: adopt D24 = option E reported by horizon, close D25 with the stated sentence, retire the PDE / PET extension (D26); D23 stays open and does not block. All four remain `pending`; Task 11F and Task 13 remain **blocked** until you decide.
- Environment: `statsmodels` is now a declared dependency; the 11E2 / 11E3 scripts run in the project `.venv`.
