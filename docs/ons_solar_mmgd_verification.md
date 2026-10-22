# Does ONS `val_gersolar` include distributed generation (MMGD)? Verification (Task 6B)

Status: **verification only; nothing in the pipeline, D16 or roadmap.md was changed.** Date: 2026-10-22.
Follows `docs/ons_solar_mmgd_capacity_crosscheck.md` (ONS solar implies a capacity factor of ~21 % until 2022 and 52-58 % from 2023).
Code: `src/curtailmit/ons_mmgd_probe.py` (reuses `ons_classification.fetch_data_dictionary`, `CkanClient`, `fetch_and_cache`).

## Answer for the MMGD question

**"Dictionary silent."** The data dictionary and the package notes of `balanco-energia-subsistema` say nothing about MMGD, distributed
generation, estimation, or "centralized". They neither state that `val_gersolar` includes MMGD nor that it is centralized-only.

However, two independent ONS sources point strongly (not conclusively) the same way, and one acquired dataset can resolve it empirically
(section 3). Because the balance dictionary is silent, **no candidate decision D20 was logged** (per the task's rule). A proposed D20 text
is at the end for your decision, not recorded in `discovered_sources.yaml`.

## (a) CONFIRMED (verbatim, with source)

**1. Balance dictionary** (`balanco-energia-subsistema`, JSON dictionary
<https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/balanco_energia_subsistema_ho/DicionarioDados_Balanco_Energia_Subsistema.json>;
retrieval manifest written by `fetch_and_cache` next to `raw/ons/generation_by_source/data_dictionary.json`). The published file carries U+FFFD
replacement characters where accents belong; accents restored here:

| Field | Definition (verbatim) |
|---|---|
| `val_gersolar` | "Valor verificado de geração fotovoltaica, em MWmed" |
| `val_gereolica` | "Valor verificado de geração eólica, em MWmed" |
| `val_geracaonaorealizadaapurada` | not a field of this package (it belongs to the COFF packages) |
| package notes | "Informações da carga e oferta de energia verificados em periodicidade horária por subsistema. A oferta é representada pelos valores de geração das usinas hidráulicas, térmicas, eólicas e fotovoltaicas, em MWmed." |

Keyword scan (`mmgd`, `geração distribuída`, `estimad`, `centralizad`, `usina`): only the word "usina(s)" matches (the `id_subsistema`
definition "Código do Subsistema da Usina" and the package note above). No hit for MMGD, distributed generation, estimated, or centralized.
The PDF version of the dictionary (read manually) is dated "Data: 02-05-2023" and repeats the same description; it is silent as well.

**2. Sibling dataset `carga-energia` (Carga de Energia Diária) states MMGD inclusion for the LOAD series, verbatim package notes:**
"Até fevereiro/2021, os dados representam a carga atendida por usinas despachadas e/ou programadas pelo ONS ... Entre março/2021 e abril/23 ...
mais a previsão de geração de usinas não despachadas pelo ONS. **A partir de 29/04/2023**, além dos dados anteriormente considerados, **passou a ser
incorporado o valor estimado da micro e minigeração distribuída (MMGD)**, com base em dados meteorológicos previstos." (`carga-energia`, via
`check_package_dictionary`; `states_mmgd_included = True`.) This is about load, not about `val_gersolar`.

**3. ONS technical report RT ONS DGL 0189/2025, section 4.3 (p. 16):** "Em 2024, a geração estimada de geração proveniente de MMGD alcançou um valor
máximo de 23.741 MWmed, em dados semi-horários, e acumulou 45.752 GWh de energia gerada" (about 5.2 GWmed on average).

**4. Dates in the data (computed from our Task 3 series, hourly SIN, and the ONS plant-level capacity-factor files):**
the balance solar series steps up from one day to the next on **2023-04-29**, the same date as the `carga-energia` note, while the dispatched
(centralized) solar series has no step:

| Day (SIN, MWmed) | Dispatched solar (capacity-factor file) | Balance `val_gersolar` | Balance minus dispatched |
|---|---|---|---|
| 2023-04-24 | 1,987 | 2,086 | 99 |
| 2023-04-25 | 2,009 | 2,113 | 104 |
| 2023-04-26 | 2,016 | 2,120 | 104 |
| 2023-04-27 | 1,793 | 1,891 | 98 |
| 2023-04-28 | 1,886 | 1,991 | 105 |
| **2023-04-29** | 1,831 | **4,377** | **2,546** |
| 2023-04-30 | 1,588 | 4,623 | 3,034 |

