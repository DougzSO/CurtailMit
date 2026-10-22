# ONS solar generation vs ANEEL centralized capacity: evidence of a definition break in 2023

Status: **findings only, flagged for review. Nothing in the pipeline or config was changed.** Date: 2026-10-22.
Found while building the Task 6 ANEEL fallback (installed capacity by source from the SIGA registry).

## What was compared

- ONS: annual generation from our Task 3 series (`ons_penetration_annual.parquet`, SIN, `val_gereolica` / `val_gersolar`).
- ANEEL SIGA registry (operating plants, cumulative by `DatEntradaOperacao`, fiscalized kW): **centralized** wind (EOL) and
  utility-scale PV (UFV) capacity. The registry excludes distributed micro/mini generation (MMGD). Average capacity of year Y =
  mean of the year-end capacities of Y-1 and Y.
- Implied capacity factor = ONS generation / (average centralized capacity x 8,760 h).

## Result

| Year | Avg centralized solar (GW) | ONS solar (TWh) | Implied solar CF | Avg centralized wind (GW) | ONS wind (TWh) | Implied wind CF |
|---|---|---|---|---|---|---|
| 2017 | 0.54 | 0.59 | 12.6 % | 11.32 | 39.80 | 40.2 % |
| 2018 | 1.43 | 2.67 | 21.3 % | 13.40 | 45.80 | 39.0 % |
| 2019 | 2.18 | 4.38 | 22.9 % | 14.90 | 53.39 | 40.9 % |
| 2020 | 2.93 | 5.23 | 20.4 % | 16.25 | 54.30 | 38.1 % |
| 2021 | 4.02 | 7.43 | 21.1 % | 19.02 | 72.32 | 43.4 % |
| 2022 | 6.08 | 12.09 | 22.7 % | 22.51 | 81.21 | 41.2 % |
| **2023** | 9.52 | **43.01** | **51.6 %** | 26.56 | 95.38 | 41.0 % |
| **2024** | 14.40 | **73.34** | **58.1 %** | 30.95 | 107.50 | 39.6 % |
| **2025** | 18.66 | **91.83** | **56.2 %** | 33.81 | 115.36 | 38.9 % |

- Wind is stable at ~38-43 % in every year: no break.
- Solar sits at ~20-23 % from 2018 to 2022 (typical for Brazilian utility-scale PV), then jumps to 52-58 % from 2023. A
  capacity factor above ~30 % is not physically plausible for centralized PV, and the 2022 -> 2023 jump in ONS solar (12.1 -> 43.0 TWh)
  is far larger than the centralized capacity growth.

## Interpretation (hypothesis, not confirmed)

From 2023 the ONS SIN balance's `val_gersolar` very likely **includes estimated distributed (MMGD) solar** on top of centralized plants,
and the SIN total generation (the denominator of P) includes it too. I found no ONS statement of this in the sources I read, so it is
unconfirmed; the ONS dataset dictionary of `balanco-energia-subsistema` should be checked.

## Consequences if confirmed (for review; no action taken)

1. **2020 baseline (D1/D15/D16): not affected.** The 2020 implied CF (20.4 %) is consistent with centralized PV only; the 554.35 TWh
   total and 5.23 TWh solar are ONS-SIN, centralized-scope. The D16 statement that the ONS SIN balance sits below the national total
   because MMGD is outside it holds for 2020 but not obviously for 2023+.
2. **Calibration series (Task 9) has a definitional break in 2023** in the solar term and in the total-generation denominator of P(t).
3. **Curtailment-rate denominator (pending decision, section 1.3e of claude_commands.md):** the COFF curtailment numerator covers
   centralized plants only (Tipo I / II-B / II-C), while the ONS balance solar generation from 2023 would include MMGD. That alone
   plausibly explains why our rates fall below ONS's published ones even though the absolute curtailed MWmed match.

   Illustration only (assumes the 2018-2022 median solar CF of 21.3 % applies to centralized PV; mid-year capacity approximated):

   | | Centralized solar est. (TWh) | Rate = curtailed / (wind gen + solar est. + curtailed) | ONS published / cited |
   |---|---|---|---|
   | 2024 | 14.40 GW x 8,784 h x 0.213 = 26.9 | 12.80 / (107.50 + 26.9 + 12.80) = **8.7 %** | 9.3 % (ONS RT DGL 0189/2025) |
   | 2025 | 18.66 GW x 8,760 h x 0.213 = 34.8 | 37.22 / (115.36 + 34.8 + 37.22) = **19.9 %** | ~20.7 % (secondary source) |

   Both land close to the published figures, versus 7.25 % and 15.2 % with the full ONS-balance solar. This strengthens, but does not
   prove, the MMGD hypothesis; the capacity-factor assumption and the secondary-source status of the 2025 figure are the main caveats.

## What could NOT be confirmed

- That ONS includes MMGD in `val_gersolar` from 2023 (and since exactly when): needs the ONS dictionary or an ONS statement.
- The exact ONS definition of "potential generation" in its published rates.
- SIGA survivorship: retired plants are absent, so earlier-year capacities are slightly understated (this would make the early implied
  CFs slightly too high, not too low, and cannot explain the 2023+ jump).
