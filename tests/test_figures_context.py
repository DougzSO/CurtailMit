"""Context figures C1, C1S, C2 (Task 17): data plotted equals source, the colour scale is monotonic and colour-vision safe, stop conditions, captions, outputs. CI uses synthetic geometry / tables
(no GADM data is committed); the real-data checks are integration tests. What needs eyes (map readability, small-state labels, the dashed extrapolation reading clearly) is NOT claimed here."""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest

from curtailmit import context_data as cd
from curtailmit import figure_checks as chk
from curtailmit import figures as fg
from curtailmit import figures_context as fc
from curtailmit import hourly_model as hm
from curtailmit import spatial as sp

matplotlib.use("Agg")

PROJECT = Path(__file__).resolve().parents[1]
FIX = PROJECT / "tests" / "fixtures"
LOW_DPI = 40


@pytest.fixture(autouse=True)
def _close():
    yield
    plt.close("all")


@pytest.fixture(scope="module")
def states():
    return sp.read_states(FIX / "spatial" / "synthetic_states.shp")


@pytest.fixture(scope="module")
def table():
    """A synthetic state-year table shaped like curtailment_by_state_year.parquet (invented numbers; UF codes of the synthetic geometry)."""
    rng = np.random.default_rng(7)
    rows = []
    plan = {"wind": [2022, 2023, 2024, 2025, 2026], "solar": [2024, 2025, 2026]}
    for tech, years in plan.items():
        for y in years:
            ufs = ["AA", "BB", "CC", "DD", "EE", "FF"] if (tech, y) != ("wind", 2025) else ["AA", "BB", "CC", "DD", "EE"]  # FF has no row in wind 2025: it must be drawn hatched
            e = rng.uniform(1e5, 9e6, len(ufs))
            total = float(e.sum())
            months = 12 if (tech, y) not in {("wind", 2026), ("solar", 2024)} else (10 if y == 2026 else 9)
            for uf, v in zip(ufs, e, strict=True):
                rows.append({"id_estado": uf, "nom_estado": f"State {uf}", "technology": tech, "year": y, "curtailed_energy_mwh": float(v), "curtailed_energy_twh": float(v) / 1e6, "national_total_mwh": total,
                             "share_of_national_pct": 100.0 * float(v) / total, "months_covered": months, "is_partial_year": months < 12})
    return pd.DataFrame(rows)[list(cd.COLUMNS)]


@pytest.fixture(scope="module")
def c2_inputs():
    rng = np.random.default_rng(3)
    idx = pd.date_range("2024-01-01", periods=24 * 60, freq="h")
    r = np.clip(rng.gamma(4.0, 9.0, len(idx)), 0, 99)  # a thin upper tail: the top classes hold < 15 hours
    pot = rng.uniform(5e3, 2e4, len(idx))
    rate = 0.7 / (1 + np.exp(-0.14 * (r - 41)))
    panel = pd.DataFrame({"r": r, "wind": pot * (1 - rate), "curt_wind": pot * rate, "solar_disp": pot * (1 - rate), "curt_solar": pot * rate}, index=idx)
    oe = pd.read_csv(FIX / "figures" / "option_e_support.csv")
    bins, curves = {}, {}
    for tech in ("wind", "solar"):
        d, real, curt = hm.technology_frame(panel.assign(solar_disp=panel["solar_disp"]), tech) if tech == "wind" else (panel, "solar_disp", "curt_solar")
        bins[tech] = hm.MonthBins(d, real, curt).bins()
        c = hm.HourlyCurve(tech, 0.7, 0.14, 41.0, float(oe[f"r_cap_{tech}"].iloc[0]), 2, len(d), "2024-01-01")  # r_cap as in the Option E table
        curves[tech] = (c, c.with_L(1.0))
    return bins, curves, oe


# -------------------------------------------------------------------------------------------------------------------------------------------------------- colour scale (accessibility)
def _srgb_to_linear(c):
    c = np.asarray(c, float)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _lab(rgb_linear):
    m = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]])
    xyz = rgb_linear @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > (6 / 29) ** 3, np.cbrt(xyz), xyz / (3 * (6 / 29) ** 2) + 4 / 29)
    return np.column_stack([116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])])


