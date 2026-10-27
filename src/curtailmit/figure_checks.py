"""Automated quality checks for the article figures (Task 13B-finalize). What can be tested programmatically is tested here; what needs eyes is not claimed.

(a) text overlap: bounding boxes of every text element (titles, axis labels, visible tick labels, annotations, legend entries, figure texts) from the drawn renderer, pairwise; also text leaving the figure, and
    legends sitting on top of data artists;
(b) plotted numbers against the source tables: the values carried by the artists (bar edges, marker positions, line data) are compared with the production tables read independently of the figure code
    (`final_results`, the Option E parquet, the backtest fixture), rtol 1e-12 (float rounding only);
(c) no placeholder text anywhere (figure text and captions);
(d) units on axis labels, OM and CM never combined, no hydrogen content (D30 stays a table), forbidden vocabulary except the one approved literal (D24).

    python -m curtailmit.figure_checks            builds every figure in memory from the production tables and prints the report (exit 1 on any finding)
"""

from __future__ import annotations

import itertools
import re
import sys

import numpy as np
import pandas as pd

from curtailmit import figures as fg

PLACEHOLDER = re.compile(r"Figure X|\bTODO\b|\bTBD\b|\bXXX\b|lorem ipsum", re.IGNORECASE)
UNIT = re.compile(r"TWh|MtCO|%")
SUM_WORDS = re.compile(r"OM\s*\+\s*CM|CM\s*\+\s*OM|sum of|summed|total deficit", re.IGNORECASE)
RTOL = 1e-12


# ================================================================================================================================================================================ (a) overlap
def _visible_ticklabels(axis) -> list:
    lo, hi = sorted(axis.get_view_interval())
    out = []
    for tick in axis.get_major_ticks():
        if lo - 1e-9 <= tick.get_loc() <= hi + 1e-9 and tick.label1.get_visible() and tick.label1.get_text().strip():
            out.append(tick.label1)
    return out


def text_elements(fig) -> list[tuple[str, object]]:
    """(name, Text) for everything that prints text on a drawn figure."""
    fig.canvas.draw()
    items: list[tuple[str, object]] = []
    for k, ax in enumerate(fig.axes):
        tag = f"ax{k}"
        for t in (ax.title, getattr(ax, "_left_title", None), getattr(ax, "_right_title", None), ax.xaxis.label, ax.yaxis.label):
            if t is not None and t.get_text().strip():
                items.append((f"{tag} label/title", t))
        items += [(f"{tag} text", t) for t in ax.texts if t.get_text().strip() and t.get_visible()]
        items += [(f"{tag} xtick", t) for t in _visible_ticklabels(ax.xaxis)] + [(f"{tag} ytick", t) for t in _visible_ticklabels(ax.yaxis)]
        if ax.get_legend() is not None:
            items += [(f"{tag} legend", t) for t in ax.get_legend().get_texts()]
    items += [("figure text", t) for t in fig.texts if t.get_text().strip()]
    for lg in fig.legends:
        items += [("figure legend", t) for t in lg.get_texts()]
    return items


def _extent(t, renderer):
    return t.get_window_extent(renderer)


def text_overlaps(fig, tol_pt: float = 0.3) -> list[str]:
    """Pairs of text elements whose boxes intersect by more than tol_pt in both directions, texts that leave the figure, and legends drawn over data artists."""
    items = text_elements(fig)
    renderer = fig.canvas.get_renderer()
    px = tol_pt * fig.dpi / 72.0
    boxes = [(n, t, _extent(t, renderer)) for n, t in items]
    problems = []
    for (n1, t1, b1), (n2, t2, b2) in itertools.combinations(boxes, 2):
        w = min(b1.x1, b2.x1) - max(b1.x0, b2.x0)
        h = min(b1.y1, b2.y1) - max(b1.y0, b2.y0)
        if w > px and h > px:
            problems.append(f"overlap: [{n1}] {t1.get_text()!r} x [{n2}] {t2.get_text()!r}")
    fb = fig.bbox
    for n, t, b in boxes:
        if b.x0 < fb.x0 - px or b.y0 < fb.y0 - px or b.x1 > fb.x1 + px or b.y1 > fb.y1 + px:
            problems.append(f"outside the figure: [{n}] {t.get_text()!r}")
    for k, ax in enumerate(fig.axes):
        lg = ax.get_legend()
        if lg is None:
            continue
        lb = lg.get_window_extent(renderer)
        for a in [*ax.patches, *ax.lines]:
            if (a.get_gid() or "").startswith("zone-") or not a.get_visible():
                continue
            if not a.get_gid() and a.get_label().startswith("_") and a in ax.lines and len(a.get_xdata()) > 2:
                continue
            ab = a.get_window_extent(renderer)
            if min(lb.x1, ab.x1) - max(lb.x0, ab.x0) > px and min(lb.y1, ab.y1) - max(lb.y0, ab.y0) > px:
                problems.append(f"legend over data: ax{k} legend x artist {a.get_gid() or type(a).__name__}")
    return problems


