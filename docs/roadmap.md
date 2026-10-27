# CurtailMit - Master Roadmap: Curtailment x CO2 Mitigation Pipeline (PTE/EPE Scenarios) - v3.1 FINAL

> **Current status (Task 15 sync).** This file keeps its original text; later sections "Update (Task ...)" at the end are the history, newest last. Where the original text below disagrees with the code, the latest update and `docs/reproducibility.md` prevail. As of Task 15: option E (hourly dose-response model, D24) is in production; `curtailmit-run` runs the whole pipeline (Task 14); D1-D34 are listed in `docs/reproducibility.md`; acceptance criteria are mapped in `docs/acceptance_criteria_status.md`. Next: Task 13B (figures, limitations summary).

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

> **Update (Task 15 sync):** "not an hourly dispatch pipeline; curtailment is an externally calibrated function applied on top of PTE shares" (section 1) was written for the monthly national C(P). The production model (D24) is an hourly dose-response model on the whole-SIN hourly panel, applied to the 2025 hourly profile scaled to each PTE scenario-year. It is still not a dispatch model. "v1 = national, no regional breakdown" (section 0, D11) still holds for the reported results (SIN); the regional formulations were investigated and kept as reference. Original text kept.

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

> **Update (Task 15 sync): current stage table of the production path** (run by `curtailmit-run`, see `docs/orchestration.md`). The table above is the original v3.1 plan; its stages 2-3 are replaced.
>
> | Step | Module | Responsibility |
> |---|---|---|
> | Stage 1 | `data_ingestion.py` (+ clients) | acquisition, classification, MCTI factors, data-quality report |
> | Hourly calibration | `hourly_model.py`, `hourly_uncertainty.py` | Option E curves, base profile, horizon bands (replaces `calibration.py`, which is reference-only) |
> | Option E projection | `projection.py`, `limitations.py` | `pte_curtailment_option_E.parquet` with D25 limitation propagation |
> | Final results | `results_writer.py`, `mitigation.py`, `hydrogen.py` | long-format `final_results` (OM/CM split, H2), 156 rows |
> | Reference check, run manifest | `pipeline.py`, `run_manifest.py` | reference totals within 1e-9; `run_manifest_<UTC>.json` |

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

> **Update (Task 15 sync): section 7 is mapped to the production table in `docs/acceptance_criteria_status.md`** (criterion 5, the 2020 historical tag, is not applicable to `final_results`, which starts at 2025; "5 anchor points" is 4 projection years).

## 8. Remaining open items (execution outputs, not decisions)

- Exact ONS/MCTI resource_ids and coverage windows - produced by Stage 1 at run time, logged.
- Calibrated C(P) function parameters - produced by Stage 2 at run time.
- Confirmation that MCTI margin (OM/BM/CM) publication has a stable public endpoint vs.
  PDF-only release (if PDF-only, flag as a manual-ingestion limitation).
- ANEEL (`aneel_client.py`, Task 6) is a FALLBACK, not the default path: standalone, never invoked automatically, and it can only
  provide installed capacity by source (ANEEL has no SIN generation-energy series), so it cannot replace the ONS generation-based P(t)
  without a new decision (D19).

> **Update (Task 15 sync):** the first bullet below, "Calibrated C(P) function parameters - produced by Stage 2 at run time", is superseded: the fitted parameters are the hourly curves `processed/hourly_curve_{wind,solar}[_L1].json` (wind L = 0.733, k = 0.1427, x0 = 40.9; solar L = 0.736, k = 0.1011, x0 = 41.9, `docs/methodology.md` section 2.3j). The resource ids and coverage windows are in `docs/stage1_data_quality_report.md` and the retrieval manifests; no fallback was triggered (the classified ONS series is available, `classification_available = true`; the ANEEL fallback was never invoked).

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

---

## Update (Task 11E4) - coverage figure, NE-hourly, sub-hourly feasibility, conformal intervals

