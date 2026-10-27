"""Task 11E4-a: publication-ready in-sample coverage figure and its data table (NOT part of the installed package; no src/ change).

Data: DATABASE_ROOT/outputs/tables/task11e2_coverage_table.csv (Task 11E2-a, phi = 1: today's flexibility), i.e. the PTE-scaled 2025 hourly shape of the SIN-wide potential VRE share of load r compared with the hourly r observed in
2022-01..2026-09 (41,616 hours). "Inside the observed support" = r <= 63 %: the last 2-pp bin of r that holds at least 15 observed hours; the largest r ever observed is 75.8 %.
Panel (a): share of the projected hours inside the support (bars) and inside the observed maximum (tick). Panel (b): share of the projected CURTAILED ENERGY produced by hours inside the support, wind (solid) and solar (dashed).
Convention for manuscript use: vector PDF (and SVG) plus a 600-dpi PNG in DATABASE_ROOT/outputs/figures/, named fig_insample_coverage.*; the numbers behind every bar are in fig_insample_coverage_data.csv in DATABASE_ROOT/outputs/tables/;
the caption text is saved as fig_insample_coverage_caption.txt next to the figure. Colour-blind-safe palette (Okabe-Ito); no colour is needed to read the panels (bar labels carry the values).
Run:  python analysis/task11e4_coverage_figure.py

SUPERSEDED (Task 13B, append-only note): the production figure is `curtailmit.figures` (F2, reading processed/pte_curtailment_option_E.parquet, without the r_max tick). This prototype is kept as the record of the analysis-time version.

"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import task11e_common as cm

SCEN = {"TB": ("TB", "#0072B2"), "TA": ("TA", "#D55E00"), "TG": ("TG", "#009E73")}
YEARS = (2025, 2030, 2040, 2050)
CAPTION = (
    "Figure X. Where the hourly dose-response model is anchored in observation. For each PTE scenario (TB, TA, TG) the 2025 hourly profile of the system-wide variable-renewable share of load is scaled to the projected annual wind, solar and load, "
    "and compared with the hourly values actually observed in Brazil in 2022-2026 (41,616 hours, maximum 75.8 %). (a) Share of projected hours that fall inside the range supported by at least 15 observed hours per 2-percentage-point class (bars) "
    "and inside the largest value ever observed (ticks); (b) share of the projected curtailed energy that is produced by hours inside the supported range. Observation essentially covers 2025 and 2030 (99.6-99.8 % of hours), covers 86-96 % of the 2040 hours "
    "and 43-70 % of the 2050 hours; in 2050, 51-77 % of the projected wind curtailment comes from hours with no historical analogue. We report this boundary explicitly and treat 2050 as a conditional range rather than a calibrated estimate: "
    "quantifying where the evidence ends is part of the method."
)


def build_table() -> pd.DataFrame:
    t = pd.read_csv(cm.tables_dir() / "task11e2_coverage_table.csv")
    t = t[(t.phi == 1.0) & t.year.isin(YEARS)].copy()
    out = pd.DataFrame({"scenario": t.scenario, "year": t.year, "pct_hours_inside_support": 100 * t.wind_hours_inside_cap15, "pct_hours_inside_observed_max": 100 * t.wind_hours_inside_r_max,
                        "pct_wind_curtailment_inside_support": 100 * (1 - t.wind_curt_share_beyond_cap15), "pct_solar_curtailment_inside_support": 100 * (1 - t.solar_curt_share_beyond_cap15),
                        "r_mean": t.r_mean, "r_p95": t.r_p95, "r_max": t.r_max})
    return out.sort_values(["year", "scenario"]).reset_index(drop=True)


def figure(tab: pd.DataFrame, stem: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 7.5, "axes.linewidth": 0.6, "axes.spines.top": False, "axes.spines.right": False, "pdf.fonttype": 42, "svg.fonttype": "none"})
    fig, (a, b) = plt.subplots(1, 2, figsize=(7.4, 3.3), gridspec_kw={"width_ratios": [1.25, 1]})
    xs = np.arange(len(YEARS))
    w = 0.26
    for i, (sc, (lab, col)) in enumerate(SCEN.items()):
        d = tab[tab.scenario == sc].set_index("year").reindex(YEARS)
        pos = xs + (i - 1) * w
        bars = a.bar(pos, d["pct_hours_inside_support"], w * 0.92, color=col, label=lab, zorder=2)
        a.plot(np.c_[pos - w * 0.46, pos + w * 0.46].T, np.c_[d["pct_hours_inside_observed_max"], d["pct_hours_inside_observed_max"]].T, color="k", lw=1.1, zorder=3)
        for r_, v, m in zip(bars, d["pct_hours_inside_support"], d["pct_hours_inside_observed_max"], strict=True):
            a.text(r_.get_x() + r_.get_width() / 2, max(v, m) + 1.5, f"{v:.0f}", ha="center", va="bottom", fontsize=6)
    a.plot([], [], color="k", lw=1.1, label="inside largest observed value")
    a.set_xticks(xs, [str(y) if y != 2025 else "2025\n(observed)" for y in YEARS])
    a.set(ylim=(0, 128), ylabel="Projected hours inside the observed range (%)", title="(a) Hours with historical support")
    a.axhline(100, color="0.6", lw=0.5, ls=":", zorder=1)
    a.legend(frameon=False, ncol=4, loc="upper center", fontsize=6.3, columnspacing=1.0, handlelength=1.4)
    a.text(-0.02, 1.0, "", transform=a.transAxes)
    for i, (sc, (lab, col)) in enumerate(SCEN.items()):
        d = tab[tab.scenario == sc].set_index("year").reindex(YEARS)
        b.plot(xs, d["pct_wind_curtailment_inside_support"], "-o", color=col, lw=1.4, ms=3.5, label=f"{lab} wind")
        b.plot(xs, d["pct_solar_curtailment_inside_support"], "--s", color=col, lw=1.0, ms=3, mfc="white", label=f"{lab} solar")
    b.set_xticks(xs, [str(y) if y != 2025 else "2025\n(observed)" for y in YEARS])
    b.set(ylim=(0, 105), ylabel="Projected curtailment from supported hours (%)", title="(b) Energy with historical support")
    b.legend(frameon=False, fontsize=6, ncol=2, loc="lower left")
    fig.tight_layout()
    for ext in ("pdf", "svg"):
        fig.savefig(stem.with_suffix(f".{ext}"))
    fig.savefig(stem.with_suffix(".png"), dpi=600)
    plt.close(fig)


def main() -> None:
    tab = build_table()
    stem = Path(cm.figs_dir()) / "fig_insample_coverage"
    tab.to_csv(Path(cm.tables_dir()) / "fig_insample_coverage_data.csv", index=False)
    figure(tab, stem)
    Path(str(stem) + "_caption.txt").write_text(CAPTION + "\n", encoding="utf-8")
    print(tab.round(1).to_string(index=False))
    print("figure files:", [p.name for p in stem.parent.glob("fig_insample_coverage*")], "in", stem.parent)


if __name__ == "__main__":
    main()