Daily peak of balance solar: ~5.9 GW on 2023-04-28, ~15.0 GW on 2023-04-29 (it stays ~15-16 GW afterwards). Wind, hydro and thermal show no step.
Monthly means (MWmed): 2022-12 dispatched 1,604 vs balance 1,711 (+107); 2023-04 1,806 vs 2,084; 2023-05 1,916 vs 4,855 (+2,940); 2024-06 2,780 vs 6,904 (+4,124).
Wind is unaffected (dispatched vs balance: 8,319 vs 8,788; 6,682 vs 6,898; 9,189 vs 9,442; 13,096 vs 13,534).
Dispatched solar capacity factor in 2024-06: 2,780 MW / 13,751 MW = 20.2 % (normal); the balance would imply ~50 %.

**5. Metadata of the package** (CKAN `package_show` / `package_activity_list`): resources 2020-2022 last modified 2024-10-20; **2023 and 2024 resources were
re-published on 2025-07-28** (2025 on 2026-01-31, 2026 daily). The package notes say "Os dados disponibilizados fazem parte de um processo de consistência recorrente
e, portanto, podem ser atualizados após a sua publicação". The activity list contains only automatic daily "changed package" entries (the last 100, i.e. the
latest ~17 days); there is no changelog or methodology note, and the resource metadata has no revision/version fields. So metadata cannot date the scope change;
**the data and the `carga-energia` note date it to 2023-04-29.**

## (b) NOT CONFIRMED

- That `val_gersolar` includes MMGD: no ONS statement for the balance series (the dictionary, the package notes and the PDF are silent).
- That the extra solar from 2023-04-29 is exactly the MMGD estimate (the step could in principle also contain other non-dispatched solar, e.g. Tipo III).
  The 2024 sizes are consistent: balance solar 73.34 TWh minus ONS's MMGD 45.75 TWh = 27.6 TWh, versus ~26.9 TWh expected for centralized PV from capacity
  and the 2018-2022 median capacity factor; but this is arithmetic consistency, not a statement.
- Whether the 2025-07-28 re-publication of the 2023 and 2024 resources changed the solar scope (the step already exists in our current download, retrieved 2026-10-21).
- Whether the balance *total* (the denominator of P) includes MMGD consistently from the same date (generation sources other than solar show no step, so MMGD would be
  added through solar only; load definition: see `carga-energia` note).

## (c) INCONCLUSIVE (judgment call)

