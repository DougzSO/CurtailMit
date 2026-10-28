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
from matplotlib.lines import Line2D
from matplotlib.text import Text

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
        if not ax.axison:  # a map panel: its tick labels and axis labels are not drawn
            items = [(n, t) for n, t in items if not (n.startswith(tag) and "label/title" in n and t in (ax.xaxis.label, ax.yaxis.label))]
            continue
        items += [(f"{tag} xtick", t) for t in _visible_ticklabels(ax.xaxis)] + [(f"{tag} ytick", t) for t in _visible_ticklabels(ax.yaxis)]
        if ax.get_legend() is not None:
            items += [(f"{tag} legend", t) for t in ax.get_legend().get_texts()]
    items += [("figure text", t) for t in fig.texts if t.get_text().strip()]
    for lg in fig.legends:
        items += [("figure legend", t) for t in lg.get_texts()]
    return items


def _extent(t, renderer):
    return Text.get_window_extent(t, renderer)  # the text box only: an Annotation's own extent would include its leader line


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
            if (a.get_gid() or "").startswith(("zone-", "beyond-")) or not a.get_visible():
                continue
            if isinstance(a, Line2D) and len(a.get_xdata()) > 2:  # a curve or a cloud of markers: a bounding box would span the whole panel, so test its points
                xy = ax.transData.transform(np.column_stack([np.asarray(a.get_xdata(), float), np.asarray(a.get_ydata(), float)]))
                if np.any((xy[:, 0] > lb.x0) & (xy[:, 0] < lb.x1) & (xy[:, 1] > lb.y0) & (xy[:, 1] < lb.y1)):
                    problems.append(f"legend over data: ax{k} legend x artist {a.get_gid() or type(a).__name__}")
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
    for ax, q in zip(fig.axes[:3], ("mitigation_deficit_marginal_om", "mitigation_deficit_marginal_cm", "mitigation_deficit_avg"), strict=True):
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
        if not ax.axison:  # a map panel: no axis to label
            continue
        if ax.get_label() == "<colorbar>":  # a colour bar carries its unit on the label of its long axis
            if not (UNIT.search(ax.get_xlabel()) or UNIT.search(ax.get_ylabel())):
                out.append(f"ax{k}: colour bar label without a unit: {ax.get_xlabel() or ax.get_ylabel()!r}")
            continue
        lab = ax.get_ylabel()
        shared = [o for o in fig.axes if o is not ax and ax.get_shared_y_axes().joined(ax, o) and UNIT.search(o.get_ylabel())]
        if not (UNIT.search(lab) or shared):
            out.append(f"ax{k}: y label without a unit: {lab!r}")
    if fid == "F1":
        titles = [ax.get_title(loc="left") for ax in fig.axes]
        if sum(1 for ax in fig.axes if ax.axison) != 3 or any(("OM" in t and "CM" in t) for t in titles):
            out.append("F1: OM and CM must be in separate panels")
    return out


# ==================================================================================================================================================================== context figures (Task 17)
def _map_axes(fig) -> list:
    """The axes that hold state patches, in figure order."""
    return [ax for ax in fig.axes if any((a.get_gid() or "").startswith("state-") for a in ax.patches)]


def _verify_map(ax, table: pd.DataFrame, states: dict, tech: str, year: int, norm, label: bool) -> tuple[list, int]:
    """Every state patch against the table: its colour is the colour map applied to the share in the table (hatched grey when the state has no row), and the labels carry the table's TWh and share."""
    from matplotlib import colormaps
    from matplotlib.colors import to_rgba

    from curtailmit import figures_context as fc

    out, n = [], 0
    d = table[(table["technology"] == tech) & (table["year"] == year)]
    shares = dict(zip(d["id_estado"], d["share_of_national_pct"], strict=True))
    cmap = colormaps[fc.CMAP_NAME]
    for uf in states:
        patch = _one(ax, f"state-{uf}")
        n += 1
        if uf in shares:
            if not np.allclose(patch.get_facecolor(), cmap(norm(shares[uf])), rtol=0, atol=1e-12) or patch.get_hatch():
                out.append(f"{tech} {year} {uf}: colour does not match the table share {shares[uf]!r}")
        elif not np.allclose(patch.get_facecolor(), to_rgba(fc.NO_DATA_FACE), rtol=0, atol=1e-12) or not patch.get_hatch():
            out.append(f"{tech} {year} {uf}: a state without a table row must be hatched grey")
    if label:
        top = d.sort_values("share_of_national_pct", ascending=False).head(fc.TOP_N)
        labels = {(a.get_gid() or "").removeprefix(f"label-{tech}-"): a.get_text() for a in ax.texts if (a.get_gid() or "").startswith(f"label-{tech}-")}
        if set(labels) != set(top["id_estado"]):
            out.append(f"{tech}: labelled states {sorted(labels)} are not the {fc.TOP_N} largest {sorted(top['id_estado'])}")
        for r in top.itertuples():
            n += 2
            m = re.fullmatch(r"(\w+)\s+([\d.]+) TWh \((\d+) %\)", labels.get(r.id_estado, ""))
            if not m or m.group(1) != r.id_estado or float(m.group(2)) != round(r.curtailed_energy_twh, 1) or int(m.group(3)) != round(r.share_of_national_pct):
                out.append(f"{tech} label {r.id_estado}: {labels.get(r.id_estado)!r} does not match the table ({r.curtailed_energy_twh!r} TWh, {r.share_of_national_pct!r} %)")
    return out, n


