"""Article figures (Task 13B): extraction, guards, the V1 rule for 2050, the scoped text exception, caption numbers, outputs, determinism.

What this file does NOT prove (manual checklist in the Task 13B report): that the hatched / dashed 2050 style reads as "not an interval" to a person, legibility at 90 / 190 mm, label overlap,
greyscale / colour-blind rendering, and the DeCarbon journal standards (provisional, addendum Q7). Structural checks on the artists below are not a substitute for looking at the figures."""

from __future__ import annotations

import json
import re
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest
from test_final_results import AVG, MARG, mock_option_e

from curtailmit import figures as fg
from curtailmit import results_writer as rw

matplotlib.use("Agg")

PROJECT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT / "tests" / "fixtures" / "figures"
LOW_DPI = 40  # file-writing tests do not need 600 dpi; the dpi test does


@pytest.fixture(scope="module")
def final_results():
    central, _ = rw.build_final_results_with_sensitivity(mock_option_e(), AVG, MARG, True)
    return central


@pytest.fixture(scope="module")
def option_e():
    return pd.read_csv(FIXTURES / "option_e_support.csv")


@pytest.fixture(autouse=True)
def _close_figures():
    yield
    plt.close("all")


def _artists(ax, prefix: str):
    return [a for a in [*ax.patches, *ax.lines, *ax.texts] if (a.get_gid() or "").startswith(prefix)]


# ------------------------------------------------------------------------------------------------------------------------------------------------------ scope and constants
def test_the_figure_set_is_f1_f2_f4_s1_s2_and_tables_are_not_figures():
    assert fg.FIGURE_IDS == ("F1", "F2", "F4", "S1", "S2")  # F3 is panel (c) of F2; T1-T3 remain tables; no comparison figure, no history overlay
    assert matplotlib.get_backend().lower() == "agg"


def test_decarbon_standards_are_marked_provisional_in_code_and_in_the_design_doc():
    assert fg.PROVISIONAL_STANDARDS is True
    src = (PROJECT / "src" / "curtailmit" / "figures.py").read_text(encoding="utf-8")
    assert "PROVISIONAL" in src and "UNCONFIRMED" in src
    assert (fg.SINGLE_COLUMN_MM, fg.DOUBLE_COLUMN_MM, fg.PNG_DPI) == (90.0, 190.0, 600)
    design = (PROJECT / "docs" / "task13b_design.md").read_text(encoding="utf-8")
    assert "PROVISIONAL" in design and "Task 13B - implementation status" in design


def test_matplotlib_is_a_declared_and_locked_dependency_and_no_new_dependency_was_added():
    lock = (PROJECT / "requirements.lock.txt").read_text(encoding="utf-8")
    assert re.search(r"^matplotlib==\d", lock, re.MULTILINE) and re.search(r"^pillow==\d", lock, re.MULTILINE)
    assert "matplotlib>=" in (PROJECT / "pyproject.toml").read_text(encoding="utf-8")


# ------------------------------------------------------------------------------------------------------------------------------------------------------------- extraction
def test_headline_frame_reads_the_table_without_recomputing(final_results):
    h = fg.headline_frame(final_results)
    assert len(h) == 12
    for _, r in h.iterrows():
        t = final_results[(final_results.scenario == r.scenario) & (final_results.year == r.year) & (final_results.quantity == "curtailed_energy") & (final_results.component == "total")].iloc[0]
        assert (r.central, r.low, r.high) == (t.central_value, t.conditional_range_low, t.conditional_range_high)


def test_mitigation_frame_keeps_om_and_cm_apart_and_never_sums_them(final_results):
    m = fg.mitigation_frame(final_results)
    assert set(m["kind"]) == {"om", "cm", "avg"}
    om = m[m.kind == "om"].set_index(["scenario", "year"])["central"]
    cm = m[m.kind == "cm"].set_index(["scenario", "year"])["central"]
    assert not np.allclose(om, cm)
    fig, _, _ = fg.figure_f4(final_results)
    plotted = {}
    for ax, kind in zip(fig.axes, ("om", "cm", "avg"), strict=True):
        pts = {a.get_gid(): float(a.get_ydata()[0]) for a in _artists(ax, "central-")}
        plotted[kind] = pts
        assert len(pts) == 12
    summed = (om + cm).to_numpy()
    for kind, pts in plotted.items():
        vals = np.array(sorted(pts.values()))
        assert not np.allclose(vals, np.sort(summed)), f"panel {kind} plots OM + CM"
    om_plotted = np.array([plotted["om"][f"central-{s}-{y}"] for s, y in om.index])
    cm_plotted = np.array([plotted["cm"][f"central-{s}-{y}"] for s, y in cm.index])
    assert np.allclose(om_plotted, om.to_numpy()) and np.allclose(cm_plotted, cm.to_numpy())


