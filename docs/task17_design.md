# Task 17-1 - Design: context figures (observed-curtailment map C1, dose-response curve C2) and the framing of a projected regional map

**Status: PROPOSAL, awaiting explicit approval.** Nothing in this document is implemented beyond Part 0 (the vector-output fix, section 0). No map code, no new dependency, no new data copied into `curtailmit_database`. Two decisions were registered as `status: pending` in `config/discovered_sources.yaml`: **D36** (geometry source and vintage, low stakes) and **D37** (spatial disaggregation rule for a projected map, high stakes).

Sources of the findings below: a file-system search of `D:\Douglas\DOUTORADO\GeoFREA_data\raw` and `D:\Douglas\OUTROS`; the raw ONS curtailment files and `processed/` tables in `curtailmit_database`; `src/curtailmit/{hourly_model,figures,figure_checks}.py`; `docs/task13b_design.md`.

---

## 0. Part 0 - vector output restored (done, separate commit `627da75`)

`figures.OUTPUT_FORMATS` is `("pdf", "svg", "png")` again; the PNG stays at the confirmed 1000 dpi (line-art class) as the raster conformance copy, and a code comment states that the DeCarbon dpi table applies to bitmaps only, vector formats being resolution-independent and the preferred master for these line- and text-heavy figures. F1, F2, F4, S1 and S2 were regenerated in the three formats; the analysis prototypes (`fig_insample_coverage.*`, `task11*`) were not touched. Record for the file: the PNG-only change of commit `6fd6394` followed the user's instruction of that review message ("generate only png, delete the other formats"); it is reverted now by a later instruction.

---

## 1. Spatial data inventory

### 1.1 What was searched

Roots: `D:\Douglas\DOUTORADO\GeoFREA_data\raw` and `D:\Douglas\OUTROS` (all sub-folders). Method: a recursive file-name search for `.shp`, `.geojson`, `.gpkg`, `.topojson` (and `.kml`, `.kmz`, `.prj` in the GeoFREA tree), plus a bounded scan (100 s limit) of every other `.json` between 20 KB and 40 MB for a `FeatureCollection` header, excluding `node_modules`, `.venv`, `.git` and the ISIMIP raw cache. Limits, stated honestly: the `.gpkg` files were **not opened** (about 290 MB each); no name-based hit for IBGE (`BR_UF`, `estados`, `ibge`) exists; the scan can miss geometry stored under unusual extensions. Nothing was copied.

### 1.2 Candidates for Brazilian state boundaries

| id | file | format | source / vintage | CRS | size | verdict |
|---|---|---|---|---|---|---|
| **A** | `DOUTORADO\GeoFREA_data\raw\gadm\BRA\gadm41_BRA_shp\gadm41_BRA_1.shp` (+ `.dbf .prj .cpg`; levels 0 and 2 alongside) | ESRI shapefile | GADM **4.1** level 1 (file name `gadm41`); the shapefile is byte-identical (SHA-256 prefix `c9921b87b7e5cdbe`) to the copy in **A'** whose date is 2022-07-18, the GADM 4.1 release period; the GeoFREA copy is dated 2026-08-26 | WGS 84 geographic, from the `.prj` (`GCS_WGS_1984`, no EPSG tag) | 16,650,204 B (`.shp`), 4,301 B (`.dbf`) | **Recommended.** 27 features (26 states + Distrito Federal), 1,035 parts, 1,040,285 vertices; attributes `GID_1`, `NAME_1`, `HASC_1` (`BR.BA` etc., matches the ONS `id_estado` after dropping `BR.`), `ISO_1`. Bounding box lon -73.99 to -28.85, lat -33.75 to 5.26 (includes the oceanic islands) |
| A' | `DOUTORADO\database\raw\countries_borders\Brazil\gadm41_BRA_1.shp` | shapefile | same bytes as A, dated 2022-07-18 | same | same | the dated original of A; identifies the vintage |
| A'' | `DOUTORADO\GeoFREA_data\raw\gadm\BRA\gadm41_BRA_1_mainland.shp` | shapefile | derived from A on 2026-10-21; **clipping procedure not documented** | same | 15,888,820 B | not recommended: 685 parts, 992,786 vertices, bounding box ends at lon -34.79 (oceanic islands removed), but the derivation is not recorded |
| B | `OUTROS\ARTIGO RISK ASSESSMENT\...\data\raw\boundaries\gadm\gadm41_BRA.gpkg`; `OUTROS\CRAEI_raw_data\raw\gadm\gadm41_BRA.gpkg` | GeoPackage | GADM 4.1, all levels in one file | not read (GPKG stores it) | 292,548,608 B each (equal sizes; hashes not compared) | equivalent source, heavier; no advantage over A |
| C | `OUTROS\ARTIGOS HIDROGÊNIO\...\data\boundaries\brazil_states.geojson` | GeoJSON FeatureCollection | undocumented; **9 features**, one property `uf` (Northeast only, for the hydrogen article); dated 2026-08-14 | CRS84 declared | 331,139 B | unsuitable: 9 states only, source unknown |
| D | `...\data\boundaries\brazil.geojson` | GeoJSON | undocumented; one feature, no properties | none declared | 277,040 B | country outline only |
| - | `DOUTORADO\GeoFREA_data\raw\natural_earth\_global\ne_50m_admin_0_countries.shp`; `OUTROS\...\ne_110m_admin_0_countries.shp`, `ne_10m_coastline.shp` | shapefile | Natural Earth | WGS 84 | various | country / coastline only, **no admin-1 states** |
| - | `DOUTORADO\GeoFREA\tests\fixtures\archetypes\BRA.geojson` | GeoJSON | synthetic archetypes (`role`, `shape`), not boundaries | CRS84 | 106,499 B | excluded |

