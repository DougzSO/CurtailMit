# Task 13B-1 - Design: article figures and `limitations_summary.md`

**Status: PROPOSAL, awaiting explicit approval.** Nothing in this document is implemented: no figure code, no `limitations_summary.md`, no change to `src/`, `config/` or the tests. Implementation is Task 13B, contingent on the answers to the questions in section 9.

Sources of the findings below: `analysis/task11e4_coverage_figure.py`, the `analysis/` plotting code, `src/curtailmit/{results_writer,limitations,projection,hourly_model,decision_registry}.py`, the production tables in `curtailmit_database` (`outputs/tables/final_results.parquet`, `processed/pte_curtailment_option_E.parquet`), `config/discovered_sources.yaml` (D23-D35), `docs/methodology.md` (2.3j, 2.3k, 3.7), `docs/pre_submission_checklist.md`, `docs/limitations.md`.

---

## 1. Investigation findings

### 1.1 The Task 11E4 coverage-figure prototype

What it plots (`analysis/task11e4_coverage_figure.py`, 7.4 x 3.3 in, two panels):

- (a) per PTE scenario and year (2025/2030/2040/2050), the **share of projected hours inside the observed support** (bars; support = r <= 63 %, the last 2-pp bin of the system-wide VRE share of load r with >= 15 observed hours) and a tick for "inside the largest observed value" (r_max = 75.8 %);
- (b) per scenario, the **share of projected curtailed energy produced by in-support hours**, wind solid, solar dashed.

Style: matplotlib with `Agg`, DejaVu Sans 7.5 pt, no top/right spines, `pdf.fonttype 42`, `svg.fonttype none`, Okabe-Ito colours (TB `#0072B2`, TA `#D55E00`, TG `#009E73`), values printed on bars, output PDF + SVG + 600-dpi PNG, a data CSV and a caption file next to it. It is already at the Elsevier double-column width (190 mm = 7.5 in).

Where its data come from: `outputs/tables/task11e2_coverage_table.csv`, an **intermediate of the analysis scripts at phi = 1**, not a production output. It is therefore not a production figure in the sense of this task, and a straight port is not what is needed.