def test_coverage_frame_matches_the_committed_option_e_diagnostics_to_1e_9(option_e):
    c = fg.coverage_frame(option_e)
    for _, r in c.iterrows():
        o = option_e[(option_e.scenario == r.scenario) & (option_e.year == r.year)].iloc[0]
        assert abs(r.pct_hours_inside_support_wind - 100 * (1 - o.H_out_wind)) < 1e-9
        assert abs(r.pct_curtailment_inside_support_wind - 100 * (1 - o.E_out_wind)) < 1e-9
        assert abs(r.pct_curtailment_inside_support_solar - 100 * (1 - o.E_out_solar)) < 1e-9
        assert abs(r.curt_in_support_total_twh - o.curt_in_support_total_twh) < 1e-9


def test_coverage_frame_reproduces_the_numbers_published_by_the_11e4_prototype(option_e):
    c = fg.coverage_frame(option_e).set_index(["scenario", "year"])
    assert abs(c.loc[("TB", 2050), "pct_hours_inside_support_wind"] - 60) < 1.0
    assert abs(c.loc[("TA", 2040), "pct_hours_inside_support_wind"] - 86) < 1.0
    for sc, v in {"TB": 62, "TA": 77, "TG": 51}.items():
        assert abs(c.loc[(sc, 2050), "pct_curtailment_beyond_support_wind"] - v) < 1.0


def test_the_r_max_reference_is_gone_from_frames_data_files_and_figure_text(option_e, tmp_path):
    assert "r_max" not in option_e.columns
    fig, cov, cap = fg.figure_f2(option_e)
    assert not [c for c in cov.columns if "r_max" in c or "observed_max" in c]
    assert not [t for t in fg.figure_texts(fig) if "largest" in t.lower() or "r_max" in t.lower()]
    assert "largest" not in cap.lower() and "r_max" not in cap.lower()


def test_decomposition_frame_splits_2040_and_2050_and_sums_to_the_total(option_e):
    d = fg.decomposition_frame(fg.coverage_frame(option_e))
    assert sorted(d.year.unique()) == [2040, 2050] and len(d) == 6
    for _, r in d.iterrows():
        o = option_e[(option_e.scenario == r.scenario) & (option_e.year == r.year)].iloc[0]
        assert abs(r.pct_beyond_support - 100 * o.curt_out_support_total_twh / (o.curt_in_support_total_twh + o.curt_out_support_total_twh)) < 1e-9


def test_supplement_frame_has_no_2050_and_the_supplement_is_wider_than_the_band(final_results):
    s = fg.supplement_frame(final_results)
    assert set(s.year) == {2025, 2030, 2040} and (s.width_ratio > 1).all()


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------- guards
def test_guards_refuse_interpolated_rows_missing_cells_and_invalid_tables(final_results):
    fg.check_final_results(final_results)
    interp = final_results.copy()
    interp.loc[interp.index[0], "is_interpolated"] = True
    with pytest.raises(fg.FigureInputError, match="interpolated"):
        fg.check_final_results(interp)
    gap = final_results[~((final_results.scenario == "TG") & (final_results.year == 2040) & (final_results.quantity == "curtailed_energy") & (final_results.component == "total"))]
    with pytest.raises(fg.FigureInputError, match="missing TG 2040"):
        fg.check_final_results(gap)
    bad = final_results.copy()
    bad["role"] = "reference"
    with pytest.raises(fg.FigureInputError, match="does not validate"):
        fg.check_final_results(bad)


