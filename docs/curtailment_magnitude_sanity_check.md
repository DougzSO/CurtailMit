# Curtailment magnitude sanity check (pre-Task 9)

Status: **findings only.** Read-only analysis; no code, config or pipeline change. Date: 2026-10-21.
Inputs: `interim/ons_generation_by_source.parquet` (Task 3, SIN balance, wind and solar generation) and
`processed/ons_curtailment_classified.parquet` (Task 4, COFF plant-level curtailment), 2022-01-01 to 2026-10-20.

## Why

The classified series sums to ~86 TWh of wind+solar curtailment over ~4.8 years. Before it feeds `calibration.py`
we want to know whether that magnitude is plausible, and expressed as a rate rather than a raw total.

## 1. Year-by-year series (computed from our data)

Rate = curtailed / (realized generation + curtailed). Realized generation is the SIN balance (`val_gereolica`,
`val_gersolar`); curtailed energy is the COFF series (`val_geracaonaorealizadaapurada` x interval, D13).

| Year | Wind gen (TWh) | Wind curt (TWh) | Wind rate | Solar gen (TWh) | Solar curt (TWh) | Solar rate | Wind+solar gen | Wind+solar curt | **Wind+solar rate** | Curtailed (MWmed) |
|---|---|---|---|---|---|---|---|---|---|---|
| 2022 | 81.21 | 0.40 | 0.49 % | 12.09 | 0.00 (no data) | n/a | 93.30 | 0.40 | 0.43 % | 46 |
| 2023 | 95.38 | 3.41 | 3.45 % | 43.01 | 0.00 (no data) | n/a | 138.39 | 3.41 | 2.40 % | 389 |
| 2024 | 107.50 | 9.55 | 8.16 % | 73.34 | 3.25 (Apr-Dec only) | 4.25 % | 180.84 | 12.80 | 6.61 % | 1,457 |
| 2025 | 115.36 | 26.22 | 18.52 % | 91.83 | 11.00 | 10.70 % | 207.19 | 37.22 | **15.23 %** | 4,249 |
| 2026 (partial, to 2026-10-19/20) | 84.39 | 21.42 | 20.24 % | 82.35 | 10.67 | 11.47 % | 166.74 | 32.08 | 16.14 % | ~4,560 |

Notes on comparability inside our own series:
- Solar curtailment is not published before 2024-04 (D14), so the "wind+solar" rate for 2022-2023 has solar generation in
  the denominator but no solar curtailment in the numerator, and 2024 is a mixed year. The wind-only rate is the
  consistent series across 2022-2025: 0.49 % -> 3.45 % -> 8.16 % -> 18.52 % (2026 YTD 20.24 %).
- Using wind for all of 2024 and solar only from April 2024 in the denominator, the 2024 rate is 7.25 % (not 6.61 %).
- Curtailed energy by class (TWh), DEB / REB / EUB: 2022 0.03/0.13/0.24; 2023 0.92/1.84/0.65; 2024 4.37/7.21/1.22;
  2025 19.98/12.39/4.85; 2026 YTD 22.45/6.23/3.40. The growth is led by the energy-reason (DEB) class from 2025.
- Plants in the series: 157-170 wind plants/complexes per year; solar 65 (2024), 73 (2025), 90 (2026).

## 2. Reference points from ONS and others (side by side, not reconciled)

### 2.1 ONS's own diagnostic report: RT ONS DGL 0189/2025 "Diagnostico e perspectiva da evolucao dos cortes de geracao no Brasil"
(https://www.ons.org.br/AcervoDigitalDocumentosEPublicacoes/RT%20DGL-ONS%200189-2025%20-%20GT%20Curtailment%20rev1.pdf; text extracted
locally, Figure 4-2 read from the page-13 image.) It states that until March 2024 the restriction series covered **wind plants only** and
that PV was added from April 2024 - the same break we see in the data.

| | ONS Figure 4-2 (% of potential variable-renewable generation curtailed | MWmed) | Ours: curtailed MWmed | Ours: rate |
|---|---|---|---|
| 2022 | 0.5 % \| 46 MWmed | 46 | 0.49 % (wind) |
| 2023 | 3.6 % \| 389 MWmed | 389 | 3.45 % (wind) |
| 2024 | 9.3 % \| 1,447 MWmed | 1,457 (+0.7 %) | 7.25 % (wind + solar from Apr) / 6.61 % (all-year denominators) |