Not state geometry and therefore ignored: HydroRIVERS and HydroLAKES, GRIP4 roads, OSM grid and WDPA files, and the H2-article `candidate_sites_*` / `h2_potential_*` layers.

### 1.3 Feasibility of the lightweight approach (checked, not rendered)

Candidate A was parsed with plain `struct` (a shapefile is a documented binary format): 27 records, all polygons, readable without `geopandas`, `pyshp` or `cartopy`, none of which is installed in the locked environment. The coordinates are already geographic (lon / lat), so no reprojection is needed; a plain equirectangular drawing with the aspect `1 / cos(mean latitude)` is adequate for a national context map. At 1.04 million vertices the geometry must be simplified for drawing (see 2.3). **The dependency fallback is therefore not needed and no dependency decision is raised.**

### 1.4 Licence and reproducibility (stop-and-report candidate -> D36)

- **Which geometry and which vintage** affects reproducibility (a different vintage shifts boundary pixels, never a number). Registered as **D36, `status: pending`**, for consistency with the project's practice. **Stakes are low**, much lower than the past pending decisions; the working reading is A, GADM 4.1 level 1.
- **Licence point to verify:** to my reading, GADM's terms allow academic and other non-commercial use and do not allow redistribution without permission. `curtailmit` is a public GitHub repository, so committing the geometry would be redistribution. Proposal: keep the shapefile **only in `curtailmit_database`** (`raw/boundaries/gadm/`), recorded by SHA-256 in the data snapshot manifest, as for every other input (D33); the CI uses a tiny synthetic polygon fixture. Please re-read the GADM licence page before relying on this.

---

## 2. Map 1 (figure C1) - observed curtailment by state, 2022-2026

### 2.1 What it shows, and what it is not

Observed curtailment energy by state, wind and solar side by side, from data the pipeline already validated. It is a **context / motivation figure** (data section): it shows where the problem is today, which is why a Northeast-concentrated bottleneck matters for the model, **not** a projection and not a result. No spatial inference or allocation is involved.

### 2.2 Data path (no new model)

- The raw ONS curtailment files (`raw/ons/curtailment_wind`, `curtailment_solar`, monthly parquet) carry `id_estado` / `nom_estado` for every plant-hour (one sample month, wind: BA, CE, MA, PB, PE, PI, RN, RS, SC; no missing state in that month). `src` does not read the field today.
- `processed/ons_curtailment_classified.parquet` (15.8 M rows, the production energy table: `usina`, `curtailed_energy_mwh`, `source`) has the plant but **not the state**. The design attributes each classified row to the state of its plant through a `usina -> id_estado` map built from the raw files, then sums by state, technology and calendar year. Using the classified table keeps the energy definition identical to the pipeline's.
- **Check to run first (stop condition):** the map must be one state per plant name; any name with more than one state (a multi-state "Conj." complex) or any classified plant without a state stops the implementation and is reported. Then **reconciliation test**: the sum over states equals the national total of the classified table for every technology and year (rtol 1e-9).
- Output: a small data table `outputs/tables/curtailment_by_state_year.csv` (the exact numbers plotted), not a pipeline stage and not part of `final_results` (D31 scope: the orchestration covers the production numbers). Whether it is computed on demand or cached is open question 5.

