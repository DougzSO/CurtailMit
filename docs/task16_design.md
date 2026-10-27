# Task 16-1 - Design: documentation generation infrastructure and stamp metadata pre-filter

**Status: PROPOSAL, awaiting explicit approval.** Design only: no `src/`, `tests/`, `config/`, workflow or dependency file was changed. Implementation is Task 16, contingent on the answers to the questions in section 9. It also absorbs the generator half of `docs/task13b_design.md` question 5 (the `limitations_summary.md` generator and the YAML `limitation:` / `theme:` fields were deferred there to this task).

Read for this design: `src/curtailmit/{decision_registry,provenance,pipeline,limitations,results_writer,run_manifest}.py`, `config/discovered_sources.yaml` (D13-D35), every file in `docs/` and `README.md` (searched for hand-copied decision, stage and limitation content), the production tables in `curtailmit_database`, and a timing of the real raw tree (section 8).

---

## 0. Stop-and-report findings (fired; nothing was fixed in this task)

**F-1. Already-drifted statements (silent drift found by the Part A.1 audit).**

| where | stale statement | truth today | kind |
|---|---|---|---|
| `README.md` line 54 | "decision register D1-D34" | the generated register has 35 rows (D35 added in Task 15-3) | hand-typed range |
| `docs/reproducibility.md` line 88 (heading `## 7. Decision register D1-D34`) | "D1-D34" | 35 decisions | hand-typed range, outside the generated block |
| `src/curtailmit/decision_registry.py` (module docstring) | "Generated decision register D1-D34" | generic | code docstring |
| `docs/limitations.md` line 35 | "`limitations_summary.md` is generated in Task 13B" | decided in the 13B-1 addendum: generator and fields belong to Task 16 | stale pointer |
| `docs/orchestration.md` line 7 | sequence ends "... reference-value check -> summary" | the code and `README.md` / `docs/reproducibility.md` add the run-manifest step | stage sequence copied by hand in 4 places, not all updated |
| `docs/claude_commands.md` line 386 (Task 13 prompt) | `limitations_summary.md` under `outputs/reports/` | design says `docs/limitations_summary.md` | historical prompt (append-only; informational) |

These are exactly the failures the generated documents are meant to prevent; none was corrected here. The first four and the orchestration line are small mechanical or stale-marker fixes under the Task 15 rules and can be done in Task 16 with your approval (question 2).

**F-2. The brief's premise about D1-D22 is partly inaccurate.** `config/discovered_sources.yaml` already contains **D13-D35** (D13 at line 174, D22 at line 510 before D23). Only **D1-D12** are not in the YAML (they live in the `docs/roadmap.md` decision table and its "Decision D12" section, and the register reads them from there). The question of "backfilling" therefore concerns D1-D12 only (section 6).

**F-3. A status inconsistency that matters for the limitations page.** D21 and D22 (the national-curve formulation) are `status: adopted` in the YAML, while D24 states that the national and regional formulations are "retained as documented reference / comparison points ... NOT the adopted production model". The registry statuses allow `superseded` and `reference_only`, but neither D21 nor D22 carries them. A limitations page must not present retired-model decisions as limitations of the production model, so Task 16 cannot decide this silently: question 3.

**F-4. A duplicated literal in code (drift-prone, not yet drifted).** `results_writer.limitations_text` writes "+1.4 to +1.6 pp per year over 2022-2026" and "phi 1.5 to L=1" as string literals, while `limitations.D25_QUANTIFIED` holds the same numbers separately and the YAML D25 text holds them a third time. Tests tie two of the three (`test_projection_hourly.py` asserts the D25 figures appear in the text; `test_final_results.py` asserts the row text contains the string), so there is no drift today, but a change to one place does not force the others. Proposed in section 4.4.

**F-5. A generated document that is tracked and unchecked.** `docs/stage1_data_quality_report.md` is written by `data_ingestion.run_stage1` on every Stage 1 run, contains a run timestamp, and is committed. It is regenerated from live data (not from a repository source), so it cannot be verified by `--check`; and each real run dirties it in git. It is outside the generation mechanism (category (d), section 3) but the tracking is worth a decision (question 4).

**F-6. Adding fields to the YAML changes the decision hashes** (section 5.4): `provenance.decision_hashes` hashes the whole entry, so adding `limitation:` / `theme:` to D23-D35 would invalidate the stage stamps once. The recompute is byte-identical (proven for D24 in Task 15) but avoidable; proposed fix in 5.4.

**Triggers not fired:** no existing manual narrative text has to be deleted to fit the marker structure (every proposed block replaces only a table or list that is already generated or purely derived); no decision failed to fit the 9 themes, but D34 (reproducibility scope) fits none cleanly, and a tenth theme is proposed rather than force-fitting it (section 5.3).

---

# Part A - Documentation generation infrastructure

## 1. Inventory of hand-duplicated information

