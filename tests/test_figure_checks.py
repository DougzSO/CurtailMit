"""The automated figure checks (Task 13B-finalize): they must pass on good figures AND demonstrably catch overlap, off-table numbers, placeholders, missing units and OM + CM wording.
Looking at the figures remains a human step; this file only covers what is programmatic."""

from __future__ import annotations

import matplotlib
import matplotlib.pyplot as plt
import pandas as pd
import pytest
from test_final_results import AVG, MARG, mock_option_e

from curtailmit import figure_checks as fc
from curtailmit import figures as fg
from curtailmit import results_writer as rw

matplotlib.use("Agg")


@pytest.fixture(scope="module")
def tables(tmp_path_factory):
    d = tmp_path_factory.mktemp("tables")
    central, _ = rw.build_final_results_with_sensitivity(mock_option_e(), AVG, MARG, True)
    central.to_parquet(d / "final_results.parquet")
    pd.read_csv(fg.PROJECT_ROOT / "tests" / "fixtures" / "figures" / "option_e_support.csv").to_parquet(d / "oe.parquet")
    return central, d / "final_results.parquet", d / "oe.parquet"


@pytest.fixture(autouse=True)
def _close():
    yield
    plt.close("all")


def test_every_figure_passes_every_check_on_the_mock_tables(tables):
    _, fr_path, oe_path = tables
    report = fc.run(fr_path, oe_path)
    assert set(report) == set(fg.FIGURE_IDS)
    for fid, r in report.items():
        assert r["overlaps"] == [] and r["mismatches"] == [] and r["text_problems"] == [], (fid, r)
        assert r["n_numbers"] > 20
        assert r["width_mm"] == fg.FIGURE_WIDTH_MM[fid]


def test_overlap_detector_finds_a_planted_overlap_text_outside_the_figure_and_a_legend_over_data():
    fig, ax = plt.subplots(figsize=(3, 2))
    ax.text(0.5, 0.5, "first label", transform=ax.transAxes)
    ax.text(0.5, 0.5, "second label", transform=ax.transAxes)
    ax.text(0.5, 1.6, "off the page", transform=ax.transAxes)
    found = fc.text_overlaps(fig)
    assert any("first label" in p and "second label" in p for p in found) and any("outside the figure" in p and "off the page" in p for p in found)
    fig2, ax2 = plt.subplots(figsize=(3, 2))
    ax2.text(0.1, 0.1, "alpha", transform=ax2.transAxes)
    ax2.text(0.1, 0.8, "beta", transform=ax2.transAxes)
    assert [p for p in fc.text_overlaps(fig2) if "alpha" in p or "beta" in p] == []
    fig3, ax3 = plt.subplots(figsize=(3, 2))
    ax3.bar([0], [1], gid="band-x")
    ax3.bar([0], [1])
    ax3.plot([0], [1], label="series")
    ax3.legend(loc="center")
    assert any("legend over data" in p for p in fc.text_overlaps(fig3))


def test_number_verification_catches_a_value_that_is_not_in_the_table(tables):
    central, _, _ = tables
    fig, _, _ = fg.figure_f1(central)
    assert fc.verify_f1(fig, central)[0] == []
    tampered = central.copy()
    hit = (tampered.quantity == "mitigation_deficit_marginal_om") & (tampered.component == "total") & (tampered.scenario == "TB") & (tampered.year == 2050)
    tampered.loc[hit, "central_value"] *= 1.001
    problems, _ = fc.verify_f1(fig, tampered)
    assert len(problems) == 1 and "TB 2050 central" in problems[0]
    t2 = central.copy()
    t2.loc[(t2.quantity == "mitigation_deficit_marginal_cm") & (t2.component == "total") & (t2.scenario == "TA") & (t2.year == 2040), "conditional_range_high"] += 1.0
    assert any("TA 2040 high" in p for p in fc.verify_f1(fig, t2)[0])


def test_f2_and_s2_verification_catch_a_changed_source():
    oe = pd.read_csv(fg.PROJECT_ROOT / "tests" / "fixtures" / "figures" / "option_e_support.csv")
    fig, _, _ = fg.figure_f2(oe)
    assert fc.verify_f2(fig, oe)[0] == []
    bad = oe.copy()
    bad.loc[(bad.scenario == "TG") & (bad.year == 2050), "E_out_solar"] += 0.01
    assert any("solar TG 2050" in p for p in fc.verify_f2(fig, bad)[0])
    figs, _, _ = fg.figure_s2()
    bt = fg.backtest_frame()
    assert fc.verify_s2(figs, bt)[0] == []
    bad_bt = bt.copy()
    bad_bt.loc[bad_bt.index[0], "obs_twh"] *= 2
    assert fc.verify_s2(figs, bad_bt)[0]


def test_text_checks_catch_placeholders_missing_units_and_om_plus_cm():
    fig, ax = plt.subplots()
    ax.set_ylabel("Deficit")
    ax.set_title("OM + CM deficit")
    ax.text(0.5, 0.5, "TODO fix", transform=ax.transAxes)
    problems = fc.check_texts(fig, "Figure X. caption", "S1")
    joined = " | ".join(problems)
    assert "placeholder" in joined and "without a unit" in joined and "never be combined" in joined
    fig2, ax2 = plt.subplots()
    ax2.set_ylabel("Energy (TWh)")
    ax2.set_title("conditional range (not a confidence interval)")
    assert fc.check_texts(fig2, "fine caption", "S1") == []
    ax2.set_title("a confidence interval")
    assert any("forbidden wording" in p for p in fc.check_texts(fig2, "ok", "S1"))
    ax2.set_title("hydrogen potential")
    assert any("hydrogen" in p for p in fc.check_texts(fig2, "ok", "S1"))


@pytest.mark.integration
def test_the_real_production_figures_pass_every_automated_check():
    from curtailmit import paths

    lay = paths.planned_layout()
    if not (lay["tables"] / "final_results.parquet").is_file() or not (lay["processed"] / rw.OPTION_E_FILENAME).is_file():
        pytest.skip("no local production tables")
    for fid, r in fc.run().items():
        assert r["overlaps"] == [] and r["mismatches"] == [] and r["text_problems"] == [], (fid, r)
