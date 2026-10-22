# Task 9 - Calibration wired to the D20 solar basis (report)

Date: 2026-10-23. Decision: D20 (adopted), `config/discovered_sources.yaml`. Code: `ons_generation.py` (P(t) tables), `ons_solar_gap.py` (dispatched series), `calibration.py` (`build_calibration_frame`, `annual_rates`, `run_calibration`).
Not touched: `projection.py`, PTE/BLUES years (D16, unrescaled), `pld.py`, the OM/CM split (Task 13), the MCTI future-year question (section 1.3d), `docs/roadmap.md`, the 2020 baseline.

## What changed in the data path

| Place | Before | After (D20) |
|---|---|---|
| Solar term of P(t), months >= 2021-01 | `val_gersolar` (balance) | ONS-dispatched solar (sum of the per-plant capacity-factor files), matched hour by hour with the balance |
| Solar part of the total-generation denominator of P(t) | `val_gersolar` | dispatched solar |
| Solar potential-generation denominator of the curtailment rate | n/a (SIN balance solar was used in the earlier sanity check) | dispatched solar + curtailed solar |
| Wind | `val_gereolica` | unchanged |
| 2020 baseline | 554.35 TWh total / 54.30 wind / 5.23 solar / 10.74 % | unchanged: identical to the digit (5.229512, 54.296531, 554.352463, 10.737942), checked before and after the rewrite |
| Raw `val_gersolar` | used | kept only as `solar_gen_ons_balance_raw_mwh` in the penetration tables (diagnostic); `build_calibration_frame` does not carry it and refuses any month whose `solar_basis` is not `dispatched` |

`config/acquisition_targets.yaml: ons.packages.generation_by_source.solar_basis.dispatched_from = "2021-01"` is required; without it `acquire_ons_generation` raises. Months of the window missing from the dispatched series, or with a different number of hours or a different balance energy than `val_gersolar`, raise `GenerationDiscoveryError` naming the months; there is no fallback to `val_gersolar`. Real data: no month missing (2021-01..2026-10; the partial 2026-10 has the same 480 hours in both series).

Annual P (wind + solar share of SIN generation, %), before and after:

| Year | P with raw `val_gersolar` | P with dispatched solar (D20) | Solar TWh raw | Solar TWh dispatched | Basis |
|---|---:|---:|---:|---:|---|
| 2020 | 10.74 | 10.74 | 5.23 | 5.23 | balance (baseline, untouched) |
| 2021 | 13.42 | 13.31 | 7.43 | 6.68 | dispatched |
| 2022 | 15.36 | 15.22 | 12.09 | 11.08 | dispatched |
| 2023 | 21.20 | 18.22 | 43.01 | 19.20 | dispatched |
| 2024 | 26.02 | 20.80 | 73.34 | 27.55 | dispatched |
| 2025 | 29.58 | 23.01 | 91.83 | 32.01 | dispatched |
| 2026 (to Oct 21) | 29.48 | 22.24 | 82.74 | 29.88 | dispatched |

The correction removes the artificial jump in P in 2023-2025 (21 -> 26 -> 29.6 %) that came from adding MMGD to the numerator.

## Recomputed curtailment rates (complete years, wind COFF from 2022-01, solar COFF from 2024-04)

Rate definitions: *combined (earlier convention)* = (curtailed wind + solar) / (wind generation + solar generation + curtailed), with solar in the denominator for the whole year even before solar curtailment is published; *scope-consistent* = solar enters numerator and denominator only in months where solar curtailment exists (2024-04 onward). Wind generation is the balance `val_gereolica` in both.

| Year | Previous (raw `val_gersolar`) | **New combined, D20 solar** | New scope-consistent | ONS published | Remaining gap (new combined vs ONS) | Remaining gap (scope-consistent vs ONS) |
|---|---:|---:|---:|---:|---:|---:|
| 2022 | 0.43 % | **0.43 %** | 0.49 % | 0.5 % | -0.07 pp | -0.01 pp |
| 2023 | 2.40 % | **2.89 %** | 3.45 % | 3.6 % | -0.71 pp | -0.15 pp |
| 2024 | 6.61 % | **8.66 %** | 9.03 % | 9.3 % | -0.64 pp | -0.27 pp |
| 2025 | 15.23 % | **20.16 %** | 20.16 % | ~20.7 % (secondary source) | -0.54 pp | -0.54 pp |