# =========================================================================================================================================================== (b) numbers against the tables
def _close(a, b) -> bool:
    return bool(np.isclose(float(a), float(b), rtol=RTOL, atol=0.0))


def _row(fr: pd.DataFrame, quantity: str, sc: str, yr: int) -> pd.Series:
    return fr[(fr["quantity"] == quantity) & (fr["component"] == "total") & (fr["scenario"] == sc) & (fr["year"] == yr)].iloc[0]


def _one(ax, gid: str):
    hits = [a for a in [*ax.patches, *ax.lines] if a.get_gid() == gid]
    if len(hits) != 1:
        raise LookupError(f"{gid}: {len(hits)} artists")
    return hits[0]


def _check_series(ax, fr: pd.DataFrame, quantity: str, scale: float, out: list, count: list) -> None:
    for sc in fg.SCENARIOS:
        for yr in fg.YEARS:
            r = _row(fr, quantity, sc, yr)
            kind = "conditional" if r["year"] == 2050 else "band"
            box = _one(ax, f"{kind}-{sc}-{yr}")
            mark = _one(ax, f"central-{sc}-{yr}")
            for what, got, want in (("low", box.get_y(), r["conditional_range_low"] / scale), ("high", box.get_y() + box.get_height(), r["conditional_range_high"] / scale),
                                    ("central", mark.get_ydata()[0], r["central_value"] / scale)):
                count.append(1)
                if not _close(got, want):
                    out.append(f"{quantity} {sc} {yr} {what}: plotted {float(got)!r} != table {float(want)!r}")


def verify_f1(fig, fr) -> tuple[list, int]:
    out, n = [], []
    _check_series(fig.axes[0], fr, "curtailed_energy", 1.0, out, n)
    return out, len(n)


def verify_f4(fig, fr) -> tuple[list, int]:
    out, n = [], []
    for ax, q in zip(fig.axes, ("mitigation_deficit_marginal_om", "mitigation_deficit_marginal_cm", "mitigation_deficit_avg"), strict=True):
        _check_series(ax, fr, q, 1e6, out, n)
    return out, len(n)


def verify_s1(fig, fr) -> tuple[list, int]:
    out, n = [], 0
    for ax, sc in zip(fig.axes, fg.SCENARIOS, strict=True):
        for yr in (2025, 2030, 2040):
            r = _row(fr, "curtailed_energy", sc, yr)
            sup, band, mark = _one(ax, f"supplement-{sc}-{yr}"), _one(ax, f"band-{sc}-{yr}"), _one(ax, f"central-{sc}-{yr}")
            for what, got, want in (("supplement low", sup.get_y(), r["supplement_low"]), ("supplement high", sup.get_y() + sup.get_height(), r["supplement_high"]),
                                    ("band low", band.get_y(), r["conditional_range_low"]), ("band high", band.get_y() + band.get_height(), r["conditional_range_high"]), ("central", mark.get_ydata()[0], r["central_value"])):
                n += 1
                if not _close(got, want):
                    out.append(f"S1 {sc} {yr} {what}: plotted {float(got)!r} != table {float(want)!r}")
    return out, n


def verify_f2(fig, oe) -> tuple[list, int]:
    a, b, c = fig.axes
    out, n = [], 0
    for sc in fg.SCENARIOS:
        t = oe[oe["scenario"] == sc].set_index("year")
        for yr in fg.YEARS:
            n += 1
            got, want = _one(a, f"hours-{sc}-{yr}").get_height(), 100 * (1 - t.loc[yr, "H_out_wind"])
            if not _close(got, want):
                out.append(f"F2(a) {sc} {yr}: plotted {got!r} != table {want!r}")
        for tech, col in (("wind", "E_out_wind"), ("solar", "E_out_solar")):
            y = _one(b, f"energy-{tech}-{sc}").get_ydata()
            for k, yr in enumerate(fg.YEARS):
                n += 1
                if not _close(y[k], 100 * (1 - t.loc[yr, col])):
                    out.append(f"F2(b) {tech} {sc} {yr}: plotted {float(y[k])!r} != table {100 * (1 - t.loc[yr, col])!r}")
        for yr in (2040, 2050):
            ins, outs = _one(c, f"in-{sc}-{yr}"), _one(c, f"out-{sc}-{yr}")
            for what, got, want in (("in-support", ins.get_height(), t.loc[yr, "curt_in_support_total_twh"]), ("beyond-support", outs.get_height(), t.loc[yr, "curt_out_support_total_twh"]),
                                    ("beyond-support base", outs.get_y(), t.loc[yr, "curt_in_support_total_twh"])):
                n += 1
                if not _close(got, want):
                    out.append(f"F2(c) {sc} {yr} {what}: plotted {got!r} != table {want!r}")
    return out, n