def test_option_e_guard_requires_the_columns_and_the_full_grid(option_e):
    fg.check_option_e(option_e)
    with pytest.raises(fg.FigureInputError, match="lacks the columns"):
        fg.check_option_e(option_e.drop(columns=["E_out_wind"]))
    with pytest.raises(fg.FigureInputError, match="lacks"):
        fg.check_option_e(option_e.iloc[1:])
    with pytest.raises(fg.FigureInputError, match="model"):
        fg.check_option_e(option_e.assign(model="national_P"))


def test_missing_input_files_are_refused_with_a_clear_message(tmp_path):
    with pytest.raises(fg.FigureInputError, match="not found"):
        fg.load_final_results(tmp_path / "nope.parquet")
    assert fg.main(["--only", "F1", "--final-results", str(tmp_path / "nope.parquet"), "--out-dir", str(tmp_path)]) == 2
    with pytest.raises(fg.FigureInputError, match="unknown figure ids"):
        fg.build(["F9"], out_dir=tmp_path)


# ------------------------------------------------------------------------------------------------------------------------- the 2050 rule, structurally (V1; Q1 of the addendum)
def test_f1_draws_2050_in_the_conditional_style_and_the_band_in_the_solid_style(final_results):
    fig, _h, _cap = fg.figure_f1(final_results)
    ax = fig.axes[0]
    cond = _artists(ax, "conditional-")
    band = _artists(ax, "band-")
    assert len(cond) == 3 and len(band) == 9
    for a in cond:  # unfilled, hatched, dashed outline
        assert not a.get_fill() and a.get_hatch() and a.get_linestyle() == "--"
    for a in band:  # filled, no hatch, solid outline
        assert a.get_fill() and not a.get_hatch() and a.get_linestyle() == "-"
    assert {a.get_facecolor() for a in band} != {a.get_facecolor() for a in cond}
    zone = _artists(ax, "zone-2050")
    assert zone  # the shaded zone is drawn
    assert [a.get_text() for a in _artists(ax, "note-2050")] == [fg.NOTE_2050]


def test_f1_central_value_is_a_diamond_at_the_table_value_and_not_at_the_midpoint(final_results):
    fig, h, _ = fg.figure_f1(final_results)
    ax = fig.axes[0]
    for _, r in h[h.year == 2050].iterrows():
        (m,) = _artists(ax, f"central-{r.scenario}-2050")
        assert m.get_marker() == "D" and float(m.get_ydata()[0]) == r.central
        assert abs(r.central - (r.low + r.high) / 2) > 1e-6, "the table's 2050 central value is not the midpoint (D25); the figure must not move it"
        assert r.low < r.central < r.high
    for _, r in h[h.year < 2050].iterrows():
        (m,) = _artists(ax, f"central-{r.scenario}-{r.year}")
        assert m.get_marker() == "o" and float(m.get_ydata()[0]) == r.central


def test_f1_legend_and_caption_carry_the_mandatory_wording_and_ta_2040_is_marked_partial(final_results):
    fig, _h, cap = fg.figure_f1(final_results)
    ax = fig.axes[0]
    legend = [t.get_text() for t in ax.get_legend().get_texts()]
    assert "conditional range (not a confidence interval)" in legend and fg.BAND_LABEL in legend
    assert fg.CONDITIONAL_NOTE in cap and "not at the midpoint" in cap
    (ta,) = _artists(ax, "central-TA-2040")
    assert ta.get_markerfacecolor() == "white"  # open marker = partial support (D24)
    assert [a.get_text() for a in _artists(ax, "partial-TA-2040")] == ["partial\nsupport"]
    assert not _artists(ax, "partial-TB-2040")


def test_f4_uses_the_same_2050_style_in_each_panel(final_results):
    fig, _, cap = fg.figure_f4(final_results)
    assert len(fig.axes) == 3
    for ax in fig.axes:
        assert len(_artists(ax, "conditional-")) == 3 and all(a.get_hatch() and a.get_linestyle() == "--" for a in _artists(ax, "conditional-"))
    assert fg.CONDITIONAL_NOTE in cap and "never added" in cap and "not included in the range" in cap
    assert "conditional range (not a confidence interval)" in [t.get_text() for lg in fig.legends for t in lg.get_texts()]


