# ONS transmission and interchange data acquired in Task 11E

Purpose: test whether the Northeast "time effect" on wind curtailment is a transmission-capacity effect (`docs/task11e_findings.md`, section 3). Only **operational** ONS data were used.
**Planning documents (EPE PDE / PET) were not used** and remain the deferred, separate extension.

Access date: 2026-10-22 (UTC), through the ONS CKAN API (`https://dados.ons.org.br/api/3/action`, `package_show`; resource URLs taken from the API response, none guessed).
License: Creative Commons Attribution (`cc-by`) on all three packages, as reported by CKAN. Files are stored under `DATABASE_ROOT/raw/ons/interchange/` with the retrieval manifest written by `acquisition.fetch_and_cache` (source URL, HTTP status, timestamp, SHA-256, size).

| Dataset (CKAN name, package id) | Files | Content | Use |
|---|---|---|---|
| `intercambio-nacional` (c3f865e5-d0ba-44d4-882e-38b08a538121), "Intercambios entre subsistemas" | `Intercambio_Nacional-2021..2026` (CSV for 2021-22, Parquet 2023-26), dictionary JSON | Hourly interchange between subsystem pairs, MWmed: "sum of the active-power flow measured on the boundary transmission lines"; 2026 also has the programmed value | Reconciliation of the NE net export (balance column `val_intercambio`) and a check of the sign convention. NE net export equals this series (correlation 1.0000, identical annual means) |
| `linha-transmissao` (4645138b-8a75-4e8c-83f9-8c7925307c57), "Linhas de Transmissao da Rede de Operacao" | `Linha_Transmissao.parquet`, dictionary JSON | 2,343 lines >= 230 kV (basic + complementary network): terminal subsystems and states, kV, km, long-duration operating current (A, with and without limiting factor), `dat_entradaoperacao`, `dat_desativacao`, `dat_prevista` | Monthly NE stocks: boundary line rating (MVA = sqrt(3) x kV x A / 1000), km of lines with the DE terminal in the NE |
| `capacidade-transformacao` (ba608479-8c15-47fb-a76e-e52e2c5de6a7), "Capacidade de Transformacao da Rede Basica" | `Capacidade_Transformacao.parquet`, dictionary JSON | 2,045 transformers: subsystem, MVA, entry / deactivation dates | Monthly NE transformer stock (MVA) |

## Caveats

- **Stocks are reconstructed, not published.** Both registries are daily snapshots of the current network ("Estes dados nao possuem informacoes historicas" is stated for the transformer package). The monthly series count equipment whose entry date is on or before the month end and whose deactivation date is empty or later. Equipment removed from the registry altogether would be missing; deactivated equipment is kept with its date.
- **Not a transfer limit.** The open data have no historical series of interchange limits. Line MVA is a thermal rating of the long-duration operating current summed over lines (21 NE boundary lines in 2026-09: 44.1 GVA), far above any coincident transfer.
- **Revealed capacity** = trailing 12-month maximum of the hourly NE net export (balance `val_intercambio`, MW). It is a lower bound of what the network can carry.
- Boundary lines are those with exactly one terminal in the NE and the other in N, SE or S; taps (empty second terminal) and international lines are excluded from the boundary stock; km counts every line with the DE terminal in the NE.
- Dates before 2022 exist in the registries (earliest line entry 1959) but only 2022-01..2026-09 is used, to match the curtailment series.
- ONS states that the data are subject to recurrent consistency processes and may be revised after publication.
- The package `programacao_fluxo_controlado` (programmed controlled-flow elements, daily files from 2024-10) was inspected through the catalogue only; it was not downloaded or used.

## Not wired into the pipeline

No `src/` or `config/acquisition_targets.yaml` change was made: these data feed throwaway analysis (`analysis/task11e_*.py`) and are not Stage 1 inputs. If a decision adopts a transmission-based driver, they would need a Stage 1 acquisition step with coverage checks like the other ONS packages.
