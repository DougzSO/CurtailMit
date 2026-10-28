"""Article figures (Task 13B, design in docs/task13b_design.md and its addendum).

Figures: F1 (mitigation deficit, OM and CM factors in separate panels, never added: D28, plus the average factor for reference), F2 (support: (a) hours, (b) energy, (c) in-support / beyond-support
decomposition), S1 (empirical band next to the split-conformal supplement), S2 (analysis-derived backtest, from the committed fixture tests/fixtures/figures/backtest_annual.csv). The earlier F1 (curtailed
energy by scenario and horizon) was dropped at the user's review and the earlier F4 became F1: the curtailed energy itself is carried by the results table (T1). T1 (full results), T2 (hydrogen and SEC
range, D30) and T3 (MCTI sensitivity, D29) stay tables. F3 was folded into F2 panel (c) (addendum Q4). There is no national / regional / Option E comparison figure (Q6) and no history overlay (Q2). The
"largest observed value" (r_max) reference of the 11E4 prototype is not drawn and no r_max column exists anywhere (Q8). The context figures C1, C1S, C2 are in `curtailmit.figures_context`.

Data discipline: every number plotted is read from `final_results` (validated with `results_writer.read_final_results`) or, for F2 only, from the Option E production table
(`processed/pte_curtailment_option_E.parquet`, the table `final_results` is built from). Nothing is recomputed from raw data. Captions take their numbers from the same frames.

2050 (D24, D25): style V1. The 2050 range is a conditional range between two stated scenarios (flexibility phi = 1.5 and L = 1), drawn as an unfilled, hatched box with a DASHED outline on a grey zone,
with the central value as a diamond; the 2025-2040 empirical annual-backtest band is a solid, tinted bar with a dot. The central value is NOT at the midpoint of the 2050 range and must not be moved
there: the table says where it is (D25). Nothing in a figure may suggest confidence-interval semantics. The one phrase the text check lets through is the literal negation `not a confidence interval`.

DeCarbon standards (Task 13B-finalize): the bitmap resolution and the column widths are CONFIRMED from the author-guide excerpt the user supplied (halftone 300 dpi, combination 500 dpi, line art 1000 dpi; columns 90 / 140 / 190 mm).
Font size (7.5 pt, floor 6 pt) and the Okabe-Ito palette were not in that excerpt: they are the project's own accessibility choices, listed in PROVISIONAL_STANDARDS and changeable in the block below.

    python -m curtailmit.figures [--only F1,F2,S1,S2] [--out-dir DIR] [--dpi N]      (also: python scripts/generate_figures.py)

Figures are not a stage of `curtailmit-run`: they do not affect the numbers, and a plotting failure must not fail a numerical run (design section 5). The CLI refuses to run on a `final_results` table
that does not validate and writes `figures_manifest.json` (SHA-256 of the inputs and of every output file, matplotlib version) so that a figure can be traced to the exact table.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Iterable
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless (CI has no display); set before pyplot is imported

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle
from matplotlib.text import Text

from curtailmit import hourly_model
from curtailmit import results_writer as rw

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKTEST_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "figures" / "backtest_annual.csv"

# ------------------------------------------------------------------------------------------------------------------------------------ DeCarbon figure standards (Task 13B-finalize)
# Source of the CONFIRMED entries: an excerpt of the DeCarbon author guide supplied by the user (not a URL). See docs/task13b_design.md, "Task 13B-finalize".
CONFIRMED_STANDARDS = {"dpi": True, "column_width_mm": True}
# Not in the excerpt: the project's own accessibility choices, final unless the user says otherwise.
PROVISIONAL_STANDARDS = {"font_size": True, "color_palette": True}
SINGLE_COLUMN_MM = 90.0
ONE_AND_HALF_COLUMN_MM = 140.0
DOUBLE_COLUMN_MM = 190.0
RASTER_DPI_BY_ART = {"halftone": 300, "combination": 500, "line": 1000}  # the guide's minima per art type
# The figures mix hatched / tinted regions with line work, which sits between "combination" and "line art". The ambiguity is removed, not resolved figure by figure: the STRICTEST category (line art, 1000 dpi)
# is applied to every PNG (the conservative choice: more pixels rather than the risk of a rejected raster). PNG is the only figure format written (see OUTPUT_FORMATS); the 1000 dpi therefore is the deliverable resolution.
PNG_DPI = RASTER_DPI_BY_ART["line"]
# Target width per figure: a layout judgment by content density (multi-panel or long-legend figures take the double column). Changing an entry only re-renders; no data is re-derived.
FIGURE_WIDTH_MM = {"F1": DOUBLE_COLUMN_MM, "F2": DOUBLE_COLUMN_MM, "S1": DOUBLE_COLUMN_MM, "S2": ONE_AND_HALF_COLUMN_MM}
FONT_FAMILY = "DejaVu Sans"  # ships with matplotlib: no system font needed
FONT_PT = 7.5
MIN_FONT_PT = 6.0
OKABE_ITO = {"TB": "#0072B2", "TA": "#D55E00", "TG": "#009E73"}  # categorical, colour-blind safe; every distinction is also carried by fill / marker / line style
OKABE_ITO_EXTRA = {"orange": "#E69F00", "sky": "#56B4E9", "purple": "#CC79A7", "grey": "#666666"}
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

SCENARIOS = ("TB", "TA", "TG")
YEARS = (2025, 2030, 2040, 2050)
FIGURE_IDS = ("F1", "F2", "S1", "S2")
CONDITIONAL_LABEL = "conditional range (not a confidence interval)"
BAND_LABEL = "empirical annual-backtest band (descriptive; not a coverage guarantee)"
CONDITIONAL_NOTE = "2050 values are a range conditional on a flexibility assumption (φ 1.5 to L = 1), not a statistical interval"
ALLOWED_NEGATION = "not a confidence interval"  # D24: an explicit denial of confidence-interval semantics; the only literal the figure-text check lets through (see check_text)
GROUP_X = {2025: 0.0, 2030: 1.0, 2040: 2.0, 2050: 3.45}  # a visible gutter before 2050
SLOT = 0.30
BAR_W = 0.25
MM = 1 / 25.4


class FigureInputError(ValueError):
    """The input table cannot be plotted (missing grid cell, interpolated row, failed validation, missing column)."""


class FigureTextError(ValueError):
    """A figure or caption string contains vocabulary that the project forbids (probabilistic-interval wording)."""


# ============================================================================================================================================================================== text check
def check_text(text: str) -> list[str]:
    """Forbidden-vocabulary hits in one string. The exact literal `not a confidence interval` is removed first and nothing else is excused (D24: the phrase denies the semantics the filter guards against)."""
    cleaned = str(text).replace(ALLOWED_NEGATION, "")
    return [m.group(0) for m in rw.FORBIDDEN_LANGUAGE.finditer(cleaned)]


def figure_texts(fig) -> list[str]:
    """Every non-empty text of a drawn figure: titles, labels, ticks, legend entries, annotations."""
    fig.canvas.draw()
    return [t.get_text() for t in fig.findobj(Text) if t.get_text().strip()]


def assert_clean(strings: Iterable[str], where: str) -> None:
    bad = {s: check_text(s) for s in strings if check_text(s)}
    if bad:
        raise FigureTextError(f"forbidden wording in {where}: {bad}")


# ============================================================================================================================================================================ input guards
def _grid_problems(df: pd.DataFrame, quantity: str, component: str = "total") -> list[str]:
    sub = df[(df["quantity"] == quantity) & (df["component"] == component)]
    have = set(zip(sub["scenario"], sub["year"].astype(int), strict=True))
    return [f"{quantity}/{component}: missing {s} {y}" for s in SCENARIOS for y in YEARS if (s, y) not in have]


def check_final_results(df: pd.DataFrame) -> None:
    """Refuses a table that does not validate, carries an interpolated row, or lacks a scenario-year the figures need."""
    try:
        rw.validate_final_results(df)
    except Exception as exc:  # FinalResultsError / ModelProvenanceError: keep the cause in the message
        raise FigureInputError(f"final_results does not validate: {exc}") from exc
    if df["is_interpolated"].astype(bool).any():
        raise FigureInputError("final_results carries interpolated rows; figures use observed-grid scenario-years only")
    problems = [p for q in ("curtailed_energy", "mitigation_deficit_avg", "mitigation_deficit_marginal_om", "mitigation_deficit_marginal_cm") for p in _grid_problems(df, q)]
    if problems:
        raise FigureInputError("; ".join(problems))


def load_final_results(path: Path | None = None) -> pd.DataFrame:
    path = Path(path) if path is not None else _tables_dir() / f"{rw.FINAL_RESULTS_FILENAME}.parquet"
    if not path.is_file():
        raise FigureInputError(f"{path} not found: run the pipeline (curtailmit-run) first")
    df = rw.read_final_results(path)
    check_final_results(df)
    return df


SUPPORT_COLUMNS = ("scenario", "year", "H_out_wind", "H_out_solar", "E_out_wind", "E_out_solar", "curt_in_support_total_twh", "curt_out_support_total_twh", "r_cap_wind")


def check_option_e(df: pd.DataFrame) -> None:
    missing = [c for c in SUPPORT_COLUMNS if c not in df.columns]
    if missing:
        raise FigureInputError(f"Option E table lacks the columns {missing}")
    if "model" in df.columns and (df["model"] != rw.REQUIRED_MODEL).any():
        raise FigureInputError(f"Option E table must hold model == {rw.REQUIRED_MODEL!r} only")
    have = set(zip(df["scenario"], df["year"].astype(int), strict=True))
    gaps = [f"{s} {y}" for s in SCENARIOS for y in YEARS if (s, y) not in have]
    if gaps:
        raise FigureInputError(f"Option E table lacks {gaps}")


def load_option_e(path: Path | None = None) -> pd.DataFrame:
    path = Path(path) if path is not None else _processed_dir() / rw.OPTION_E_FILENAME
    if not path.is_file():
        raise FigureInputError(f"{path} not found: run the pipeline (curtailmit-run) first")
    df = pd.read_parquet(path)
    check_option_e(df)
    return df


def _tables_dir() -> Path:
    from curtailmit import paths

    return paths.planned_layout()["tables"]


def _processed_dir() -> Path:
    from curtailmit import paths

    return paths.planned_layout()["processed"]


def default_out_dir() -> Path:
    from curtailmit import paths

    return paths.planned_layout()["tables"].parent / "figures"


# =================================================================================================================================================================== data-extraction frames
def _order(df: pd.DataFrame) -> pd.DataFrame:
    df = df.assign(_s=df["scenario"].map({s: i for i, s in enumerate(SCENARIOS)})).sort_values(["year", "_s"]).drop(columns="_s")
    return df.reset_index(drop=True)


def headline_frame(fr: pd.DataFrame, quantity: str = "curtailed_energy", scale: float = 1.0) -> pd.DataFrame:
    """Total component of one quantity: central value and range exactly as in the table (only a unit scale is applied, for display)."""
    sub = fr[(fr["quantity"] == quantity) & (fr["component"] == "total")]
    out = pd.DataFrame({"scenario": sub["scenario"].to_numpy(), "year": sub["year"].astype(int).to_numpy(), "unit": sub["unit"].to_numpy(),
                        "central": sub["central_value"].to_numpy() / scale, "low": sub["conditional_range_low"].to_numpy() / scale, "high": sub["conditional_range_high"].to_numpy() / scale,
                        "horizon_treatment": sub["horizon_treatment"].to_numpy(), "support_status": sub["support_status"].to_numpy(), "in_support_fraction": sub["in_support_fraction"].to_numpy(),
                        "supplement_low": sub["supplement_low"].to_numpy() / scale, "supplement_high": sub["supplement_high"].to_numpy() / scale})
    return _order(out)


def mitigation_frame(fr: pd.DataFrame) -> pd.DataFrame:
    """Long frame: one row per scenario / year / factor kind (om, cm, avg) with its own central value and range, in MtCO2. OM and CM are separate rows and are never combined (D28)."""
    parts = []
    for kind, quantity in (("om", "mitigation_deficit_marginal_om"), ("cm", "mitigation_deficit_marginal_cm"), ("avg", "mitigation_deficit_avg")):
        parts.append(headline_frame(fr, quantity, scale=1e6).assign(kind=kind))
    return pd.concat(parts, ignore_index=True)


def coverage_frame(oe: pd.DataFrame) -> pd.DataFrame:
    """Support diagnostics straight from the Option E table: percentages of hours / energy inside the observed support (wind and solar) and the in / beyond-support TWh of the total."""
    sub = oe.copy()
    out = pd.DataFrame({"scenario": sub["scenario"], "year": sub["year"].astype(int),
                        "pct_hours_inside_support_wind": 100 * (1 - sub["H_out_wind"]), "pct_hours_inside_support_solar": 100 * (1 - sub["H_out_solar"]),
                        "pct_curtailment_inside_support_wind": 100 * (1 - sub["E_out_wind"]), "pct_curtailment_inside_support_solar": 100 * (1 - sub["E_out_solar"]),
                        "pct_curtailment_beyond_support_wind": 100 * sub["E_out_wind"],
                        "curt_in_support_total_twh": sub["curt_in_support_total_twh"], "curt_out_support_total_twh": sub["curt_out_support_total_twh"], "r_cap_wind": sub["r_cap_wind"]})
    return _order(out)


def decomposition_frame(cov: pd.DataFrame, years: tuple[int, ...] = (2040, 2050)) -> pd.DataFrame:
    """Panel (c): curtailed energy of the total split into in-support and beyond-support parts (D24 requires the split for 2050)."""
    d = cov[cov["year"].isin(years)][["scenario", "year", "curt_in_support_total_twh", "curt_out_support_total_twh"]].copy()
    d["pct_beyond_support"] = 100 * d["curt_out_support_total_twh"] / (d["curt_in_support_total_twh"] + d["curt_out_support_total_twh"])
    return _order(d)


def supplement_frame(fr: pd.DataFrame) -> pd.DataFrame:
    """S1: band and split-conformal supplement of the total curtailed energy, 2025-2040 only (the supplement is empty in 2050), with the width ratio."""
    h = headline_frame(fr)
    h = h[h["horizon_treatment"] == rw.HORIZON_BAND].copy()
    h["band_width"] = h["high"] - h["low"]
    h["supplement_width"] = h["supplement_high"] - h["supplement_low"]
    h["width_ratio"] = h["supplement_width"] / h["band_width"]
    return h.reset_index(drop=True)


SCHEME_GROUPS = ("in-sample", "leave-one-year-out", "train on earlier years, test later")


def scheme_group(scheme: str) -> str:
    s = str(scheme)
    return SCHEME_GROUPS[0] if s.startswith("in-sample") else SCHEME_GROUPS[1] if s.startswith("leave-one-year-out") else SCHEME_GROUPS[2]


def period_order(d: pd.DataFrame) -> list[str]:
    """Chronological x order of the evaluation periods: by year, a partial-year window after the full year of the same calendar year."""
    return sorted(dict.fromkeys(d["period"].astype(str)), key=lambda p: (int(p[:4]), "(" in p))


def backtest_frame(path: Path | None = None) -> pd.DataFrame:
    """S2 data: observed vs hourly-model annual curtailment (TWh) from the committed analysis fixture. ANALYSIS-DERIVED (Task 11E2), not production pipeline output."""
    path = Path(path) if path is not None else BACKTEST_FIXTURE
    if not path.is_file():
        raise FigureInputError(f"{path} not found")
    df = pd.read_csv(path)
    need = {"tech", "scheme", "period", "obs_twh", "hourly_twh"}
    if need - set(df.columns):
        raise FigureInputError(f"backtest table lacks {sorted(need - set(df.columns))}")
    df = df.assign(group=df["scheme"].map(scheme_group))
    return df.reset_index(drop=True)


# ============================================================================================================================================================================= caption builders
def _rng(values: Iterable[float], nd: int = 0, suffix: str = "") -> str:
    v = [float(x) for x in values]
    lo, hi = round(min(v), nd), round(max(v), nd)
    fmt = f"{{:.{nd}f}}"
    return fmt.format(lo) + suffix if lo == hi else f"{fmt.format(lo)}-{fmt.format(hi)}{suffix}"


DRAFT = "[DRAFT caption, subject to revision.]"


def caption_f2(cov: pd.DataFrame) -> str:
    def hours(y):
        return _rng(cov[cov["year"] == y]["pct_hours_inside_support_wind"])

    dec = decomposition_frame(cov)
    return (f"{DRAFT} Figure F2. Where the hourly model is anchored in observation. (a) Share of the projected hours whose system-wide variable-renewable share of load lies inside the observed range, "
            f"defined as the classes of 2 percentage points with at least {hourly_model.MIN_HOURS} observed hours (up to {cov['r_cap_wind'].iloc[0]:.0f} % of load); (b) share of the projected curtailed energy produced by hours inside that range, wind (solid) and solar (dashed); "
            f"(c) curtailed energy of 2040 and 2050 split into the part from hours inside and beyond the observed range. Observation covers {hours(2025)} % of the 2025 hours and {hours(2030)} % of the 2030 hours, "
            f"{hours(2040)} % of the 2040 hours and {hours(2050)} % of the 2050 hours; {_rng(cov[cov['year'] == 2050]['pct_curtailment_beyond_support_wind'])} % of the 2050 wind curtailment comes from hours with no historical analogue "
            f"({_rng(dec[dec['year'] == 2050]['pct_beyond_support'])} % of the 2050 total). The boundary is reported explicitly: 2050 (cond. = conditional) is a conditional range (not a confidence interval), not a calibrated estimate.")


def caption_f1(m: pd.DataFrame) -> str:
    y50 = m[(m["year"] == 2050) & (m["kind"] != "avg")]
    return (f"{DRAFT} Figure F1. Avoided-emission deficit (MtCO2) caused by curtailed wind and solar energy for the three PTE scenarios, with the operating-margin (a) and combined-margin (b) factors in separate panels: the two are alternative proxies for the marginal "
            f"emission factor and are never added (D28). Panel (c) gives the average-factor deficit for reference. Bars are the empirical annual-backtest band (descriptive; not a coverage guarantee) around the central "
            f"value (dot); the emission factor is not included in the range. In 2050 the hatched box with a dashed outline is a conditional range (not a confidence interval). {CONDITIONAL_NOTE}; the central value (diamond) is not at its midpoint. "
            f"Central 2050 values (MtCO2): operating margin {_rng(y50[y50['kind'] == 'om']['central'])}, combined margin {_rng(y50[y50['kind'] == 'cm']['central'])}.")


def caption_s1(s: pd.DataFrame) -> str:
    return (f"{DRAFT} Figure S1 (supplement). Empirical annual-backtest band (narrow bars) and the nominal 80 % split-conformal supplement (wide bars) of the annual curtailed energy, 2025-2040; the supplement is empty in 2050. "
            f"The supplement is {_rng(s['width_ratio'])} times wider than the band, so it cannot share an axis with the headline range without dominating it. Dot: central value.")


def caption_s2() -> str:
    return (f"{DRAFT} Figure S2 (supplement). Observed and modelled annual curtailment (TWh) for wind and solar, Task 11E2 backtest: model fitted on all months (in-sample), with one year left out, or fitted on earlier years and tested on later ones. "
            "ANALYSIS-DERIVED: these numbers come from the analysis scripts (committed fixture tests/fixtures/figures/backtest_annual.csv), not from the production pipeline output. "
            "Partial years are marked with their months. Out-of-sample errors are large and of both signs in the early, low-curtailment years.")


# ================================================================================================================================================================================= styling
def apply_style() -> None:
    plt.rcParams.update({"font.family": FONT_FAMILY, "font.size": FONT_PT, "axes.linewidth": 0.6, "axes.spines.top": False, "axes.spines.right": False, "pdf.fonttype": 42, "svg.fonttype": "none",
                         "svg.hashsalt": "curtailmit", "hatch.linewidth": 0.6, "xtick.major.width": 0.6, "ytick.major.width": 0.6, "legend.fontsize": MIN_FONT_PT + 0.3})


def _fig(width_mm: float, height_in: float, **kw):
    apply_style()
    return plt.subplots(figsize=(width_mm * MM, height_in), **kw)


def _label(ax, text: str) -> None:
    ax.text(0.0, 1.02, text, transform=ax.transAxes, fontsize=FONT_PT, fontweight="bold", va="bottom", ha="left")


def _year_ticks(ax) -> None:
    """Year labels as major ticks; the scenario name is printed under every bar (text, not minor ticks: the TA slot coincides with the year tick)."""
    ax.set_xticks([GROUP_X[y] for y in YEARS], [str(y) if y != 2050 else "2050\n(conditional)" for y in YEARS])
    ax.tick_params(axis="x", length=0, pad=10)
    for y in YEARS:
        for i, sc in enumerate(SCENARIOS):
            ax.text(GROUP_X[y] + (i - 1) * SLOT, -0.015, sc, transform=ax.get_xaxis_transform(), ha="center", va="top", fontsize=MIN_FONT_PT - 0.5, color=OKABE_ITO[sc])


NOTE_2050 = "conditional,\nmostly out of support"


def _zone_2050(ax, top: float, note: str = NOTE_2050) -> None:
    x0, x1 = GROUP_X[2050] - 0.5, GROUP_X[2050] + 0.5
    ax.axvspan(x0, x1, facecolor="0.93", edgecolor="none", zorder=0, gid="zone-2050")
    ax.text(GROUP_X[2050], top, note, ha="center", va="top", fontsize=MIN_FONT_PT, color="0.25", zorder=4, gid="note-2050")


def draw_series(ax, df: pd.DataFrame, ylabel: str, note: str = NOTE_2050) -> None:
    """Style V1 on one axis: solid tinted bar + dot for the empirical band (2025-2040), unfilled hatched box with a dashed outline + diamond for the 2050 conditional range."""
    for i, sc in enumerate(SCENARIOS):
        col = OKABE_ITO[sc]
        for _, r in df[df["scenario"] == sc].iterrows():
            x = GROUP_X[int(r["year"])] + (i - 1) * SLOT
            tag = f"{sc}-{int(r['year'])}"
            if r["horizon_treatment"] == rw.HORIZON_CONDITIONAL:
                ax.add_patch(Rectangle((x - BAR_W / 2, r["low"]), BAR_W, r["high"] - r["low"], fill=False, hatch="////", edgecolor=col, linestyle="--", linewidth=0.9, zorder=3, gid=f"conditional-{tag}"))
                ax.plot([x], [r["central"]], marker="D", ms=3.6, mfc=col, mec="k", mew=0.5, ls="none", zorder=5, gid=f"central-{tag}")
            else:
                ax.add_patch(Rectangle((x - BAR_W / 2, r["low"]), BAR_W, r["high"] - r["low"], facecolor=col, alpha=0.35, edgecolor=col, linestyle="-", linewidth=0.6, zorder=3, gid=f"band-{tag}"))
                partial = r["support_status"] != "within_support"
                ax.plot([x], [r["central"]], marker="o", ms=3.4, mfc="white" if partial else col, mec=col if partial else "k", mew=0.9 if partial else 0.5, ls="none", zorder=5, gid=f"central-{tag}")
                if partial:
                    ax.text(x, r["high"], "partial\nsupport", ha="center", va="bottom", fontsize=MIN_FONT_PT, color="0.2", gid=f"partial-{tag}")
    top = float(df["high"].max()) * 1.25
    ax.set_ylim(0, top)
    ax.set_xlim(GROUP_X[2025] - 0.55, GROUP_X[2050] + 0.55)
    _zone_2050(ax, top * 0.995, note)
    _year_ticks(ax)
    ax.set_ylabel(ylabel)


def _v1_handles() -> list:
    return [Patch(facecolor="0.55", alpha=0.35, edgecolor="0.4", label=BAND_LABEL), Line2D([], [], marker="o", color="none", mfc="0.4", mec="k", ms=3.4, label="central value"),
            Patch(facecolor="none", hatch="////", edgecolor="0.3", linestyle="--", linewidth=0.9, label=CONDITIONAL_LABEL), Line2D([], [], marker="D", color="none", mfc="0.4", mec="k", ms=3.6, label="central value, 2050")]


# ============================================================================================================================================================================ figure builders
def figure_f1(fr: pd.DataFrame):
    """Mitigation deficit (MtCO2): the operating-margin (a) and combined-margin (b) factors in separate panels, never added (D28), and the average factor (c) for reference; the legend sits in the fourth cell of a 2 x 2 grid."""
    m = mitigation_frame(fr)
    fig, axes = _fig(FIGURE_WIDTH_MM["F1"], 5.6, nrows=2, ncols=2, layout="constrained")
    titles = {"om": "(a) Operating margin (OM) factor", "cm": "(b) Combined margin (CM) factor", "avg": "(c) Average factor (reference)"}
    for ax, kind in zip(axes.flat, ("om", "cm", "avg"), strict=False):
        draw_series(ax, m[m["kind"] == kind], "Avoided-emission deficit (MtCO$_2$)")
        ax.set_title(titles[kind], fontsize=FONT_PT, loc="left")
    key = axes.flat[3]
    key.axis("off")
    key.legend(handles=_v1_handles(), loc="center left", frameon=False, ncol=1, handlelength=2.0, fontsize=MIN_FONT_PT + 0.5, labelspacing=0.9)
    key.text(0.0, 0.12, "The emission factor is not included in the ranges (D28).", transform=key.transAxes, fontsize=MIN_FONT_PT, color="0.25", va="top", gid="note-factor")
    return fig, m, caption_f1(m)


def figure_f2(oe: pd.DataFrame):
    cov = coverage_frame(oe)
    dec = decomposition_frame(cov)
    fig, (a, b, c) = _fig(FIGURE_WIDTH_MM["F2"], 3.4, ncols=3, gridspec_kw={"width_ratios": [1.25, 1, 0.9]})
    xs = np.arange(len(YEARS))
    ticks = [str(y) if y != 2050 else "2050\n(cond.)" for y in YEARS]
    w = 0.26
    for i, sc in enumerate(SCENARIOS):
        d = cov[cov["scenario"] == sc].set_index("year").reindex(YEARS)
        pos = xs + (i - 1) * w
        bars = a.bar(pos, d["pct_hours_inside_support_wind"], w * 0.92, color=OKABE_ITO[sc], label=sc, zorder=2)
        for rect, v, yr in zip(bars, d["pct_hours_inside_support_wind"], YEARS, strict=True):
            rect.set_gid(f"hours-{sc}-{yr}")
            a.text(rect.get_x() + rect.get_width() / 2, v + 1.5, f"{v:.0f}", ha="center", va="bottom", fontsize=MIN_FONT_PT, rotation=90)
        b.plot(xs, d["pct_curtailment_inside_support_wind"], "-o", color=OKABE_ITO[sc], lw=1.4, ms=3.5, label=f"{sc} wind", gid=f"energy-wind-{sc}")
        b.plot(xs, d["pct_curtailment_inside_support_solar"], "--s", color=OKABE_ITO[sc], lw=1.0, ms=3, mfc="white", label=f"{sc} solar", gid=f"energy-solar-{sc}")
    a.set_xticks(xs, ticks)
    a.set(ylim=(0, 128), ylabel="Projected hours inside the observed range (%)")
    a.legend(frameon=False, ncol=3, loc="upper center", handlelength=1.2)
    _label(a, "(a) Hours with support")
    b.set_xticks(xs, ticks)
    b.set(ylim=(0, 105), ylabel="Projected curtailment from supported hours (%)")
    b.legend(frameon=False, ncol=2, loc="lower left", handlelength=1.6, fontsize=MIN_FONT_PT)
    _label(b, "(b) Energy with support")
    yrs = sorted(dec["year"].unique())
    cx = np.arange(len(yrs))
    for i, sc in enumerate(SCENARIOS):
        d = dec[dec["scenario"] == sc].set_index("year").reindex(yrs)
        pos = cx + (i - 1) * w
        for rect, yr in zip(c.bar(pos, d["curt_in_support_total_twh"], w * 0.92, color=OKABE_ITO[sc], zorder=2), yrs, strict=True):
            rect.set_gid(f"in-{sc}-{yr}")
        for rect, yr in zip(c.bar(pos, d["curt_out_support_total_twh"], w * 0.92, bottom=d["curt_in_support_total_twh"], facecolor="white", edgecolor=OKABE_ITO[sc], linewidth=0.9, zorder=2), yrs, strict=True):
            rect.set_gid(f"out-{sc}-{yr}")
        for p, tot, pct in zip(pos, d["curt_in_support_total_twh"] + d["curt_out_support_total_twh"], d["pct_beyond_support"], strict=True):
            c.text(p, tot + 6, f"{pct:.0f}%", ha="center", va="bottom", fontsize=MIN_FONT_PT)
    c.set_xticks(cx, [str(y) if y != 2050 else "2050\n(cond.)" for y in yrs])
    c.set(ylim=(0, float((dec["curt_in_support_total_twh"] + dec["curt_out_support_total_twh"]).max()) * 1.4), ylabel="Curtailed energy (TWh)")
    c.legend(handles=[Patch(facecolor="0.35", label="inside observed range"), Patch(facecolor="white", edgecolor="0.35", label="beyond it (share on top)")], frameon=False, loc="upper left", handlelength=1.2)
    _label(c, "(c) Origin of the energy")
    fig.tight_layout()
    return fig, cov, caption_f2(cov)


def figure_s1(fr: pd.DataFrame):
    s = supplement_frame(fr)
    fig, axes = _fig(FIGURE_WIDTH_MM["S1"], 3.0, ncols=3, sharey=True)
    xs = {2025: 0, 2030: 1, 2040: 2}
    for ax, sc in zip(axes, SCENARIOS, strict=True):
        d = s[s["scenario"] == sc]
        col = OKABE_ITO[sc]
        for _, r in d.iterrows():
            x = xs[int(r["year"])]
            ax.add_patch(Rectangle((x - 0.3, r["supplement_low"]), 0.6, r["supplement_high"] - r["supplement_low"], facecolor=col, alpha=0.15, edgecolor=col, linewidth=0.6, linestyle=":", zorder=2, gid=f"supplement-{sc}-{int(r['year'])}"))
            ax.add_patch(Rectangle((x - 0.1, r["low"]), 0.2, r["high"] - r["low"], facecolor=col, alpha=0.6, edgecolor=col, linewidth=0.6, zorder=3, gid=f"band-{sc}-{int(r['year'])}"))
            ax.plot([x], [r["central"]], marker="o", ms=3.2, mfc=col, mec="k", mew=0.5, ls="none", zorder=5, gid=f"central-{sc}-{int(r['year'])}")
        ax.set_xticks(list(xs.values()), [str(y) for y in xs])
        ax.set_xlim(-0.6, 2.6)
        ax.set_ylim(0, float(s["supplement_high"].max()) * 1.05)
        ax.set_title(sc, fontsize=FONT_PT, loc="left", color=col, fontweight="bold")
    axes[0].set_ylabel("Curtailed energy (TWh)")
    fig.legend(handles=[Patch(facecolor="0.5", alpha=0.15, edgecolor="0.4", linestyle=":", label="nominal 80 % split-conformal supplement"), Patch(facecolor="0.4", alpha=0.6, label=BAND_LABEL),
                        Line2D([], [], marker="o", color="none", mfc="0.4", mec="k", ms=3.2, label="central value")], loc="lower center", frameon=False, ncol=3, handlelength=1.6, bbox_to_anchor=(0.5, 0.0))
    fig.tight_layout(rect=(0, 0.1, 1, 1))
    return fig, s, caption_s1(s)


GROUP_STYLE = {SCHEME_GROUPS[0]: ("o", OKABE_ITO_EXTRA["orange"], "none"), SCHEME_GROUPS[1]: ("s", OKABE_ITO_EXTRA["sky"], "full"), SCHEME_GROUPS[2]: ("^", OKABE_ITO_EXTRA["purple"], "full")}


def figure_s2(path: Path | None = None):
    bt = backtest_frame(path)
    fig, axes = _fig(FIGURE_WIDTH_MM["S2"], 3.4, ncols=2)
    for ax, tech in zip(axes, ("wind", "solar"), strict=True):
        d = bt[bt["tech"] == tech]
        periods = period_order(d)
        xs = {p: i for i, p in enumerate(periods)}
        obs = d.drop_duplicates("period").set_index(d.drop_duplicates("period")["period"].astype(str))["obs_twh"]
        ax.bar([xs[p] for p in periods], [obs[p] for p in periods], 0.55, color="0.82", edgecolor="0.4", linewidth=0.5, zorder=1, label="observed", gid=f"observed-{tech}")
        for g, (mk, col, fill) in GROUP_STYLE.items():
            dg = d[d["group"] == g]
            for j, (p, grp) in enumerate(dg.groupby(dg["period"].astype(str), sort=False)):
                n = len(grp)
                off = (np.arange(n) - (n - 1) / 2) * 0.1 + {SCHEME_GROUPS[0]: -0.2, SCHEME_GROUPS[1]: 0.0, SCHEME_GROUPS[2]: 0.2}[g]
                ax.plot(xs[p] + off, grp["hourly_twh"], ls="none", marker=mk, ms=4, mfc="white" if fill == "none" else col, mec=col, mew=1.0, zorder=4, label=g if j == 0 else None, gid=f"model-{tech}-{g}-{p}")
        ax.set_xticks(range(len(periods)), [p.replace(" (", "\n(") for p in periods])
        ax.tick_params(axis="x", labelsize=MIN_FONT_PT)
        ax.set_ylabel(f"Annual {tech} curtailment (TWh)")
        ax.set_ylim(0, float(max(d["obs_twh"].max(), d["hourly_twh"].max())) * 1.15)
        _label(ax, f"({'a' if tech == 'wind' else 'b'}) {tech.capitalize()}")
    h, lab = axes[0].get_legend_handles_labels()
    fig.legend(h, lab, loc="lower center", frameon=False, ncol=4, handlelength=1.4, bbox_to_anchor=(0.5, 0.0))
    fig.text(0.995, 0.995, "Analysis-derived (Task 11E2 backtest); not production pipeline output", ha="right", va="top", fontsize=MIN_FONT_PT, color="0.25", style="italic", gid="note-analysis-derived")
    fig.tight_layout(rect=(0, 0.1, 1, 0.96))
    return fig, bt, caption_s2()


# ================================================================================================================================================================================== output
def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


OUTPUT_FORMATS = ("png",)  # user decision (Task 17 housekeeping): PNG only; no PDF / SVG is generated. The 1000 dpi of the author guide applies to this bitmap. Adding "pdf" / "svg" back is this one line (the vector writers below are kept).
_VECTOR_METADATA = {"pdf": {"Creator": "curtailmit.figures", "Producer": "matplotlib", "CreationDate": None}, "svg": {"Date": None, "Creator": "curtailmit.figures"}}


def write_figure(fig, name: str, frame: pd.DataFrame, caption: str, out_dir: Path, dpi: int = PNG_DPI) -> dict[str, Path]:
    """The figure in OUTPUT_FORMATS (PNG at `dpi`) + data CSV + caption. Runs the forbidden-wording check on the figure text and the caption first. No creation dates are embedded, so equal inputs give equal files."""
    assert_clean(figure_texts(fig), f"figure {name}")
    assert_clean([caption], f"caption of {name}")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / name
    files = {fmt: stem.with_suffix(f".{fmt}") for fmt in OUTPUT_FORMATS}
    files.update({"csv": out_dir / f"{name}_data.csv", "caption": out_dir / f"{name}_caption.txt"})
    for fmt in OUTPUT_FORMATS:
        if fmt == "png":
            fig.savefig(files[fmt], dpi=dpi)
        else:
            fig.savefig(files[fmt], metadata=_VECTOR_METADATA[fmt])
    frame.to_csv(files["csv"], index=False, lineterminator="\n")
    files["caption"].write_text(caption + "\n", encoding="utf-8")
    plt.close(fig)
    return files


FILE_NAMES = {"F1": "F1_mitigation_deficit", "F2": "F2_support", "S1": "S1_band_vs_supplement", "S2": "S2_backtest"}


def build(only: Iterable[str] | None = None, final_results: Path | None = None, option_e: Path | None = None, backtest: Path | None = None, out_dir: Path | None = None, dpi: int = PNG_DPI) -> dict:
    """Draw and write the selected figures; returns the manifest (also written to figures_manifest.json, merged with an earlier one)."""
    wanted = list(only) if only else list(FIGURE_IDS)
    unknown = [w for w in wanted if w not in FIGURE_IDS]
    if unknown:
        raise FigureInputError(f"unknown figure ids {unknown}; choose from {list(FIGURE_IDS)}")
    out_dir = Path(out_dir) if out_dir is not None else default_out_dir()
    inputs: dict[str, Path] = {}
    fr = oe = None
    if any(w in ("F1", "S1") for w in wanted):
        fr_path = Path(final_results) if final_results is not None else _tables_dir() / f"{rw.FINAL_RESULTS_FILENAME}.parquet"
        fr = load_final_results(fr_path)
        inputs["final_results"] = fr_path
    if "F2" in wanted:
        oe_path = Path(option_e) if option_e is not None else _processed_dir() / rw.OPTION_E_FILENAME
        oe = load_option_e(oe_path)
        inputs["option_e"] = oe_path
    if "S2" in wanted:
        inputs["backtest_fixture"] = Path(backtest) if backtest is not None else BACKTEST_FIXTURE
    made = {}
    for fid in wanted:
        fig, frame, cap = {"F1": lambda: figure_f1(fr), "F2": lambda: figure_f2(oe), "S1": lambda: figure_s1(fr), "S2": lambda: figure_s2(inputs["backtest_fixture"])}[fid]()
        made[fid] = write_figure(fig, FILE_NAMES[fid], frame, cap, out_dir, dpi=dpi)
    manifest_path = out_dir / "figures_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = {}
    manifest.update({"matplotlib": matplotlib.__version__, "png_dpi": dpi, "confirmed_decarbon_standards": CONFIRMED_STANDARDS, "provisional_decarbon_standards": PROVISIONAL_STANDARDS, "figure_width_mm": FIGURE_WIDTH_MM})
    manifest.setdefault("inputs", {}).update({k: {"path": p.as_posix(), "sha256": sha256_of(p)} for k, p in inputs.items()})
    for stale in [k for k in manifest.get("figures", {}) if k not in FIGURE_IDS and not k.startswith("C")]:  # a figure id that was retired (F4 became F1, the old F1 was dropped)
        del manifest["figures"][stale]
        manifest.get("figure_width_mm", {}).pop(stale, None)
    manifest.setdefault("figures", {}).update({fid: {k: {"file": p.name, "sha256": sha256_of(p)} for k, p in files.items()} for fid, files in made.items()})
    manifest_path.write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Generate the article figures (Task 13B). Raster resolution 1000 dpi and column widths follow the DeCarbon author guide (see module docstring).")
    ap.add_argument("--only", default="", help=f"comma-separated figure ids from {','.join(FIGURE_IDS)} (default: all)")
    ap.add_argument("--out-dir", type=Path, default=None, help="default: DATABASE_ROOT/outputs/figures")
    ap.add_argument("--final-results", type=Path, default=None)
    ap.add_argument("--option-e", type=Path, default=None)
    ap.add_argument("--backtest-csv", type=Path, default=None, help="default: tests/fixtures/figures/backtest_annual.csv (analysis-derived fixture)")
    ap.add_argument("--dpi", type=int, default=PNG_DPI)
    args = ap.parse_args(argv)
    only = [s.strip() for s in args.only.split(",") if s.strip()]
    try:
        manifest = build(only, args.final_results, args.option_e, args.backtest_csv, args.out_dir, args.dpi)
    except (FigureInputError, FigureTextError) as exc:
        print(f"figures: refused: {exc}", file=sys.stderr)
        return 2
    print(f"figures written: {', '.join(sorted(manifest['figures']))} (matplotlib {manifest['matplotlib']}; provisional: {sorted(manifest['provisional_decarbon_standards'])})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