# ---------------------------------------------------------------------------------------------------------------------------- the text check and its single literal exception (D24)
def test_exception_is_the_exact_literal_and_nothing_else():
    assert fg.check_text("conditional range (not a confidence interval)") == []
    assert fg.check_text("a confidence interval") and fg.check_text("95 % confidence") and fg.check_text("credible band") and fg.check_text("margin of error") and fg.check_text("lower_ci_95")
    assert fg.check_text("Not a confidence interval")  # not the literal: still rejected
    assert fg.check_text("not a  confidence interval") and fg.check_text("not a confidence intervals and credible")  # a variant, or the literal plus another hit
    assert fg.check_text("not a confidence interval; credible") == ["credible"]
    assert fg.check_text("not a confidence interval, but a confidence level")


def test_the_table_filter_is_not_relaxed_by_the_figure_exception(final_results):
    assert rw.FORBIDDEN_LANGUAGE.search(fg.ALLOWED_NEGATION)
    assert "not a confidence interval" not in rw.FORBIDDEN_LANGUAGE.pattern
    bad = final_results.copy()
    bad["range_basis"] = bad["range_basis"] + "; conditional range (not a confidence interval)"
    with pytest.raises(rw.FinalResultsError, match="forbidden wording"):
        rw.validate_final_results(bad)
    bad2 = final_results.rename(columns={"supplement_basis": "ci_basis"})
    with pytest.raises(rw.FinalResultsError):
        rw.validate_final_results(bad2)


def test_every_figure_text_and_caption_passes_the_filter_with_the_one_exception(final_results, option_e, tmp_path):
    for builder in (lambda: fg.figure_f1(final_results), lambda: fg.figure_f4(final_results), lambda: fg.figure_f2(option_e), lambda: fg.figure_s1(final_results), lambda: fg.figure_s2()):
        fig, _, cap = builder()
        texts = fg.figure_texts(fig)
        assert texts and not [t for t in texts if fg.check_text(t)] and not fg.check_text(cap)
        plt.close(fig)


def test_write_figure_refuses_forbidden_wording_in_a_label_or_caption(tmp_path):
    fig, ax = plt.subplots()
    ax.set_title("95 % confidence band")
    with pytest.raises(fg.FigureTextError, match="figure t"):
        fg.write_figure(fig, "t", pd.DataFrame({"a": [1]}), "ok", tmp_path, dpi=LOW_DPI)
    fig, ax = plt.subplots()
    with pytest.raises(fg.FigureTextError, match="caption"):
        fg.write_figure(fig, "t", pd.DataFrame({"a": [1]}), "a credible range", tmp_path, dpi=LOW_DPI)
    assert not list(tmp_path.glob("t*"))


# ------------------------------------------------------------------------------------------------------------------------------------------------ caption numbers come from the frames
def _numbers(text: str) -> list[str]:
    return re.findall(r"(\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)?) %", text)


def test_f2_caption_percentages_are_recomputed_from_the_option_e_table(option_e):
    cov = fg.coverage_frame(option_e)

    def rng(s):
        lo, hi = round(s.min()), round(s.max())
        return str(lo) if lo == hi else f"{lo}-{hi}"

    expected = [rng(cov[cov.year == y].pct_hours_inside_support_wind) for y in (2025, 2030, 2040, 2050)]
    expected.append(rng(cov[cov.year == 2050].pct_curtailment_beyond_support_wind))
    dec = fg.decomposition_frame(cov)
    expected.append(rng(dec[dec.year == 2050].pct_beyond_support))
    cap = fg.caption_f2(cov)
    assert _numbers(cap)[-6:] == expected
    assert f"{fg.hourly_model.MIN_HOURS} observed hours" in cap


def test_f1_caption_percentages_are_recomputed_from_final_results(final_results):
    h = fg.headline_frame(final_results)
    beyond = (100 * (1 - h[h.year == 2050].in_support_fraction)).round().astype(int)
    lo, hi = beyond.min(), beyond.max()
    cap = fg.caption_f1(h)
    assert f"{lo if lo == hi else f'{lo}-{hi}'} % of the projected 2050 curtailed energy" in cap
    ta = h[(h.scenario == "TA") & (h.year == 2040)].iloc[0]
    assert f"({100 * (1 - ta.in_support_fraction):.0f} % of its curtailed energy lies beyond it" in cap