Migration finding (the analogue of the 11F investigation): **the production Option E table already carries everything panels (a) and (b) need**, so the figure can be rebuilt from production code without the prototype's intermediate table. `processed/pte_curtailment_option_E.parquet` has `H_out_wind` / `H_out_solar` (share of hours beyond the support edge), `E_out_wind` / `E_out_solar` (share of the predicted curtailed energy beyond it) and `curt_in_support_*_twh` / `curt_out_support_*_twh`. Spot checks against the prototype's published numbers agree (the Option E table is evaluated at the support edge with phi = 1 for these diagnostics even though the table's `flex_phi` column is 1.5, which is the 2050 lower scenario):

| quantity | prototype (docs / `task11e2_coverage_table`) | production Option E parquet |
|---|---|---|
| hours inside support, TB 2050 | 60 % | 1 - `H_out_wind` = 59.9 % |
| hours inside support, TA 2040 | 86 % | 1 - 0.145 = 85.5 % |
| wind curtailment beyond support, 2050 TB / TA / TG | 62 / 77 / 51 % | `E_out_wind` 62.2 / 77.5 / 50.7 % |

Two things cannot be ported as they are:

1. **The "inside the largest observed value" tick** needs r_max = 75.8 %, which is not a column of any production table. Options: drop the tick (recommended: the support-edge criterion is the one the model uses, and the tick is secondary), or add an `r_max` field to the Option E table (a production-table change, which this task does not propose).
2. **`final_results` alone is not enough for this figure.** It carries only `in_support_fraction` (= 1 - `E_out`, an *energy* share, total) and `support_status`. The coverage figure therefore reads the Option E parquet as a second, documented input. This departs from "sourced from `final_results`" only for this validation figure, and the data CSV written beside the figure records that source.

The figure's caption in the prototype contains the numbers 99.6-99.8 %, 86-96 %, 43-70 %, 51-77 %. In the production version these numbers are **generated from the table into the caption**, not copied (so the caption cannot drift from the data).

### 1.2 Other plotting code in `analysis/`

Matplotlib appears in 9 analysis scripts. Only the coverage figure is publication-formatted; all the others are exploratory diagnostics (`dpi=130`, `figsize` 13-18 in, `viridis` for time-colouring):

| script | what it shows | model it draws | status for 13B |
|---|---|---|---|
| `task11c_diagnostics.py` | regional diagnostics, class share | national / regional (reference) | not promoted |
| `task11d_pooled_panel.py`, `task11d_regional_recalibration.py` | pooled international panel, NE-only wind curve | **regional formulation (Task 11D), retired as primary by D24** | not promoted |
| `task11e_wind_envelope.py` | national vs regional vs E envelope | mixes retired and adopted models | not promoted |
| `task11e2_insample_coverage.py`, `task11e2_transmission_mechanism.py` | exploratory coverage / mechanism | E + transmission (D26 retired) | not promoted |
| `task11e3_error_growth.py` | error vs extrapolation distance (negative result) | E | not promoted (could be a supplement figure; see question 6) |
| `task11e4_coverage_figure.py` | coverage | **E (primary)** | **migrated (F2)** |

**Stop trigger 2 (retired model shown as a primary result): not fired.** The only figure proposed for migration plots the adopted model. None of the national-P / regional prototypes is proposed for the article; if the article's "methodological journey" (D24: the national and regional formulations "retained as documented reference / comparison points") needs a figure, it must be built as a separate, explicitly captioned "comparison, not a result" figure (question 6), never reusing the exploratory PNGs.

### 1.3 Production table: what a figure may read

`final_results` (156 rows = 12 scenario-years x 13 quantity/component blocks; 32 columns) is long format: `quantity` in {`curtailed_energy`, `mitigation_deficit_avg`, `mitigation_deficit_marginal_om`, `mitigation_deficit_marginal_cm`, `h2_potential`}, `component` in {total, wind, solar}. Columns usable for figures: `central_value`, `conditional_range_low/high` (+ `range_basis`), `supplement_low/high` (split-conformal 80 %, 2025-2040 only; NaN in 2050), `sec_sensitivity_low/high` (H2 only), `horizon_treatment` (`band_plus_conformal` for 2025-2040, `decomposition_conditional` for 2050), `support_status`, `in_support_fraction`, `known_limitations`, `known_limitations_text`, `is_interpolated` (False everywhere; no interpolated year exists, acceptance criterion 4). Actual central values (total, TWh): TB 43.8 / 64.3 / 127.6 / 354.8; TA 43.7 / 63.1 / 242.4 / 536.1; TG 43.8 / 58.2 / 181.4 / 333.9 (2025/2030/2040/2050). TA 2040 is `partially_out_of_support`; every 2050 row is `mostly_out_of_support`.

Facts that constrain the visual design:

- The 2050 central value is **not** the midpoint of its range (TB 354.8 within 230.9-432.1), so a symmetric error-bar glyph would misrepresent it even before the semantic problem.
- The conformal supplement is 3-10 times wider than the empirical band (TB 2030: band 60.7-76.5, supplement 21.7-190.3). It cannot share an axis with the band without dominating the picture.
- The project's own column-name / text filter (`results_writer.FORBIDDEN_LANGUAGE`, case-insensitive: `ci_`, `_ci`, `confiden`, `credible`, `margin of error`) would reject the caption text the task requires ("conditional range (not a confidence interval)"). See section 3.4: the figure text check needs one narrowly scoped exception.

### 1.4 DeCarbon figure requirements

**Not found.** The journal's guide for authors (ScienceDirect page for *DeCarbon*) returned HTTP 403 to an automated fetch, and a web search returned only generic Elsevier artwork guidance, not a DeCarbon page. What the search did establish is Elsevier's general artwork standard (not necessarily binding for DeCarbon): resolution 300 dpi halftone, 500 dpi combination, 1000 dpi line art; single column 90 mm, double column 190 mm; lettering about 7 pt at final size, never below 6 pt for sub/superscripts; formats TIFF, EPS, PDF, JPEG accepted; colour in RGB.

Nothing found conflicts with the project tooling (**stop trigger 3: not fired**), but nothing was confirmed either, so the following are **defaults for user confirmation, not final requirements**:

| aspect | proposed default | reason |
|---|---|---|
| vector master | PDF (fonts embedded, `pdf.fonttype 42`) and SVG for editing | accepted by Elsevier; scales to any column width; matches the prototype |
| raster fallback | 600-dpi PNG (as in the prototype); TIFF at 1000 dpi on request | 600 dpi meets the Elsevier combination-art figure (500) but is below the line-art figure (1000); the vector PDF is the primary deliverable, and the raster is generated at 1000 dpi if the journal insists on raster line art |
| width | 90 mm (single) or 190 mm (double) only | Elsevier columns |
| font | DejaVu Sans, 7-8 pt body, >= 6 pt anywhere | fonts matplotlib ships; no system dependency |
| palette | Okabe-Ito for categorical (scenario) data, `cividis` for any sequential encoding; every distinction also carried by marker/line style or direct labels | colour-blind safe, greyscale-safe printing |
| captions | written into a `_caption.txt` beside each figure, and into the article by hand | journals usually want captions in the manuscript text, not in the figure |

The user should check the guide for authors (in a browser) before the submission and confirm or correct this table; the figure module will keep these as named constants in one place.

---

## 2. Proposed figure list (for approval - not assumed)

Source for all: `final_results` (production table), except F2, which also reads the Option E parquet (section 1.1). Every figure uses only rows with `is_interpolated == False` (all of them) and prints scenario names TB/TA/TG directly on the plot.

| id | purpose (one sentence) | data | formats | main or supplement |
|---|---|---|---|---|
| **F1** | Show the central curtailed energy of each scenario at 2025, 2030, 2040 and 2050, with the empirical annual-backtest band for 2025-2040 and the flexibility-conditional range for 2050, visually distinct. | `final_results`, `quantity = curtailed_energy`, `component = total` | PDF/SVG/PNG, double column | main |
| **F2** | Show where the hourly model is anchored in observation (hours and curtailed energy inside the observed support), the methodological strength adopted in D24. | Option E parquet: `H_out_*`, `E_out_*` (migration of the 11E4 prototype) | PDF/SVG/PNG, double column | main |
| **F3** | Decompose the curtailment of 2040 and 2050 into in-support and beyond-support energy, as D24 requires for 2050. | Option E parquet: `curt_in/out_support_total_twh` (or, if approved, a panel (c) of F2) | PDF/SVG/PNG, single/double | main or merged into F2 (question 4) |
| **F4** | Show the mitigation deficit as OM and CM in **separate panels**, never added (D28), plus the average-factor deficit for reference. | `final_results`, `mitigation_deficit_{avg,marginal_om,marginal_cm}`, `component = total` | PDF/SVG/PNG, double column | main |
| **S1** | Show the nominal 80 % split-conformal supplement (2025-2040) next to the empirical band, to make the 3-10x width difference visible. | `supplement_low/high` vs `conditional_range_low/high` | PDF/SVG/PNG | supplement |

Proposed **tables instead of figures**:

- T1, complete results: central, range, support status per scenario-year-quantity (the numbers a figure cannot carry).
- T2, hydrogen: central H2 and the `sec_sensitivity_*` range (D30). The SEC range is a three-point sensitivity of a fixed conversion factor; a table communicates it better than a band that would be confused with the energy range.
- T3, MCTI factor-year sensitivity (D29): the `mcti_sensitivity_avg_2021_2025_central_value` column of `final_results_mcti_sensitivity`; one column of numbers, no figure needed.

Not proposed (flagged in section 9): a historical-context overlay in F1 (observed 2022-2025 curtailment), and a backtest figure; both need data that are not in `final_results` (see questions 2 and 3).

---

## 3. The 2050 conditional range: visual distinction (decision for the user)

D24 rule restated: **no figure may suggest confidence-interval semantics for the 2050 range**. The 2025-2040 element is an empirical annual-backtest band (descriptive, "not a coverage guarantee"); the 2050 element is the span between two stated scenarios (phi = 1.5 flexibility and L = 1), with the central value (phi = 1) inside but not at the midpoint.

### 3.1 Options (the choice is yours)

**Option V1 - separate zone, hatched dashed-outline box (my recommendation).**
F1 is one axis with a visible vertical gutter between 2040 and 2050. The 2025-2040 columns carry the empirical band as a **solid-filled bar** (same hue as the scenario, alpha 0.35, solid thin edge) with a dot for the central value. The 2050 column sits on a **light-grey shaded background**, headed "2050 - conditional", and its range is an **unfilled box with diagonal hatching and a dashed outline**, with the central value as a **diamond** (different glyph from the dot). The legend has two entries: "empirical annual-backtest band (descriptive; not a coverage guarantee)" and "conditional range, phi 1.5 to L = 1 (not a confidence interval)". Sketch:

```
 TWh
 700|                                   |///////|  <- dashed outline, hatched
    |                           grey    |///<>//|  <- diamond = central (phi=1)
 400|                          zone      |///////|
    |                  [==]              
 100|   [|]   [|]     [==]
    |  2025   2030    2040   ||   2050 (conditional)
        solid bars = empirical band     hatched dashed = conditional range
```

**Option V2 - separate panel.** F1 is two panels side by side: (a) 2025-2040 with the empirical band; (b) 2050 with its own y-axis, titled "2050: conditional on a flexibility assumption", range drawn as hatched bars. Strongest separation, but loses the single-axis view of growth from 2040 to 2050, which is a message of the article.

**Option V3 - no interval glyph at 2050; named endpoints.** At 2050 each scenario is a vertical thin dotted line between two **labelled markers**, "phi = 1.5" (lower) and "L = 1" (upper), with the central value as a third marker. Because each end carries the name of the assumption that produces it, nothing reads as "plus or minus"; it reads as "two scenarios". Most explicit, least familiar to reviewers, and slightly more cluttered.

All three share these **mandatory elements**, whichever is chosen:

- legend text "conditional range (not a confidence interval)" (V1/V2) or endpoint labels (V3);
- a caption sentence: "2050 values are a range conditional on a flexibility assumption (phi 1.5 to L = 1), not a statistical interval; 51-77 % of the 2050 wind curtailment comes from hours with no historical analogue." (numbers filled from the table);
- an **in-figure annotation** at 2050 ("conditional, mostly out of support"), so the label survives if the caption is detached;
- the 2040 TA bar marked with an open marker and a "partial support" tag (14.5 % of hours beyond the support, from `support_status`), so the partial-support flag of D24 is visible at 2040 without borrowing the 2050 hatching;
- no colour distinction alone: the difference is carried by fill (solid / hatched) and outline (solid / dashed), so it survives greyscale and colour-blindness.

### 3.2 The F2 / F3 representation of 2050

F2 and F3 report shares and energy of hours, not intervals; the 2050 bars there are drawn the same as the other years (they are facts about the support), with the 2050 tick label "2050 (conditional)".

### 3.3 Why not a shaded band or error bars

A continuous shaded band (as in a fan chart) or capped error bars are, in the reader's habit, confidence/credible intervals. They are therefore reserved for **nothing** in 2050 and used (as filled bars with explicit label) only for the 2025-2040 descriptive band. The label "empirical annual-backtest band" is itself constrained to avoid "interval" language (it is a ratio envelope from 2023-2026 holdout years, wind truth/prediction 1.09-1.31, solar 0.87-1.13).

### 3.4 Automated text check, and the one allowed phrase

Planned test: every text string in every generated figure (titles, labels, tick labels, legend, annotations, caption file) is run through `FORBIDDEN_LANGUAGE`. The required legend wording contains "confiden", so the test needs an explicit allow-list of exactly one negation phrase: `not a confidence interval`. Any other occurrence still fails. This is a (narrow) relaxation of the existing filter for figure text only; the table filter is untouched. Please confirm (question 1).

---

## 4. `docs/limitations_summary.md`

### 4.1 Structure: by theme, not by decision

Investigation: `docs/methodology.md` 3.7 is an append-only historical list (partly stale: it still describes the 5-anchor / two-curve structure, now marked superseded); `docs/limitations.md` is a pointer page; `docs/pre_submission_checklist.md` holds the open licensing item. A reader (article reviewer) asks "what should I not trust, and why", not "what did D29 decide". D23-D35 are 13 decisions, of which only some carry limitations (D23 basis, D24/D25 model and drift, D26 retired transmission, D28-D30 emission/SEC treatment, D33 data availability, D35 historical validation); one section per decision would give 13 uneven sections and split a single limitation across several (the drift limitation touches D24, D25, D35).

Proposed themes, each with the decisions it draws on:

1. Residual drift of the wind curtailment (D24, D25, D35)
2. Extrapolation beyond the observed support; 2040 TA partial support; 2050 conditional range (D24, D28)
3. Flexibility held at today's level; transmission expansion not modelled (D24, D26)
4. Solar record length (D14, D20, D24)
5. Generation basis and gross vs net (D16, D23)
6. Emission factors: OM/CM as proxies, never summed; factor year (D12, D18, D28, D29)
7. Hydrogen: fixed SEC and its range (D30)
8. Data provenance, availability and licensing (D33; open licensing item of `docs/pre_submission_checklist.md`)
9. Historical validation (D35 supersedes criterion 5; backtest bias)

Plus an **appendix per decision**: a generated table of D23-D35 giving status, the theme(s) it feeds, and "no reader-facing limitation" where that is the case. Existing prose is cross-referenced (`docs/methodology.md` sections, `docs/task11e2_findings.md`), not repeated.

### 4.2 Generation mechanism (no hand-written drift)

Module `src/curtailmit/limitations_summary.py`, same pattern as `decision_registry.py` (`--write` / `--check`, markers, tests).

Two inputs:

1. **The YAML decisions**, via the existing duplicate-key-refusing loader of `decision_registry`. To get reader-facing limitation text without parsing 60-line `decided:` blocks by pattern, I propose **one optional new field per decision**, `limitation:`, `theme:` and, for decisions without one, `limitation: none` with a one-line reason. The field text is a 1-3 sentence statement, written once, next to the adopted text, and a test requires every number in it to appear in the same decision's text (the pattern already used for `D25_QUANTIFIED` in `limitations.py`). This **edits adopted decisions' entries (adds a field; status and adopted text unchanged)**; it follows the append-only rule but touches D23-D35 in the YAML, so I ask for authorization (question 5). The alternative without YAML edits is a Python mapping (id -> theme -> verbatim excerpt of `decided`), cheaper, but excerpts of long paragraphs read badly.
2. **The production table**, `final_results.parquet`: the distinct `known_limitations_text` strings (5 today: base text on 104 rows; + partial support for TA 2040; + the 2050 variants per scenario) and `known_limitations` ids (`D25;SOLAR_SHORT_RECORD`), reproduced **verbatim** in a "Caveats carried by the output rows" section, together with the sidecar `final_results.parquet.limitations.json` (D25 adopted text, solar note, D26 note). Because the table lives in the local database (D33), this section is regenerated locally; CI cannot compute it.

Two marker blocks accordingly: `LIMITATIONS-FROM-DECISIONS` (CI-checkable from the repository alone) and `LIMITATIONS-FROM-TABLE` (checked by an integration test when the database is present, as for other table-dependent tests).

### 4.3 Consistency tests (proposed)

- every decision with `status: adopted` in D23-D35 has either a `limitation:` text or `limitation: none` with a reason; one without raises (forces a conscious classification when a new decision is adopted);
- every non-`none` decision appears in the generated summary under its theme, and the file in the repo equals the freshly generated text (`--check`, in CI);
- a decision that is not `adopted` never appears as a limitation of the production model (mirrors `limitations.load_adopted_decision`);
- numbers in `limitation:` texts occur in the decision text; numbers in the D25 line match `limitations.D25_QUANTIFIED`;
- (integration) every distinct `known_limitations_text` of the production table appears verbatim in the summary, and every `known_limitations` id of the table maps to a decision or a named note;
- no hand-written prose outside the markers: the file consists of the generated blocks plus a short fixed header, checked by comparison with the generator output;
- the summary never uses the forbidden CI language, except the one allowed negation phrase.

---

## 5. Module and file layout

| file | role |
|---|---|
| `src/curtailmit/figures.py` | style constants (DeCarbon defaults, palette), pure data-extraction functions (`headline_frame`, `coverage_frame`, `decomposition_frame`, `mitigation_frame`), one plotting function per figure, caption builders (numbers generated from the frames), `write_figure` (PDF/SVG/PNG + data CSV + caption), CLI `python -m curtailmit.figures [--only F1,F2]` |
| `src/curtailmit/limitations_summary.py` | generator, `--write` / `--check` |
| `docs/limitations_summary.md` | generated; committed |
| `tests/test_figures.py`, `tests/test_limitations_summary.py` | tests (section 6) |
| outputs: `DATABASE_ROOT/outputs/figures/F1_*.{pdf,svg,png}`, `_data.csv`, `_caption.txt`, `figures_manifest.json` | local-only, like all outputs (D33); nothing binary is committed |

Justification: a module in `src/` (not a script) because the 11F lesson is that prototypes in `analysis/` are not tested or locked; the data-extraction functions must be unit-testable without drawing. It is run with `python -m` like `run_manifest` and `decision_registry`, so no new script directory. **Figures are not a stage of `curtailmit-run`**: they are article-time products, they do not affect the numbers, and a plotting failure must not turn a successful numerical run into a gate failure (D31 scope: the orchestration covers the numbers). The figure CLI instead refuses to run unless `results_writer.validate_final_results` passes on the table it reads, and writes `figures_manifest.json` recording the SHA-256 of `final_results.parquet` (and of the Option E parquet for F2) and of each figure file, so a figure can be traced to the exact table. Reproducibility note: PDF/SVG embed creation timestamps by default; the writer sets `metadata` / `SOURCE_DATE_EPOCH` so that same inputs on the same machine give identical files, and the manifest records the matplotlib version. Cross-platform pixel identity is not promised (same stance as the numerical reference check, `docs/reproducibility.md`).

The prototype `analysis/task11e4_coverage_figure.py` is left in place and annotated as superseded by `curtailmit.figures` (append-only note, as with the other migrated prototypes).

---

## 6. Test plan

**Unit-testable (CI, empty database, synthetic frames shaped like the production tables):**

- extraction: each `*_frame` returns the expected rows/columns, uses only `final_results` / Option E columns, never recomputes (e.g. `headline_frame` values equal the table's `central_value` exactly);
- guards: a table with an interpolated row, a missing scenario-year, or a failed `validate_final_results` is refused;
- F2 against the prototype: `coverage_frame` reproduces `H_out` / `E_out` numbers of a committed fixture (a small fixture of the 12 rows of the Option E diagnostics, extracted like `tests/fixtures/final_results/reference_totals.json`) within 1e-9;
- OM and CM never summed: F4 frame contains OM and CM in separate columns/panels; a test fails if any plotted series equals OM + CM;
- file output: each figure writes PDF, SVG, PNG, data CSV and caption; files are non-empty; PNG dpi metadata is 600; fonts embedded (PDF contains no Type 3 fonts); no exception for each figure on the synthetic data; `Agg` backend forced;
- 2050 rule, automated: for F1 (a) the artists for 2050 are of the conditional style (hatch set, dashed linestyle, not the same facecolor/linestyle as the band artists); (b) the legend contains the exact conditional label; (c) the figure's annotations contain the conditional caption note; (d) the caption file contains the sentence about the flexibility assumption;
- text check: all figure strings through `FORBIDDEN_LANGUAGE` with the single allowed phrase (section 3.4);
- caption numbers: every percentage in a caption is derived from the frame (test recomputes it);
- determinism: two runs, same inputs, byte-identical PDF/SVG (timestamps neutralised);
- limitations summary: the tests of section 4.3.

**Only the user can verify (visual inspection, listed in the Task 13B report):** legibility at 90/190 mm, overlap of labels and annotations, whether the hatched/dashed 2050 style reads as "not an interval", greyscale and colour-blind (simulator) rendering, caption wording, and the DeCarbon guide for authors. Matplotlib output correctness beyond the structural checks above is not unit-testable.

---

## 7. Dependency note

`matplotlib>=3.8` is already a core dependency (`pyproject.toml` `dependencies`, `requirements.txt`) and is pinned in `requirements.lock.txt` as `matplotlib==3.11.2` with its transitive dependencies (`contourpy`, `cycler`, `fonttools`, `kiwisolver`, `pillow`, `pyparsing` all present as exact pins). **No change to `pyproject.toml`, `requirements.txt` or the lock file is needed**, and the Task 15 lock-consistency tests (`tests/test_environment_lock.py`: every declared dependency pinned, pin satisfies the floor, lock header/Python version) are unaffected. The locked CI job (`unit-tests-locked`) already installs it. The only environment point to handle is headless rendering: the module selects the `Agg` backend explicitly and tests set `MPLBACKEND=Agg`, because CI runners have no display. Font: DejaVu Sans ships with matplotlib, so no system font is required. If the later choice of font or a LaTeX-style rendering is wanted, that would be a dependency change and would come back for approval.

---

## 8. Stop-and-report triggers

| trigger | result |
|---|---|
| Ambiguity in how to distinguish the 2050 range from a confidence interval | **Fired by design**: three options given in section 3.1 (V1 recommended); no choice is made without approval |
| A prototype that, ported naively, shows a retired / reference-only model as a result | Not fired: the only migrated prototype plots Option E; the national / regional scripts are not promoted (section 1.2) |
| A mandatory DeCarbon format conflicting with the tooling | Not fired and not excluded: the DeCarbon guide for authors could not be read (HTTP 403); defaults in 1.4 are unconfirmed |

---

## 9. Questions for approval

1. **2050 representation** (section 3): V1 (recommended), V2 or V3? And do you approve the single allowed phrase "not a confidence interval" in the figure-text check (3.4)?
2. **Historical context in F1** (the editorial question deferred by D35): show the observed ONS annual curtailment 2022-2025 as grey reference points? It needs Stage 1 observed data (not in `final_results`), so F1 would read a second source. Recommended: no, keep F1 pure `final_results`, and treat history in the text/table.
3. **Backtest figure** (the validation evidence that D35 uses to replace the 2020 anchor): include the 11E2 observed-vs-modelled annual figure as a main or supplementary figure? Its numbers exist only as analysis output (`task11e2_backtest_annual.csv`), not as a production table, so including it means committing a small fixture and labelling it analysis-derived. Recommended: supplementary figure S2, built from that fixture, if you want the validation visible.
4. **F3**: separate figure, or panel (c) of F2? Recommended: panel (c) of F2 (keeps the main text to four figures).
5. **YAML `limitation:` / `theme:` fields** on D23-D35 (section 4.2): authorize adding them (status and adopted text unchanged), or use the code mapping instead?
6. **Comparison figure for the methodological journey** (national vs regional vs Option E, D24 "reference / comparison points"): not proposed; if wanted, it would be a separate figure labelled "comparison, not a result", built from a fixture, never from the exploratory PNGs. Include or leave to the text?
7. **DeCarbon defaults** (section 1.4): confirm after reading the guide for authors, or tell me the actual requirements.
8. **The "largest observed value" tick** of the coverage figure (section 1.1): drop it (recommended) or add `r_max` to the Option E table (production-table change)?

---

## Update (Task 13B-1 Addendum - Decisions, 2026-10-27)

Documentation-only addendum. Sections 1-9 above are unchanged (append-only); this section records the user's resolution of the eight open questions of section 9. No code was touched and the design is not re-opened.

1. **Q1 - 2050 representation: option V1 approved** (separate shaded zone, hatched box with dashed outline, diamond for the central value, legend "conditional range (not a confidence interval)", caption note and in-figure annotation, as in section 3.1). The `FORBIDDEN_LANGUAGE` check on figure text gets a **narrow, literal exception for the exact string `not a confidence interval`**, and for nothing else; it is not a general relaxation of the filter, and the filter on table columns and text is untouched. The implementation must carry a code comment referencing D24 stating that the exception exists because the phrase explicitly *denies* being a confidence interval.
2. **Q2 - no historical 2022-2025 overlay in F1 for now.** Closed decision, not pending. F1 stays sourced from `final_results` only.
3. **Q3 - backtest figure approved as supplement S2** (Task 11E2 observed-vs-modelled annual figure). Its numbers exist only as analysis output (`task11e2_backtest_annual.csv`), so a small committed fixture dataset has to be built for it and the figure labelled analysis-derived.
4. **Q4 - F3 becomes panel (c) of F2**, not a separate figure. The main text carries four figures: F1, F2 (panels a-c), F4, plus supplements S1 and S2.
5. **Q5 - `limitation:` and `theme:` fields will be added to the entries D23-D35 of `config/discovered_sources.yaml`** (not a code mapping; status and adopted text unchanged). **Dependency, flagged explicitly:** the schema of these fields and the generator that consumes them (`limitations_summary.py`, the generated `docs/limitations_summary.md` and its consistency tests, section 4) are designed and implemented in **Task 16** (see `docs/task16_design.md` once it exists), not directly in Task 13B. Task 13B therefore does not produce `limitations_summary.md` until Task 16 delivers the generator.
6. **Q6 - no methodological-journey comparison figure.** The national / regional / Option E comparison stays text-only in `docs/methodology.md` (already present in section 2.3k); the exploratory PNGs of `analysis/` are not promoted.
7. **Q7 - DeCarbon figure standards remain UNCONFIRMED** (DPI, column width, font size, colour palette; section 1.4 defaults are not final). The user will verify the author guide manually. **Task 13B must not be marked complete until the user confirms these standards or explicitly waives the check.**
8. **Q8 - the "largest observed value" (r_max) reference is removed from the coverage-figure design.** No `r_max` column is added to the Option E production table.

---

## Task 13B - implementation status (2026-10-27)

Appended; sections 1-9 and the addendum above are unchanged. **Implemented but NOT closed.** Closing needs (a) the user's visual review of the V1 style and of the output figures and (b) the user's confirmation or explicit waiver of the DeCarbon figure standards (addendum Q7).

**PROVISIONAL standards in force.** The figure standards of section 1.4 are implemented as named constants at the top of `src/curtailmit/figures.py` (`PROVISIONAL_STANDARDS = True`, 90 / 190 mm, 600-dpi PNG beside the PDF / SVG vector masters, DejaVu Sans 7.5 pt with 6 pt as the floor, Okabe-Ito palette). They are UNCONFIRMED. `figures_manifest.json` records `provisional_decarbon_standards: true`; the constant is to be set to `False` only when the user confirms or waives the check.

**What was built.**

- `src/curtailmit/figures.py` and the shim `scripts/generate_figures.py` (`python -m curtailmit.figures [--only F1,F2,F4,S1,S2]`). Figures are not a stage of `curtailmit-run`.
- F1 (central value and range, style V1 for 2050), F2 (panels a-c; F3 folded in as panel c; reads the Option E production table, not the 11E4 intermediate CSV; no r_max line, tick, column or caption number), F4 (OM, CM and the average factor in three separate panels, never added), S1 (band beside the split-conformal supplement), S2 (backtest, from the fixture `tests/fixtures/figures/backtest_annual.csv`, columns of the hourly model only, labelled analysis-derived in the figure and in the caption).
- T1, T2 and T3 stay tables. No methodology-comparison figure and no 2022-2025 overlay in F1 (addendum Q6, Q2).
- 2050: hatched, unfilled box with a dashed outline on a grey zone, diamond for the central value, legend text `conditional range (not a confidence interval)`, in-figure note and caption sentence. The central value is plotted at the table value, which is not the midpoint of the range (D25); this is expected and a test asserts both facts.
- The figure-text check (`check_text`) removes the exact literal `not a confidence interval` and applies `results_writer.FORBIDDEN_LANGUAGE` to the rest. The exception exists only because the phrase denies confidence-interval semantics (D24); it is a literal, it is case-sensitive, and it lives in `figures.py`, so the table / column filter in `results_writer` is untouched (a test proves it still rejects the phrase in a table).
- `docs/limitations_summary.md` is produced by the Task 16 mechanism (`python -m curtailmit.doc_generation --check|--write`; blocks `limitations-themes`, `limitations-appendix`, `limitations-row-caveats`), with the fixture-based CI check and the integration test against the live production table that Task 16 delivered. No second mechanism was built.

**Not testable automatically (manual checklist, in the Task 13B report):** whether V1 reads as "not an interval" to a person; legibility at 90 / 190 mm; label overlap; greyscale and colour-blind rendering; opening the PDF / SVG / PNG; the DeCarbon author guide.

---

## Task 13B-finalize - DeCarbon raster specification confirmed (2026-10-27)

Appended; everything above is unchanged (the "PROVISIONAL" wording of the previous status section is superseded for the entries below, not rewritten).

**Provenance, stated honestly:** the specification below was retrieved by the user from the DeCarbon author guide and supplied to the project as a text excerpt (source: user-provided excerpt, not a URL). It was not fetched or verified by the project tooling, and the guide itself was not re-read; the earlier automated fetch had returned HTTP 403 (section 1.4).

| item | confirmed specification |
|---|---|
| halftone art (bitmap) | 300 DPI |
| combination art (line plus continuous tone / shading) | 500 DPI |
| line art (pure line / text, no shading) | 1000 DPI |
| single column | 90 mm |
| 1.5 column | 140 mm |
| double column | 190 mm |

**Deliberate conservative choice.** The figures combine hatched and tinted regions with line work, which is ambiguous between "combination" and "line art". The ambiguity is removed rather than classified figure by figure: the strictest category (line art, **1000 DPI**) is applied uniformly to every PNG (`figures.PNG_DPI`). The submission master is expected to be the vector PDF / SVG, which is resolution-independent; the PNG is a conformance / convenience copy.

**Column assignment (a layout judgment, re-renderable without touching any data):** `figures.FIGURE_WIDTH_MM` = F1 190, F2 190 (three panels), F4 190 (three panels), S1 190 (three panels with a long legend), S2 140 (two panels). Changing an entry only re-renders.

**Still the project's own choices, not mandated by the excerpt:** font size (DejaVu Sans 7.5 pt, floor 6 pt) and the Okabe-Ito palette. They are final unless the user says otherwise and are recorded as `PROVISIONAL_STANDARDS = {font_size, color_palette}` in `figures.py`; the confirmed entries are `CONFIRMED_STANDARDS = {dpi, column_width_mm}`. `figures_manifest.json` records both.

**Automated checks added** (`src/curtailmit/figure_checks.py`, `python -m curtailmit.figure_checks`; tests in `tests/test_figure_checks.py`): text bounding-box overlap and text leaving the figure, legend over data, every plotted number against the source tables (rtol 1e-12), no placeholder text, units on y labels, no OM + CM wording, no hydrogen content (D30 stays a table), forbidden vocabulary with the single approved literal. These do not replace looking at the figures.

## Task 13B - review decisions (2026-10-27)

Appended. The user reviewed the figures and decided:

- **Figure set unchanged**: F4 stays as it is (all three panels, the user likes it); F1 stays a main figure. The proposal to drop F4 panel (c) or to move F4 to a supplement was not taken. The question whether F1 could go to the supplement instead was answered with a recommendation against (F1 is the headline quantity of which F4 is a derived deficit), left as the user's editorial call.
- The sentence in the manuscript text explaining why the 2025 central value (a PTE scenario) is not the 2025 observation is accepted as the way to handle that point; F1 keeps no history overlay (addendum Q2 stands). The "wind hours" remark for F2 panel (a) is left as is; font size 7.5 pt and the Okabe-Ito palette are kept.
- **PNG only.** `figures.OUTPUT_FORMATS = ("png",)`: no PDF or SVG is generated, and the existing PDF and SVG of F1, F2, F4, S1 and S2 in `DATABASE_ROOT/outputs/figures/` were deleted. This supersedes the earlier expectation that the vector files would be the submission master: the 1000 dpi PNG (the line-art minimum, applied to every figure) is now the only figure file, and the `_data.csv` / `_caption.txt` companions remain. Re-enabling vector output is a one-line change to `OUTPUT_FORMATS`. The older analysis-prototype files (`fig_insample_coverage.*`, `task11*`) were not touched.

## Task 17 Part 0 - vector output restored (2026-10-28)

Appended. The "PNG only" decision of the review section above is reverted at the user's request: `figures.OUTPUT_FORMATS = ("pdf", "svg", "png")`. PDF and SVG are the preferred / master formats (resolution-independent, better for line- and text-heavy figures); the 1000 dpi PNG stays as the raster conformance copy. The DeCarbon dpi table applies to bitmap submissions only. Note on the record: the PNG-only change (commit `6fd6394`) followed the user's instruction of that review message; it is reverted by a later instruction, not because it was a misreading. The five figures were regenerated in all three formats. The analysis-prototype files (`fig_insample_coverage.*`, `task11*`) were not touched.


## Task 17 housekeeping - PNG only again (2026-10-28)

Appended. At the user's request `figures.OUTPUT_FORMATS = ("png",)` again (the "vector restored" section above is superseded for the formats), the PDF / SVG files were deleted from the local figures folder, exploratory analysis PNGs were moved to `outputs/figures_exploratory/`, and the analysis scripts no longer write PDF / SVG. The 1000 dpi PNG is the only figure file; the `_data.csv`, `_caption.txt` and `figures_manifest.json` companions remain.