MACHADO = {  # severity 1.0, linear RGB (Machado, Oliveira, Fernandes 2009)
    "protanopia": np.array([[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]]),
    "deuteranopia": np.array([[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.011820, 0.042940, 0.968881]]),
}


def _ramp():
    return np.asarray(matplotlib.colormaps[fc.CMAP_NAME](np.linspace(0, 1, 256)))[:, :3]


def test_the_sequential_scale_is_cividis_and_okabe_ito_is_not_used_for_it():
    assert fc.CMAP_NAME == "cividis"
    assert not (set(fc.TECH_COLOURS.values()) & set(fg.OKABE_ITO.values()))  # technology colours differ from the F1-F4 scenario colours
    assert set(fc.TECH_COLOURS.values()) <= {"#E69F00", "#56B4E9", "#CC79A7", "#F0E442", "#000000"}  # Okabe-Ito entries not used for scenarios


def test_cividis_lightness_is_strictly_monotonic_over_256_steps():
    lab = _lab(_srgb_to_linear(_ramp()))
    assert np.all(np.diff(lab[:, 0]) > 0)


def test_cividis_stays_distinguishable_under_simulated_deuteranopia_and_protanopia():
    lin = _srgb_to_linear(_ramp())
    stride = 16  # 17 distinguishable levels along the scale
    for name, m in MACHADO.items():
        sim = np.clip(lin @ m.T, 0, 1)
        lab = _lab(sim)
        step = np.hypot(*(lab[stride:] - lab[:-stride]).T[:3])
        assert step.min() > 2.3, (name, step.min())  # above the usual just-noticeable difference (CIE76 about 2.3)
        assert np.all(np.diff(lab[:, 0]) > 0), name  # and still ordered by lightness


def test_the_map_stays_monotonic_in_greyscale():
    lin = _srgb_to_linear(_ramp())
    luma = lin @ np.array([0.2126, 0.7152, 0.0722])
    assert np.all(np.diff(luma) > 0)


def test_colour_scale_rounds_the_maximum_up_and_state_colour_handles_missing():
    n = fc.colour_scale([3.2, 41.3, 7.0])
    assert (n.vmin, n.vmax) == (0.0, 45.0) and fc.colour_scale([0.4]).vmax == 5.0
    assert fc.state_colour(None, n) is None and fc.state_colour(float("nan"), n) is None and fc.state_colour(45.0, n) == tuple(matplotlib.colormaps["cividis"](1.0))


# --------------------------------------------------------------------------------------------------------------------------------------------------------------------- C1 / C1S
def test_c1_plots_the_table_exactly_and_hatches_the_state_without_a_row(table, states):
    fig, frame, _cap = fc.figure_c1(table, states)
    problems, n = chk.verify_c1(fig, table, states)
    assert problems == [] and n > 20
    wind = chk._map_axes(fig)[0]
    ff = chk._one(wind, "state-FF")
    assert ff.get_hatch() and np.allclose(ff.get_facecolor(), matplotlib.colors.to_rgba(fc.NO_DATA_FACE))
    assert len(frame) == len(table[table.year == fc.C1_YEAR])


def test_c1_verification_catches_a_wrong_colour_and_a_wrong_label(table, states):
    fig, _, _ = fc.figure_c1(table, states)
    bad = table.copy()
    hit = (bad.technology == "wind") & (bad.year == fc.C1_YEAR) & (bad.id_estado == "AA")
    bad.loc[hit, "share_of_national_pct"] += 7.0
    problems, _ = chk.verify_c1(fig, bad, states)
    assert any("AA" in p for p in problems)
    bad2 = table.copy()
    bad2.loc[hit, "curtailed_energy_twh"] += 1.0
    assert any("label" in p for p in chk.verify_c1(fig, bad2, states)[0])