def verify_s2(fig, bt: pd.DataFrame) -> tuple[list, int]:
    out, n = [], 0
    for ax, tech in zip(fig.axes, ("wind", "solar"), strict=True):
        d = bt[bt["tech"] == tech]
        periods = fg.period_order(d)
        obs = d.drop_duplicates("period").set_index(d.drop_duplicates("period")["period"].astype(str))["obs_twh"]
        heights = [r.get_height() for r in _one_container(ax, f"observed-{tech}")]
        for p, h in zip(periods, heights, strict=True):
            n += 1
            if not _close(h, obs[p]):
                out.append(f"S2 {tech} observed {p}: plotted {h!r} != fixture {obs[p]!r}")
        plotted = sorted(float(y) for ln in ax.lines if (ln.get_gid() or "").startswith("model-") for y in ln.get_ydata())
        want = sorted(float(v) for v in d["hourly_twh"])
        n += len(want)
        if len(plotted) != len(want) or not np.allclose(plotted, want, rtol=RTOL, atol=0):
            out.append(f"S2 {tech}: plotted model values differ from the fixture")
    return out, n


def _one_container(ax, gid: str):
    return [p for p in ax.patches if p.get_gid() == gid]


# ============================================================================================================================================================ (c), (d) text and units
def check_texts(fig, caption: str, fid: str) -> list[str]:
    out = []
    texts = fg.figure_texts(fig)
    for s in [*texts, caption]:
        if PLACEHOLDER.search(s):
            out.append(f"placeholder text: {s[:60]!r}")
        if fg.check_text(s):
            out.append(f"forbidden wording outside the approved literal: {s[:60]!r} {fg.check_text(s)}")
        if SUM_WORDS.search(s):
            out.append(f"OM and CM must never be combined (D28): {s[:60]!r}")
        if re.search(r"hydrogen|\bH2\b|\bSEC\b", s):
            out.append(f"hydrogen content belongs in table T2 (D30), not in a figure: {s[:60]!r}")
    for k, ax in enumerate(fig.axes):
        lab = ax.get_ylabel()
        shared = [o for o in fig.axes if o is not ax and ax.get_shared_y_axes().joined(ax, o) and UNIT.search(o.get_ylabel())]
        if not (UNIT.search(lab) or shared):
            out.append(f"ax{k}: y label without a unit: {lab!r}")
    if fid == "F4":
        titles = [ax.get_title(loc="left") for ax in fig.axes]
        if len(fig.axes) != 3 or any(("OM" in t and "CM" in t) for t in titles):
            out.append("F4: OM and CM must be in separate panels")
    return out


# ================================================================================================================================================================================== driver
def run(final_results=None, option_e=None, backtest=None) -> dict[str, dict]:
    """Builds every figure in memory from the given (or the production) tables and returns {figure id: {overlaps, mismatches, n_numbers, text_problems}}."""
    import matplotlib.pyplot as plt

    fr = fg.load_final_results(final_results)
    oe = fg.load_option_e(option_e)
    bt = fg.backtest_frame(backtest)
    builds = {"F1": lambda: fg.figure_f1(fr), "F2": lambda: fg.figure_f2(oe), "F4": lambda: fg.figure_f4(fr), "S1": lambda: fg.figure_s1(fr), "S2": lambda: fg.figure_s2(backtest)}
    verify = {"F1": lambda f: verify_f1(f, fr), "F2": lambda f: verify_f2(f, oe), "F4": lambda f: verify_f4(f, fr), "S1": lambda f: verify_s1(f, fr), "S2": lambda f: verify_s2(f, bt)}
    report = {}
    for fid, build in builds.items():
        fig, _frame, cap = build()
        mism, n = verify[fid](fig)
        report[fid] = {"overlaps": text_overlaps(fig), "mismatches": mism, "n_numbers": n, "text_problems": check_texts(fig, cap, fid), "width_mm": round(fig.get_size_inches()[0] * 25.4, 1)}
        plt.close(fig)
    return report


def main() -> int:
    report = run()
    bad = 0
    for fid, r in report.items():
        findings = len(r["overlaps"]) + len(r["mismatches"]) + len(r["text_problems"])
        bad += findings
        print(f"{fid} ({r['width_mm']} mm): numbers checked {r['n_numbers']}, mismatches {len(r['mismatches'])}; text overlaps {len(r['overlaps'])}; text/unit/language problems {len(r['text_problems'])} -> {'PASS' if not findings else 'FAIL'}")
        for line in [*r["overlaps"], *r["mismatches"], *r["text_problems"]]:
            print("   -", line)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