def test_s1_caption_width_ratio_is_the_table_ratio(final_results):
    s = fg.supplement_frame(final_results)
    cap = fg.caption_s1(s)
    lo, hi = round(s.width_ratio.min()), round(s.width_ratio.max())
    assert f"{lo if lo == hi else f'{lo}-{hi}'} times wider" in cap


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------ S2 and its fixture
def test_backtest_fixture_holds_only_hourly_model_columns_of_the_analysis_table():
    raw = pd.read_csv(FIXTURES / "backtest_annual.csv")
    assert set(raw.columns) == {"tech", "scheme", "period", "obs_twh", "hourly_twh", "hourly_err_pct"}  # no national-P / time-only comparators (retired formulations)
    assert len(raw) == 22 and set(raw.tech) == {"wind", "solar"}
    bt = fg.backtest_frame()
    assert set(bt.group) == set(fg.SCHEME_GROUPS)


def test_s2_labels_itself_analysis_derived_in_the_figure_and_in_the_caption():
    fig, _bt, cap = fg.figure_s2()
    assert any("Analysis-derived" in t and "not production pipeline output" in t for t in fg.figure_texts(fig))
    assert "ANALYSIS-DERIVED" in cap and "not from the production pipeline output" in cap
    assert len(fig.axes) == 2 and all(_artists(ax, "observed-") and _artists(ax, "model-") for ax in fig.axes)


def test_s2_plots_the_fixture_values_unchanged():
    fig, bt, _ = fg.figure_s2()
    wind = fig.axes[0]
    plotted = sorted(float(y) for a in _artists(wind, "model-") for y in a.get_ydata())
    assert np.allclose(plotted, sorted(bt[bt.tech == "wind"].hourly_twh.to_numpy()))


@pytest.mark.integration
def test_backtest_fixture_equals_the_analysis_output_it_was_taken_from():
    from curtailmit import paths

    src = paths.planned_layout()["tables"] / "task11e2_backtest_annual.csv"
    if not src.is_file():
        pytest.skip("no local analysis table")
    live = pd.read_csv(src)[["tech", "scheme", "period", "obs_twh", "hourly_twh", "hourly_err_pct"]]
    fix = pd.read_csv(FIXTURES / "backtest_annual.csv")
    assert live.astype({"period": str}).equals(fix.astype({"period": str})) or np.allclose(live[["obs_twh", "hourly_twh", "hourly_err_pct"]], fix[["obs_twh", "hourly_twh", "hourly_err_pct"]], rtol=1e-7)


# -------------------------------------------------------------------------------------------------------------------------------------------------------------------- file output
def test_every_figure_writes_pdf_svg_png_data_and_caption_with_embedded_fonts(final_results, option_e, tmp_path):
    builders = {"F1": lambda: fg.figure_f1(final_results), "F2": lambda: fg.figure_f2(option_e), "F4": lambda: fg.figure_f4(final_results), "S1": lambda: fg.figure_s1(final_results), "S2": lambda: fg.figure_s2()}
    for fid, build in builders.items():
        fig, frame, cap = build()
        files = fg.write_figure(fig, fg.FILE_NAMES[fid], frame, cap, tmp_path, dpi=LOW_DPI)
        assert set(files) == {"pdf", "svg", "png", "csv", "caption"} and all(p.stat().st_size > 0 for p in files.values())
        pdf = files["pdf"].read_bytes()
        assert pdf.startswith(b"%PDF") and b"/Subtype /Type3" not in pdf and b"/Subtype /CIDFontType2" in pdf and b"/FontFile2" in pdf  # fonttype 42: embedded TrueType outlines, no Type 3 fonts
        assert b"<svg" in files["svg"].read_bytes()
        assert pd.read_csv(files["csv"]).shape[0] == len(frame)
        assert files["caption"].read_text(encoding="utf-8").strip() == cap


def test_png_is_written_at_600_dpi_and_the_figure_is_double_column_width(option_e, tmp_path):
    from PIL import Image

    fig, frame, cap = fg.figure_f2(option_e)
    assert abs(fig.get_size_inches()[0] * 25.4 - fg.DOUBLE_COLUMN_MM) < 1e-6
    files = fg.write_figure(fig, "F2_dpi", frame, cap, tmp_path)
    with Image.open(files["png"]) as im:
        assert round(im.info["dpi"][0]) == 600 and im.size[0] == round(fg.DOUBLE_COLUMN_MM / 25.4 * 600)