Coverage limits to print on the figure: solar series starts 2024-04 (first complete solar month), 2026 covers January-September only.

### 2.3 Rendering without a new dependency (the default)

- Reader: ~40 lines of `struct` in `src/curtailmit/spatial.py` (shapefile polygon records, optional `.dbf` attribute reader), tested on a synthetic fixture.
- Simplification: Douglas-Peucker implemented in `numpy`, tolerance of about 0.02 degrees, to bring 1.04 M vertices to the order of 10-20 k; a test bounds the area change per state (< 0.5 %) so that simplification cannot visibly move a boundary.
- Drawing: `matplotlib.path.Path` compound paths (outer rings and holes) as `PathPatch`, one patch per state, `gid = state-<UF>`, face colour from the colour map; state outlines thin grey; the Distrito Federal and small states (SE, AL, RJ, ES) labelled by leader lines, not inside.
- **If this proves impractical** (it should not, section 1.3) `geopandas` / `cartopy` would be a fallback and **a dependency decision requiring explicit approval**; nothing is added.

### 2.4 Design choices for approval (not decided here)

| aspect | options | recommendation |
|---|---|---|
| time | (a) one complete year (2025); (b) small multiples 2022-2026; (c) animation | **(a) as C1** (main text) and **(b) as a supplementary C1S** if the evolution matters. (c) is impractical for a print journal (GIF cannot be printed); not recommended |
| variable | absolute TWh; share of the national total (%) | **share of the national total** for the colour (comparable across years and technologies), TWh printed for the top states; the colour-bar states the unit |
| layout | wind and solar as two panels with **separate** scales | two panels, separate sequential scales (the two technologies can differ widely in some states) |
| zero / no plants | colour-less grey with a hatch | "no curtailment recorded" grey, explained in the legend |

Naming: **context figures use the prefix C** (C1 map, C2 dose-response) so that the reviewed result figures F1, F2, F4, S1, S2 are not renumbered; the article numbers them in its own order.

---

## 3. Map 2 - projected regional risk (STOP: framing only, nothing to implement)

**This is not a visualization task.** The Option E model is national and hourly; it has no spatial component (D24 retired the regional formulation as the primary model, and the transmission-data scope was retired in D26). A map of projected 2030 / 2040 / 2050 curtailment by state or region needs a **rule for spatially disaggregating the national projection**: a new, high-impact methodological decision. It is registered as **D37, `status: pending`**, with no working choice. Map 2 is not designed in detail, not prototyped and not implemented in this task.

Candidate allocation rules, listed as options, none chosen:

