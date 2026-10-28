# Limitations of the production model - summary

This page lists what a reader should not read into the CurtailMit results. It is the article-facing summary of the limitations; it is a partly generated document (Task 16).

**How it is built.** The three blocks between the `GENERATED` markers are written by `python -m curtailmit.doc_generation --write` from two sources, and a test fails when the page disagrees with them: (A) the `limitation` fields of the adopted decisions D23-D35 (and the optional ones of D14, D16, D18, D20, D21, D22) in [config/discovered_sources.yaml](../config/discovered_sources.yaml), and (B) the caveat texts that the production table `final_results` carries on every row (a committed copy of the five distinct texts, `tests/fixtures/final_results/limitation_texts.json`, is compared with the real table wherever the local database exists). The text outside the markers is written by hand. The wording of each statement still needs a human reader: the checks catch a wrong number, a missing field or an unknown theme, not an overstated claim.

**How to read the central values and ranges.** The central values of the production model (option E, the hourly dose-response model, D24) are more likely low than high (D25). The 2025-2040 ranges are an empirical backtest band with a conformal supplement; the 2050 range is a range conditional on a flexibility assumption, and is not a statistical interval of any kind. All 2050 rows are `mostly_out_of_support`.

Longer discussion: [methodology](methodology.md) sections 2.3j, 2.3k and 3.7. Open items to close by hand before submission, including the unverified ONS and MCTI licensing terms: [pre-submission checklist](pre_submission_checklist.md).

## Limitations by theme

<!-- GENERATED:BEGIN id=limitations-themes sources=discovered_sources.yaml
     do not edit by hand; regenerate with: python -m curtailmit.doc_generation --write -->

### Residual drift of the wind curtailment

Longer prose: [methodology](methodology.md), sections 2.3h and 2.3j.

- **[D25](../config/discovered_sources.yaml)** (adopted): Central values are more likely low than high: the wind curtailment rate at a fixed hourly VRE share drifts upward by about +1.4 to +1.6 pp per year over 2022-2026, the cause is not identified and the drift is not corrected. Compounded to 2050 it adds at most +15-20 TWh (saturating) or +34-52 TWh (linear, capped), upward only.

### Extrapolation beyond the observed support

Longer prose: [methodology](methodology.md), sections 2.3j and 2.3k.

- **[D24](../config/discovered_sources.yaml)** (adopted): Option E is validated for 2030-2040, not for 2050: 51-77 percent of the 2050 energy comes from hours with no historical analogue, and the TA scenario is partially outside the observed hourly support in 2040. The 2050 range is conditional, not a statistical interval, and no valid conformal interval could be produced at that horizon.
- **[D28](../config/discovered_sources.yaml)** (adopted): The energy-side range depends on the horizon: an empirical band with a conformal supplement for 2025-2040, a flexibility-conditional range for 2050.

### Flexibility held fixed; transmission expansion not modelled

Longer prose: [methodology](methodology.md), sections 2.3g and 2.3j.

- **[D24](../config/discovered_sources.yaml)** (adopted): Option E holds today's flexibility fixed; the 2050 range varies the flexibility assumption (phi = 1.5 as the lower scenario to L = 1 as the upper) but remains conditional on it.
- **[D26](../config/discovered_sources.yaml)** (adopted): Transmission expansion is not modelled (retired by D26): in 2026 about 38 percent of Northeast wind curtailment is still attributable to network-element limits and 23 percent of it is internal to the Northeast network, which expansion could reduce; this share is covered only by the flexibility sensitivity of option E. The finding supported is that curtailment is not primarily export-bound, not that transmission is irrelevant.

### Short solar record

Longer prose: [methodology](methodology.md), section 2.3j.

- **[D14](../config/discovered_sources.yaml)** (adopted): The 2020 baseline solar curtailment is a documented zero, an assumption backed by ONS not publishing earlier data, not a measurement: 3.3 GW of PV existed in 2020.
- **[D24](../config/discovered_sources.yaml)** (adopted): The solar curve is fitted on 30 months of data, a shorter record than wind.

### Generation basis of the scenarios and of the calibration

Longer prose: [methodology](methodology.md), sections 2.3g and 3.7.

- **[D16](../config/discovered_sources.yaml)** (adopted): The calibrated curve is fitted on ONS SIN-basis data and applied to PTE-basis data without reconciliation, under the assumption that curtailment risk scales with the penetration share regardless of the accounting scope; this is an assumption, not a proven equivalence.
- **[D20](../config/discovered_sources.yaml)** (adopted): Solar generation is defined as the ONS-dispatched series, not the balance series that includes a non-dispatched component from 2023-04-29 onward; this is a project-level methodological choice, not an ONS-confirmed fact for that field.
- **[D23](../config/discovered_sources.yaml)** (adopted): The generation of the PTE / BLUES scenarios is treated as gross (pre-curtailment) by user decision, not by evidence; if it is in fact delivered energy, the curtailment figures are a lower bound of what the same curve implies. The net-basis alternative is documented as a sensitivity only.