Sources audited: (S1) `config/discovered_sources.yaml`, (S2) the production results table (`known_limitations`, `known_limitations_text`, `support_status`), (S3) the pipeline stage list (`pipeline.STAGES` / `SPECS`, plus the pre-check, reference check and run manifest steps that are hard-coded in `run_pipeline`).

| # | duplicated item | source | where it is copied by hand | drift today | realistically generatable |
|---|---|---|---|---|---|
| 1 | decision register D1-D35 (id, topic, status, where decided, implemented in) | S1 + roadmap | `docs/reproducibility.md` | none inside the block (generated and tested); the *range label* "D1-D34" drifted (F-1) | **already generated** (Task 15) |
| 2 | decision range label "D1-Dn", "D13 onward" | S1 | `README.md:54,61`, `docs/reproducibility.md:88,90`, `docs/roadmap.md:3,320` (history), `docs/progress_log.md:229` (history), code docstring | **yes** (F-1) | yes, but better removed (section 3) |
| 3 | decision *summaries* in prose | S1 | `docs/reproducibility.md` section 5 ("D23 fixes the basis ..."), `docs/methodology.md` 2.3j / 2.3k, `README.md` model paragraph | none found; every sentence checked against the YAML status; they will drift when a decision changes | **no**: they are narrative; link to the register instead |
| 4 | per-decision limitation statements | S1 | `docs/methodology.md` 3.7 (append-only, partly stale by design), `docs/limitations.md` pointers, `docs/pre_submission_checklist.md` | `limitations.md:35` stale pointer (F-1) | **yes**: this is the `limitations_summary.md` generator (section 4) |
| 5 | limitation caveat texts of the output rows (5 distinct strings; ids `D25;SOLAR_SHORT_RECORD`) | S2 | `docs/task13_design.md` (historical), `docs/data_dictionary.md` (describes the columns, not the text), the sidecar `final_results.parquet.limitations.json` | design text calls it "a fixed one-sentence summary", the real text is a multi-sentence paragraph (historical document, not corrected) | yes, as part of section 4 |
| 6 | support-status rule and meaning (`within_support` / `partially_out_of_support` / `mostly_out_of_support`) | `projection.support_status` | `docs/task11f_design.md`, `docs/task13_design.md` (historical), `docs/data_dictionary.md` | consistent (rule E_out >= 0.50 / E_out >= 0.30 or H_out >= 0.10) | partly: thresholds could be generated into the data dictionary; low value |
| 7 | stage sequence "pre-check -> Stage 1 -> hourly calibration -> Option E projection -> final results -> reference check -> run manifest" | S3 | `README.md:38`, `docs/orchestration.md:7`, `docs/reproducibility.md:66`, `docs/data_dictionary.md:87` (stage names), `docs/roadmap.md:308` (history), `docs/claude_commands.md:516,522` (history) | **yes**: `orchestration.md:7` lacks the manifest step (F-1) | yes, **after** the sequence becomes an explicit constant in `pipeline.py` (today the pre-check, reference check and manifest are inline code, not a list) |
| 8 | stage names in stamp file names | S3 | `docs/data_dictionary.md:87` | consistent | yes (same constant) |
| 9 | CI job list, test counts, row counts (156, 250 files, ...) | CI file / tables | README, reproducibility, orchestration | consistent today; counts like "156 rows" would drift if the scenario grid changed | not proposed: pinned by tests (`test_docs_sync`, `test_final_results`) already |

Outside the three named sources (listed because they are generated or checked already): `data_snapshot_manifest.json` (tool-generated, verified by `run_manifest verify`), `requirements.lock.txt` (generated by `pip freeze`, checked by `test_environment_lock`), `docs/stage1_data_quality_report.md` (F-5).

## 2. One mechanism: `src/curtailmit/doc_generation.py`

**Proposal: a single module, one command, one marker syntax, a registry of per-block generator functions.** Generalise the Task 15 convention (`--write` / `--check`, markers, a test that fails when the document differs from the generator output) instead of adding one module per document.

```
python -m curtailmit.doc_generation --check            # all blocks; exit 1 when any is stale, 2 on a source error
python -m curtailmit.doc_generation --write            # regenerate all blocks
python -m curtailmit.doc_generation --check --only decision-register,limitations-themes
python -m curtailmit.doc_generation --list             # block id -> document -> sources -> needs_database
```

Layout:

- `Block(id, document, render, sources, needs_database)` dataclass and a module-level registry `BLOCKS`. `render(ctx) -> str` receives a `Sources` object that loads each source once, lazily: the YAML (strict duplicate-key loader, moved from `decision_registry`), the roadmap decision table, the pipeline sequence constant, and the limitation-text fixture (section 4.3).
- A document is either **partial** (blocks between markers inside a hand-written file) or **fully generated** (the whole file; first line carries the generated header). One writer, one comparer, shared by both: the existing `_read` / LF-normalising comparison is kept (git autocrlf already handled in Task 15).
- `decision_registry.py` stays as the **source-reader and renderer** of the register (`collect`, `render`; its tests stay valid), and becomes one registered block. Its `python -m curtailmit.decision_registry` CLI is kept as a thin alias for one release so the commands quoted in `README.md` and `docs/reproducibility.md` keep working; the docs are then updated to the new command.
- New generator functions live in the same module, grouped by source: `render_limitations_*` (section 4), `render_pipeline_sequence`. If the module grows beyond roughly 400 lines it splits into `doc_generation/` (core) and per-document modules; not needed at the start.