def verify_c1(fig, table: pd.DataFrame, states: dict) -> tuple[list, int]:
    from curtailmit import figures_context as fc

    out, n = [], 0
    for ax, tech in zip(_map_axes(fig), ("wind", "solar"), strict=True):
        d = table[(table["technology"] == tech) & (table["year"] == fc.C1_YEAR)]
        p, k = _verify_map(ax, table, states, tech, fc.C1_YEAR, fc.colour_scale(d["share_of_national_pct"]), True)
        out += p
        n += k
    return out, n


def verify_c1s(fig, table: pd.DataFrame, states: dict) -> tuple[list, int]:
    from curtailmit import figures_context as fc

    out, n = [], 0
    layout = [(tech, int(y)) for tech in ("wind", "solar") for y in sorted(table[table["technology"] == tech]["year"].unique())]
    axes = _map_axes(fig)
    if len(axes) != len(layout):
        return [f"C1S has {len(axes)} maps, the table has {len(layout)} technology-years"], 0
    for ax, (tech, year) in zip(axes, layout, strict=True):
        p, k = _verify_map(ax, table, states, tech, year, fc.colour_scale(table[table["technology"] == tech]["share_of_national_pct"]), False)
        out += p
        n += k
    return out, n


def verify_c2(fig, bins: dict, curves: dict, oe: pd.DataFrame) -> tuple[list, int]:
    from curtailmit import figures_context as fc
    from curtailmit import hourly_model as hm

    out, n = [], 0
    for ax, tech in zip(fig.axes[:2], ("wind", "solar"), strict=True):
        central, l1 = curves[tech]
        b = bins[tech]
        sup, thin = _one(ax, f"bins-supported-{tech}"), None
        thin_hits = [a for a in ax.lines if a.get_gid() == f"bins-thin-{tech}"]
        thin = thin_hits[0] if thin_hits else None
        want_sup = b[b["hours"] >= hm.MIN_HOURS]
        want_thin = b[b["hours"] < hm.MIN_HOURS]
        for line, want, what in ((sup, want_sup, "supported"), (thin, want_thin, "thin")):
            got_x = np.sort(np.asarray(line.get_xdata(), float)) if line is not None else np.array([])
            got_y = np.sort(np.asarray(line.get_ydata(), float)) if line is not None else np.array([])
            n += 2 * len(want)
            if len(got_x) != len(want) or not (np.allclose(got_x, np.sort(want["x"].to_numpy()), rtol=RTOL, atol=0) and np.allclose(got_y, np.sort(100.0 * want["rate"].to_numpy()), rtol=RTOL, atol=0)):
                out.append(f"C2 {tech}: plotted {what} bins differ from MonthBins.bins()")
        for gid, curve, side in ((f"curve-central-supported-{tech}", central, "le"), (f"curve-central-beyond-{tech}", central, "ge"), (f"curve-L1-beyond-{tech}", l1, "ge")):
            ln = _one(ax, gid)
            x, y = np.asarray(ln.get_xdata(), float), np.asarray(ln.get_ydata(), float)
            n += len(x)
            if not np.allclose(y, 100.0 * np.asarray(curve.rate(x), float), rtol=RTOL, atol=0):
                out.append(f"C2 {tech}: {gid} differs from HourlyCurve.rate")
            if (side == "le" and x.max() > central.r_cap + 1e-9) or (side == "ge" and x.min() < central.r_cap - 1e-9):
                out.append(f"C2 {tech}: {gid} is drawn on the wrong side of the boundary")
        boundary = float(_one(ax, f"boundary-{tech}").get_xdata()[0])
        table_caps = oe[f"r_cap_{tech}"].astype(float)
        n += 1
        if not (_close(boundary, central.r_cap) and np.allclose(table_caps, boundary, rtol=1e-9, atol=0)):
            out.append(f"C2 {tech}: boundary {boundary!r} differs from r_cap {central.r_cap!r} / the Option E table")
        text = next((a.get_text() for a in ax.texts if a.get_gid() == f"annotation-{tech}"), "")
        found = {(m.group(2), int(m.group(1))): (int(m.group(3)), int(m.group(4))) for m in re.finditer(r"(\d{4}) (T[ABG])\s+(\d+) %\s+(\d+) %", text)}
        for sc, yr, h, e in fc.annotation_rows(oe, tech):
            n += 2
            r = oe[(oe["scenario"] == sc) & (oe["year"] == yr)].iloc[0]
            if found.get((sc, yr)) != (round(100 * float(r[f"H_out_{tech}"])), round(100 * float(r[f"E_out_{tech}"]))) and found.get((sc, yr)) != (int(f"{h:.0f}"), int(f"{e:.0f}")):
                out.append(f"C2 {tech} {sc} {yr}: annotation {found.get((sc, yr))} differs from the Option E table")
    return out, n


