# PTE scenario curtailment with the two D22 curves (Task 11B)

Date: 2026-10-23. Code: `projection.project_curtailment_two_curves` / `build_pte_curtailment_table`, carried through `mitigation.compute_mitigation`.
Output: `processed/pte_curtailment_two_curves.parquet` (DATABASE_ROOT). Inputs: the D22 curves of `docs/task9_calibration_report.md` (C_wind: L = 1, k = 0.1669, P0 = 35.57, observed P 10.3-29.4 %; C_solar: L = 1, k = 0.0899, P0 = 37.74, observed P 15.1-29.4 %) and the PTE table of `config/scenarios.yaml`, used as published (D16, no rescaling, `source: pte_projection`).

This report only states computed, labelled figures with their uncertainty bounds. It draws no conclusion about whether any scenario succeeds or fails at mitigation.

## Method

- For each scenario (TB, TA, TG) and grid year (2025, 2030, 2040, 2050): P = solar_pct + wind_pct; wind_gen = wind_pct x total generation, solar_gen = solar_pct x total generation (PTE table).
- wind_curtailed = wind_gen x C_wind(P); solar_curtailed = solar_gen x C_solar(P); total = wind + solar (D22 rule). The combined single curve is not used.
- **low / central / high:** central is the fitted curve. low and high are the 2.5 and 97.5 percentiles of each curve's own bootstrap (1000 resamples of that curve's calibration months, bounded refit each time, seed 0) evaluated at the scenario's P. Total low/high are the sum of the wind and solar bounds: a conservative envelope, wider than a joint 95 % interval, since the two bounds are not reached together.
- **The intervals capture sampling uncertainty only, not the uncertainty of the logistic functional form (D21/D22).** Far outside the calibrated range the functional form dominates, so a narrow-looking interval there must not be read as confidence.
- **extrapolated = yes** when P lies outside that curve's observed P range. Both curves end at 29.4 %, so every 2040 and 2050 point is extrapolated for both; 2025 (P = 26) and 2030 (P = 28-29) are inside the observed range.
- Inherited assumption (methodology 2.4, E_curt = generation x C_hat): the PTE generation is treated as the potential generation on which the calibrated rate is defined (curtailed / (generation + curtailed)). The PTE report does not say whether its generation is before or after curtailment.

## Curtailed energy (TWh per year)

| Scenario | Year | P (%) | Wind low / central / high (TWh) | Solar low / central / high (TWh) | **Total low / central / high (TWh)** | Extrapolated wind | Extrapolated solar |
|---|---:|---:|---|---|---|:---:|:---:|
| TB | 2025 | 26 | 16.9 / 19.7 / 22.8 | 22.1 / 25.9 / 28.6 | **39.0 / 45.6 / 51.4** | no | no |
| TB | 2030 | 29 | 22.5 / 30.2 / 36.3 | 35.6 / 46.5 / 52.9 | **58.1 / 76.7 / 89.2** | no | no |
| TB | 2040 | 36 | 33.2 / 82.6 / 107.1 | 53.4 / 91.9 / 113.7 | **86.6 / 174.6 / 220.8** | yes | yes |
| TB | 2050 | 50 | 82.9 / 360.6 / 385.1 | 54.8 / 152.0 / 181.0 | **137.7 / 512.6 / 566.1** | yes | yes |
| TA | 2025 | 26 | 16.9 / 19.7 / 22.7 | 22.0 / 25.9 / 28.6 | **38.9 / 45.5 / 51.3** | no | no |
| TA | 2030 | 29 | 22.1 / 29.7 / 35.6 | 35.0 / 45.7 / 51.9 | **57.1 / 75.3 / 87.5** | no | no |
| TA | 2040 | 44 | 54.1 / 206.2 / 237.4 | 63.4 / 149.3 / 185.7 | **117.4 / 355.5 / 423.1** | yes | yes |
| TA | 2050 | 58 | 122.5 / 567.5 / 579.1 | 65.3 / 207.3 / 231.4 | **187.8 / 774.9 / 810.5** | yes | yes |
| TG | 2025 | 26 | 16.9 / 19.7 / 22.8 | 22.1 / 25.9 / 28.6 | **39.0 / 45.6 / 51.4** | no | no |
| TG | 2030 | 28 | 21.3 / 26.6 / 31.2 | 32.9 / 41.0 / 46.2 | **54.2 / 67.6 / 77.4** | no | no |
| TG | 2040 | 39 | 44.9 / 136.8 / 171.4 | 60.6 / 119.0 / 149.5 | **105.5 / 255.8 / 320.9** | yes | yes |
| TG | 2050 | 47 | 77.9 / 321.7 / 354.9 | 62.1 / 159.8 / 195.1 | **140.0 / 481.6 / 549.9** | yes | yes |