### Emission factors

Longer prose: [methodology](methodology.md), section 2.3k.

- **[D18](../config/discovered_sources.yaml)** (adopted): Margin factors exist only for completed years, so projection years have no factor of their own, and the annual operating margin is a simple mean of 12 monthly values because MCTI publishes no generation weights.
- **[D28](../config/discovered_sources.yaml)** (adopted): Emission factors are fixed point values, not conditioned on the flexibility assumption of the energy range, so the 2050 figures carry a partial uncertainty composition (energy-side conditional range plus a point-value factor). OM and CM are alternative proxies and are never summed.
- **[D29](../config/discovered_sources.yaml)** (adopted): Projected years use the MCTI factor of the last complete year (2025); the 2021-2025 mean is only a labelled sensitivity. The annual average factor varies about 3x over 2021-2025 (0.0385 to 0.1263 tCO2/MWh), so the tCO2 figures depend on the factor year chosen.

### Hydrogen: fixed specific energy consumption

Longer prose: [methodology](methodology.md), section 2.3k.

- **[D30](../config/discovered_sources.yaml)** (adopted): The hydrogen potential uses a fixed specific energy consumption of 52.5 kWh/kg; the 50 to 55 kWh/kg sensitivity interval is kept in separate columns and is not part of the conditional range.

### Data availability and licensing

Longer prose: [reproducibility](reproducibility.md), section 1, and [pre-submission checklist](pre_submission_checklist.md).

- **[D33](../config/discovered_sources.yaml)** (adopted): The raw data are not bundled (curtailmit_database is local-only). A snapshot manifest lets readers re-download and verify hash by hash, but the redistribution terms of the ONS and MCTI datasets are not verified, so no statement of permission is made.

### Historical validation

Longer prose: [acceptance criteria status](acceptance_criteria_status.md), criterion 5, and [Task 11E2 findings](task11e2_findings.md).

- **[D35](../config/discovered_sources.yaml)** (adopted): No 2020 historical anchor is part of the production table; historical validation rests on the 2023-2026 backtest, which shows a downward bias in the latest years (wind 2025: -8 percent in sample, -19 percent trained on 2022-24), recorded as the D25 limitation.

### What reproducibility promises

Longer prose: [reproducibility](reproducibility.md).

- **[D34](../config/discovered_sources.yaml)** (adopted): Reproducibility is verified for the locked environment: no non-determinism was found across hash seeds and thread counts, and the reference-value check is the portable promise. Bitwise identity of the outputs across platforms or library versions is not promised.

<!-- GENERATED:END id=limitations-themes -->

## Caveats carried by the output rows

<!-- GENERATED:BEGIN id=limitations-row-caveats sources=limitation_texts.json
     do not edit by hand; regenerate with: python -m curtailmit.doc_generation --write -->

The production table `final_results` (156 rows) carries 5 distinct caveat texts in `known_limitations_text`, reproduced verbatim. Each row also carries the ids in `known_limitations`.

**Caveat 1** - `support_status` = `within_support`; ids: D25 (residual drift of the wind curtailment rate), short solar record (30 months); 104 rows; scenario-years: TA 2025, 2030; TB 2025, 2030, 2040; TG 2025, 2030, 2040.

> Central values are more likely low than high: residual upward drift of the wind curtailment rate at fixed hourly VRE share (D25; +1.4 to +1.6 pp per year over 2022-2026, not corrected). Solar curve fitted on 30 months (shorter record than wind).

**Caveat 2** - `support_status` = `partially_out_of_support`; ids: D25 (residual drift of the wind curtailment rate), short solar record (30 months); 13 rows; scenario-years: TA 2040.

> Central values are more likely low than high: residual upward drift of the wind curtailment rate at fixed hourly VRE share (D25; +1.4 to +1.6 pp per year over 2022-2026, not corrected). Solar curve fitted on 30 months (shorter record than wind). Part of the projected curtailment (38 percent) comes from hours with no historical analogue (partially_out_of_support).

**Caveat 3** - `support_status` = `mostly_out_of_support`; ids: D25 (residual drift of the wind curtailment rate), short solar record (30 months); 13 rows; scenario-years: TA 2050.

> Central values are more likely low than high: residual upward drift of the wind curtailment rate at fixed hourly VRE share (D25; +1.4 to +1.6 pp per year over 2022-2026, not corrected). Solar curve fitted on 30 months (shorter record than wind). Part of the projected curtailment (76 percent) comes from hours with no historical analogue (mostly_out_of_support). 2050 values are a range conditional on a flexibility assumption (phi 1.5 to L=1), not a calibrated forecast; the emission factor is a fixed point value (D28).