Task 11E4 (investigation / prototype, Brazil-only, no `src/` change; `docs/task11e4_findings.md`) tested four extensions; none changes the Task 11E3 conclusion that 2050 is a flexibility-conditional range:

- Publication-ready in-sample coverage figure produced (`fig_insample_coverage.{pdf,svg,png}`): 99.6-99.8 percent of the hours are inside the observed support in 2025-2030, 86-96 percent in 2040, 43-70 percent in 2050; the figure is to be used as the method's transparency exhibit.
- NE-hourly driver: does not extend the support (2050 hours inside 32-59 percent against 43-70 percent for the SIN-wide hourly driver); no validation gain.
- Sub-hourly data: ONS publishes 30-minute realized load and COFF data; a 2025 sample shows no wider range of r than the hourly aggregation (maximum ratio 1.006); candidate D27-candidate (an unregistered Task 11E4 candidate, never adopted; not the adopted D27 of Task 13) **not registered** (negative result). Sample documented in `docs/ons_subhourly_data_sources.md`.
- Conformal prediction: finite 80 percent intervals for 2030 / 2040 (3-10 times wider than the empirical band; coverage confirmed by leave-one-quarter-out), none for 2050 (unbounded: exchangeability violated), reported explicitly.
- Updated recommendation for the next step: unchanged in substance (D24 = E by horizon, D25 closed, D26 retire), with the coverage figure and the "no valid conformal interval at 2050" statement added to the 2050 reporting. D23 still open. Task 11F and Task 13 remain **blocked** until you decide. International hourly data were excluded by your decision (note in the memo).

---

## Update (Task 11F0) - D23, D24 and D26 adopted; the transmission-expansion extension is retired

On 2026-10-26 the user adopted three candidates (`config/discovered_sources.yaml`, `status: adopted`); no new analysis, no code change. Evidence: `docs/task11c_investigation_report.md`, `docs/task11d_findings.md`, `docs/task11e_findings.md`, `docs/task11e2_findings.md`, `docs/task11e3_findings.md`, `docs/task11e4_findings.md`.

- **D23 - PTE generation is treated as GROSS (pre-curtailment potential)**, as a working assumption by explicit user decision; the evidence remained weak and mixed (Task 11C) and no later task changed it. All figures of Tasks 7-11E4 already use it. The net-basis sensitivity stays documented and recommended, no longer blocking.
- **D24 - option E (hourly dose-response, system-wide potential VRE share of load) is the primary curtailment model**, reported by horizon: 2025 / 2030 central estimate with the empirical annual-backtest band as headline and the split-conformal 80 percent interval as supplement; 2040 the same with TA flagged as partly outside the observed support; 2050 central estimate with the in-support / out-of-support decomposition, the flexibility-conditional range (phi 1.5 to L = 1), the coverage figure and the statement that no valid conformal interval exists, with no probability and no "calibrated" label. The national-curve (Tasks 7-11B) and regional-only (Task 11D) formulations stay as documented reference points, not as the production model.
- **D26 - the transmission-capacity-expansion extension (EPE PDE / PET planning data), listed above as a deferred optional refinement, is formally RETIRED, not merely deferred.** The "deferred extension" items of the earlier Task 11D / 11E / 11E2 updates and of the task tables are superseded by this entry (annotated, not rewritten). Declared caveat kept in the decision: in 2026 about 38 percent of NE wind curtailment is attributable to network-element limits (23 percent internal to the NE), covered only through the flexibility sensitivity of option E.
- **D25 remains `pending`**, deferred to Task 11E5; it is adopted last.
- **Task 11F (production migration of option E into `src/`) is unblocked in principle** but should wait for D25 (Task 11E5). **Task 13 stays blocked** until Task 11F is done.

---

## Update (Task 11E5) - residual wind drift of option E: quantified limitation, recommendation for D25

Task 11E5 (investigation / prototype, Brazil-only, no new data, no `src/` change; `docs/task11e5_findings.md`) examined the residual upward drift of the hourly wind model, the last open item (D25):