- **Evidence level for "ONS solar includes estimated MMGD from 2023-04-29":** strong circumstantial (same-day step; the dispatched series is flat; ONS states the same
  inclusion for load on that date; magnitudes match ONS's MMGD estimate), but not an explicit statement for `val_gersolar`. Whether that is enough to act on is your call.
- **ONS verified-load API (`carga-energia-verificada`, `val_cargammgd`)** was acquired and its schema verified, but it is not usable to quantify MMGD as is: the sum of the four
  area codes N/NE/S/SE gives a global load of ~33 GW (about half of the SIN), the code `SIN` returns zeros, and the implied MMGD (~2.0 GWmed in June 2024) is well below ONS's own
  5.2 GWmed 2024 average. The meaning of `cod_areacarga` values needs checking before use. The MMGD component also exists for days before 2023-04-29 (~1.5 GWmed on 2023-04-26), so it is a
  retrospective estimate series, not the operational definition.
- Which denominator ONS uses for its published curtailment percentages (section 1.3e) remains open; this verification only bears on the solar term.

## Datasets assessed (Part B, 6 queries, 13 distinct packages)

Queries: fator de capacidade; geracao distribuida; MMGD; geracao solar distribuida; capacidade instalada usina; geracao eolica solar fator. No ONS package is named "MMGD" or
"geração distribuída"; MMGD appears only as a component of load datasets.

| Package | Range | Verdict | Reason |
|---|---|---|---|
| `fator-capacidade-2` | 2009..2026-10 (monthly from 2022) | **ACCEPT, acquired (2022-12, 2023-04, 2023-05, 2024-06)** | hourly, per plant/conjunto of ONS-dispatched wind and solar plants (Tipo I / II-B / conjuntos): `val_geracaoverificada`, `val_capacidadeinstalada`, `val_fatorcapacidade` (text decimals); 21 columns verified |
| `carga-energia-verificada` | API only | **ACCEPT, acquired (N/NE/S/SE, 2023-04-20..05-10 and 2024-06)** | semi-hourly load by area with `val_cargammgd`; API, no bulk files; semantics of area codes unclear (see c) |
| `carga-energia` | 2000..2026 | ACCEPT (dictionary/notes read; not downloaded) | daily load; its notes carry the 29/04/2023 MMGD statement |
| `carga-mensal` | n/a | ACCEPT (not acquired) | monthly load; returned by the MMGD query; same fields as `carga-energia` |
| `demanda_maxima_di` | 2024..2026 | ACCEPT (not acquired) | daily maximum demand; returned by the MMGD query; time series with subsystem ids |
| `capacidade-geracao` | n/a | REJECT | static registry of generating units (no timestamp column, "não possuem informações históricas") |
| `capacidade-transformacao` | n/a | REJECT | static registry, grid transformers |
| `ear-diario-*` (4 packages), `res_volumeespera` | 2000..2026 | REJECT | hydrological storage series; not wind/solar/capacity/distributed generation |
| `programacao_x_previsao` | 2024-10..2026-10 | judged **not useful** | forecast vs programmed values per plant (`dat_programacao`); it is a time series but not capacity factor or MMGD |

ONS has **no dataset named for MMGD generation** and no capacity-factor series for the whole SIN; the plant-level capacity-factor file covers only plants ONS dispatches.
The more complete resolver would be the ONS statement itself; asking ONS (or reading the "Boletim"/PMO documents) is the remaining route.

## Files acquired (all under DATABASE_ROOT, none wired into the pipeline)

`raw/ons/capacity_factor/Fator_Capacidade_2-{2022-12,2023-04,2023-05,2024-06}.parquet` (13 MB, manifests alongside);
`raw/ons/mmgd/cargaverificada_{N,NE,S,SE}_{2023-04-20_2023-05-10,2024-06-01_2024-06-30}.json` (4.6 MB);
`raw/ons/generation_by_source/data_dictionary.json`, `raw/ons/carga_energia/data_dictionary.json`.

## Proposed candidate D20 (NOT adopted, not in discovered_sources.yaml)

"From 2023-04-29 the ONS balance series `val_gersolar` (and the SIN total) appear to include estimated MMGD. Evidence: same-day +2.5 to +3 GWmed step absent from dispatched solar;
ONS `carga-energia` states MMGD inclusion from 29/04/2023; magnitudes agree with ONS's 2024 MMGD estimate. Consequences to decide: (1) split calibration inputs into a centralized-scope
series (balance solar minus an MMGD estimate, or the dispatched plant-level series) versus a total-scope series; (2) use a centralized-scope denominator for curtailment rates (section 1.3e);
(3) revisit the D16 wording for 2023+. 2020 baseline unaffected."


---

# Task 6C - Measured gap between `val_gersolar` and ONS-dispatched solar (monthly, 2021-01 to 2026-10)

Status: **measurement only; nothing in the pipeline, D16, calibration.py or roadmap.md was changed. D20 is logged as a candidate, "pending (not adopted)".** Date: 2026-10-22.
Code: `src/curtailmit/ons_solar_gap.py` (standalone; reuses `CkanClient`, `fetch_and_cache` and the Task 6B solar filter `ons_mmgd_probe.solar_mask`).
Output: `interim/ons_solar_dispatched_monthly.parquet`. This run also rebuilt `interim/ons_generation_by_source.parquet` and the Task 3 `processed/` tables, which were empty in the real DATABASE_ROOT (Task 3 function `acquire_ons_generation`, unchanged).

## Method and data

- **Acquisition:** every PARQUET resource of `fator-capacidade-2` from 2021 on: the yearly file `Fator_Capacidade-2021` plus the 58 monthly files 2022-01..2026-10 = **59 files, 200 MB** (estimate before download: ~210 MB, far below the 1.5 GB stop limit). The 4 months cached in Task 6B were reused, not re-downloaded.
- **Schema check (every file against the Task 6B-verified 2022-12 schema):** no missing or added column in any file, **including the 2021 yearly file** (identical). One difference, logged as a WARNING and kept as is: in the 10 files **2026-01..2026-10** the column `val_fatorcapacidade` is `double` instead of `string`. It is not used here (`val_geracaoverificada` has the same type in all files). Nothing was skipped or coerced.
- **Dispatched solar:** sum of `val_geracaoverificada` over all rows with `nom_tipousina` starting with "solar" (the Task 6B filter), per hour, SIN level. These hours are compared with the same hours of `val_gersolar` (SIN, Task 3 interim); GWh = mean MW x hours of the calendar month / 1000. Coverage is 100 % in every month except 2026-10 (480 of 744 h, the month is still running; excluded from the statistics).
- **Gap** = `val_gersolar` - dispatched solar. Check: 2022-12, 2023-04, 2023-05 and 2024-06 reproduce the Task 6B means (e.g. 2024-06: dispatched 2,780, balance 6,904 MWmed).

## Full monthly table

| Month | Dispatched (GWh) | val_gersolar (GWh) | Gap (GWh) | Gap (MWmed) | Gap % of val_gersolar | Coverage |
|---|---:|---:|---:|---:|---:|---:|
| 2021-01 | 452 | 467 | 15 | 20 | 3.2 | 1.00 |
| 2021-02 | 362 | 371 | 9 | 14 | 2.5 | 1.00 |
| 2021-03 | 487 | 557 | 70 | 94 | 12.6 | 1.00 |
| 2021-04 | 477 | 549 | 72 | 100 | 13.1 | 1.00 |
| 2021-05 | 496 | 563 | 67 | 90 | 11.9 | 1.00 |
| 2021-06 | 506 | 576 | 70 | 98 | 12.2 | 1.00 |
| 2021-07 | 523 | 597 | 74 | 100 | 12.5 | 1.00 |
| 2021-08 | 545 | 619 | 74 | 100 | 12.0 | 1.00 |
| 2021-09 | 708 | 792 | 83 | 116 | 10.5 | 1.00 |
| 2021-10 | 715 | 797 | 82 | 110 | 10.3 | 1.00 |
| 2021-11 | 717 | 784 | 66 | 92 | 8.5 | 1.00 |
| 2021-12 | 694 | 764 | 69 | 93 | 9.1 | 1.00 |
| 2022-01 | 750 | 818 | 69 | 93 | 8.4 | 1.00 |
| 2022-02 | 732 | 800 | 67 | 100 | 8.4 | 1.00 |
| 2022-03 | 811 | 887 | 76 | 102 | 8.6 | 1.00 |
| 2022-04 | 803 | 870 | 66 | 92 | 7.6 | 1.00 |
| 2022-05 | 770 | 841 | 71 | 95 | 8.4 | 1.00 |
| 2022-06 | 764 | 829 | 64 | 89 | 7.8 | 1.00 |
| 2022-07 | 881 | 955 | 74 | 99 | 7.7 | 1.00 |
| 2022-08 | 1,009 | 1,101 | 91 | 123 | 8.3 | 1.00 |
| 2022-09 | 1,103 | 1,209 | 107 | 148 | 8.8 | 1.00 |
| 2022-10 | 1,191 | 1,338 | 147 | 197 | 11.0 | 1.00 |
| 2022-11 | 1,072 | 1,170 | 98 | 136 | 8.4 | 1.00 |
| 2022-12 | 1,193 | 1,273 | 79 | 107 | 6.2 | 1.00 |
| 2023-01 | 1,274 | 1,356 | 81 | 109 | 6.0 | 1.00 |
| 2023-02 | 1,282 | 1,349 | 67 | 100 | 5.0 | 1.00 |
| 2023-03 | 1,326 | 1,396 | 70 | 93 | 5.0 | 1.00 |
| 2023-04 | 1,301 | 1,500 | 200 | 277 | 13.3 | 1.00 |
| 2023-05 | 1,425 | 3,612 | 2,187 | 2,940 | 60.5 | 1.00 |
| 2023-06 | 1,316 | 3,411 | 2,095 | 2,910 | 61.4 | 1.00 |
| 2023-07 | 1,555 | 3,956 | 2,401 | 3,228 | 60.7 | 1.00 |
| 2023-08 | 1,797 | 4,501 | 2,704 | 3,634 | 60.1 | 1.00 |
| 2023-09 | 1,907 | 4,914 | 3,007 | 4,176 | 61.2 | 1.00 |
| 2023-10 | 1,981 | 5,247 | 3,266 | 4,390 | 62.2 | 1.00 |
| 2023-11 | 2,089 | 5,833 | 3,743 | 5,199 | 64.2 | 1.00 |
| 2023-12 | 1,949 | 5,935 | 3,986 | 5,358 | 67.2 | 1.00 |
| 2024-01 | 1,961 | 5,710 | 3,749 | 5,039 | 65.7 | 1.00 |
| 2024-02 | 1,877 | 5,458 | 3,582 | 5,146 | 65.6 | 1.00 |
| 2024-03 | 2,223 | 5,850 | 3,627 | 4,875 | 62.0 | 1.00 |
| 2024-04 | 2,160 | 5,478 | 3,318 | 4,608 | 60.6 | 1.00 |
| 2024-05 | 2,192 | 5,315 | 3,123 | 4,197 | 58.8 | 1.00 |
| 2024-06 | 2,002 | 4,971 | 2,969 | 4,124 | 59.7 | 1.00 |
| 2024-07 | 2,137 | 5,396 | 3,259 | 4,380 | 60.4 | 1.00 |
| 2024-08 | 2,427 | 6,235 | 3,808 | 5,118 | 61.1 | 1.00 |
| 2024-09 | 2,496 | 6,605 | 4,108 | 5,706 | 62.2 | 1.00 |
| 2024-10 | 2,719 | 7,492 | 4,773 | 6,415 | 63.7 | 1.00 |
| 2024-11 | 2,642 | 7,210 | 4,568 | 6,344 | 63.4 | 1.00 |
| 2024-12 | 2,717 | 7,624 | 4,906 | 6,595 | 64.4 | 1.00 |
| 2025-01 | 2,764 | 7,669 | 4,905 | 6,593 | 64.0 | 1.00 |
| 2025-02 | 2,513 | 7,250 | 4,737 | 7,049 | 65.3 | 1.00 |
| 2025-03 | 2,982 | 8,393 | 5,411 | 7,273 | 64.5 | 1.00 |
| 2025-04 | 2,788 | 7,083 | 4,295 | 5,965 | 60.6 | 1.00 |
| 2025-05 | 2,415 | 6,753 | 4,338 | 5,830 | 64.2 | 1.00 |
| 2025-06 | 2,275 | 6,187 | 3,911 | 5,433 | 63.2 | 1.00 |
| 2025-07 | 2,379 | 6,853 | 4,474 | 6,013 | 65.3 | 1.00 |
| 2025-08 | 2,418 | 7,298 | 4,880 | 6,559 | 66.9 | 1.00 |
| 2025-09 | 2,522 | 7,683 | 5,161 | 7,168 | 67.2 | 1.00 |
| 2025-10 | 2,799 | 8,465 | 5,666 | 7,616 | 66.9 | 1.00 |
| 2025-11 | 2,885 | 8,877 | 5,991 | 8,321 | 67.5 | 1.00 |
| 2025-12 | 3,272 | 9,324 | 6,052 | 8,134 | 64.9 | 1.00 |
| 2026-01 | 3,179 | 9,110 | 5,931 | 7,972 | 65.1 | 1.00 |
| 2026-02 | 2,989 | 7,873 | 4,884 | 7,268 | 62.0 | 1.00 |
| 2026-03 | 3,157 | 8,458 | 5,301 | 7,125 | 62.7 | 1.00 |
| 2026-04 | 3,044 | 7,805 | 4,761 | 6,613 | 61.0 | 1.00 |
| 2026-05 | 2,862 | 6,999 | 4,137 | 5,560 | 59.1 | 1.00 |
| 2026-06 | 2,842 | 7,030 | 4,188 | 5,817 | 59.6 | 1.00 |
| 2026-07 | 2,995 | 8,446 | 5,452 | 7,328 | 64.5 | 1.00 |
| 2026-08 | 3,263 | 9,831 | 6,567 | 8,827 | 66.8 | 1.00 |
| 2026-09 | 3,313 | 10,114 | 6,801 | 9,446 | 67.2 | 1.00 |
| 2026-10 | 3,460 | 10,969 | 7,508 | 10,092 | 68.5 | 0.65 |

Annual sums (GWh; 2026 = Jan-Oct, the last month partial):

| Year | Dispatched | val_gersolar | Gap |
|---|---:|---:|---:|
| 2021 | 6,681 | 7,434 | 753 |
| 2022 | 11,081 | 12,090 | 1,009 |
| 2023 | 19,202 | 43,009 | 23,807 |
| **2024** | 27,555 | 73,343 | **45,789** |
| 2025 | 32,012 | 91,833 | 59,820 |
| 2026 (Jan-Oct) | 31,105 | 86,636 | 55,531 |

## Findings (precise)

**(a) First non-trivial month.** The answer depends on the definition, so both are reported:
- *Relative rule (the step):* first month whose gap exceeds twice the mean of the previous 12 months and stays above that for 3 more months = **2023-04**. At day level the step is exactly on **2023-04-29**: daily gap 98-105 MWmed on 04-24..04-28, then **2,546** on 04-29, 3,034 on 04-30, 3,069 on 05-01 (the 2023-04 monthly mean, 277 MWmed / 13.3 %, is the 28 days before plus the 2 days after).
- *Absolute rule (gap > 5 % of `val_gersolar` for 4 months running):* **2021-03**, not 2023-04. See (d): the gap already carries a small, stable component before the step.

**(b) Shape from 2023 onward: growing, with seasonality (not flat, not erratic).** Gap 2,940 MWmed (2023-05) -> 4,000-6,600 (2024) -> 5,400-8,300 (2025) -> 5,600-10,100 (2026). Linear trend +1,477 MWmed per year over 2023-04..2026-09, coefficient of variation 0.31 (seasonal swings follow the solar resource). **As a share of `val_gersolar` it is flat: 58.8-68.5 % in every month from 2023-05**, i.e. the extra component scales with the solar resource and grows with capacity, as an MMGD estimate would. The dispatched series grows too (1,916 -> 4,651 MWmed) with no step.
One exception: **2024-11-09** has a daily gap of only 68 MWmed (neighbours 5,500 and 9,100; hour by hour the balance is dispatched + ~85 MW on that day). On that single day the balance series behaves as if it carried no extra component. It is the only such day after 2023-05-01 (listed by `glitch_days`).

**(c) 2024 sum vs RT ONS DGL 0189/2025 (45,752 GWh).** Measured 2024 gap = **45,789 GWh (ratio 1.0007)**. Subtracting the pre-step baseline of ~103 MWmed (median of the 12 months before the step, ~0.9 TWh) gives 44,878 GWh (ratio 0.981). **Tolerance used: +/-10 %**, applied to both numbers. Justification: the only known confounder is the pre-step baseline, ~2 % of the RT figure, plus the model uncertainty of ONS's own meteorological estimate, which ONS does not quantify; 10 % is about 5x the known confounder and still small against the effect being tested (the gap is 2.4x the dispatched solar in 2024). Result: **consistent (0.1 % off raw, 1.9 % off adjusted)**. Caveat: a match this tight on one year can be partly coincidental (both figures are estimates), so it supports the hypothesis but is not independent proof for other years; the RT gives no figure for 2023 or 2025.

**(d) Before April 2023: NOT near zero in the literal sense.** Exact numbers:
- 2021-01 / 2021-02: gap 20 / 14 MWmed (3.2 / 2.5 %).
- **2021-03 to 2023-03 (25 months): gap 89-197 MWmed (median of the last 12 months before the step: 103), 5.0-13.1 % of `val_gersolar`;** the maximum is 197 MWmed in 2022-10; the 2022 annual gap is 1,009 GWh.
- The jump from ~15 to ~95 MWmed happens between 2021-02 and 2021-03, the month from which the `carga-energia` package notes say ONS started adding "a previsao de geracao de usinas nao despachadas pelo ONS" to the load. This is an inference from timing (the notes are about load); it would mean the small baseline is non-dispatched centralized solar, not MMGD.
- Relative to the step this baseline is small: ~100 MWmed before vs 2,900-3,100 MWmed right after, about 1/30.

## Verdict against the Task 6B hypothesis

| Check | Result |
|---|---|
| Clear step at/near 2023-04-29 | **Yes**: exact day 2023-04-29, +2.4 GWmed day over day, none in dispatched solar |
| Near zero before the step | **Partly**: small and stable (89-197 MWmed, 5-13 %) but not zero; explained as non-dispatched plants added in 2021-03 (inference) |
| Magnitude vs RT 0189/2025 (2024) | **Consistent**: 45,789 GWh vs 45,752 GWh (+0.1 %); 44,878 GWh (-1.9 %) after removing the baseline |
| Gradual drift instead of a step | No: no month-by-month ramp around 2023-04 |

The measurement therefore **supports** the Task 6B hypothesis ("`val_gersolar` includes an MMGD estimate from 2023-04-29") with direct numbers, with one deviation from the literal "near zero before" criterion, flagged above. A candidate D20 was logged in `config/discovered_sources.yaml` as **pending (not adopted)**. ONS still does not say so in words for this field; the dictionary remains silent. The decision to adopt D20, and how it feeds the Task 9 denominator (section 1.3e), is for the joint decision with the user. D16 and the pipeline were not touched.