**Caveat 4** - `support_status` = `mostly_out_of_support`; ids: D25 (residual drift of the wind curtailment rate), short solar record (30 months); 13 rows; scenario-years: TB 2050.

> Central values are more likely low than high: residual upward drift of the wind curtailment rate at fixed hourly VRE share (D25; +1.4 to +1.6 pp per year over 2022-2026, not corrected). Solar curve fitted on 30 months (shorter record than wind). Part of the projected curtailment (62 percent) comes from hours with no historical analogue (mostly_out_of_support). 2050 values are a range conditional on a flexibility assumption (phi 1.5 to L=1), not a calibrated forecast; the emission factor is a fixed point value (D28).

**Caveat 5** - `support_status` = `mostly_out_of_support`; ids: D25 (residual drift of the wind curtailment rate), short solar record (30 months); 13 rows; scenario-years: TG 2050.

> Central values are more likely low than high: residual upward drift of the wind curtailment rate at fixed hourly VRE share (D25; +1.4 to +1.6 pp per year over 2022-2026, not corrected). Solar curve fitted on 30 months (shorter record than wind). Part of the projected curtailment (53 percent) comes from hours with no historical analogue (mostly_out_of_support). 2050 values are a range conditional on a flexibility assumption (phi 1.5 to L=1), not a calibrated forecast; the emission factor is a fixed point value (D28).

<!-- GENERATED:END id=limitations-row-caveats -->

## Earlier decisions (D1-D12) - maintained by hand

*This section is written by hand from the decision table and the "Decision D12" section of [roadmap](roadmap.md). It is not generated and not checked against the roadmap by a test. D1-D12 are not in the YAML (decision D34), so they carry no `limitation` field.*

- **D1, D2, D3 (baseline, year grid, interpolation).** These were written for a five-point grid with a 2020 historical anchor. The production table has the four projection years 2025, 2030, 2040 and 2050, no interpolated year and no 2020 row; criterion 5 is recorded as superseded by D35 (see the historical-validation theme above and [acceptance criteria status](acceptance_criteria_status.md)).
- **D5, D6 (classification).** The mapping of ONS reason codes to DEB / REB / EUB is a default that can be adjusted in configuration (D5). If the classified series were unavailable the pipeline would fall back to the aggregate and set `classification_available: false` (not triggered; the production table carries `True`).
- **D7 (electrolyzer SEC).** 52.5 kWh/kg is a mid-point assumption inside a 50-55 kWh/kg band; its treatment in the results is the hydrogen-sec theme above (D30).
- **D8, D9, D12 (emission factors).** The average factor is the MCTI figure; the marginal factors are the MCTI operating and build margins used as marginal proxies (D9), not a bespoke dispatch estimate. The Combined Margin is computed here as 0.5 x OM + 0.5 x BM (the CDM default weighting), a methodological assumption and not a published MCTI figure. OM and CM are alternative proxies and are never summed.
- **D10 (PLD).** The price module is optional and not part of the production pipeline (the source was closed); no price-based result is produced.
- **D11 (scope).** National scope (SIN) only; there is no regional or subsystem breakdown in the results.

## Decision-by-decision appendix

The statements of the table below are the same as above, one row per decision. A decision with no reader-facing limitation states why. D21 and D22 keep the status `adopted` but were replaced in practice by D24; the field `superseded_in_practice_by` shows it.

<!-- GENERATED:BEGIN id=limitations-decision-appendix sources=discovered_sources.yaml
     do not edit by hand; regenerate with: python -m curtailmit.doc_generation --write -->