- ONS section 4.2: 2024 energy-reason restrictions "cerca de 4.330 GWh ou 493 MWmed". Ours: DEB (ENE) 2024 = **4,371 GWh / 498 MWmed** (+0.9 %).

### 2.2 Secondary sources (press/analysis; they cite ONS but I could not trace the underlying table)
- Ensaio Energetico (https://ensaioenergetico.com.br/impacto-do-constrained-off-nas-fontes-eolica-e-solar-fotovoltaica-no-brasil/): wind+solar constrained-off
  of **20.7 % in 2025** (table attributed to IEA/ONS; the denominator is not stated); monthly 2025: Aug 6,091 MWmed (24.9 %), Sep 7,062 MWmed (26.1 %), Oct 8,313 MWmed (30.4 %).
  Ours: Aug **6,091**, Sep **7,062**, Oct **8,313** MWmed - identical in MWmed.
- Movimento Economico (press): energy not produced "~20.6 % of renewable generation potential" in 2025 (source of the figure not identified as ONS).

| 2025 wind+solar | Reference | Ours |
|---|---|---|
| Annual rate | 20.7 % (Ensaio Energetico), ~20.6 % (press) | 15.23 % of (SIN generation + curtailed); 18.0 % if divided by realized generation only |
| Aug / Sep / Oct rate | 24.9 / 26.1 / 30.4 % | 19.3 / 20.2 / 23.3 % of (SIN generation + curtailed); 23.9 / 25.3 / 30.5 % of realized generation only |

## 3. Assessment

- **Absolute magnitude: reasonable, and independently corroborated.** Curtailed energy matches ONS's own published numbers: 46 / 389 MWmed
  (2022 / 2023) exactly, 1,457 vs 1,447 MWmed in 2024 (+0.7 %), the 2024 energy-reason total within 0.9 %, and Aug-Oct 2025 monthly MWmed exactly. The ~86 TWh is
  therefore not a parsing or unit artifact; it reflects ONS's own COFF accounting (D13). The rapid growth (0.4 TWh in 2022 -> 37 TWh in 2025) is itself what ONS
  and the press describe.
- **Percentage rate: inconclusive as a single number, because the denominator is not common.** The numerators agree; the published percentages are on a
  different (or undisclosed) denominator. ONS's 2022 and 2023 percentages (0.5 %, 3.6 %) are close to our wind-only rates (0.49 %, 3.45 %), but for 2024 ONS's 9.3 %
  is above our 7.25 % (which uses the whole SIN wind+solar generation). The implied ONS "potential" is 46/0.005 = 9.2 GW (2022), 389/0.036 = 10.8 GW (2023),
  1,447/0.093 = 15.6 GW (2024) - 96-99 % of our wind-only potential in 2022-2023 but only ~77 % of our wind+solar potential in 2024, consistent with ONS counting a
  narrower plant set for solar (not confirmed). For 2025, the published ~20.7 % sits above our 15.2 % and close to curtailed/realized-generation (18.0 %); the
  monthly 2025 published rates imply a "potential" roughly equal to our realized generation alone, i.e. they may be curtailed divided by realized generation.
  I could not determine the exact definition.

## 4. What could NOT be confirmed

1. The exact denominator ("potential generation") behind ONS's Figure 4-2 and behind the 2025 secondary figures (20.7 %, 24.9/26.1/30.4 %).
2. Whether the 2025 secondary figures are ONS-published aggregates or a third-party calculation.
3. Which plant set ONS's potential covers for solar (the COFF series covers plant modalities Tipo I / II-B / II-C per the dataset description; the SIN balance covers all SIN generation).
4. A 2025 or 2026 ONS-published annual rate: the ONS report extracted here covers 2022-2024 only.

## 5. Implication for Task 9 (no action taken here)

The calibration needs a curtailment **rate** C(P), and the rate level depends on the denominator by up to ~25 % relative (2025: 15.2 % vs 18.0 % vs the published ~20.7 %),
while the absolute curtailed energy is solid. The denominator convention (SIN balance, curtailed/realized, or an ONS-style potential for the COFF plant set) therefore needs an
explicit choice before fitting; it is a definitional choice, not a data error. For 2022-2023 only wind is observed, so any joint wind+solar calibration inherits the solar gap documented in D14.