Components (new): wind rate 0.49 / 3.45 / 8.16 / 18.52 % for 2022-2025; solar rate (Apr-Dec 2024, 2025) 13.15 / 25.57 %. 2026 is not in the table: 9 complete months, wind 20.08 %, solar 25.91 %, combined 21.69 %.

Reading:
- **The earlier gap to ONS is largely closed but not exactly.** 2022 matches within 0.07 pp. For 2023-2025 the new rates are below ONS's by 0.15-0.71 pp (scope-consistent: 0.15, 0.27, 0.54 pp), a relative residual of 3-4 % on the scope-consistent basis (about 20 % on the combined basis in 2023). Not claimed as a match.
- Using the *combined* convention in 2022-2023 puts dispatched solar in the denominator while no solar curtailment is published, which is why those two years sit further from ONS (whose 2022 and 2023 figures are wind-only in practice, section 2.1 of the sanity check). The scope-consistent column is the fairer comparison for 2022-2024.
- The remaining 2025 gap (-0.54 pp) is against a figure from a secondary source whose exact denominator is unknown, so it cannot be attributed.
- The 2024 ONS value (9.3 %) is still 0.27 pp above the scope-consistent rate; ONS's own definition of potential generation (plant set, interval) remains unreconstructed.

## Fit (`processed/calibration_params.json`, `processed/calibration_frame.parquet`)

Input: 57 complete months 2022-01..2026-09 (27 wind-only, 30 wind+solar), P(s,t) from 10.3 % to 29.4 %, C from 0 to 29.7 %.

| Fit | L | k | P0 | in-sample RMSE |
|---|---:|---:|---:|---:|
| Primary (saved), unconstrained, all 57 months | 1.254 | 0.1635 | 36.77 | 0.0612 |
| Sensitivity, 30 wind+solar months only (not saved) | 2,235.6 | 0.0652 | 169.3 | 0.0601 |
| Diagnostic only, `L <= 1` bound, all 57 months | 1.000 | 0.1688 | 34.82 | 0.0612 |
| Diagnostic only, `L <= 1` bound, 30 wind+solar months | 1.000 | 0.0765 | 44.45 | 0.0603 |

**The logistic is not well identified by the observed range.** All the data sit below P = 29.4 %, but P0 is 35-44 % (and 169 % in the unbounded sensitivity). The saved primary fit has L = 1.25, i.e. a curtailment fraction above 100 % at high P (C(60 %) = 1.226), which is unphysical; with `L <= 1` the in-sample fit is the same (RMSE 0.0612) but C(30 %) = 0.31, C(40 %) = 0.71, C(60 %) = 0.99, while the wind+solar-only bounded fit gives 0.25 / 0.42 / 0.77: the extrapolation to PTE penetrations is very sensitive to this choice. I did not change `fit_calibration` (no bounds, as before); whether to bound L at 1 (and how to treat the mixed wind-only / wind+solar scope) is a methodological decision for you, since it drives Stage 3.

In-sample RMSE (6 pp) is large because monthly C is noisy (it depends on hydrology, transmission and demand as well as P); the fit uses P only, as designed.

## Tests

`pytest -v -m "not integration"`: 210 before, **231 passed** after (9 deselected integration tests, including the new live ones for the baseline values and for the real-data calibration). New or updated: `tests/test_ons_generation.py` (D20 basis, hour/month mismatch failures, missing config, baseline independence), `tests/test_calibration_d20.py` (frame, rates in closed form, balance-basis refusal, end-to-end fit), `tests/test_ons_solar_gap.py` (matched energy, loader, builder).

## Notes

- `data_ingestion.run_stage1` still does not call `acquire_ons_generation` (Task 8 orchestrates it); nothing was changed there.
- The `implemented_in` field of D20 keeps the pasted text ("to be implemented in Task 9"); it can be updated to point at the commit.
- `interim/ons_curtailment_raw.parquet` (15.8 M rows) was rebuilt in the real DATABASE_ROOT for this run, since `interim/` and `processed/` were empty.