Why a new module rather than extending `decision_registry.py`: that module's name and CLI promise "the decision register"; the second consumer (limitations) needs the same writer, marker handling and check, so the shared part has to move out of it anyway. Why a registry rather than one file per document: a new generated block then costs one function and one marker pair, and the single `--check` covers all of them in CI.

**No templating dependency.** Every generated block in sections 1-4 is a table, a list or a short sequence of paragraphs assembled from dictionaries. Plain f-strings and `"\n".join` (the existing `decision_registry.render` style) are sufficient; Jinja2 would add a dependency, a lock-file entry and a second language to review for no capability the blocks need. Revisit only if a block needs conditionals over nested structures that exceed what `render` functions can express readably; that is not the case in this design.

**Marker syntax (HTML comments, invisible in rendered Markdown):**

```
<!-- GENERATED:BEGIN id=decision-register sources=roadmap.md,discovered_sources.yaml
     do not edit by hand; regenerate with: python -m curtailmit.doc_generation --write -->
... generated content ...
<!-- GENERATED:END id=decision-register -->
```

Rules: the id must be registered; BEGIN and END must pair and not nest; a block id appears once in the repository; the generator replaces only the text between the pair; a document with a registered block but no markers, or markers with an unregistered id, is an error (not a silent no-op). The existing `<!-- DECISION-REGISTER:START/END -->` markers are replaced by the new pair in the migration commit (a mechanical edit of `docs/reproducibility.md`, the only document that carries them). Fully generated files start with `<!-- GENERATED:FILE id=... -->` on the first line instead of a pair.

## 3. Classification of documents

**(a) Fully generated, CI-checked:** none initially. `docs/limitations_summary.md` is proposed as (b), not (a), because the user's item 6 asks for a hand-written historical section for D1-D12 inside it (section 6). A pure (a) document would be an index that has no narrative to protect; none currently exists. The mechanism supports (a) when one appears.

**(b) Partially generated (hand-written frame, generated blocks):**

| document | block id | content | needs database |
|---|---|---|---|
| `docs/reproducibility.md` | `decision-register` | D1-Dn table (exists) | no |
| `docs/reproducibility.md`, `docs/orchestration.md`, `README.md` | `pipeline-sequence` | the stage sequence line, from the constant in `pipeline.py` | no |
| `docs/limitations_summary.md` | `limitations-themes`, `limitations-row-caveats`, `limitations-decision-appendix` | sections 4.1-4.2 | `row-caveats` uses the committed fixture, not the database (4.3) |

Whether the sequence block goes into all three documents or only into `orchestration.md` with the others linking to it is question 5. Preferred principle, stated once: **remove a duplicate where a link does the job, generate it only where the reader needs the content in place.** Under that principle the range labels "D1-D34" (README line 54, reproducibility heading) are not generated: they are reworded to not carry a number ("decision register"), since a count in a heading adds nothing the table does not already say.

**(c) Left manual / narrative:** `docs/roadmap.md`, `docs/progress_log.md`, `docs/claude_commands.md`, `docs/methodology.md`, the `task*_design.md` and `task*_findings.md` files, `docs/acceptance_criteria_status.md` (hand-written evidence map, already checked by `test_docs_sync`), `docs/pre_submission_checklist.md`, `docs/limitations.md` (a short pointer page). Reason: they are the project's append-only history (Task 15 rule); the facts they quote were true when written, are superseded by dated update notes rather than rewritten, and a generator would erase that history. Their current-state counterparts are `docs/reproducibility.md`, `README.md` and the generated blocks.

**(d) Run reports, outside the mechanism:** `docs/stage1_data_quality_report.md` and similar outputs of a live run. They depend on live data, not on a repository source, so `--check` cannot verify them (F-5, question 4).

**Reconciliation with append-only (stated explicitly).** The Task 15 rule protects narrative text from being rewritten so that its history stays readable. A generated block is not narrative: it is a *view of the current state of a structured source*. Regenerating it can only change it to reflect that source, and the generator writes only between its own markers, so the surrounding narrative is untouched byte for byte (a test asserts that text outside every marker pair is unchanged by `--write`). The history of a block is the git history of its source plus the commit that regenerated it. Two limits keep this honest: (1) no block is placed inside a document of category (c), so no append-only history ever contains a block whose content silently changes; (2) a generated block states "current" (it carries the marker comment and, where useful, the source commit date), and narrative text that wants to quote a value *as of a past date* stays outside the block.

## 4. `limitations_summary.md` generator

### 4.1 Structure (absorbing the Task 13B-1 proposal)

