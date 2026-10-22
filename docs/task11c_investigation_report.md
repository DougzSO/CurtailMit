# Task 11C - Pre-Task 13 investigation: PTE generation basis, international benchmarks, regional/mechanism diagnostic

Status: **investigation only.** No pipeline module (`calibration.py`, `projection.py`, `mitigation.py`, `results_writer.py`), no fit, no combination rule, no year grid and no locked decision (D13-D22) was changed. Two candidate decisions are logged as `pending` (D23, D24) in `config/discovered_sources.yaml`; nothing is adopted. Date: 2026-10-23.
Throwaway code: `analysis/task11c_diagnostics.py` (outside `src/`, not installed, no tests). Tables: `DATABASE_ROOT/outputs/tables/task11c_*.csv`; figures: `DATABASE_ROOT/outputs/figures/task11c_regional_diagnostics.png`, `task11c_class_share.png`.

Why this was run: the Task 11B central estimates at 2040/2050 are C_wind 0.87-0.98 and C_solar 0.70-0.86, against a highest observed monthly rate of 0.29 (wind) and 0.37 (solar).

---

## Section (a) - Is the PTE/BLUES generation gross (potential) or net (as dispatched)?

Note: `docs/pte_ons_basis_investigation.md` answered a different question (ONS-SIN vs national geographic/scope basis). It does **not** resolve this gross/net timing question and is not used as if it did.

### What was searched

