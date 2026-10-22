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

## Documented limitation: residual gap to ONS (permanent)

The scope-consistent rates remain 0.01 / 0.15 / 0.27 / 0.54 pp below ONS's published values for 2022-2025 (about 3-4 % relative in 2023-2025). The numerators agree with ONS, so the difference sits in the potential-generation denominator, whose ONS definition was not reconstructed. The 2025 ONS figure (~20.7 %) is a secondary-source citation (Ensaio Energetico), not an ONS primary publication, so the 2025 residual cannot be fully attributed. Also recorded in `docs/methodology.md` section 3.7.

## Fit (`processed/calibration_params.json`, `processed/calibration_frame.parquet`) - final, D21 (Task 7C)

Input: 57 complete months 2022-01..2026-09 (27 wind-only, 30 wind+solar), P(s,t) 10.3-29.4 %, C 0-29.7 %. `fit_calibration` now bounds 0 < L <= 1 and k > 0 (P0 free).

| Fit | L | k | P0 | in-sample RMSE |
|---|---:|---:|---:|---:|
| **Final (saved): bounded L, all 57 months** | **1.000 (on the bound)** | 0.1688 | 34.82 | 0.06123 |
| Superseded: unconstrained, all 57 months | 1.254 | 0.1635 | 36.77 | 0.0612 |
| Sensitivity: bounded L, 30 wind+solar months | 1.000 (on the bound) | 0.0765 | 44.45 | 0.06026 |
| Superseded: unconstrained, 30 wind+solar months | 2,235.6 | 0.0652 | 169.3 | 0.0601 |

RMSE with the bound is materially the same as without it (0.06123 vs 0.0612). L is bounded, not fixed, and it ends exactly at 1: the data do not support a plateau below 100 %; they simply do not reach it. In-sample RMSE (6 pp) is large because monthly C is noisy (hydrology, transmission, demand) while the fit uses P only.

### C(P) at the PTE exposure points (bounded fits)

| P (%) | 29.4 (last observed) | 36 | 40 | 44 | 47 | 50 | 58 |
|---|---:|---:|---:|---:|---:|---:|---:|
| All 57 months (final) | 0.286 | 0.550 | 0.706 | 0.825 | 0.887 | 0.928 | 0.980 |
| 30 solar months only | 0.240 | 0.344 | 0.416 | 0.491 | 0.549 | 0.604 | 0.738 |

### Check on the wind-only months (Task 7C, part B)

- With L bounded, the 30 solar-coverage months **do not degenerate**: L = 1, k = 0.0765, P0 = 44.5, RMSE 0.0603. The earlier degenerate result (L = 2,236, P0 = 169) was caused by the missing bound. The expected finding "still degenerates" did **not** occur.
- P span of the 30 solar months: **15.1-29.4 %** (14.3 pp). The 27 wind-only months span 10.3-23.5 %; the full frame spans 10.3-29.4 % (19.1 pp). The solar window therefore lacks the low-P tail (C near 0) and has the same upper end.
- Both fits put P0 beyond the observed maximum, so neither identifies the upper curve. They disagree outside the data: C(50) = 0.93 (all months) vs 0.60 (solar only), and the all-months point estimate lies outside the solar-only 95 % interval for P >= 40 (table below).
- Conclusion: excluding the wind-only months is **not shown to be statistically unsupportable** by degeneracy; it is a materially different model choice that discards 27 of 57 points and the low-P anchor. The all-months fit is kept (D21) with the solar-only fit reported as a sensitivity. Residual limitation: the wind-only months are left-censored for solar curtailment (small, uncorrected, not measured).

### Bootstrap 95 % interval of C(P) (1000 resamples of the frame, bounded refit each time, seed 0; 0 failed refits)

| P (%) | All 57 months: point | lo | hi | width | 30 solar months: point | lo | hi | width |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 29.4 | 0.286 | 0.211 | 0.341 | 0.130 | 0.240 | 0.176 | 0.283 | 0.107 |
| 36 | 0.550 | 0.236 | 0.682 | 0.445 | 0.344 | 0.182 | 0.470 | 0.288 |
| 40 | 0.706 | 0.240 | 0.841 | 0.601 | 0.416 | 0.182 | 0.597 | 0.414 |
| 44 | 0.825 | 0.241 | 0.929 | 0.688 | 0.491 | 0.182 | 0.714 | 0.532 |
| 47 | 0.887 | 0.241 | 0.963 | 0.722 | 0.549 | 0.182 | 0.787 | 0.605 |
| 50 | 0.928 | 0.241 | 0.981 | 0.740 | 0.604 | 0.182 | 0.844 | 0.662 |
| 58 | 0.980 | 0.241 | 0.997 | 0.756 | 0.738 | 0.182 | 0.936 | 0.754 |

Width grows from 0.13 at the last observed P (29.4 %) to 0.45 at 36 % and 0.74-0.76 at 50-58 % (TA 2050 exposure), i.e. about 6x. It saturates beyond ~50 % because C is confined to [0, 1] (the lower bound sits at ~0.24 because some resamples give a flat low curve), not because the extrapolation becomes safe. The interval covers sampling uncertainty only, not the logistic functional form. Stored in `processed/calibration_ci_bootstrap.parquet` (all-months). **Stage 3 must propagate this interval** (section "STAGE 3 REQUIREMENT" of `claude_commands.md`); it is not wired into `projection.py` or `mitigation.py`.

## Extrapolation exposure (read-only diagnostic, PTE table values from config/scenarios.yaml; no fit decision taken)

P = solar_pct + wind_pct (%). Observed calibration range: 10.3-29.4 %.

| Scenario | 2025 | 2030 | 2040 | 2050 | Maximum |
|---|---:|---:|---:|---:|---:|
| TB | 26 | 29 | 36 | 50 | 50 |
| TA | 26 | 29 | 44 | 58 | 58 |
| TG | 26 | 28 | 39 | 47 | 47 |

2025-2030 are inside the observed range; 2040 and 2050 are outside in all three scenarios (tracked as candidate D21 and section 1.3g of `claude_commands.md`).

## Tests

`pytest -v -m "not integration"`: 210 before, **231 passed** after Task 9 and **236 passed** after Task 7C (bounded fit and bootstrap tests) (9 deselected integration tests, including the new live ones for the baseline values and for the real-data calibration). New or updated: `tests/test_ons_generation.py` (D20 basis, hour/month mismatch failures, missing config, baseline independence), `tests/test_calibration_d20.py` (frame, rates in closed form, balance-basis refusal, end-to-end fit), `tests/test_ons_solar_gap.py` (matched energy, loader, builder).

## Notes

- `data_ingestion.run_stage1` still does not call `acquire_ons_generation` (Task 8 orchestrates it); nothing was changed there.
- The `implemented_in` field of D20 keeps the pasted text ("to be implemented in Task 9"); it can be updated to point at the commit.
- `interim/ons_curtailment_raw.parquet` (15.8 M rows) was rebuilt in the real DATABASE_ROOT for this run, since `interim/` and `processed/` were empty.