def run_context(table: pd.DataFrame, states: dict, bins: dict, curves: dict, oe: pd.DataFrame) -> dict[str, dict]:
    """Builds C1, C1S and C2 in memory from the given inputs and runs the same checks as for the result figures."""
    import matplotlib.pyplot as plt

    from curtailmit import figures_context as fc

    builds = {"C1": (lambda: fc.figure_c1(table, states), lambda f: verify_c1(f, table, states)), "C1S": (lambda: fc.figure_c1s(table, states), lambda f: verify_c1s(f, table, states)),
              "C2": (lambda: fc.figure_c2(bins, curves, oe), lambda f: verify_c2(f, bins, curves, oe))}
    report = {}
    for fid, (build, verify) in builds.items():
        fig, _frame, cap = build()
        mism, n = verify(fig)
        report[fid] = {"overlaps": text_overlaps(fig), "mismatches": mism, "n_numbers": n, "text_problems": check_texts(fig, cap, fid), "width_mm": round(fig.get_size_inches()[0] * 25.4, 1)}
        plt.close(fig)
    return report


def run_context_real() -> dict[str, dict]:
    from curtailmit import context_data as cd
    from curtailmit import figures_context as fc
    from curtailmit import spatial as sp

    bins, curves, oe = fc.load_c2_inputs()
    return run_context(cd.build(), sp.read_states(sp.default_shp()), bins, curves, oe)


# ================================================================================================================================================================================== driver
def run(final_results=None, option_e=None, backtest=None) -> dict[str, dict]:
    """Builds every figure in memory from the given (or the production) tables and returns {figure id: {overlaps, mismatches, n_numbers, text_problems}}."""
    import matplotlib.pyplot as plt

    fr = fg.load_final_results(final_results)
    oe = fg.load_option_e(option_e)
    bt = fg.backtest_frame(backtest)
    builds = {"F1": lambda: fg.figure_f1(fr), "F2": lambda: fg.figure_f2(oe), "S1": lambda: fg.figure_s1(fr), "S2": lambda: fg.figure_s2(backtest)}
    verify = {"F1": lambda f: verify_f1(f, fr), "F2": lambda f: verify_f2(f, oe), "S1": lambda f: verify_s1(f, fr), "S2": lambda f: verify_s2(f, bt)}
    report = {}
    for fid, build in builds.items():
        fig, _frame, cap = build()
        mism, n = verify[fid](fig)
        report[fid] = {"overlaps": text_overlaps(fig), "mismatches": mism, "n_numbers": n, "text_problems": check_texts(fig, cap, fid), "width_mm": round(fig.get_size_inches()[0] * 25.4, 1)}
        plt.close(fig)
    return report


def _print(report: dict) -> int:
    bad = 0
    for fid, r in report.items():
        findings = len(r["overlaps"]) + len(r["mismatches"]) + len(r["text_problems"])
        bad += findings
        print(f"{fid} ({r['width_mm']} mm): numbers checked {r['n_numbers']}, mismatches {len(r['mismatches'])}; text overlaps {len(r['overlaps'])}; text/unit/language problems {len(r['text_problems'])} -> {'PASS' if not findings else 'FAIL'}")
        for line in [*r["overlaps"], *r["mismatches"], *r["text_problems"]]:
            print("   -", line)
    return bad


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Automated quality checks of the article figures (result figures F1-S2 and context figures C1, C1S, C2).")
    ap.add_argument("--only", choices=("results", "context", "all"), default="all")
    args = ap.parse_args(argv)
    bad = 0
    if args.only in ("results", "all"):
        bad += _print(run())
    if args.only in ("context", "all"):
        bad += _print(run_context_real())
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