The CEBRI PTE Phase 2 technical report (121 pp., re-downloaded from the CEBRI URL cited in `pte_ons_basis_investigation.md`, text extracted locally) was searched for: potencial, bruta, antes de cortes, líquida, realizada, despachada, curtailment, corte(s) de geração, vertimento, restrição de geração, capacidade instalada, fator de capacidade, NEWAVE, MMGD. No supplementary EPE/BLUES methodology notes exist in DATABASE_ROOT (`raw/pte_epe/` is empty). The IAMC documentation page for BLUES (https://www.iamcdocumentation.eu/Model_Documentation_-_BLUES) could not be fetched (HTTP 502), so BLUES internals beyond the web-search summary are **not verified**.

### What was found

1. **The report never describes the generation it publishes as gross or net.** The words "bruta", "líquida", "despachada", "realizada" occur only for emissions, jobs and similar. "Potencial" appears only in generic senses (renewable potential of the country, hydro potential reduced by climate change). Nothing distinguishes potential from delivered electricity.
2. **Curtailment is not modeled; it appears only as a policy risk.** PDF p. 62 ("Aprimorar a gestão e a alocação de riscos sistêmicos (curtailment, congestionamentos...)") and p. 64 ("...expansão das redes (T&D) são essenciais para... reduzir o curtailment"). This agrees with `docs/roadmap.md` line 21 ("PTE does not model curtailment ... qualitative policy risk, p.60-62").
3. **The NEWAVE adjustment step feeds energy quantities, not capacities with a resource profile**: "Oferta Renovável: MMGD, Biomassa, Eólica e Solar foram consideradas as quantidades de energia definidas no cenário" (PDF p. 110, printed 109), with BLUES output on five-year cuts and linear interpolation in between. NEWAVE takes these as given energy blocks; it does not curtail them.
4. **BLUES** (web search summary, not the model documentation): perfect-foresight, least-cost optimization on the MESSAGE platform; a COPPE/UFRJ presentation lists a load curve with 12 months x 24 time slices. Whether the electricity module spills wind/solar below availability could **not** be determined. The technical report states the model database is calibrated for 2015.
5. **No installed-capacity (GW) figures for wind or solar** are given in the report text (the only GW figures are nuclear), so the requested check "implied PTE capacity factor = generation / capacity / 8760 h" **cannot be computed from PTE data**.

### Substitute internal-consistency checks (computed from our data, indicative only)

Because the PTE capacity is unavailable, the 2025 PTE value was compared with ONS observed 2025 data (ONS SIN scope vs PTE scope is itself unreconciled, D16):

| 2025 | PTE (TB, TWh) | ONS realized | ONS potential (realized + curtailed) | PTE vs realized | PTE vs potential |
|---|---:|---:|---:|---:|---:|
| Wind | 117.0 | 115.4 | 141.6 | +1.5 % | -17.3 % |
| Solar (balance, includes MMGD) | 100.3 | 91.8 | 102.8 (91.8 + 11.0 centralized curtailed) | +9.2 % | -2.4 % |

- Wind sits on the **realized (net)** value; solar sits closer to the **potential (gross)** value. The two technologies point in opposite directions, so this is not decisive. The solar comparison also rests on the MMGD inclusion (D20) and on a solar curtailment that covers centralized plants only.
- Implied installed capacity at the observed 2025 realized capacity factors of dispatched plants (wind 0.382, solar 0.205): PTE 2025 wind 117 TWh -> **35.0 GW**, which is close to the ANEEL SIGA centralized wind capacity of **34.75 GW** in 2025 (D19 side data); solar 100 TWh -> 56 GW (centralized 20.1 GW plus MMGD; not checked). For 2050 the same arithmetic gives wind 110-174 GW and solar 113-134 GW. This is an illustration of scale, **not** a check of the PTE, because the PTE publishes no capacity.

### Sensitivity of the formula at the current 11B central estimates (illustrative, not a pipeline change)

`E_curt = generation x C` (gross) vs `E_curt = generation x C / (1 - C)` (net), using the 11B central C:

| Scenario | Year | Tech | P (%) | PTE generation (TWh) | C central | E_curt gross (TWh) | E_curt net (TWh) | Implied potential if net (TWh) | Net / gross |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| TB | 2040 | wind | 36 | 159.5 | 0.518 | 82.6 | 171 | 331 | 2.1x |
| TB | 2040 | solar | 36 | 199.4 | 0.461 | 91.9 | 171 | 370 | 1.9x |
| TB | 2050 | wind | 50 | 393.0 | 0.918 | 360.6 | 4,372 | 4,765 | 12.1x |
| TB | 2050 | solar | 50 | 202.5 | 0.751 | 152.0 | 610 | 812 | 4.0x |
| TA | 2040 | wind | 44 | 256.7 | 0.803 | 206.2 | 1,049 | 1,305 | 5.1x |
| TA | 2040 | solar | 44 | 234.4 | 0.637 | 149.3 | 412 | 646 | 2.8x |
| TA | 2050 | wind | 58 | 581.0 | 0.977 | 567.5 | 24,561 | 25,142 | 43.3x |
| TA | 2050 | solar | 58 | 240.9 | 0.861 | 207.3 | 1,489 | 1,730 | 7.2x |
| TG | 2040 | wind | 39 | 213.9 | 0.639 | 136.8 | 379 | 593 | 2.8x |
| TG | 2040 | solar | 39 | 225.2 | 0.528 | 119.0 | 252 | 478 | 2.1x |
| TG | 2050 | wind | 47 | 369.5 | 0.871 | 321.7 | 2,491 | 2,860 | 7.7x |
| TG | 2050 | solar | 47 | 229.3 | 0.697 | 159.8 | 527 | 757 | 3.3x |

The choice changes the answer by 1.9x (TB 2040) to 43x (TA 2050 wind). Under the net reading the implied wind potential of TA 2050 (25,142 TWh) would be 18 times the PTE's **total** 2050 generation (1,417 TWh): the net formula is numerically unusable with the current extrapolated C, so the combination of "net basis + current C" is internally impossible, not merely large.

### Finding (a)

The PTE sources are **silent**. The evidence gathered is weak and mixed: (i) neither the PTE nor NEWAVE represents curtailment, which suggests the published generation is the energy the model needs to deliver (a *delivered/net-like* quantity, with no spillage accounted for); (ii) the 2025 wind figure and the implied 35 GW match the realized side, while the 2025 solar figure matches the potential side. No statement in the sources settles it.

Working assumption options (none adopted):
- **Gross** (as in 11B): formula `generation x C`. Bounded results, but the PTE generation would then have to be potential generation, which nothing supports specifically.
- **Net/delivered**: formula `generation x C/(1-C)`, or equivalently a calibration rate defined on realized generation (curtailed / realized, the convention behind ONS-related press figures such as ~18 % for 2025) so that the PTE generation is the right base without a division. Which of these is right depends on a definition the sources do not give.

The most defensible reading on current evidence is that the PTE generation is **closer to a delivered (net-like) quantity than to a potential one**, with low confidence, because a model that does not represent curtailment reports what it dispatches. This is a reading, not a finding.

### Implication for methodology

The 11B formula (`generation x C`, methodology 2.4) contains an unverified basis assumption that can move the 2040/2050 numbers by a factor of 2 to more than 40 and cannot be settled from the documents in hand. Two paths exist (user decision): ask the PTE/CEBRI authors what Gráfico 13 represents, or redefine the calibrated rate on realized generation (a calibration change, out of scope here). Either way, the current C extrapolation is the larger problem: even the gross formula yields 90-98 % of PTE wind curtailed. Logged as candidate **D23** (pending).

---

## Section (b) - International high-penetration curtailment benchmarks (qualitative plausibility check only)

This section is **not** used to recalibrate, blend into or modify C_wind(P) / C_solar(P). Definitions differ across systems (dispatch-down vs curtailment vs economic offloading; share of generation vs share of demand). Figures are those found in the cited primary reports; where a primary figure was not retrieved it is marked.

| System | Period | Wind + solar share (P) | Reported curtailment | Source |
|---|---|---|---|---|
| Ireland + Northern Ireland (all-island) | 2024 | 35.0 % of **demand** (wind 33.0 %, solar 2.0 %) | Wind dispatch-down **14.0 %** of available wind (9.3 % constraints + 4.7 % curtailment); solar 7.1 %; all renewables 12.1 %. Northern Ireland wind 29.6 %, Ireland wind 10.1 %. Wind 2023: 10.7 % | EirGrid / SONI, *Annual Renewable Energy Constraint and Curtailment Report 2024* (https://www.eirgrid.ie/sites/default/files/publications/Annual-Renewable-Constraint-and-Curtailment-Report-2024-V1.0.pdf; the file's running header still reads "2022 / May 2023", the data are 2024) |
| South Australia (state, inside the NEM) | FY 2024-25 | wind 44.5 % + rooftop PV 22.4 % + larger solar 10.1 % = **~77 %** of generation | Wind curtailment + economic offloading **11 %** of availability (7 % in FY 2023-24); grid-scale solar economic offloading **32 %** (22 % in FY 2023-24), solar curtailment < 1 MW average | AEMO, *South Australian Electricity Report 2025* (https://www.aemo.com.au/-/media/files/electricity/nem/planning_and_forecasting/sa_advisory/2025/2025-south-australian-electricity-report.pdf) |
| Denmark | 2023 | wind 54 %; wind + solar **64 %** of consumption | "In previous years up to 1,000 GWh of Danish wind production was curtailed due to bottlenecks in the German grid"; after a new countertrade model, curtailment estimated at **0-10 GWh in H2 2023**. 1,000 GWh is about 5 % of 2023 wind output of ~19.4 TWh (my arithmetic; the 19.4 TWh figure is from a World Nuclear Association table seen through a search summary). No annual curtailment-rate series found | IEA Wind TCP, *Denmark 2023* (https://iea-wind.org/wp-content/uploads/2024/11/Denmark_2023.pdf) |
| California ISO | 2024 | **not retrieved** (capacity: wind 8.1 GW + solar 19.0 GW, April 2024; solar supplies nearly half of CAISO electricity 08:00-16:00) | **3.4 TWh** of utility-scale wind + solar curtailed (+29 % vs 2023, about 2.6 TWh derived), 93 % solar; April 2024 alone 839,582 MWh. Rate as % of potential generation **not retrieved** | U.S. EIA *Today in Energy* (https://www.eia.gov/todayinenergy/detail.php?id=65364); CAISO *Key Statistics* April 2024 |

Brazil, for comparison (this project, ONS): 2025 wind + solar P = 23.0 % (D20 basis); curtailment 20.2 % of potential (wind 18.5 %, solar 25.6 %); highest monthly C: wind 0.29, solar 0.37 (calibration frame).

### Structural differences limiting transferability

- **Hydro reservoirs:** Brazil's SIN has large dispatchable hydro storage that can absorb or defer energy (and is also a source of must-run/energy-balance constraints); Ireland, Denmark and SA have little or none (Denmark leans on Nordic hydro through interconnectors).
- **Interconnection:** Denmark reaches 64 % wind + solar with near-zero curtailment largely because of strong interconnection to Norway/Sweden/Germany; South Australia exports to Victoria; Ireland is weakly interconnected (and has a system non-synchronous penetration cap of 75 %). Brazil's SIN is large and meshed but its wind/solar are concentrated in the Northeast, far from the load centers.
- **Thermal mix and must-run:** gas dominates SA and Ireland; Brazil's thermal share is small but includes must-run units.
- **Market and dispatch rules:** SA's "economic offloading" is price-driven (negative prices), unlike ONS COFF restrictions, which are operator-imposed; Irish dispatch-down splits constraints and curtailment; CAISO curtailment is mostly oversupply in spring midday.
- **Metrics differ** (share of demand vs generation; dispatch-down vs curtailment vs offloading), so P and rates are only loosely comparable.

### Finding (b)

Brazil's projected 2040/2050 central estimates (C_wind 0.87-0.98, C_solar 0.70-0.86, i.e. 70-98 % of the technology's potential curtailed) are **far outside the envelope of everything retrieved**: the highest annual figures found are Northern Ireland wind 29.6 % (2024), SA grid-scale solar economic offloading 32 % (FY 2024-25), Ireland all-island wind 14.0 %, SA wind 11 %, and Danish wind near 0-5 %. The international envelope **does** reach the PTE penetration range of 44-58 % (SA ~77 % of generation, Denmark 64 % of consumption), so the penetration levels themselves are not unprecedented; the curtailment rates attached to them at those levels are an order of magnitude lower than the Brazilian extrapolation. Caveat: SA and Denmark are strongly interconnected and have different dispatch rules, so this is a plausibility check only, and an extreme Brazilian case (a concentrated Northeast without new transmission) cannot be excluded by it.

### Implication for methodology

The extrapolated central values look implausible as a *prediction*, and the logistic with L bounded at 1 and P0 beyond the data is the likely source. This does not by itself say which correction is right; it says the 2040/2050 point estimates should not be presented without the uncertainty and the caveat already required by D21/D22, and that structural factors absent from P (interconnection, storage, flexibility) matter at these levels. No recalibration is made here.

---

## Section (c) - Regional / mechanism diagnostic (subsystem concentration, DEB / REB / EUB)

Descriptive only; **no curve is fit**. Data: the raw ONS COFF files (the `id_subsistema`, `id_estado`, `cod_razaorestricao`, `cod_origemrestricao` fields that the pipeline's parsed series drops), the balance by subsystem, and dispatched solar by subsystem (capacity-factor files, D20), over the same 57 complete months as the calibration (2022-01..2026-09; solar from 2024-04). Reason codes per the ONS data dictionary: **REL** = external (electrical) unavailability; **CNF** = reliability requirements; **ENE** = energy reason; **PAR** = access-opinion restriction. Origin: **LOC** = local, **SIS** = systemic. The project's classification maps ENE -> DEB, CNF -> REB, REL -> EUB (D17), so **DEB is the energy-balance reason**, and the network-availability reason is EUB.

### c.1 Subsystem concentration

Curtailed energy (TWh) and share by subsystem:

| Year | Tech | N | NE | S | SE | NE share of curtailment | NE share of that technology's generation |
|---|---|---:|---:|---:|---:|---:|---:|
| 2022 | wind | 0.00 | 0.39 | 0.01 | 0.00 | 98.4 % | 90.4 % |
| 2023 | wind | 0.01 | 3.36 | 0.04 | 0.00 | 98.5 % | 91.9 % |
| 2024 | wind | 0.04 | 9.41 | 0.09 | 0.00 | 98.6 % | 92.3 % |
| 2024 | solar (Apr-Dec) | 0.00 | 2.33 | 0.00 | 0.93 | 71.5 % | 56.0 % |
| 2025 | wind | 0.19 | 25.70 | 0.30 | 0.02 | 98.0 % | 92.6 % |
| 2025 | solar | 0.00 | 5.68 | 0.00 | 5.32 | 51.6 % | 53.5 % |
| 2026 (Jan-Sep) | wind | 0.17 | 18.62 | 0.81 | 0.06 | 94.7 % | 92.8 % |
| 2026 (Jan-Sep) | solar | 0.00 | 5.32 | 0.00 | 4.35 | 55.0 % | 53.6 % |

Curtailment rate = curtailed / (generation + curtailed), by subsystem, 2025: wind NE 19.4 %, N 9.5 %, S 4.7 %, SE 3.4 %; solar NE 24.9 %, SE 26.3 %. 2026: wind S rises to 16.9 %.

- **Wind curtailment is concentrated in the Northeast (94.7-98.6 %), but so is wind generation (90-93 %)**: the concentration is only slightly stronger than the generation share. The Northeast rate (19.4 % in 2025) is 4x the South's.
- **Solar curtailment is split almost evenly between the Northeast and the Southeast** (Minas Gerais alone is 9.6 TWh, third state after RN 28.6 and BA 22.9 TWh over the period), in proportion to each subsystem's solar generation. The two rates are equal (24.9 vs 26.3 % in 2025), although the Southeast is the load center.
- **Local penetration is a poor explanation of where curtailment occurs.** The Southeast has a local P of only 4-7 % and a solar curtailment rate of 24-26 %; the South has a local P of 3-13 % and a monthly wind rate up to 55 %. Conversely, the Northeast operates at a local P of **49-84 %** (wind + dispatched solar over NE generation) with annual rates of 9-19 % and a monthly maximum of 31 %. The Northeast therefore already spends its time at local penetrations at or above the PTE national 2050 values, with observed curtailment far below the extrapolated 0.9+ (the Northeast exports to other subsystems, so local P overstates its effective exposure).

Origin: over the window 75 % of wind and 91 % of solar curtailment is **systemic (SIS)**; the local-origin (LOC) share falls from 42 % (2022) to 16-18 % (2025-2026).

### c.2 DEB / REB / EUB against national P

Energy by class (TWh) and share of curtailed energy:

| Year | DEB | REB | EUB | DEB share | REB share | EUB share |
|---|---:|---:|---:|---:|---:|---:|
| 2022 | 0.03 | 0.13 | 0.24 | 8.5 % | 32.3 % | 59.2 % |
| 2023 | 0.92 | 1.84 | 0.65 | 26.9 % | 54.1 % | 19.0 % |
| 2024 | 4.37 | 7.21 | 1.22 | 34.1 % | 56.3 % | 9.5 % |
| 2025 | 19.98 | 12.39 | 4.85 | 53.7 % | 33.3 % | 13.0 % |
| 2026 (to Sep) | 20.24 | 5.80 | 3.30 | 69.0 % | 19.8 % | 11.2 % |

Monthly class rate (% of potential wind + solar generation) against national P (57 months; indicative statistics, not a model):

| Class | Spearman vs P | Pearson vs P | Linear slope (pp per 1 pp P) | Mean rate below / above median P (pp) |
|---|---:|---:|---:|---|
| DEB (energy reason) | 0.72 | 0.63 | 0.75 | 2.2 / 7.9 |
| REB (reliability) | 0.74 | 0.71 | 0.50 | 1.1 / 5.1 |
| EUB (external unavailability) | 0.54 | 0.10 | 0.05 | 1.3 / 1.3 |
| Total | 0.73 | 0.72 | 1.29 | |

- **DEB is growing fastest with P** and its share rose from 8.5 % to 69 %; all DEB energy is systemic (100 % SIS). REB grows with P too (slope 0.50) but its share peaked in 2024 (56 %) and fell to 20 %. **EUB, the network-availability reason, is flat against P** (slope 0.05, Pearson 0.10) and its share fell from 59 % to 11 %.
- Time is a strong confounder: the monthly rate correlates more with calendar time (Spearman 0.91) than with P (0.73), because P itself trends up (Spearman with time 0.64). The partial Spearman of C on P controlling for time is **0.45** over the 57 months and **0.63** over the last 30 months (where P no longer trends, Spearman with time 0.15), so P keeps a genuine, though not dominant, association.

### c.3 Does subsystem P explain subsystem curtailment better than national P? (monthly, indicative)

| Subsystem | n | Mean rate (%) | Max (%) | Local P range (%) | Spearman rate vs **local** P | Spearman rate vs **national** P |
|---|---:|---:|---:|---|---:|---:|
| N | 57 | 5.2 | 32.6 | 0-6 | 0.05 | 0.62 |
| NE | 57 | 9.6 | 31.0 | 49-84 | 0.71 | 0.72 |
| S | 57 | 3.7 | 55.1 | 3-13 | -0.05 | 0.72 |
| SE | 30 | 19.8 | 34.9 | 4-7 | 0.58 | 0.48 |
| All (pooled) | 201 | 8.2 | 55.1 | 0-84 | 0.17 | 0.62 |

Linear R^2 of the subsystem rate on local P vs national P: Northeast 0.39 vs 0.52; pooled 0.01 vs 0.27. **Local penetration is not a better predictor than national P**; where it works (NE, SE) it does about as well as national P, and where local P is low (N, S) it explains nothing while national P still correlates (all of them share the same upward trend and the national P is a proxy for system conditions).

Figure: `task11c_regional_diagnostics.png` (rate vs national P, rate vs subsystem P, class rates vs P); `task11c_class_share.png` (class share by year).

### Finding (c)

1. Wind curtailment is geographically concentrated (~95-98 % Northeast) but in line with where wind sits; solar curtailment is spread over NE and SE. Curtailment occurs in subsystems with very low local penetration (SE solar, S wind).
2. The component that grows fastest and now dominates is the **energy-reason (DEB, systemic) class**; the network-availability reason (EUB) is flat with P and shrinking in share, and local-origin restrictions fall to 16-18 %. The data therefore **do not support a simple transmission-bottleneck story** as the main driver of the recent growth: the growing part is a system-level energy-balance restriction, a national (not local) phenomenon, although it depends on more than P (load level and shape, hydro, must-run thermal, interchange, MMGD).
3. National P is a **moderately informative correlate** (partial Spearman 0.45-0.63 after removing the time trend) and a better single predictor than subsystem P, but it is confounded with the time trend of capacity growth, and the one region that already operates at "2050-like" local penetration (Northeast, 49-84 %) shows rates far below the national-P extrapolation.

Does this support or undermine the hypothesis that national aggregate P is a structurally adequate explanatory variable for 2040/2050 extrapolation? **It undermines it, moderately, on structural grounds, without supporting the specific transmission-bottleneck alternative.** Supporting P: DEB and REB rise with P and the dominant mechanism is systemic. Undermining P as a structural driver: (i) the rate is more tightly tied to time than to P and the partial association falls to 0.45 when time is removed; (ii) curtailment appears at very low local P and not (or little) at very high local P (Northeast), so local penetration is not the mechanism; (iii) the dominant DEB component is an energy-balance outcome that depends on demand, hydro and flexibility, which the PTE scenarios change (storage, demand response, transmission, electrification, hydrogen) but P does not capture. A transmission expansion would affect mainly the REL/CNF part (EUB + REB), which is 31 % of 2026 curtailment and 46-92 % in 2022-2025, and would not remove the DEB component. The evidence is descriptive and in-sample (57 monthly points, one regime), so it cannot demonstrate causality either way.

### Implication for methodology

National P remains usable as a descriptive, short-range driver inside the calibrated range, but there is no structural support for carrying the fitted C(P) to P = 44-58 % without scenario-specific structural information. A mechanism-aware model (separating the energy-balance component, which depends on supply-demand balance, from the network components, which depend on transmission) would be more defensible, but building it needs data not yet acquired (for example transmission-expansion assumptions); **that is not started here**. Logged as candidate **D24** (pending).

---

## Candidate decisions (pending, not adopted)

- **D23** - Gross vs net basis of the PTE generation and the formula for E_curt (section (a)).
- **D24** - Adequacy of national P as the sole driver for 2040/2050 and the regional/mechanism hypothesis (sections (b), (c)).

## Stop point

No Task 13 draft, no curve fitting, no methodology change and no Task 11D data-acquisition task were started. Findings are reported for review and an explicit decision on next steps.