def test_smallest_font_in_any_figure_is_at_least_the_minimum(final_results, option_e):
    for fig in (fg.figure_f1(final_results)[0], fg.figure_f2(option_e)[0], fg.figure_f4(final_results)[0], fg.figure_s1(final_results)[0], fg.figure_s2()[0]):
        fig.canvas.draw()
        sizes = [t.get_fontsize() for t in fig.findobj(matplotlib.text.Text) if t.get_text().strip()]
        assert min(sizes) >= fg.MIN_FONT_PT - 0.5 - 1e-9, min(sizes)  # the scenario tags under the bars are MIN_FONT_PT - 0.5 by design
        plt.close(fig)


def test_same_inputs_give_byte_identical_pdf_and_svg(final_results, tmp_path):
    outs = []
    for k in range(2):
        fig, frame, cap = fg.figure_f1(final_results)
        outs.append(fg.write_figure(fig, "F1", frame, cap, tmp_path / str(k), dpi=LOW_DPI))
    for ext in ("pdf", "svg", "png"):
        assert outs[0][ext].read_bytes() == outs[1][ext].read_bytes(), ext


def test_build_records_hashes_and_the_provisional_flag_in_the_manifest(final_results, option_e, tmp_path):
    fr_path = tmp_path / "final_results.parquet"
    final_results.to_parquet(fr_path)
    oe_path = tmp_path / "oe.csv.parquet"
    option_e.to_parquet(oe_path)
    out = tmp_path / "figs"
    m = fg.build(["F1", "F2"], final_results=fr_path, option_e=oe_path, out_dir=out, dpi=LOW_DPI)
    assert m["provisional_decarbon_standards"] is True and m["matplotlib"] == matplotlib.__version__
    assert m["inputs"]["final_results"]["sha256"] == fg.sha256_of(fr_path) and m["inputs"]["option_e"]["sha256"] == fg.sha256_of(oe_path)
    assert set(m["figures"]) == {"F1", "F2"}
    for f in m["figures"]["F1"].values():
        assert f["sha256"] == fg.sha256_of(out / f["file"])
    m2 = fg.build(["S2"], out_dir=out, dpi=LOW_DPI)  # a later partial run keeps the earlier entries
    assert set(m2["figures"]) == {"F1", "F2", "S2"}
    assert json.loads((out / "figures_manifest.json").read_text(encoding="utf-8"))["figures"].keys() == m2["figures"].keys()


def test_f1_and_f2_do_not_draw_a_history_overlay_or_a_methodology_comparison(final_results, option_e):
    f1 = fg.figure_f1(final_results)[0]
    texts = " ".join(fg.figure_texts(f1)).lower()
    assert "observed" not in texts and "2022" not in texts and "national" not in texts and "regional" not in texts
    f2 = " ".join(fg.figure_texts(fg.figure_f2(option_e)[0])).lower()
    assert "national" not in f2 and "regional" not in f2


# --------------------------------------------------------------------------------------------------------------------------------------------------- against the real production tables
@pytest.mark.integration
def test_real_tables_build_every_figure_and_match_the_prototype_numbers(tmp_path):
    from curtailmit import paths

    layout = paths.planned_layout()
    if not (layout["tables"] / "final_results.parquet").is_file() or not (layout["processed"] / rw.OPTION_E_FILENAME).is_file():
        pytest.skip("no local production tables")
    m = fg.build(out_dir=tmp_path, dpi=LOW_DPI)
    assert set(m["figures"]) == set(fg.FIGURE_IDS)
    fr = fg.load_final_results()
    h = fg.headline_frame(fr)
    assert len(h) == 12
    oe = fg.load_option_e()
    c = fg.coverage_frame(oe).set_index(["scenario", "year"])
    assert abs(c.loc[("TB", 2050), "pct_hours_inside_support_wind"] - 60) < 1.0
    fixture = pd.read_csv(FIXTURES / "option_e_support.csv")
    live = oe[list(fixture.columns)].sort_values(["scenario", "year"]).reset_index(drop=True)
    assert np.allclose(live.drop(columns=["scenario"]).astype(float), fixture.sort_values(["scenario", "year"]).reset_index(drop=True).drop(columns=["scenario"]).astype(float), rtol=1e-9)