| option | how | implicit assumption | main risk |
|---|---|---|---|
| **A. Capacity share** | allocate each scenario-year's curtailed energy by the state's (or region's) share of the PTE-projected installed wind and solar capacity | curtailment is proportional to where the capacity is built; local transmission is not the limiting factor | observed curtailment is **not** proportional to capacity today (it is concentrated where lines are constrained); the rule would spread the risk onto states that do not curtail now. Needs state-level PTE capacity, which the PTE table may not provide |
| **B. Historical curtailment share** | allocate by each state's share of observed curtailment 2022-2026 and keep it fixed | today's bottleneck geography does not change | optimistic if transmission is built (the pattern would flatten), pessimistic if new capacity concentrates elsewhere; ties directly to the retired D26 scope (transmission is not modelled) |
| **C. Hybrid / other** | for example capacity share weighted by an observed per-state curtailment propensity (curtailed / potential energy) estimated on 2022-2026; or a resource-potential based split | the propensity is stable and capacity is the exposure | two estimated layers on top of a national model; propensity is estimated on a short record (wind 2022-2026, solar from 2024-04) |

Points the decision should weigh (stated, not resolved):

1. **2050 is mostly out of the calibration support at the national level** (F2). A regional split stacks a second uncertain layer on a range that is already conditional; the "conditional range (not a confidence interval)" semantics would have to carry over, and a state-level range would be wider still.
2. **Annual shares hide the hourly structure.** Curtailment happens in the hours of high VRE share, and which states curtail in those hours can differ from the annual average. A rule on annual shares ignores this.
3. **Testability exists**: the observed state shares of 2022-2025 allow a hold-out test of any rule (allocate with rules fitted on earlier years, compare with the observed shares of later years), in the spirit of the Task 11E2 backtest. This is the only validation available and should be a condition of adopting a rule.
4. The first question is whether the article needs this map at all; Map 1 plus the national projection may already carry the point.

---

## 4. Dose-response figure (C2) - why 2040 and 2050 partly leave the calibration support

### 4.1 Purpose

A context / explanatory figure: the calibrated curve of curtailment rate against the system-wide variable-renewable share of load r, the observed points it is fitted to, and the support boundary beyond which the curve is an extrapolation. It explains visually why the 2040 (partly) and 2050 (mostly) scenarios fall outside observation, which F2 states in numbers.

### 4.2 Existing data (no new modelling)

| element | existing source |
|---|---|
| fitted curve, wind and solar: `L`, `k`, `x0`, `r_cap`, `n_hours`, window | `processed/hourly_curve_wind.json`, `hourly_curve_solar.json` (production calibration output; `HourlyCurve.rate` evaluates it) |
| the L = 1 curve of the 2050 upper scenario | `processed/hourly_curve_wind_L1.json` (and the solar equivalent) |
| support boundary `r_cap` (62.99 % wind, 62.97 % solar) | the same JSON; equals `r_cap_wind` / `r_cap_solar` of the Option E table (a cross-check test) |
| observed bins (2 pp classes, hours and rate per class, >= 15 hours = supported) | `hourly_model.MonthBins.bins()` on `interim/hourly_sin_panel.parquet`, i.e. the code path of the calibration itself; the bins are not stored as an output, so C2 calls the existing deterministic function (no new computation, no new estimate) |
| share of projected hours / curtailed energy beyond `r_cap` for 2040 and 2050 by scenario | the Option E table `H_out_*`, `E_out_*` (the same numbers as F2) |

### 4.3 Content

- x: r (% of load); y: curtailment rate (share of the potential energy that is curtailed).
- Observed bins as points (filled where the class has at least 15 hours, open otherwise), the fitted curve through the supported range, and the **support boundary** as a vertical line with the region beyond it shaded.
- Beyond the boundary the central curve and the L = 1 curve are drawn **dashed**, so that their divergence, the reason the 2050 range is conditional, is visible.
- A short annotation or inset table with the shares beyond the boundary (e.g. "2050: 30 % - 58 % of projected hours beyond the boundary" from `H_out_wind`), generated from the table, not typed.
- Wind and solar as two panels (their windows and curves differ); technology colours distinct from the scenario colours of F1-F4, so that colour never means two things.
- Option (question 8): a rug or histogram of the projected r of 2040 / 2050 per scenario. It would need `projected_r` (an existing function) and the base profile, i.e. a recomputation of an existing quantity, so it is offered, not assumed.

---

## 5. Testing plan

**Automated (CI where data-free, integration where the local database is needed), reusing `figure_checks`:**

- *Map data:* the state attribution is one state per plant; the sum over states reconciles with the national total of the classified table (integration); the plotted value of every state patch equals the table, checked through the patch `gid` and the colour (the face colour must equal the colour map applied to the table value), and the printed labels equal the table.
- *Geometry:* the reader parses the synthetic fixture exactly (vertex count, ring orientation, holes); simplification keeps each state's area within 0.5 % and never drops a state; the 27 `HASC_1` codes map one-to-one to the ONS `id_estado` set (integration).
- *Text and quality:* no placeholder text, units on the colour bar and axes, bounding-box overlap of every label and legend (small-state labels with leader lines are exactly the case the overlap check protects), forbidden-vocabulary check; captions are draft descriptive text, generated numbers.
- *C2:* the curve values equal `HourlyCurve.rate` on a grid; the boundary equals `r_cap` and equals the Option E `r_cap_*`; the bins plotted equal `MonthBins.bins()`; annotations equal the Option E shares.
- *Colour maps:* **a choropleth is a sequential encoding, so the qualitative Okabe-Ito palette is not appropriate for it.** Proposal: `cividis` (designed for colour-vision deficiency; perceptually uniform), with `viridis` as the alternative. Automated: the CIELAB lightness of the chosen map is strictly monotonic across 256 steps (implemented in `numpy`, no new dependency), adjacent steps stay above a minimum perceptual difference under simulated deuteranopia and protanopia matrices, and the map remains monotonic in greyscale. Okabe-Ito remains for the categorical series (technologies in C2).

**Only the user can verify (manual checklist in the report of the implementation task):** whether the map reads clearly at the column width; legibility of the small states and their leader labels (DF, SE, AL, ES, RJ); that the coastline and islands look right after simplification; that the sequential scale separates the states in print and in greyscale; whether the figure motivates the Northeast point without overstating it; the caption wording; C2's reading of "support boundary" and the dashed extrapolation by a person who has not seen the model.

---

## 6. Module and file layout (proposal)

| file | role |
|---|---|
| `src/curtailmit/spatial.py` | shapefile / dbf reader, Douglas-Peucker simplification, `usina -> UF` map and the state-year aggregation, reconciliation |
| `src/curtailmit/figures_context.py` | C1 and C2 builders, using the style constants of `figures.py` and the checks of `figure_checks.py` |
| `tests/test_spatial.py`, `tests/test_figures_context.py`, `tests/fixtures/spatial/` | synthetic geometry and small state-year fixture (no GADM data committed) |
| outputs | `DATABASE_ROOT/outputs/figures/C1_*`, `C2_*` in PDF, SVG and 1000 dpi PNG, `curtailment_by_state_year.csv`, the manifest entry; local only (D33) |

No new dependency, no change to the locked environment, no stage in `curtailmit-run`.

---

## 7. Stop-and-report triggers

| trigger | result |
|---|---|
| Choice of geometry source / vintage | **Reported** (low stakes): D36 `pending`, working reading GADM 4.1 level 1, local-only because of the licence |
| Projected regional map (spatial disaggregation rule) | **Fired**: D37 `pending`, no working choice, nothing implemented |
| A new dependency would be needed | Not fired: the lightweight reader and `matplotlib` suffice (section 1.3); `geopandas` / `cartopy` is described only as an unused fallback needing approval |
| Geometry licence prevents committing the data | **Reported**: keep the shapefile local only, verify the GADM terms |

---

## 8. Questions for approval

1. **D36**: GADM 4.1 level 1 (candidate A) as the boundary reference, kept local-only? Or download IBGE's state mesh (cleaner licence, a different vintage)?
2. **C1 time axis**: one complete year (2025) as C1 plus the 2022-2026 small multiples as a supplement C1S (recommended), only the single year, or only the small multiples? (Animation is not recommended for print.)
3. **C1 variable**: colour by the share of the national curtailment (recommended) or by TWh? Two panels with separate scales for wind and solar?
4. **Naming**: the prefix C for context figures (C1 map, C2 dose-response) - agreed?
5. **State-year table**: compute on demand from the raw files each time the figure is built, or cache it in `interim/`? (Neither is a pipeline stage.)
6. **Stop condition on plant names**: if a plant name maps to more than one state, report and stop (recommended), or assign by the state with most of its energy?
7. **Map 2 / D37**: leave pending (recommended until Map 1 is reviewed), or open the decision now with one of the three rules, in which case a hold-out test of the rule on 2022-2025 should be part of its adoption?
8. **C2**: include the projected-r rug for 2040 / 2050 (needs `projected_r` and the base profile), or only the share-beyond-boundary annotation from the Option E table (recommended)?
9. **Colour map** for the choropleth: `cividis` (recommended) or `viridis`?
10. **Where the figures live**: a new `figures_context.py` module (recommended) or inside `figures.py`?


---

## Update (Task 17 - Decisions, 2026-10-28)

Appended; sections 0-8 above are unchanged. Resolution of the ten questions of section 8, and the housekeeping asked with it:

1. **Q1 / D36: ADOPTED** (not merely pending). GADM 4.1 level 1 (candidate A) is the boundary reference, kept local-only in `curtailmit_database/raw/boundaries/gadm/`, never committed to the public repository, recorded by SHA-256 in `data_snapshot_manifest.json` under D33's pattern (vintage noted: GADM 4.1, 2022-07-18 per the file-identity finding of section 1). `status: adopted` in `config/discovered_sources.yaml`. A new item (section 3) in `docs/pre_submission_checklist.md` records that the GADM licence terms must be verified manually before submission, cross-referenced to D36.
2. **Q2:** C1 (single year 2025, main text) plus C1S (2022-2026 small multiples, supplement). No animation.
3. **Q3:** colour by the share of the national total; two panels (wind, solar) with separate sequential scales; top states annotated with TWh.
4. **Q4:** the prefix C for context figures: C1, C2, C1S.
5. **Q5:** the state-year aggregation is cached in `interim/curtailment_by_state_year.parquet`, built by the standalone `scripts/build_context_data.py` (not a `curtailmit-run` stage); regenerated when missing or with `--force`; no pipeline-stamp integration.
6. **Q6:** a plant name that maps to more than one state raises a clear exception (no split by energy share).
7. **Q7 / D37:** remains `pending`; Map 2 is not implemented.
8. **Q8:** C2 carries only the share-beyond-boundary annotation (Option E `H_out_*` / `E_out_*`); no projected-r rug in this iteration.
9. **Q9:** `cividis` for the choropleth; Okabe-Ito stays for categorical series.
10. **Q10:** a new module `src/curtailmit/figures_context.py`, separate from `figures.py`.

**Deviation from the section 6 layout, stated:** the state attribution and aggregation live in `src/curtailmit/context_data.py` instead of `spatial.py`, so that `spatial.py` stays a data-free geometry module (reader, simplification, patches) testable without pandas or the database.

**Figure formats (housekeeping, 2026-10-28):** the user asked for PNG only again: `figures.OUTPUT_FORMATS = ("png",)`, and the analysis scripts no longer write PDF / SVG (the 11E4 prototype's vector loop was removed; exploratory analysis figures are written to `outputs/figures_exploratory/`, so that `outputs/figures/` holds main figures only). This supersedes the "vector restored" note of section 0 for the formats. The context figures C1, C1S and C2 are therefore also PNG (1000 dpi) plus data CSV and caption; the Task 17 prompt's mention of PDF / SVG for them is read as superseded by this later instruction, and this is reported.


## Update (Task 17 - Review of the figures, 2026-10-28)

Appended. The user reviewed the figures; those not mentioned are approved. Three requests and how they were handled:

1. **C1S with more diverse years (e.g. 2025, 2030, 2035, 2040, 2050, wind and solar): NOT done, blocked by D37.** Observed state data exist only for 2022-2026 (wind) and 2024-2026 (solar). Years beyond 2026 are projections, and the Option E model has no spatial component, so a state map of 2030-2050 needs the allocation rule of decision D37 (`pending`). In addition 2035 is not in the PTE year grid (2025, 2030, 2040, 2050): it would be an interpolated year, which must be labelled as such (roadmap D3, acceptance criterion 4). C1S therefore stays as built until D37 is decided.
2. **F1 (curtailed energy) dropped, F4 becomes F1: DONE.** The figure ids are now F1 (mitigation deficit), F2, S1, S2 (`figures.FIGURE_IDS`); the curtailed energy itself remains in the results table T1. F1 was re-laid out as a 2 x 2 grid (OM, CM, average factor, and the legend with the factor note in the fourth cell), which gives each panel the width to separate the scenario labels; the old files `F1_curtailed_energy.*` and `F4_mitigation_deficit.*` were deleted from the local figures folder and the manifest no longer lists them.
3. **C1 / C2 as three-map series over years (wind; solar): NOT done as asked, same dependency.** Answer to the question raised: observed maps do not depend on the scenario (TB, TA, TG share the same observed history and the same 2025 starting point); projected maps do, because the national projection differs by scenario, and they also depend on the allocation rule of D37. A multi-year projected map therefore has two axes of choice (scenario and rule) and cannot be drawn until D37 is decided. Options for presenting it once decided are listed in the report of this review (a single scenario, scenario columns with a fixed rule, regional bars instead of a choropleth); none was implemented.
