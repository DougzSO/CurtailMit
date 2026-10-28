# Acceptance criteria - status against the production pipeline

Task 15 (documentation-sync audit finding 11). The acceptance criteria of `docs/roadmap.md` section 7 were written in v3.1, before the production model changed (D24: hourly Option E; D27: long-format `final_results`). This table states, for each criterion, whether it is met, by which artifact, and where the criterion applies differently to the production table. The original criteria text in the roadmap is unchanged. Every test named below exists (a test checks it).

| # | Criterion (roadmap section 7) | Status | Evidence | Note |
|---|---|---|---|---|
| 1 | P(s,t) = solar_pct + wind_pct <= 100 for every s,t of the PTE table | **Met** | `tests/test_validation.py::test_penetration_ceiling_rejects_over_100`, `tests/test_schemas.py`; `curtailmit-run` pre-check (`load_config`) | Checked before any download on every run. |
| 2 | If Stage 1 falls back to the unclassified series, `classification_available: false` is explicit and propagated by every later stage | **Met** (fallback not triggered) | `tests/test_ons_classification.py::test_aggregate_only_branch_sets_flag_false_and_leaks_no_classified_field`, `tests/test_final_results.py::test_unclassified_wording_has_no_deb_reb`; `final_results` column `classification_available` | The classified series is available; the production table carries `classification_available = True` on every row. |
| 3 | If Stage 1 cannot confirm MCTI sources against a minimum coverage window it fails explicitly | **Met** | `tests/test_validation.py::test_mcti_coverage_rejects_missing_years`, `tests/test_mcti_client.py::test_incomplete_required_year_fails_explicitly`, `tests/test_stage1.py::test_step_failure_writes_a_fail_report_and_stops` | A Stage 1 FAIL stops `curtailmit-run` with exit code 2. |
| 4 | Every interpolated year used in a figure/table is labelled as such | **Met by construction** for the production table | `tests/test_final_results.py::test_production_table_has_no_interpolated_years_and_no_2020_row_and_carries_the_classification_flag`; legacy labelling: `tests/test_projection.py::TestInterpolateSeries::test_non_anchor_years_labeled_as_interpolated` | `final_results` has 12 scenario-years (2025, 2030, 2040, 2050), no interpolated year; `is_interpolated` is False on every row. Figures (Task 13B) must keep this label if they ever interpolate. |
| 5 | 2020 is tagged `source: historical_ons`, never `pte_projection` | **Superseded (D35), not unmet** | Decision D35 (`config/discovered_sources.yaml`); superseding evidence: the Task 11E2 backtest / holdout validation (`docs/task11e2_findings.md` section 2); where a 2020 point is still built (legacy `projection.py` anchors) the tag is enforced: `tests/test_projection.py::TestBuildAnchorPoints::test_2020_tagged_historical`, `tests/test_projection.py::TestAnchorPointValidation::test_2020_must_be_historical` | A single 2020 anchor is replaced as historical validation by the 11E2 backtest against observed ONS curtailment for 2023-2026 (in-sample, leave-one-year-out and train-on-earlier-years schemes, benchmarked against the national-P and time-trend alternatives), which tests the model on several observed years instead of one point. No 2020 row is added to `final_results` (production table: 2025/2030/2040/2050). The backtest evidence includes a downward bias in the latest years (recorded as D25). D35 is a pipeline decision; whether article figures show historical context is an editorial choice deferred to Task 13B. |

## Related statements that replaced older roadmap wording

- "5 anchor points per scenario" (roadmap section 7, methodology 3.7) -> the production table has 4 projection years per scenario (D2 grid without the 2020 anchor); see criterion 5.
- "Calibrated C(P) parameters produced by Stage 2" (roadmap section 8) -> the fitted parameters are the four hourly curves `processed/hourly_curve_{wind,solar}[_L1].json` (see `docs/methodology.md` section 2.3j for the values).

## Task 16 (documentation generation, stamp pre-filter)

Task 16 does not correspond to any of the five acceptance criteria of `docs/roadmap.md` section 7: it adds generated documentation blocks (`curtailmit.doc_generation`) and a hashing pre-filter (`curtailmit.hash_cache`), neither of which changes a result. The table above is unchanged.

## Task 13B (figures)

Criterion 4 is tied to figures. `curtailmit.figures` refuses a `final_results` table that carries an interpolated row (`check_final_results`; test `test_guards_refuse_interpolated_rows_missing_cells_and_invalid_tables`), which supports the criterion, but **no status in the table above is changed**: Task 13B is implemented and not accepted (user visual review of the V1 style and of the output figures, and confirmation or waiver of the DeCarbon figure standards, are pending). Revisit this table when 13B is closed.


## Task 17 (context figures)

Task 17 does not correspond to any of the five acceptance criteria of `docs/roadmap.md` section 7: it adds context figures built from observed data and calibration outputs (C1, C1S, C2) and the local-only boundary data they need. No production table value changes and no status in the table above is changed. (Task 13B remains implemented but not closed.)

## Status of the figure tasks (Task 17-4)

Tasks 13B and 17 are **implemented but not formally closed or accepted**: both await the user's final visual sign-off on the figure files themselves. No status in the table above is changed.

- **Task 13B, pending sign-off:** F1 (mitigation deficit), F2 (support), S1 (band vs supplement), S2 (backtest).
- **Task 17, pending sign-off:** C1 (observed curtailment map, 2025), C1S (observed curtailment by year), C2 (dose-response).
- Figure C3 does not exist: decision D37 (regional allocation of the projection) was rejected in Task 17-3.
