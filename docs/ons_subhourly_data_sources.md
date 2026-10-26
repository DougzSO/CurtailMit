# ONS sub-hourly data: what exists and what was acquired in Task 11E4 (feasibility sample)

Probe date and access date: 2026-10-26. Catalogue: ONS open-data CKAN (`https://dados.ons.org.br/api/3/action/`, 85 packages listed) and the ONS verified-load API. Operational data, not planning documents.

## 1. Inventory of sub-hourly resources (what a search of the catalogue found)

| Resource | Resolution | Realized or programmed | Status in the project |
|---|---|---|---|
| COFF wind / solar plant files (`restricao_coff_eolica_usi`, `restricao_coff_fotovoltaica`) | 30 minutes, per plant: generation, reference generation, curtailed generation, reason / origin codes, description | realized (verified) | **Already acquired** (Task 3 / 11C), wind 2021-10.., solar 2024-04.. ; the hourly frame of Task 11E sums them to the hour. No new acquisition needed. |
| Verified load (`carga-energia-verificada`, API `https://apicarga.ons.org.br/prd/cargaverificada`) | 30 minutes, per load area N / NE / S / SE (`SECO` from 2025-05) | realized | **2025 sample acquired here** (4 areas x 12 months). Earlier probes (Task 10) hold two small NE / N samples. |
| DESSEM balance (`balanco_dessem_geral`, `balanco_dessem_detalhe`) | 30 minutes, per subsystem, generation by source and load | **programmed** (day-ahead DESSEM schedule), one file per day since 2025-05-23 | not acquired; a forecast, not a realized series |
| COFF intra-half-hour (`coff_eolica_usi_intrasemihora`, `coff_fotovoltaica_intrasemihora`) | periods of restriction inside the half-hour (finer than 30 min) | realized | not acquired; describes restriction intervals, not generation or load, so it cannot give an instantaneous VRE share of load |
| Hourly packages (balance by subsystem, capacity factor, load curve) | 1 hour | realized | in use |
| `cmo-semi-horario` | 30 minutes | price (CMO), not generation / load | irrelevant here |
No package with generation or load below 30 minutes (e.g. 5-minute SCADA) was found in the open catalogue.

## 2. The acquired sample (verified load, 2025)

- Source: `GET https://apicarga.ons.org.br/prd/cargaverificada?dat_inicio=...&dat_fim=...&cod_areacarga=...`, one request per month and area; function `curtailmit.ons_mmgd_probe.acquire_mmgd_load` (existing, unchanged); `fetch_and_cache` stores each response with a `.manifest.json` (URL, HTTP status, retrieval time UTC, sha256, byte size, parameters) under `DATABASE_ROOT/raw/ons/mmgd/cargaverificada_<AREA>_<start>_<end>.json`.
- Size: 37 MB for 2025 (60 requests: 12 months x N / NE / S / SE / SECO; the retired SE code answers empty lists for 2025-05..12). Fields used: `val_cargaglobal` (verified global load, MW, including the estimated MMGD component), `din_referenciautc`.
- License: Creative Commons Attribution (package `carga-energia-verificada`). Cached analysis panel (regenerable): `DATABASE_ROOT/interim/task11e4_subhourly_2025.parquet`.
- Extrapolated cost of a full history 2022-2026 for four areas: about 4.75 x 37 MB = 180 MB, 240 requests, seconds per request.

## 3. Caveats
- The timestamp is the **end** of the half-hour in UTC (the first record of a local day is 00:30 local = 03:30Z); the analysis converts to local period start (UTC-3, no daylight saving since 2019) to match the COFF stamps.
- **Area code change:** the Southeast / Center-West area is `SE` until 2025-04 and `SECO` from 2025-05 (the retired code returns an empty list, not an error). Area `SIN` returns zeros. A downstream acquisition must request both codes.
- `val_cargaglobal` includes the MMGD estimate; the verified load is 2.3 % above the balance load in 2025 (ratio 1.023); COFF plants carry 96.3 % of the balance wind and 99.1 % of the dispatched solar of 2025.
- Records carry `din_atualizacao` (the series is revised after publication); the sample reflects the state on 2026-10-26.