## Underlying rates and generation

| Scenario | Year | P (%) | Generation wind / solar (TWh) | C_wind low / central / high | C_solar low / central / high |
|---|---:|---:|---|---|---|
| TB | 2025 | 26 | 117.0 / 100.3 | 0.144 / 0.168 / 0.195 | 0.220 / 0.258 / 0.286 |
| TB | 2030 | 29 | 120.6 / 148.5 | 0.187 / 0.250 / 0.301 | 0.240 / 0.313 / 0.356 |
| TB | 2040 | 36 | 159.5 / 199.4 | 0.208 / 0.518 / 0.672 | 0.268 / 0.461 / 0.570 |
| TB | 2050 | 50 | 393.0 / 202.5 | 0.211 / 0.918 / 0.980 | 0.271 / 0.751 / 0.894 |
| TA | 2025 | 26 | 116.8 / 100.1 | 0.144 / 0.168 / 0.195 | 0.220 / 0.258 / 0.286 |
| TA | 2030 | 29 | 118.4 / 145.8 | 0.187 / 0.250 / 0.301 | 0.240 / 0.313 / 0.356 |
| TA | 2040 | 44 | 256.7 / 234.4 | 0.211 / 0.803 / 0.925 | 0.270 / 0.637 / 0.792 |
| TA | 2050 | 58 | 581.0 / 240.9 | 0.211 / 0.977 / 0.997 | 0.271 / 0.861 / 0.961 |
| TG | 2025 | 26 | 117.0 / 100.3 | 0.144 / 0.168 / 0.195 | 0.220 / 0.258 / 0.286 |
| TG | 2030 | 28 | 120.8 / 139.3 | 0.176 / 0.220 / 0.258 | 0.236 / 0.294 / 0.331 |
| TG | 2040 | 39 | 213.9 / 225.2 | 0.210 / 0.639 / 0.801 | 0.269 / 0.528 / 0.664 |
| TG | 2050 | 47 | 369.5 / 229.3 | 0.211 / 0.871 / 0.960 | 0.271 / 0.697 / 0.851 |

## Which points are furthest outside the calibrated range

P minus the observed maximum (29.4 %), largest first: **TA 2050** (P = 58, +28.6 pp), TB 2050 (50, +20.6 pp), TG 2050 (47, +17.6 pp), TA 2040 (44, +14.6 pp), TG 2040 (39, +9.6 pp), TB 2040 (36, +6.6 pp). The 2025 and 2030 points (26-29 %) are within the observed range, although 2030 sits at its upper edge.

Observations on the numbers (no verdict implied):
- At the 2050 points the central C_wind is 0.87-0.98 and C_solar 0.70-0.86, i.e. most of the PTE wind generation is curtailed in the central estimate. These values come from the logistic with L at its bound of 1 and P0 beyond the data; they are extrapolation behaviour of the fitted form, not observed curtailment levels (the highest observed monthly C is 0.29 for wind and 0.37 for solar).
- The lower bounds are far below the central values at 2040/2050 (for example TA 2050 total 187.8 vs 774.9 TWh central), because some bootstrap resamples give a flat, low curve. The upper bound is close to the central value there because C is confined to [0, 1] and the central curve is already near 1.

## Mitigation carry-through

`mitigation.compute_mitigation` now also accepts the columns written by `project_curtailment_two_curves` (`E_curt_twh_low/high`, `E_curt_wind_twh[_low|_high]`, `E_curt_solar_twh[_low|_high]`, `extrapolated_wind/solar`) and applies the same average and marginal factors to them, adding the low/high deficits and the wind/solar split to its output (`MitigationRow` gained optional fields only). The single marginal-factor input is passed through unchanged; the OM/CM dual-column split and the choice of factor year for projection years remain Task 13 / section 1.3d. Without the new columns the output is identical to before.