def test_c1_labels_the_largest_states_with_twh_through_leader_lines_outside_the_map(table, states):
    fig, _, _ = fc.figure_c1(table, states)
    ax = chk._map_axes(fig)[0]
    labels = [a for a in ax.texts if (a.get_gid() or "").startswith("label-wind-")]
    assert len(labels) == fc.TOP_N
    xs = {round(a.get_position()[0], 6) for a in labels}
    assert len(xs) == 1 and next(iter(xs)) > fc.mainland_x1(states)  # one column east of the continental outline
    assert all(a.arrow_patch is not None for a in labels) and all("TWh" in a.get_text() for a in labels)


def test_label_spreading_keeps_a_minimum_gap_inside_the_bounds():
    ys = fc._spread([10.0, 9.9, 9.8, 9.7, 0.0], 3.0, -5.0, 12.0)
    ordered = sorted(ys, reverse=True)
    assert all(a - b >= 3.0 - 1e-12 for a, b in itertools.pairwise(ordered)) and min(ys) >= -5.0 and max(ys) <= 12.0


def test_c1s_has_one_map_per_technology_year_with_totals_and_partial_months_in_the_titles(table, states):
    fig, _frame, cap = fc.figure_c1s(table, states)
    problems, n = chk.verify_c1s(fig, table, states)
    assert problems == [] and n > 40
    titles = [ax.get_title(loc="left") for ax in chk._map_axes(fig)]
    assert len(titles) == 8 and any("(10 of 12 months)" in t for t in titles) and any("(9 of 12 months)" in t for t in titles) and all("TWh nationally" in t for t in titles)
    assert "SHARE" in cap and "national total" in cap


def test_captions_are_generated_from_the_table_and_have_no_placeholders(table, states, c2_inputs):
    _bins, curves, oe = c2_inputs
    c1 = fc.caption_c1(table, states)
    ne = fc.northeast_share(table, "wind", fc.C1_YEAR)
    assert f"{ne:.0f} % in the nine Northeast states" in c1 and "not a projection" in c1
    d = table[(table.technology == "wind") & (table.year == fc.C1_YEAR)].sort_values("share_of_national_pct", ascending=False)
    assert f"{d['share_of_national_pct'].iloc[0]:.0f} % of it in {states[d['id_estado'].iloc[0]]['name']}" in c1
    c2 = fc.caption_c2(oe, curves)
    for cap in (c1, fc.caption_c1s(table), c2):
        assert cap.startswith(fg.DRAFT) and "Figure X" not in cap and not fg.check_text(cap)
    assert "(not a confidence interval)" in c2  # the 2050 range is mentioned (D24)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ C2
def test_c2_curves_boundary_bins_and_annotations_match_their_sources(c2_inputs):
    bins, curves, oe = c2_inputs
    fig, _frame, _cap = fc.figure_c2(bins, curves, oe)
    problems, n = chk.verify_c2(fig, bins, curves, oe)
    assert problems == [] and n > 200
    for tech, ax in zip(("wind", "solar"), fig.axes[:2], strict=True):
        central, _ = curves[tech]
        grid = np.asarray(chk._one(ax, f"curve-central-supported-{tech}").get_xdata(), float)
        assert np.allclose(chk._one(ax, f"curve-central-supported-{tech}").get_ydata(), 100 * central.rate(grid))  # HourlyCurve.rate on the grid
        assert float(chk._one(ax, f"boundary-{tech}").get_xdata()[0]) == central.r_cap  # the vertical line sits exactly at the curve's r_cap


def test_c2_boundary_check_requires_the_option_e_r_cap(c2_inputs):
    bins, curves, oe = c2_inputs
    fig, _, _ = fc.figure_c2(bins, curves, oe)
    assert chk.verify_c2(fig, bins, curves, oe)[0] == []  # aligned: the curve's r_cap is the table's
    assert any("boundary" in p for p in chk.verify_c2(fig, bins, curves, oe.assign(r_cap_wind=50.0))[0])


