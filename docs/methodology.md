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

### Emission factor data - RESOLVED, same empirical discovery pattern (new in v3.1)

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

## 2.4. Step 2 - Applying the function to PTE scenarios

For each scenario s in {TB, TA, TG} and year t in {2020, 2025, 2030, 2040, 2050}
(2020 = ONS historical actual, tagged accordingly - D1):

- P(s,t) - from Table 2, or linearly interpolated (D3) if needed.
- C_hat(s,t) = C(P(s,t)) - from the calibrated logistic function (2.3), produced by Stage 2.
- E_curt(s,t) = Solar+wind generation(s,t) [Table 2] x C_hat(s,t).

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
