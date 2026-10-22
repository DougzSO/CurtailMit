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