def test_c2_boundary_equals_r_cap_when_the_curve_comes_from_the_table(c2_inputs):
    bins, curves, oe = c2_inputs
    cap = float(oe["r_cap_wind"].iloc[0])
    same = {t: (hm.HourlyCurve(c.technology, c.L, c.k, c.x0, float(oe[f"r_cap_{t}"].iloc[0]), c.n_months, c.n_hours, c.window_start), None) for t, (c, _) in curves.items()}
    same = {t: (c, c.with_L(1.0)) for t, (c, _) in same.items()}
    fig, _, _ = fc.figure_c2(bins, same, oe)
    assert chk.verify_c2(fig, bins, same, oe)[0] == [] and float(chk._one(fig.axes[0], "boundary-wind").get_xdata()[0]) == cap


def test_c2_draws_the_supported_curve_solid_and_both_extrapolations_dashed_beyond_a_shaded_boundary(c2_inputs):
    bins, curves, oe = c2_inputs
    fig, _, _ = fc.figure_c2(bins, curves, oe)
    for tech, ax in zip(("wind", "solar"), fig.axes[:2], strict=True):
        assert chk._one(ax, f"curve-central-supported-{tech}").get_linestyle() == "-"
        assert chk._one(ax, f"curve-central-beyond-{tech}").get_linestyle() == "--"
        assert chk._one(ax, f"curve-L1-beyond-{tech}").get_linestyle() == "-."
        assert chk._one(ax, f"beyond-{tech}") is not None  # shaded region
        assert chk._one(ax, f"bins-supported-{tech}").get_markerfacecolor() == fc.TECH_COLOURS[tech]
        assert chk._one(ax, f"bins-thin-{tech}").get_markerfacecolor() == "white"  # open: fewer than 15 observed hours
        assert chk._one(ax, f"curve-central-supported-{tech}").get_color() == fc.TECH_COLOURS[tech]


def test_c2_annotation_is_generated_from_the_option_e_columns(c2_inputs):
    _, _, oe = c2_inputs
    rows = fc.annotation_rows(oe, "wind")
    assert len(rows) == 6
    for sc, yr, h, e in rows:
        r = oe[(oe.scenario == sc) & (oe.year == yr)].iloc[0]
        assert h == 100 * r.H_out_wind and e == 100 * r.E_out_wind
    text = fc.annotation_text(oe, "solar")
    assert "2050 TA" in text and f"{100 * oe[(oe.scenario == 'TA') & (oe.year == 2050)].iloc[0].H_out_solar:.0f} %" in text


# ------------------------------------------------------------------------------------------------------------------------------------------------- whole-figure checks and output
def test_all_context_figures_pass_every_automated_check_on_the_synthetic_inputs(table, states, c2_inputs):
    bins, curves, oe = c2_inputs
    same = {t: (hm.HourlyCurve(c.technology, c.L, c.k, c.x0, float(oe[f"r_cap_{t}"].iloc[0]), c.n_months, c.n_hours, c.window_start), None) for t, (c, _) in curves.items()}
    same = {t: (c, c.with_L(1.0)) for t, (c, _) in same.items()}
    report = chk.run_context(table, states, bins, same, oe)
    assert set(report) == {"C1", "C1S", "C2"}
    for fid, r in report.items():
        assert r["overlaps"] == [] and r["mismatches"] == [] and r["text_problems"] == [], (fid, r)
        assert r["width_mm"] == fc.CONTEXT_WIDTH_MM[fid] and r["n_numbers"] > 20


def test_context_figures_are_written_as_png_with_data_and_caption_only(table, states, c2_inputs, tmp_path):
    bins, curves, oe = c2_inputs
    for fid, build in (("C1", lambda: fc.figure_c1(table, states)), ("C1S", lambda: fc.figure_c1s(table, states)), ("C2", lambda: fc.figure_c2(bins, curves, oe))):
        fig, frame, cap = build()
        files = fg.write_figure(fig, fc.FILE_NAMES[fid], frame, cap, tmp_path, dpi=LOW_DPI)
        assert set(files) == {"png", "csv", "caption"} and all(p.stat().st_size > 0 for p in files.values())
    assert not list(tmp_path.glob("*.pdf")) and not list(tmp_path.glob("*.svg"))