- Size: +1.4 to +1.6 pp of the wind curtailment rate per year (95 percent interval 0.5-2.7), better described as a step of about +4.6 pp in January 2025 (coinciding with the doubling of the energy-balance share of curtailment) than as a smooth trend; it sits at r between 20 and 40 percent and in RN and BA. Fleet vintage and state composition do not explain it (rejected); the cause is not identified with the data in hand.
- Compounded naively to 2050 it would be about +39 pp, but the asymptote bounds it (only 7-17 pp of headroom): +1-4 percent (step), +15-20 TWh (saturating), at most +34-52 TWh (linear, capped), i.e. 3-15 percent of the 2050 total, upward only.
- An explicit trend term does not pass the pre-registered safety and worth criteria; not recommended. The bounded step variant is the only safe sensitivity.
- Recommendation for D25: accept the drift as a documented, quantified limitation (text in the memo, section 5). D25 stays `pending` for your decision; Task 11F (production migration of option E, D24 adopted) can start after it, with your confirmation. Task 13 remains blocked until Task 11F is done.

---

## Update (Task 11F-0) - all four decisions D23-D26 are now adopted; Task 11F proceeding

D25 was adopted on 2026-10-26 by explicit user decision (accept as a documented, quantified limitation; text verbatim from `docs/task11e5_findings.md` section 5 / `config/discovered_sources.yaml`). With D23, D24 and D26 (Task 11F0) all four pending decisions are resolved. Task 11F (production migration of option E into `src/`) is proceeding; its design proposal is in `docs/task11f_design.md` and awaits approval before any `src/` change. Task 13 stays blocked until Task 11F is complete.

---

## Update (Task 11F) - option E migrated to production; Task 13 unblocked

Task 11F (D23-D26 adopted) migrated the hourly dose-response model into `src/`: new modules `hourly_model.py` (panel, binning, fit, curve, distance metrics, PTE-scaled profile, calibration bundle), `hourly_uncertainty.py` (annual-backtest band, quarter splits, weighted split-conformal, frozen `HorizonBands`) and `limitations.py` (D25 text from the YAML into the outputs); `projection.project_curtailment_hourly` / `build_option_e_table` implement the by-horizon treatment (2025/2030/2040 band + conformal supplement; 2050 decomposition + flexibility-conditional range, no conformal, no "calibrated" label); the national and regional formulations stay as labelled references (`model`/`role` columns, `calibration.fit_regional_reference`); `mitigation.compute_mitigation` gained `require_model` and passes the labels through. Regression: the production code reproduces the validated prototypes and the committed Task 11E2-11E4 tables to 1e-9 (golden fixture `tests/fixtures/option_e/`, integration tests `pytest -m integration`). Design and implementation notes: `docs/task11f_design.md`. Consolidated methods text: `docs/methodology.md` section 2.3j.

**Task 11F is complete; Task 13 (mitigation deficit and hydrogen with the option-E table `processed/pte_curtailment_option_E.parquet`) is formally unblocked and waits for the user's confirmation to start.**

---

## Update (Task 13-1) - design proposal for the final output layer; Task 13 awaits approval

Design only (`docs/task13_design.md`, no `src/` change). A legacy `results_writer.py` (frozen `ResultsRow`, schema + CSV/JSON only) already exists; it is unreachable from any entry point, has never produced an output and does not contradict Option E figures, but it is structurally incompatible with the required per-row ranges and caveats. Three decisions are registered as `pending` (D27 fate of `ResultsRow`, D28 OM/CM split versus the horizon-dependent range, D29 MCTI factor year for 2030-2050). Task 13 starts only after the user answers the questions in section 9 of the design. The 2050 range stays a flexibility-conditional range (`conditional_range_low/high`, `range_basis`), never a confidence interval.

---

## Update (Task 13) - final results layer implemented; D27, D28, D29 adopted

