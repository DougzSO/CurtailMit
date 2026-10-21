# PTE vs ONS generation basis — investigation report (Task 3 closeout, Part B)

Status: **OPEN. Investigation only.** No calibration, projection or config value was changed.
Date: 2026-10-21. Related: D1, D15, `docs/methodology.md` (Table 2), `docs/claude_commands.md` 1.3b.

## The discrepancy

| | Value | Source |
|---|---|---|
| ONS SIN total generation, 2020 (hydro + thermal + wind + solar) | **554.35 TWh** | `ons_generation.py`, `balanco-energia-subsistema`, `id_subsistema == "SIN"` |
| ONS SIN total generation, 2025 (observed) | **700.41 TWh** | same |
| PTE `total_generation_twh`, 2025 (TB / TA / TG) | **836 / 834 / 836 TWh** | `config/scenarios.yaml` |

2020 -> 2025 growth implied if both were the same basis: 554 -> 836 TWh = +51 % (8.6 %/yr), which is not plausible.

## 1. What our own documents say

- `config/scenarios.yaml`, `docs/methodology.md` Table 2 and `docs/roadmap.md` give `total_generation_twh` **no definition**: no statement of whether it includes distributed generation (MMGD), self-production (autoprodução), isolated systems or imports.
- `docs/roadmap.md` only says PTE does not model curtailment. Nothing about generation scope.
- Conclusion: the repo does not record the scope; it must come from the PTE publication.

## 2. What the PTE publication says

The "PTE" in this project is the CEBRI **Programa de Transição Energética — Fase 2** (with BID, EPE, BNDES), *Relatório Técnico* (https://www.cebri.org/media/documentos/arquivos/CEBRI_PTE2_Relatorio_Tecnico_V.pdf, 121 pp.; text extracted locally with pypdf).

Confirmed in the text:
- **Gráfico 13, "Geração Elétrica (TWh)"** is the source of the totals; the TG series reads 836 (2025), 929, 1,008, 1,126, 1,229, 1,274 (2050), matching `scenarios.yaml`. Its footnote only defines "biomassa" (bagasse).
- Scenarios come from the **BLUES** model (MESSAGE platform); the model database is stated to be **calibrated for 2015** (methodology annex, section 7.2).
- In the annex step that adjusts the PDE 2031 base case for NEWAVE runs, **"Oferta Renovável: MMGD, Biomassa, Eólica e Solar"** take the energy quantities defined by the scenario (p. 109). The body text (p. 58) also speaks of "usinas solares distribuídas e centralizadas". So MMGD is part of the scenario's supply representation.

**Not found:** any sentence defining what the Gráfico 13 total includes (MMGD, autoprodução, isolated systems, losses), nor a 2020/2021 historical total for that chart.

## 3. Public cross-check: Brazil's national electricity total, 2020

EPE *Anuário Estatístico de Energia Elétrica 2021* fact sheet (BEN 2021 data; https://www.epe.gov.br/sites-pt/publicacoes-dados-abertos/publicacoes/PublicacoesArquivos/publicacao-160/topico-168/EPEFactSheetAnuario2021.pdf):

| 2020, GWh | BEN | ONS SIN (ours) | BEN - ONS |
|---|---|---|---|
| Hydraulic | 396,381 | 404,610 | -8,229 |
| Wind | 57,051 | 54,297 | +2,754 |
| Solar | 10,717 | 5,230 | +5,487 |
| Thermal-type (gas 53,515 + oil 8,556 + coal 11,946 + nuclear 14,053 + biomass 55,613 + other 13,387) | 157,070 | 90,217 | +66,853 |
| **Total** | **621,219** (hydro 396,381 = 63.8 %) | **554,353** | **+66,950** |

- ONS SIN is **~89 %** of the BEN national total. 554 TWh is therefore "narrower than national", not an error of scale.
- Nearly the whole gap sits in the thermal-type block (+66.9 TWh), plus solar (+5.5) and wind (+2.8), partly offset by hydro (-8.2).
- Secondary source (web summary of BEN 2021, **not verified in the primary text**): total 621.2 TWh, autoprodução 106.5 TWh (17.1 %), of which 60.7 TWh not injected into the grid.

## 4. Findings, best-supported hypothesis, and what is NOT confirmed

**Best-supported hypothesis (consistent with the numbers, not proven):** the ONS SIN balance covers grid-connected, ONS-visible generation only. The national BEN basis additionally includes (a) **autoprodução / industrial and biomass thermal** not seen by ONS (matches the +66.9 TWh thermal-type gap and the secondary 60.7 TWh non-injected figure), (b) **MMGD solar** (matches the ~+5.5 TWh solar gap), and (c) smaller wind/isolated-system items. The PTE (BLUES) total is a national-scale figure that explicitly carries MMGD in its supply, so it is more likely on the BEN-like national basis than the ONS basis.

**A second, independent observation (computed from our ONS data):**

| 2025 | PTE (TB) | ONS SIN observed |
|---|---|---|
| Wind + solar generation | 217.4 TWh (26 % x 836) | 207.2 TWh (115.4 wind + 91.8 solar) |
| Total generation | 836 TWh | 700.4 TWh |
| P = (wind+solar)/total | 26 % | 29.6 % |

The wind+solar **numerators agree within ~5 %**; the **denominators differ by ~19 %**. Even adding the ~11 % that the 2020 BEN/ONS ratio suggests (621/554), 700 TWh becomes ~785 TWh, still below 836. So the national-basis hypothesis explains most, but not all, of the 2025 gap on its own.

**Could NOT confirm:**
1. Whether PTE Gráfico 13 includes MMGD and/or autoprodução in the total (and in the solar/wind shares). The report's text never defines it.
2. The composition of the residual gap in 2025 (835 vs ~785 TWh): possible model overshoot vs. history (BLUES calibrated to 2015), new loads (electrification, hydrogen), or other scope items. No evidence either way.
3. That the BEN hydro excess in ONS (-8.2 TWh) is Itaipu's Paraguayan share booked as imports in the BEN. Plausible, not checked.
4. The autoprodução split (106.5 / 60.7 TWh) against the primary BEN text (secondary source only; the BEN síntese PDF is image-based and was not machine-readable).
5. Whether BEN "solar 10,717 GWh" includes MMGD.
6. Whether ONS-observed 2025 solar (91.8 TWh, centralized) plus MMGD would exceed the PTE solar of ~100 TWh, i.e. whether the PTE solar share is on a comparable footing at all.

## 5. Why it matters for Task 9 (decision still needed, nothing decided here)

Calibration will fit curtailment against P(t) computed on the **ONS-SIN denominator**, while projection applies it to PTE P(s,t) on an **unconfirmed, larger denominator**. P would be systematically ~3.6 points lower on the PTE basis in 2025 (26 % vs 29.6 %), and absolute curtailed TWh depends on which total generation is used. Options to decide among (none chosen): keep both on shares only; rebase PTE to an ONS-equivalent denominator once the scope is known; or rescale the ONS history to a national basis. The missing definition (item 1) is the information that most reduces the uncertainty — worth asking the PTE/CEBRI/EPE authors directly.