`docs/limitations_summary.md` is a category (b) document: a short hand-written frame (what the document is, how to read it, the historical D1-D12 section of item 6, the cross-reference to `docs/pre_submission_checklist.md`) around three generated blocks.

1. **`limitations-themes`** - the main body, one subsection per theme (vocabulary in 5.3), in a fixed theme order. Each subsection lists the limitation statements of the decisions that feed it (decision id, status, the `limitation` text, link to the decision in the YAML), then the cross-reference to the longer prose in `docs/methodology.md` (the section pointer is part of the theme definition, not generated prose).
2. **`limitations-row-caveats`** - "Caveats carried by the output rows": the distinct `known_limitations_text` strings of the production table, verbatim, each with the scenario-years it applies to and the `known_limitations` ids mapped to their decisions / named notes (`D25`, `SOLAR_SHORT_RECORD`, `D26_NOTE`).
3. **`limitations-decision-appendix`** - per decision D23-D35 (and D13-D22 where fields exist): id, status, theme(s), and either the limitation text or "no reader-facing limitation: <reason>".

### 4.2 Dual-source nature, and what "can never disagree" means

The document is **not** a function of the YAML alone. Its sources are: **(A) the YAML decisions** (`status`, `limitation`/`theme`, the decision text), and **(B) the production results table** (`known_limitations`, `known_limitations_text`, `support_status`). With two sources, "the document and its sources can never disagree" has to be spelled out as four separate guarantees, each with its own test:

1. **Document = f(sources).** The committed blocks equal what the generator produces from (A) and (B). Checked in CI by `--check`.
2. **(A) is internally consistent.** Every adopted decision in scope has a limitation statement or an explicit "none" with a reason; numbers in a `limitation` text occur in the same decision's adopted text; only `adopted` decisions are rendered as limitations of the production model.
3. **(B) is what the code produces from (A).** The row texts come from `limitations.py` / `results_writer.limitations_text`, which read the YAML (D25 adopted text, `D25_QUANTIFIED`); a test ties every number in a row text to the D25 text of the YAML (closing F-4).
4. **(A) and (B) agree with each other.** Every `known_limitations` id present in the table maps to a decision or a named note in the document, and no limitation text of the YAML contradicts a row text (the shared numbers are checked mechanically; contradiction in wording is not checkable, see section 7).

Guarantee 1 must hold in CI, where the database does not exist. The table-derived input is therefore reduced to a small committed fixture, in the same spirit as `tests/fixtures/final_results/reference_totals.json`: `tests/fixtures/final_results/limitation_texts.json` holds the distinct `known_limitations_text` strings, their ids, and the scenario-years they apply to (5 strings, 156 rows). CI generates the block from YAML + fixture. Guarantee 3/4 against the *real* table is an **integration test** (needs the local database): the fixture must equal what `final_results.parquet` contains now; `curtailmit-run`'s existing reference check is not extended (it is a numeric check), but `python -m curtailmit.doc_generation --check` run locally with the database present also compares the fixture to the live table and fails when the table has moved on. This is the honest limit: the table-vs-fixture comparison can only happen where the table exists.

### 4.3 What stays out of the generator