Task 13 (Parts A and B) done: `results_writer.py` superseded in place (D27 A), long-format writer with per-row caveats, OM/CM split with the energy range applied after the split and fixed emission factors (D28), MCTI factor 2025 central with the 2021-2025 mean as a labelled sensitivity (D29), `mitigation.ModelProvenanceError`. Outputs in DATABASE_ROOT/outputs/tables. Part C (figures and the auto-generated limitations report) is out of scope and deferred to a later task (13B). The 2050 range stays a flexibility-conditional range, never a confidence interval. See `docs/methodology.md` section 2.3k.

---

## Update (Task 13-2) - closeout of Task 13

D30 registered (hydrogen SEC treatment, extension of D28). The `central_inside_range = False` pattern for wind 2025-2040 is documented as an expected D25 effect. Task 13_pre was already complete. Task 13B (figures) and Task 14 await the user's sign-off.

---

## Update (Task 14-1) - design proposal for orchestration and CI; Task 14 awaits approval

Design only (`docs/task14_design.md`, no code change). Findings: `scripts/run_pipeline.py` runs Stage 1 only (no retired-model logic); hourly calibration, Option E projection and final results have no entry point; the existing CI never passed (13 of 13 runs failed, remote 37 commits behind) and one default test depends on the local database. Pending decisions D31 (scope of end to end) and D32 (CI test isolation) registered. Task 14 starts only after the user answers section 6 of the design.

---

## Update (Task 14) - orchestration command and CI implemented; D31, D32 adopted

Task 14 done: `curtailmit-run` / `python -m curtailmit.pipeline` runs pre-check, Stage 1, hourly calibration, Option E projection and final results with stamp-verified skip logic (re-run whenever validity cannot be established), per-stage `SKIPPED/RAN` reporting, hard gates with exit code 2, and an always-on reference-value check (`tests/fixtures/final_results/reference_totals.json`). CI rewritten (lint, unit tests with integration excluded, dry-run smoke test). See `docs/orchestration.md`. Figures and the limitations report remain Task 13B; the run manifest remains Task 15.

---

## Update (Task 15-1) - design proposal for reproducibility and documentation sync; Task 15 awaits approval

Design only (`docs/task15_design.md`, no code change). Findings: no non-determinism (seeded bootstrap; 13 output files byte-identical across runs with different hash seeds and thread counts); dependencies are floors only, no lock; no single reproducibility document; a 15-item documentation audit (README and the Task 12-era stage tables are stale). Pending decisions D33 (data-availability promise: the database is local-only) and D34 (scope split, lock mechanism, D1-D12 handling). Task 13B (figures) follows Task 15.

---

## Update (Task 15) - reproducibility manifest and documentation sync implemented; D33, D34 adopted

Task 15 done (design `docs/task15_design.md`): standing determinism tests (synthetic unit test in CI, real-pipeline integration test), exact pin lock `requirements.lock.txt` with CI job `unit-tests-locked`, run manifest `logs/run_manifest_<UTC>.json` (success runs only), committed `data_snapshot_manifest.json` (250 raw files; no data redistributed, D33), `docs/reproducibility.md` with the generated D1-D34 register and a consistency test (it also catches decision-number collisions), `docs/acceptance_criteria_status.md`, README rewritten, and the 15-item documentation audit applied (narrative history annotated, status markers struck through with update notes, the unregistered Task 11E4 "D27" relabelled `D27-candidate`). The article needs a data-availability statement citing the snapshot manifest (open item for the article step). Next: Task 13B (figures, `limitations_summary.md`).

---

## Update (Task 15-3) - acceptance criterion 5 superseded (D35)

Criterion 5 of section 7 (2020 tagged `historical_ons`) is superseded by decision D35: the Task 11E2 backtest / holdout validation replaces a single 2020 anchor as historical validation; no 2020 row is added to `final_results`. It is superseded, not unmet and not an open question (this refines the "not applicable" wording of the Task 15 sync note above). See `docs/acceptance_criteria_status.md`.