def test_unknown_ids_and_missing_inputs_are_refused(tmp_path, table):
    with pytest.raises(fc.ContextFigureError, match="unknown figure ids"):
        fc.build(["C9"], out_dir=tmp_path)
    with pytest.raises(fc.ContextFigureError, match="no wind rows for 1999"):
        fc._year_slice(table, "wind", 1999)


def test_the_context_module_adds_no_dependency_and_keeps_map_two_out():
    src = (PROJECT / "src" / "curtailmit" / "figures_context.py").read_text(encoding="utf-8")
    for banned in ("import geopandas", "import cartopy", "import shapefile", "import shapely"):
        assert banned not in src and banned not in (PROJECT / "src" / "curtailmit" / "spatial.py").read_text(encoding="utf-8")
    lock = (PROJECT / "requirements.lock.txt").read_text(encoding="utf-8").lower()
    assert "geopandas" not in lock and "cartopy" not in lock and "pyshp" not in lock
    assert "D37" in src and "NOT implemented" in src  # the projected regional map stays out of scope


# --------------------------------------------------------------------------------------------------------------------------------------------------------- real tables (local database)
@pytest.mark.integration
def test_real_context_figures_pass_every_check_and_every_state_patch_matches_the_state_year_table():
    from curtailmit import paths

    if not sp.default_shp().is_file() or not (paths.planned_layout()["interim"] / cd.CACHE_NAME).is_file():
        pytest.skip("no local database / boundary files")
    for fid, r in chk.run_context_real().items():
        assert r["overlaps"] == [] and r["mismatches"] == [] and r["text_problems"] == [], (fid, r)
    table = pd.read_parquet(paths.planned_layout()["interim"] / cd.CACHE_NAME)
    st = sp.read_states(sp.default_shp())
    fig, _, _ = fc.figure_c1(table, st)
    assert chk.verify_c1(fig, table, st)[0] == [] and len(chk._map_axes(fig)) == 2  # every state patch, matched by gid, equals curtailment_by_state_year


@pytest.mark.integration
def test_real_c2_uses_the_production_curve_files_and_the_option_e_boundary(tmp_path):
    from curtailmit import paths

    proc = paths.planned_layout()["processed"]
    if not (proc / "hourly_curve_wind.json").is_file() or not (paths.planned_layout()["interim"] / "hourly_sin_panel.parquet").is_file():
        pytest.skip("no local database")
    bins, curves, oe = fc.load_c2_inputs()
    for tech in ("wind", "solar"):
        saved = json.loads((proc / f"hourly_curve_{tech}.json").read_text(encoding="utf-8"))
        assert curves[tech][0].r_cap == saved["r_cap"] and abs(saved["r_cap"] - float(oe[f"r_cap_{tech}"].iloc[0])) < 1e-9
        assert np.isclose(float(oe[f"r_cap_{tech}"].nunique()), 1.0)
    fig, _, _ = fc.figure_c2(bins, curves, oe)
    assert chk.verify_c2(fig, bins, curves, oe)[0] == []


@pytest.mark.integration
def test_real_build_writes_png_only_and_records_the_boundary_hash_of_the_snapshot_manifest(tmp_path):
    from curtailmit import paths

    if not sp.default_shp().is_file() or not (paths.planned_layout()["interim"] / cd.CACHE_NAME).is_file():
        pytest.skip("no local database / boundary files")
    m = fc.build(["C1", "C1S", "C2"], out_dir=tmp_path, dpi=LOW_DPI)
    assert {"C1", "C1S", "C2"} <= set(m["figures"]) and not list(tmp_path.glob("*.pdf")) and not list(tmp_path.glob("*.svg"))
    snap = json.loads((PROJECT / "data_snapshot_manifest.json").read_text(encoding="utf-8"))
    entry = next(f for f in snap["files"] if f["path"] == "boundaries/gadm/gadm41_BRA_1.shp")
    assert m["inputs"]["boundary_shapefile"]["sha256"] == entry["sha256"] and "D36" in entry["note"]