The licensing item (D33's data-availability limitation is generated from its `limitation` field, which states that the ONS/MCTI terms are *not verified*) is cross-referenced to `docs/pre_submission_checklist.md` by a fixed link in the frame; the checklist stays manual. A test asserts the D33 limitation text contains "not verified" so the generated page cannot be read as a clean bill.

### 4.4 Code change that closes F-4

`results_writer.limitations_text` builds its sentences from `limitations.D25_QUANTIFIED` and one named constant for the 2050 flexibility wording, instead of literals; the existing tests keep passing and a new test asserts each number in the row text occurs in the YAML D25 text. No change to the output table text (the five strings stay byte-identical), so `final_results` and the reference check are unaffected; this is verified by the reference check in the acceptance criteria of Task 16.

## 5. Schema additions to `config/discovered_sources.yaml`

### 5.1 Fields

Additive metadata only: `status`, `implemented_in`, `decided` and every other existing key are not touched. For D23-D35:

```yaml
  D25:
    ...existing keys unchanged...
    theme: drift                       # slug from the fixed vocabulary (5.3)
    limitation: >                      # 1-3 sentences, reader-facing, English
      Central values are more likely low than high: the wind curtailment rate at a fixed hourly VRE share drifts upward by +1.4 to +1.6 pp per year (2022-2026) and the drift is not corrected.
```

For a decision with no reader-facing limitation: `limitation: none` and `limitation_reason: "<one line>"` (for example D27: "output schema decision"; D31: "orchestration scope"; D32: "CI test isolation"). A decision that feeds more than one theme (D24 feeds support-extrapolation and flexibility-transmission; D28 feeds emission-factors and support-extrapolation) needs more than one (theme, text) pair. The brief names singular fields; two shapes are possible (question 6):

- **S1 (as named in the brief):** one `theme` and one `limitation` per decision; a decision with several limitations carries them as separate sentences under its primary theme, and the other themes cite it by id only.
- **S2 (recommended):** `limitations:` as a list of `{theme, text}` pairs, with `limitation: none` + `limitation_reason` for the empty case. Equivalent for single-theme decisions, and no sentence is filed under a theme it does not belong to.

### 5.2 Validation (a schema check in `doc_generation`)

Rejected with a named error: unknown theme slug; `theme` without `limitation` or the reverse; both a `limitation` text and `limitation: none`; an empty text; `limitation: none` without a reason; an adopted D23-D35 entry without either; a limitation on a decision whose status is not `adopted`; a number in the text absent from the decision's own text (the `D25_QUANTIFIED` pattern); a key outside the allowed set among the new keys (typo guard). D13-D22 entries may carry the fields (5.5) but are not required to.

### 5.3 Theme vocabulary (fixed list, a constant in the module)

| slug | theme | decisions feeding it (proposed) |
|---|---|---|
| `drift` | residual drift of the wind curtailment | D25 (D24, D35 cite it) |
| `support-extrapolation` | extrapolation beyond the observed support; TA 2040 partial support; 2050 conditional range | D24, D28 |
| `flexibility-transmission` | today's flexibility held fixed; transmission expansion not modelled | D24, D26 |
| `solar-record` | short solar record | D14 (record start), D24 |
| `generation-basis` | PTE generation basis, gross vs net | D16, D20, D23 |
| `emission-factors` | OM/CM as proxies, never summed; factor year | D12 (narrative), D18, D28, D29 |
| `hydrogen-sec` | fixed SEC and its range | D30 |
| `data-provenance` | data availability, licensing, snapshot manifest | D33 |
| `historical-validation` | backtest in place of a 2020 anchor | D35 |
| `reproducibility-scope` *(proposed new, see below)* | what reproducibility promises and does not | D34 |

**Stop-and-report outcome:** nine themes fit D23-D33 and D35; **D34 does not fit cleanly** (its reader-facing content is "bitwise identity is not promised across platforms; the promise is the 1e-9 reference check", which is about reproducibility, not data provenance). A tenth theme `reproducibility-scope` is proposed instead of forcing D34 into `data-provenance`. Decisions D27, D31, D32 are `none` with reasons. Adding a theme later is a one-line change to the constant plus a theme section title; the validator rejects use of an unlisted slug, so a new decision that does not fit stops the check (the trigger is built into the tooling).

### 5.4 Interaction with the stage stamps (F-6)

`provenance.decision_hashes` hashes the *whole* decision entry (`json.dumps(sort_keys=True)`), so adding the fields to D24, D25, D26, D23, D27-D30 invalidates the calibration, projection and results stamps once (and, if fields are added to D14, D18, D20, D22, the Stage 1 stamp too). The recompute is byte-identical (as for the D24 text edit in Task 15) but wasteful, and it means a wording change to a documentation-only field would force a recompute forever. Proposed, in this order inside Task 16:

1. Add to `provenance.decision_hashes` an explicit `DOC_ONLY_KEYS = {"theme", "limitations", "limitation", "limitation_reason"}` that is **excluded** from the hash. The default stays conservative: a key not on that list is hashed, so a new key invalidates stamps until someone deliberately lists it. A test asserts the list is exactly this set and that adding a doc-only key does not change the hash while changing `decided` does.
2. Implementing step 1 first changes no existing hash (no entry has these keys yet), so the stamps stay valid; then the fields are added, still no recompute.

This touches the fingerprint semantics of Task 14, so it is flagged for approval (question 7). Without it, the cost is one verified recompute.

### 5.5 D13-D22

Optional fields. Recommended for those that feed live themes: D14 (solar record), D16 (generation basis), D18 (emission factors), D20 (generation basis, MMGD). D21 and D22 are `none` with the reason "superseded as primary model by D24" **only if** their status question (F-3) is resolved first.

## 6. D1-D12 (and the D1-D22 question)

Per F-2 the real gap is D1-D12. **Recommendation: option (a), a hand-written historical section** in `docs/limitations_summary.md` (and nothing in the YAML): "Earlier decisions (D1-D12, recorded in `docs/roadmap.md`)", listing only those that carry a standing limitation (D12: OM/CM are proxies of the marginal factor; D1/D2: the grid of projection years; D3-D11 as the roadmap table says) as one sentence each with a link to the roadmap row. It is marked as manual, outside the generated blocks, and states that it is not machine-checked against the roadmap.

Reasons against (b), backfilling D1-D12 into the YAML: D34 decided explicitly not to; the roadmap entries are one-line changelog rows plus the D12 section, so a backfill would require *authoring* "decided" texts, which is rewriting how settled decisions read; and the register already covers them by reading the roadmap. This is a decision about how settled decisions read, so it is flagged for confirmation (question 8) although the recommendation is the conservative one.

## 7. Test plan (Part A)

**Unit-testable (CI, no database):**

- every block: `render(sources)` equals the committed text (`--check`), for the decision register, the pipeline sequence, and the three limitations blocks (generated from the YAML + fixture);
- marker handling: pairing, nesting, duplicate id, unregistered id, missing markers, text outside markers unchanged by `--write` (byte comparison), `--write` idempotent, LF/CRLF both accepted;
- migration: the old register block text equals the new block's body (no content change in the migration commit);
- YAML schema (5.2): each rejection case, with synthetic YAML; the real YAML passes; every adopted D23-D35 has fields or an explicit `none` + reason (this is the "missing field detection" test: removing the fields from one entry fails the suite);
- limitation numbers occur in the decision text; D25 numbers equal `D25_QUANTIFIED`; row-text numbers (F-4) occur in the YAML D25 text;
- the D33 limitation says "not verified"; no non-adopted decision is rendered; the forbidden-language filter (`results_writer.FORBIDDEN_LANGUAGE`) is applied to the generated limitations text (it contains no "confidence" wording except the one allowed negation phrase of the 13B-1 addendum, if quoted);
- fixture: five strings, ids resolvable, total scenario-years = 12;
- `decision_registry` tests keep passing unchanged.

**Integration (local database):** fixture equals the live `final_results.parquet` texts; `--check` with the database present passes.

**Needs human reading (not unit-testable):** whether the by-theme page is readable and well ordered, whether each `limitation` sentence is accurate and not overstated relative to the decision text (the number check catches wrong digits, not wrong claims), whether the historical D1-D12 section is complete, and whether the theme names read well to the DeCarbon audience.

---

# Part B - Stamp metadata pre-filter

## 8. Design

**Where the cost is.** `provenance.tree_hashes` / `file_hashes` read every input and output file in full whenever a stage is considered (`decide` before the stage; `compare` re-hashes the outputs; `write_stamp` hashes after a stage ran). Measured on the real tree (500 files, 509,060,937 bytes): **16.75 s cold (disk), 1.21 s warm (OS cache), 0.05 s for `stat` alone.** A full no-op run decides four stages, so the raw tree is hashed at least at Stage 1 and again for the calibration panel inputs. The gain is therefore real only on cold caches (first run of a session, slow disk) and a modest ~1 s per repeat run on a warm cache; the user approved the optimisation, and this is stated so the cost-benefit is on the record (question 9).

**What it is.** A cache that answers one question: *"do I have to read this file to know its hash?"* It never answers *"has the stage changed?"*.

**Storage: one separate cache file, not the stamps.** `processed/pipeline_stamps/hash_cache.json`, schema 1, shared by all stages (the raw tree is hashed by two stages; outputs of one stage are inputs of the next). The stamp format (schema 1) is **not changed**, so existing stamps stay valid and no stage recomputes because of this change. (The alternative, extending each stamp with size/mtime per entry as a stamp schema 2, was rejected: it duplicates entries across the four stamps and invalidates every stamp once.) Deleting the cache file is always safe (everything is rehashed).

```json
{
  "schema": 1,
  "written_utc": "2026-10-28T12:00:00+00:00",
  "guard_ns": 5000000000,
  "entries": {
    "raw/ons/curtailment/2024/file.parquet": {
      "size": 1234567,
      "mtime_ns": 1790000000123456789,
      "ino": 281474976710656,
      "sha256": "9f2c...",
      "hashed_at_ns": 1790000100000000000
    }
  }
}
```

Keys are paths relative to `DATABASE_ROOT` with `/` separators (portable if the database is moved; a copy changes mtimes, so every entry then simply misses and is rehashed). `ino` is `st_ino` (Python gives the NTFS file index on Windows; 0 where unavailable, then it is not compared). Written atomically (`tmp` + `os.replace`, like the stamps). A missing, unreadable, other-schema or malformed cache is treated as empty, exactly like `read_stamp`.

**Lookup rule** (`hash_cache.cached_sha256(path)`), applied only to files of at least 1 MiB (code, configuration and small files are always hashed; reading them costs nothing and keeps the shortcut off the files that matter most for correctness). The recorded hash is reused only if **all** hold; otherwise the file is read and rehashed and the entry replaced:

1. an entry exists for the path;
2. `st_size` equals `size`;
3. `st_mtime_ns` equals `mtime_ns` exactly (equality, never "not newer than");
4. `st_ino` equals `ino` (when both are non-zero);
5. **racy guard:** `hashed_at_ns - mtime_ns >= guard_ns` (5 s): the file had been quiet for at least the guard before the hash was taken, so a later write within the same timestamp tick cannot have gone unnoticed. An entry written for a file modified within 5 s of hashing is never trusted (the same idea as git's "racily clean" index entries); it is rehashed on the next run and, being then old enough, becomes trustworthy;
6. `mtime_ns <= hashed_at_ns` (an mtime in the future relative to the hash time, which indicates clock skew or a tampered timestamp, forces a rehash).

Newly produced outputs (`write_stamp` after a stage) are hashed for real, their entries are racy by construction, and they are therefore rehashed once on the next run before the shortcut applies. This is intended.

**What the pre-filter does not touch.** The stamp comparison (`provenance.compare`), the `Decision` logic, the conservative default, the trust blocker, the `--force-*` flags, the run manifest's raw-file verification against the retrieval sidecars (`run_manifest.raw_inventory` hashes in full: it is the authoritative provenance record written only on success, and it must not rest on a metadata shortcut; question 9 asks whether to keep that cost), and `data_snapshot_manifest.json`. A flag `--no-hash-cache` (and an environment-independent API argument) bypasses the cache entirely for one run: full hashing, cache neither read nor written. CI always runs on an empty database, so it never has a cache.

**Dependency:** none. `os.stat` / `Path.stat` are standard library; confirmed that no change to `pyproject.toml`, `requirements.txt` or `requirements.lock.txt` is needed, and the Task 15 lock tests are unaffected. The modules in the stage code fingerprints (`CALIBRATION_MODULES`, ...) do not include `provenance` or `pipeline`, so changing them does not invalidate the stamps (the new `hash_cache` module is likewise outside the lists).

## 9. Pitfalls, and precisely what this design does and does not guarantee

**Timestamp resolution.** NTFS stores 100 ns, ext4 1 ns, HFS+ 1 s, FAT 2 s, some network and container filesystems coarser or truncated values. Equality on `st_mtime_ns` is only as strong as the filesystem's resolution, and a coarse tick is exactly what makes two different writes look identical. The racy guard (condition 5, 5 s > the coarsest tick supported, FAT's 2 s) is the control: an entry is only trusted if the file was already quiet for longer than any tick before it was hashed.

**Clock skew.** `mtime_ns` is stamped by the filesystem's host, `hashed_at_ns` by the local clock. On a local disk they are the same clock. On a network share they may differ by more than the guard; condition 6 catches future mtimes but a server clock far *behind* the local clock would make the guard too lax. Supported configuration: local disk. For network shares use `--no-hash-cache`; this is documented in `docs/orchestration.md`.

**Why classic Make fails, and how this differs (stated without overclaiming).** Make decides whether to rebuild by *ordering*: a target is out of date if a prerequisite's mtime is **newer** than the target's. It trusts the clock and the ordering alone, so it fails when a prerequisite is replaced by an older file (restored backup, checkout of an older revision, `cp -p`), when clocks differ between machines, or when mtimes are coarse, and in all of those it silently skips a rebuild that was needed. This design differs in four ways: (1) the comparison is **equality with a recorded value, not ordering**, so a restored older file differs from the recorded mtime and is rehashed, which is the case Make gets wrong; (2) the **content hash** remains the only thing the stamp compares: every stage input and output that is small, that is code, config, a decision entry or a parameter, that is newly written, or whose metadata differs in any way is read and hashed in full; (3) the shortcut is allowed only after the racy and future-mtime guards; (4) `--no-hash-cache` gives a full-hash run on demand.

**What is *not* the same as the brief's wording, stated plainly.** The requirement says the metadata "only gates whether a hash is recomputed, never whether a stage is skipped". That holds for the *decision structure* (the stage compares hashes), but it is not true as a statement about *outcomes*: when the shortcut is taken, the "current hash" fed into the comparison is the cached value, so the skip decision for that file rests on `(size, mtime_ns, ino)` being unchanged. The design therefore keeps a **residual weakness of the Make family, narrowed to one case**: file content changed while size, `mtime_ns` and inode all stayed equal to the recorded values, and the recorded mtime was already older than the guard. Accidental causes are essentially limited to tools that rewrite a file in place and restore its modification time (some sync and "preserve timestamps" utilities when the new version has identical size). This is the same residual risk as git's index and rsync's default quick check, and it is accepted under the threat model below; it is mitigated, not eliminated, and `--no-hash-cache` is the way to eliminate it for a run that matters (for example before submission).

**Threat model.** The optimisation defends against **accidental staleness** (the project's actual risk: an edited, replaced, restored or partially written file whose old hash is reused). It does **not** defend against deliberate forgery of size, mtime and inode to match stale values: that is out of scope, as it is for the existing hash-only mechanism, which also cannot defend against an adversary who can edit `processed/pipeline_stamps/*.json` or the raw files together with their sidecars. The statement "the hash is authoritative" is true for every file that is hashed; the cache narrows *which* files are hashed in a given run, nothing more.

## 10. Test plan (Part B)

**Guarantees tested** (each named by what it proves):

1. **Equivalence:** with the cache disabled and enabled, `tree_hashes` / `file_hashes` return identical mappings for unchanged and for changed trees (changed content with different size; changed content with the same size and a new mtime; file added; file removed; file renamed). The cache cannot change an outcome in any case where metadata changed.
2. **The hash governs when it is consulted:** a file's content is changed while its size is kept and its mtime and inode are set back with `os.utime` (forged metadata). (a) With the cache **disabled** the change is detected: this proves the hash is the authority. (b) With the cache **enabled** the stale hash is returned: this is asserted explicitly as `test_forged_metadata_is_the_documented_residual_risk`, so the residual risk is a tested, named, documented behaviour and not a hidden one. The test does **not** claim the optimisation defends against forged metadata; it claims that bypassing it restores full detection.
3. **Racy guard:** a file modified within the guard window after being hashed (same size, same mtime tick) is rehashed on the next lookup and the change is detected.
4. **Older file restored:** replacing a file with an older-mtime copy of different content is detected (the case Make misses).
5. **Future mtime / skew:** an entry whose mtime is in the future relative to `hashed_at_ns` is rehashed.
6. **Cache failure modes:** missing, truncated, malformed-JSON, wrong-schema and unreadable cache files behave as an empty cache; deleting the cache leaves every stage decision identical.
7. **Scope limits:** files below 1 MiB, code files, config files and decision hashes never use the cache (the cache is never consulted: asserted by a counter on the stat/lookup path).
8. **Stamp and pipeline unchanged:** stamp files written with the cache enabled equal those written without it (byte-identical JSON apart from `created_utc`); a two-run pipeline test with fake stage actions gives the same skip/run decisions with and without the cache; the second run reads fewer bytes (counted through an instrumented hasher), proving the optimisation actually engages.
9. **`--no-hash-cache`:** reads no cache and writes none.

**What is not tested:** behaviour on specific filesystems (FAT, network shares, HFS+) and real clock skew, which need the platform; the 5 s guard is justified by the documented tick sizes, not by a test on each.

---

## 11. Files and commit plan (for Task 16)

New: `src/curtailmit/doc_generation.py`, `src/curtailmit/hash_cache.py`, `tests/test_doc_generation.py`, `tests/test_hash_cache.py`, `tests/fixtures/final_results/limitation_texts.json`, `docs/limitations_summary.md`. Changed: `src/curtailmit/provenance.py` (optional `cache` argument, `DOC_ONLY_KEYS`), `src/curtailmit/pipeline.py` (explicit sequence constant, `--no-hash-cache`), `src/curtailmit/results_writer.py` (F-4, string-identical output), `src/curtailmit/decision_registry.py` (CLI alias), `config/discovered_sources.yaml` (fields only), `README.md`, `docs/reproducibility.md`, `docs/orchestration.md`, `docs/data_dictionary.md`, `docs/limitations.md` (pointer), the acceptance appendix of this file. Suggested order: (1) `DOC_ONLY_KEYS` + tests; (2) YAML fields; (3) `doc_generation` core + migration of the register (no content change); (4) limitations blocks + fixture + `limitations_summary.md`; (5) pipeline sequence block; (6) `hash_cache`. Each step keeps the suite and `ruff` green; the reference check (`final_results` md5 `918fdb743d9cfebe40c4d64c60155981` at the time of this design) must be unchanged at the end.

---

## 12. Open questions for approval

1. **Mechanism.** Approve `doc_generation.py` (registry of blocks, `GENERATED:BEGIN/END` markers, plain string assembly, no Jinja2) with `decision_registry.py` kept as reader/renderer plus a CLI alias?
2. **Drift fixes (F-1).** Approve fixing in Task 16 the small drifts found: README line 54 and the `reproducibility.md` heading reworded to not carry "D1-D34", the `decision_registry` docstring, the `limitations.md` pointer, and `orchestration.md` line 7 (stage-sequence block)? The `claude_commands.md` line 386 is left (historical prompt).
3. **D21 / D22 status (F-3).** They are `adopted` in the YAML but retired as primary model by D24. Leave as is, or set `reference_only` / `superseded` (a status change on an adopted decision, which only you can authorise), or leave the status and exclude them from the limitations page with an explicit `none` + reason?
4. **`docs/stage1_data_quality_report.md` (F-5).** Keep it tracked as is, stop tracking it (add to `.gitignore`, regenerated each run), or keep tracking it but strip the run timestamp so reruns do not dirty git?
5. **Pipeline-sequence block.** Generate it in `orchestration.md` only (README and reproducibility link to it), or in all three documents?
6. **Schema shape.** S1 (singular `theme` + `limitation`, as named in the brief) or S2 (`limitations:` list of `{theme, text}`, recommended)?
7. **Stamp interaction (5.4).** Approve `DOC_ONLY_KEYS` excluded from the decision hash (conservative default kept), implemented before the fields are added, so no stage recomputes? Otherwise accept one byte-identical recompute.
8. **D1-D12.** Confirm option (a), a manual historical section in `limitations_summary.md` and no backfill into the YAML? And approve optional fields on D14, D16, D18, D20?
9. **Pre-filter cost-benefit.** Measured gain: about 1.2 s per repeat run on a warm cache, up to about 17 s cold, in exchange for the residual risk of section 9. Proceed as approved; and should `run_manifest` verification of the raw files stay a full hash (recommended), or may it use the cache?
10. **Tenth theme.** Accept `reproducibility-scope` for D34, or fold D34 into `data-provenance`?