| Decision | Status | Themes | Limitation statement |
|---|---|---|---|
| [D14](../config/discovered_sources.yaml) | adopted | `solar-record` | The 2020 baseline solar curtailment is a documented zero, an assumption backed by ONS not publishing earlier data, not a measurement: 3.3 GW of PV existed in 2020. |
| [D16](../config/discovered_sources.yaml) | adopted | `generation-basis` | The calibrated curve is fitted on ONS SIN-basis data and applied to PTE-basis data without reconciliation, under the assumption that curtailment risk scales with the penetration share regardless of the accounting scope; this is an assumption, not a proven equivalence. |
| [D18](../config/discovered_sources.yaml) | adopted | `emission-factors` | Margin factors exist only for completed years, so projection years have no factor of their own, and the annual operating margin is a simple mean of 12 monthly values because MCTI publishes no generation weights. |
| [D20](../config/discovered_sources.yaml) | adopted | `generation-basis` | Solar generation is defined as the ONS-dispatched series, not the balance series that includes a non-dispatched component from 2023-04-29 onward; this is a project-level methodological choice, not an ONS-confirmed fact for that field. |
| [D21](../config/discovered_sources.yaml) | adopted; superseded in practice by D24 | - | No reader-facing limitation: Superseded in practice by D24: kept as a documented reference / comparison point of the methodological journey, not the production model. |
| [D22](../config/discovered_sources.yaml) | adopted; superseded in practice by D24 | - | No reader-facing limitation: Superseded in practice by D24: kept as a documented reference / comparison point of the methodological journey, not the production model. |
| [D23](../config/discovered_sources.yaml) | adopted | `generation-basis` | The generation of the PTE / BLUES scenarios is treated as gross (pre-curtailment) by user decision, not by evidence; if it is in fact delivered energy, the curtailment figures are a lower bound of what the same curve implies. The net-basis alternative is documented as a sensitivity only. |
| [D24](../config/discovered_sources.yaml) | adopted | `support-extrapolation`, `flexibility-transmission`, `solar-record` | Option E is validated for 2030-2040, not for 2050: 51-77 percent of the 2050 energy comes from hours with no historical analogue, and the TA scenario is partially outside the observed hourly support in 2040. The 2050 range is conditional, not a statistical interval, and no valid conformal interval could be produced at that horizon. Option E holds today's flexibility fixed; the 2050 range varies the flexibility assumption (phi = 1.5 as the lower scenario to L = 1 as the upper) but remains conditional on it. The solar curve is fitted on 30 months of data, a shorter record than wind. |
| [D25](../config/discovered_sources.yaml) | adopted | `drift` | Central values are more likely low than high: the wind curtailment rate at a fixed hourly VRE share drifts upward by about +1.4 to +1.6 pp per year over 2022-2026, the cause is not identified and the drift is not corrected. Compounded to 2050 it adds at most +15-20 TWh (saturating) or +34-52 TWh (linear, capped), upward only. |
| [D26](../config/discovered_sources.yaml) | adopted | `flexibility-transmission` | Transmission expansion is not modelled (retired by D26): in 2026 about 38 percent of Northeast wind curtailment is still attributable to network-element limits and 23 percent of it is internal to the Northeast network, which expansion could reduce; this share is covered only by the flexibility sensitivity of option E. The finding supported is that curtailment is not primarily export-bound, not that transmission is irrelevant. |
| [D27](../config/discovered_sources.yaml) | adopted | - | No reader-facing limitation: Output-schema decision: it fixes how the results table is laid out and carries no modelling assumption. |
| [D28](../config/discovered_sources.yaml) | adopted | `emission-factors`, `support-extrapolation` | Emission factors are fixed point values, not conditioned on the flexibility assumption of the energy range, so the 2050 figures carry a partial uncertainty composition (energy-side conditional range plus a point-value factor). OM and CM are alternative proxies and are never summed. The energy-side range depends on the horizon: an empirical band with a conformal supplement for 2025-2040, a flexibility-conditional range for 2050. |
| [D29](../config/discovered_sources.yaml) | adopted | `emission-factors` | Projected years use the MCTI factor of the last complete year (2025); the 2021-2025 mean is only a labelled sensitivity. The annual average factor varies about 3x over 2021-2025 (0.0385 to 0.1263 tCO2/MWh), so the tCO2 figures depend on the factor year chosen. |
| [D30](../config/discovered_sources.yaml) | adopted | `hydrogen-sec` | The hydrogen potential uses a fixed specific energy consumption of 52.5 kWh/kg; the 50 to 55 kWh/kg sensitivity interval is kept in separate columns and is not part of the conditional range. |
| [D31](../config/discovered_sources.yaml) | adopted | - | No reader-facing limitation: Orchestration-scope decision (what end to end means for the command): no modelling assumption. |
| [D32](../config/discovered_sources.yaml) | adopted | - | No reader-facing limitation: CI test-isolation decision: it affects how the tests run, not the results. |
| [D33](../config/discovered_sources.yaml) | adopted | `data-provenance` | The raw data are not bundled (curtailmit_database is local-only). A snapshot manifest lets readers re-download and verify hash by hash, but the redistribution terms of the ONS and MCTI datasets are not verified, so no statement of permission is made. |
| [D34](../config/discovered_sources.yaml) | adopted | `reproducibility-scope` | Reproducibility is verified for the locked environment: no non-determinism was found across hash seeds and thread counts, and the reference-value check is the portable promise. Bitwise identity of the outputs across platforms or library versions is not promised. |
| [D35](../config/discovered_sources.yaml) | adopted | `historical-validation` | No 2020 historical anchor is part of the production table; historical validation rests on the 2023-2026 backtest, which shows a downward bias in the latest years (wind 2025: -8 percent in sample, -19 percent trained on 2022-24), recorded as the D25 limitation. |
| [D36](../config/discovered_sources.yaml) | adopted | - | No reader-facing limitation: Boundary geometry only draws the context maps (C1, C1S); no result, range or table value depends on it. |

<!-- GENERATED:END id=limitations-decision-appendix -->
