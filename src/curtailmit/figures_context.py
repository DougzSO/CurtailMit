"""Context figures (Task 17, docs/task17_design.md and its decisions update): C1 (observed curtailment by state, 2025), C1S (small multiples 2022-2026, supplement) and C2 (dose-response curve with the
observed-support boundary). They are CONTEXT figures: they show where curtailment is today and why 2040 / 2050 leave the calibration support, not a projection and not a result. Result figures are F1-F4, S1, S2
(`curtailmit.figures`); the prefix C keeps the reviewed numbering untouched. Map 2 (projected regional risk, decision D37) is NOT implemented: it needs a spatial-allocation rule that has not been decided.

C1 / C1S: colour = share of the NATIONAL curtailment of that technology and year (observed ONS data, attributed to the plant's state: `curtailmit.context_data`); two technologies, separate sequential
scales (`cividis`, colour-vision-deficiency safe and perceptually uniform; the qualitative Okabe-Ito palette is not used for a continuous scale); states without recorded curtailment are hatched grey and say so;
the top states are labelled with TWh through leader lines in a column outside the map (labels never sit on the geometry, so small states cannot collide). Geometry: GADM 4.1 level 1, local-only (D36),
read by `curtailmit.spatial` (no new dependency), simplified at 0.02 degrees.

C2: observed hourly bins (`hourly_model.MonthBins.bins()` on the production hourly panel; filled with >= 15 observed hours, open below), the fitted curve through the supported range, the support boundary `r_cap`
(vertical line, region beyond it shaded), and beyond the boundary the central curve and the L = 1 curve (the upper scenario of the 2050 range) dashed, so that their divergence is visible. The shares beyond the
boundary come straight from the Option E table (`H_out_*`, `E_out_*`) and are generated text. Technology colours are Okabe-Ito entries not used for the scenarios of F1-F4 (colour never means two things).

Output: PNG (1000 dpi, the format policy of `curtailmit.figures`) + data CSV + caption in DATABASE_ROOT/outputs/figures/, entries in the same figures_manifest.json. Run:

    python -m curtailmit.figures_context [--only C1,C1S,C2] [--out-dir DIR] [--dpi N]
"""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Iterable
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib import colormaps
from matplotlib.cm import ScalarMappable
from matplotlib.colors import Normalize
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, PathPatch
from matplotlib.path import Path as MPath

from curtailmit import figures as fg
from curtailmit import hourly_model as hm
from curtailmit import spatial as sp

CONTEXT_IDS = ("C1", "C1S", "C2")
FILE_NAMES = {"C1": "C1_observed_curtailment_map_2025", "C1S": "C1S_observed_curtailment_by_year", "C2": "C2_dose_response"}
CONTEXT_WIDTH_MM = {"C1": fg.DOUBLE_COLUMN_MM, "C1S": fg.DOUBLE_COLUMN_MM, "C2": fg.DOUBLE_COLUMN_MM}  # a layout judgment, re-renderable
C1_YEAR = 2025
TOP_N = 5
CMAP_NAME = "cividis"  # sequential scale for the choropleth (Q9); Okabe-Ito stays for categorical series
NO_DATA_FACE = "0.93"
NO_DATA_EDGE = "0.62"
TECH_COLOURS = {"wind": "#CC79A7", "solar": "#56B4E9"}  # Okabe-Ito entries not used for the scenarios TB / TA / TG of F1-F4
TECH_TITLES = {"wind": "Wind", "solar": "Solar"}
NORTHEAST = ("AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE")
L1_COLOUR = "0.15"
GRID_R = np.linspace(0.0, hm.XMAX - 2.0, 400)


class ContextFigureError(ValueError):
    """An input of a context figure is unusable."""


# ============================================================================================================================================================================== colour scale
def colour_scale(shares: Iterable[float], step: float = 5.0) -> Normalize:
    """Linear 0 .. vmax with vmax the largest share rounded UP to a multiple of `step` (percent): one scale per technology panel (or per technology row in C1S)."""
    top = float(np.nanmax(np.asarray(list(shares), dtype=float)))
    return Normalize(vmin=0.0, vmax=max(step, math.ceil(top / step) * step))


def state_colour(value: float | None, norm: Normalize):
    return colormaps[CMAP_NAME](norm(value)) if value is not None and not (isinstance(value, float) and math.isnan(value)) else None


# =================================================================================================================================================================================== map core
def _centroid(rings) -> tuple[float, float]:
    """Area centroid of the largest ring (representative point for the leader line)."""
    r = max(rings, key=lambda q: abs(sp.signed_area(q)))
    x, y = r[:, 0], r[:, 1]
    cross = x[:-1] * y[1:] - x[1:] * y[:-1]
    a = cross.sum() / 2.0
    if a == 0:
        return float(x.mean()), float(y.mean())
    return float(((x[:-1] + x[1:]) * cross).sum() / (6 * a)), float(((y[:-1] + y[1:]) * cross).sum() / (6 * a))


def map_extent(states: dict[str, dict]) -> tuple[float, float, float, float]:
    boxes = np.array([sp.shape_bounds(s["rings"]) for s in states.values()])
    return float(boxes[:, 0].min()), float(boxes[:, 1].min()), float(boxes[:, 2].max()), float(boxes[:, 3].max())


def mainland_x1(states: dict[str, dict]) -> float:
    """Eastern edge of the continental outline: the largest ring of each state (the oceanic islands lie further east and are drawn, but do not set the label column)."""
    return max(float(max(states[uf]["rings"], key=lambda q: abs(sp.signed_area(q)))[:, 0].max()) for uf in states)


def draw_map(ax, states: dict[str, dict], shares: dict[str, float], norm: Normalize, label_room_deg: float = 0.0) -> None:
    """One PathPatch per state (`gid = state-<UF>`): sequential colour for a recorded share, hatched grey for none. Aspect 1 / cos(mean latitude); axes off."""
    cmap = colormaps[CMAP_NAME]
    for uf, st in states.items():
        verts, codes = sp.path_arrays(st["rings"])
        v = shares.get(uf)
        if v is None:
            ax.add_patch(PathPatch(MPath(verts, codes), facecolor=NO_DATA_FACE, edgecolor=NO_DATA_EDGE, hatch="//////", linewidth=0.3, gid=f"state-{uf}"))
        else:
            ax.add_patch(PathPatch(MPath(verts, codes), facecolor=cmap(norm(v)), edgecolor="0.25", linewidth=0.3, gid=f"state-{uf}"))
    x0, y0, x1, y1 = map_extent(states)
    ax.set_xlim(x0 - 1.0, (mainland_x1(states) + 3.0 + label_room_deg) if label_room_deg else x1 + 1.0)
    ax.set_ylim(y0 - 1.0, y1 + 1.0)
    ax.set_aspect(1.0 / math.cos(math.radians((y0 + y1) / 2.0)))
    ax.axis("off")


def _spread(desired: list[float], gap: float, lo: float, hi: float) -> list[float]:
    """Label y positions: as close as possible to the wanted ones, never closer than `gap`, inside [lo, hi]."""
    order = sorted(range(len(desired)), key=lambda i: -desired[i])
    pos = {}
    prev = None
    for i in order:
        y = min(desired[i], hi) if prev is None else min(desired[i], prev - gap)
        pos[i] = y
        prev = y
    low = min(pos.values())
    if low < lo:
        shift = lo - low
        pos = {i: y + shift for i, y in pos.items()}
    return [pos[i] for i in range(len(desired))]


def label_text(uf: str, twh: float, share: float) -> str:
    return f"{uf}  {twh:.1f} TWh ({share:.0f} %)"


def draw_leader_labels(ax, states: dict[str, dict], rows: pd.DataFrame, tech: str, gap_deg: float = 3.6) -> None:
    """The top states (largest share) labelled with their TWh in a column east of the map, joined to the state by a thin leader line."""
    _x0, y0, _x1, y1 = map_extent(states)
    top = rows.sort_values("share_of_national_pct", ascending=False).head(TOP_N)
    reps = [_centroid(states[r.id_estado]["rings"]) for r in top.itertuples()]
    ys = _spread([p[1] for p in reps], gap_deg, y0 + 1.0, y1 - 1.0)
    for r, rep, y in zip(top.itertuples(), reps, ys, strict=True):
        ax.annotate(label_text(r.id_estado, r.curtailed_energy_twh, r.share_of_national_pct), xy=rep, xytext=(mainland_x1(states) + 3.0, y), textcoords="data", ha="left", va="center", fontsize=6.3, gid=f"label-{tech}-{r.id_estado}",
                    arrowprops={"arrowstyle": "-", "lw": 0.5, "color": "0.3", "shrinkA": 0, "shrinkB": 0, "connectionstyle": "arc3"}, annotation_clip=False)


def _ctx_fig(width_mm: float, height_in: float, **kw):
    fg.apply_style()
    return plt.subplots(figsize=(width_mm * fg.MM, height_in), layout="constrained", **kw)


def _no_data_handle() -> Patch:
    return Patch(facecolor=NO_DATA_FACE, edgecolor=NO_DATA_EDGE, hatch="//////", label="no curtailment recorded")


def _year_slice(table: pd.DataFrame, tech: str, year: int) -> pd.DataFrame:
    d = table[(table["technology"] == tech) & (table["year"] == year)]
    if d.empty:
        raise ContextFigureError(f"no {tech} rows for {year} in the state-year table")
    return d


def _partial_note(d: pd.DataFrame) -> str:
    m = int(d["months_covered"].iloc[0])
    return "" if m >= 12 else f" ({m} of 12 months)"


# ====================================================================================================================================================================================== C1
def northeast_share(table: pd.DataFrame, tech: str, year: int) -> float:
    d = _year_slice(table, tech, year)
    return float(d[d["id_estado"].isin(NORTHEAST)]["share_of_national_pct"].sum())


def caption_c1(table: pd.DataFrame, states: dict[str, dict]) -> str:
    parts = []
    for tech in ("wind", "solar"):
        d = _year_slice(table, tech, C1_YEAR).sort_values("share_of_national_pct", ascending=False)
        lead = d.iloc[0]
        parts.append(f"{tech}: {d['national_total_mwh'].iloc[0] / 1e6:.1f} TWh nationally, {lead['share_of_national_pct']:.0f} % of it in {states[lead['id_estado']]['name']}, "
                     f"{northeast_share(table, tech, C1_YEAR):.0f} % in the nine Northeast states")
    return (f"{fg.DRAFT} Figure C1 (context). Observed curtailment in {C1_YEAR} by the state of the plant, for wind (a) and solar (b). Colour is the state's share of the national curtailment of that technology "
            f"(separate sequential scales); the largest states are labelled with their curtailed energy (TWh); hatched states recorded no curtailment. Source: ONS plant-level curtailment data, "
            f"attributed to states by plant; state boundaries GADM 4.1. In {C1_YEAR}: " + "; ".join(parts) + ". This is observed data, not a projection.")


def figure_c1(table: pd.DataFrame, states: dict[str, dict]):
    fig, axes = _ctx_fig(CONTEXT_WIDTH_MM["C1"], 3.4, ncols=2)
    rows_out = []
    for ax, tech, tag in zip(axes, ("wind", "solar"), ("(a)", "(b)"), strict=True):
        d = _year_slice(table, tech, C1_YEAR)
        shares = dict(zip(d["id_estado"], d["share_of_national_pct"], strict=True))
        norm = colour_scale(d["share_of_national_pct"])
        draw_map(ax, states, shares, norm, label_room_deg=20.0)
        draw_leader_labels(ax, states, d, tech)
        ax.set_title(f"{tag} {TECH_TITLES[tech]}, {C1_YEAR}{_partial_note(d)}: national total {d['national_total_mwh'].iloc[0] / 1e6:.1f} TWh", fontsize=fg.FONT_PT, loc="left", fontweight="bold")
        cb = fig.colorbar(ScalarMappable(norm=norm, cmap=colormaps[CMAP_NAME]), ax=ax, orientation="horizontal", fraction=0.045, pad=0.02, aspect=30)
        cb.set_label(f"Share of national {tech} curtailment, {C1_YEAR} (%)", fontsize=fg.FONT_PT)
        cb.ax.tick_params(labelsize=fg.MIN_FONT_PT, width=0.5)
        ax.legend(handles=[_no_data_handle()], loc="lower right", frameon=False, fontsize=fg.MIN_FONT_PT, handlelength=1.4, borderaxespad=0.0)
        rows_out.append(d.assign(colour_vmax_pct=norm.vmax))
    frame = pd.concat(rows_out, ignore_index=True)
    return fig, frame, caption_c1(table, states)


# ===================================================================================================================================================================================== C1S
def caption_c1s(table: pd.DataFrame) -> str:
    return (f"{fg.DRAFT} Figure C1S (context, supplement). Observed curtailment by state, share of the national curtailment of each technology, 2022-2026 (wind) and 2024-2026 (solar; the solar series starts in "
            f"April 2024). One sequential colour scale per technology row, common to its years; colour is a SHARE, so the national total of each map is printed above it (the totals differ widely between years). Hatched states recorded no curtailment. Partial years are marked with their months of data. Source: ONS plant-level "
            f"curtailment data attributed to states by plant; state boundaries GADM 4.1. Observed data, not a projection.")


def figure_c1s(table: pd.DataFrame, states: dict[str, dict]):
    years = {"wind": sorted(table[table["technology"] == "wind"]["year"].unique()), "solar": sorted(table[table["technology"] == "solar"]["year"].unique())}
    ncol = max(len(v) for v in years.values())
    fig, axes = _ctx_fig(CONTEXT_WIDTH_MM["C1S"], 3.7, nrows=2, ncols=ncol)
    rows_out = []
    for r, tech in enumerate(("wind", "solar")):
        norm = colour_scale(table[table["technology"] == tech]["share_of_national_pct"])
        for c in range(ncol):
            ax = axes[r][c]
            if c >= len(years[tech]):
                ax.axis("off")
                continue
            y = int(years[tech][c])
            d = _year_slice(table, tech, y)
            draw_map(ax, states, dict(zip(d["id_estado"], d["share_of_national_pct"], strict=True)), norm)
            ax.set_title(f"{y}{_partial_note(d)}" + chr(10) + f"{d['national_total_mwh'].iloc[0] / 1e6:.1f} TWh nationally", fontsize=fg.FONT_PT, loc="left")
            rows_out.append(d.assign(colour_vmax_pct=norm.vmax))
            if c == 0:
                ax.text(-0.02, 0.5, TECH_TITLES[tech], transform=ax.transAxes, rotation=90, ha="right", va="center", fontsize=fg.FONT_PT, fontweight="bold")
        cb = fig.colorbar(ScalarMappable(norm=norm, cmap=colormaps[CMAP_NAME]), ax=list(axes[r]), orientation="vertical", fraction=0.03, pad=0.01, aspect=18)
        cb.set_label("National share (%)", fontsize=fg.MIN_FONT_PT + 0.5)
        cb.ax.tick_params(labelsize=fg.MIN_FONT_PT, width=0.5)
    fig.legend(handles=[_no_data_handle()], loc="lower left", frameon=False, fontsize=fg.MIN_FONT_PT, handlelength=1.4)
    return fig, pd.concat(rows_out, ignore_index=True), caption_c1s(table)


# ====================================================================================================================================================================================== C2
def annotation_rows(oe: pd.DataFrame, tech: str, years: tuple[int, ...] = (2040, 2050)) -> list[tuple[str, int, float, float]]:
    """(scenario, year, % of projected hours beyond the boundary, % of projected curtailed energy beyond it) straight from the Option E table."""
    out = []
    for yr in years:
        for sc in fg.SCENARIOS:
            r = oe[(oe["scenario"] == sc) & (oe["year"] == yr)].iloc[0]
            out.append((sc, yr, 100.0 * float(r[f"H_out_{tech}"]), 100.0 * float(r[f"E_out_{tech}"])))
    return out


def annotation_text(oe: pd.DataFrame, tech: str) -> str:
    lines = ["beyond the boundary:", "          hours  energy"]
    lines += [f"{yr} {sc}  {h:4.0f} %  {e:4.0f} %" for sc, yr, h, e in annotation_rows(oe, tech)]
    return "\n".join(lines)


def curve_grid(curve: hm.HourlyCurve) -> tuple[np.ndarray, np.ndarray]:
    return GRID_R, 100.0 * np.asarray(curve.rate(GRID_R), dtype=float)


def caption_c2(oe: pd.DataFrame, curves: dict[str, tuple[hm.HourlyCurve, hm.HourlyCurve]]) -> str:
    cap = {t: curves[t][0].r_cap for t in curves}
    h50 = {t: [row[2] for row in annotation_rows(oe, t, (2050,))] for t in curves}
    e50 = {t: [row[3] for row in annotation_rows(oe, t, (2050,))] for t in curves}
    return (f"{fg.DRAFT} Figure C2 (context). The hourly dose-response relationship behind the projection: curtailment rate (share of the potential energy that is curtailed) against the system-wide variable-renewable "
            f"share of load r, for wind (a) and solar (b). Points are observed 2-percentage-point classes of r (filled: at least {hm.MIN_HOURS} observed hours; open: fewer), the solid line is the fitted curve through the "
            f"supported range, and the grey region beyond the support boundary (r = {cap['wind']:.0f} % for wind, {cap['solar']:.0f} % for solar) is extrapolation. There the fitted curve (dashed) and the L = 1 curve "
            f"(dash-dotted), the upper scenario of the 2050 range, diverge: the 2050 range is a conditional range (not a confidence interval) between them. In 2050 {min(h50['wind']):.0f}-{max(h50['wind']):.0f} % of the "
            f"projected hours ({min(e50['wind']):.0f}-{max(e50['wind']):.0f} % of the wind curtailment) lie beyond the boundary for wind, {min(h50['solar']):.0f}-{max(h50['solar']):.0f} % of the hours for solar "
            f"(Option E table; table in the panels).")


def figure_c2(bins: dict[str, pd.DataFrame], curves: dict[str, tuple[hm.HourlyCurve, hm.HourlyCurve]], oe: pd.DataFrame):
    fig, axes = _ctx_fig(CONTEXT_WIDTH_MM["C2"], 3.7, ncols=2)
    rows = []
    for ax, tech, tag in zip(axes, ("wind", "solar"), ("(a)", "(b)"), strict=True):
        col = TECH_COLOURS[tech]
        central, l1 = curves[tech]
        cap = central.r_cap
        xmax = float(GRID_R[-1])
        ax.axvspan(cap, xmax, facecolor="0.92", edgecolor="none", zorder=0, gid=f"beyond-{tech}")
        ax.axvline(cap, color="k", lw=0.9, zorder=2, gid=f"boundary-{tech}")
        b = bins[tech]
        full = b["hours"] >= hm.MIN_HOURS
        for sel, face, gid in ((full, col, "bins-supported"), (~full, "white", "bins-thin")):
            if sel.any():
                ax.plot(b.loc[sel, "x"], 100.0 * b.loc[sel, "rate"], ls="none", marker="o", ms=3.2, mfc=face, mec=col, mew=0.9, zorder=4, gid=f"{gid}-{tech}")
        r, y = curve_grid(central)
        inside, outside = r <= cap, r >= cap
        ax.plot(r[inside], y[inside], color=col, lw=1.5, zorder=3, gid=f"curve-central-supported-{tech}")
        ax.plot(r[outside], y[outside], color=col, lw=1.3, ls="--", zorder=3, gid=f"curve-central-beyond-{tech}")
        r1, y1 = curve_grid(l1)
        ax.plot(r1[outside], y1[outside], color=L1_COLOUR, lw=1.1, ls="-.", zorder=3, gid=f"curve-L1-beyond-{tech}")
        ax.text(cap, 108.0, f"support boundary\nr = {cap:.0f} %", ha="center", va="top", fontsize=fg.MIN_FONT_PT, zorder=5, gid=f"boundary-label-{tech}")
        ax.text(0.985, 0.03, annotation_text(oe, tech), transform=ax.transAxes, ha="right", va="bottom", fontsize=fg.MIN_FONT_PT, family="monospace", zorder=5, gid=f"annotation-{tech}",
                bbox={"facecolor": "white", "edgecolor": "0.7", "linewidth": 0.4, "pad": 2.5})
        ax.set(xlim=(0, xmax), ylim=(0, 110), xlabel="System-wide VRE share of load, r (%)", ylabel="Curtailment rate (% of potential energy)")
        ax.set_title(f"{tag} {TECH_TITLES[tech]} (fit window from {central.window_start[:4]}, {central.n_hours:,} h)", fontsize=fg.FONT_PT, loc="left", fontweight="bold")
        ax.legend(handles=[Line2D([], [], ls="none", marker="o", ms=3.2, mfc=col, mec=col, label=f"observed class, >= {hm.MIN_HOURS} h"), Line2D([], [], ls="none", marker="o", ms=3.2, mfc="white", mec=col, label=f"observed class, < {hm.MIN_HOURS} h"),
                           Line2D([], [], color=col, lw=1.5, label="fitted curve"), Line2D([], [], color=col, lw=1.3, ls="--", label="fitted curve, extrapolated"),
                           Line2D([], [], color=L1_COLOUR, lw=1.1, ls="-.", label="L = 1 curve, extrapolated")], loc="upper left", frameon=False, handlelength=2.2, fontsize=fg.MIN_FONT_PT, borderaxespad=0.2)
        rows.append(pd.DataFrame({"kind": "bin", "technology": tech, "x": b["x"].to_numpy(), "y": 100.0 * b["rate"].to_numpy(), "hours": b["hours"].to_numpy()}))
        rows.append(pd.DataFrame({"kind": "curve_central", "technology": tech, "x": r, "y": y}))
        rows.append(pd.DataFrame({"kind": "curve_L1", "technology": tech, "x": r1, "y": y1}))
        rows.append(pd.DataFrame([{"kind": "beyond_boundary", "technology": tech, "x": cap, "scenario": sc, "year": yr, "pct_hours": h, "pct_energy": e} for sc, yr, h, e in annotation_rows(oe, tech)]))
    return fig, pd.concat(rows, ignore_index=True), caption_c2(oe, curves)


# ============================================================================================================================================================================= data loading
def load_c2_inputs(processed: Path | None = None, option_e: Path | None = None):
    """Production calibration outputs: curves (central and L = 1), the observed bins of the hourly panel (the calibration's own binning), and the Option E table."""
    from curtailmit import paths

    processed = Path(processed) if processed is not None else paths.planned_layout()["processed"]
    cal = hm.load_hourly_calibration(processed)
    panel = hm.load_sin_panel(refresh=False)
    bins = {}
    for tech in ("wind", "solar"):
        d, real, curt = hm.technology_frame(panel, tech)
        bins[tech] = hm.MonthBins(d, real, curt).bins()
    curves = {"wind": (cal.wind, cal.wind_L1), "solar": (cal.solar, cal.solar_L1)}
    return bins, curves, fg.load_option_e(option_e)


def build(only: Iterable[str] | None = None, out_dir: Path | None = None, dpi: int = fg.PNG_DPI, force_table: bool = False) -> dict:
    """Draw and write the selected context figures; merges their entries (with the SHA-256 of every input, including the local-only boundary file) into figures_manifest.json."""
    import json

    from curtailmit import context_data as cd

    wanted = list(only) if only else list(CONTEXT_IDS)
    unknown = [w for w in wanted if w not in CONTEXT_IDS]
    if unknown:
        raise ContextFigureError(f"unknown figure ids {unknown}; choose from {list(CONTEXT_IDS)}")
    out_dir = Path(out_dir) if out_dir is not None else fg.default_out_dir()
    inputs: dict[str, Path] = {}
    made = {}
    if any(w in ("C1", "C1S") for w in wanted):
        shp = sp.default_shp()
        if not shp.is_file():
            raise ContextFigureError(f"{shp} not found: provision the boundary files (python -m curtailmit.spatial provision --source ...)")
        states = sp.read_states(shp)
        table = cd.build(force=force_table)
        from curtailmit import paths

        inputs.update({"boundary_shapefile": shp, "state_year_table": paths.planned_layout()["interim"] / cd.CACHE_NAME})
        for fid, build_fn in (("C1", lambda: figure_c1(table, states)), ("C1S", lambda: figure_c1s(table, states))):
            if fid in wanted:
                fig, frame, cap = build_fn()
                made[fid] = fg.write_figure(fig, FILE_NAMES[fid], frame, cap, out_dir, dpi=dpi)
    if "C2" in wanted:
        bins, curves, oe = load_c2_inputs()
        proc = fg._processed_dir()
        inputs.update({"option_e": proc / fg.rw.OPTION_E_FILENAME, "curve_wind": proc / "hourly_curve_wind.json", "curve_solar": proc / "hourly_curve_solar.json",
                       "curve_wind_L1": proc / "hourly_curve_wind_L1.json", "curve_solar_L1": proc / "hourly_curve_solar_L1.json"})
        fig, frame, cap = figure_c2(bins, curves, oe)
        made["C2"] = fg.write_figure(fig, FILE_NAMES["C2"], frame, cap, out_dir, dpi=dpi)
    manifest_path = out_dir / "figures_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = {}
    manifest.update({"matplotlib": matplotlib.__version__, "png_dpi": dpi, "confirmed_decarbon_standards": fg.CONFIRMED_STANDARDS, "provisional_decarbon_standards": fg.PROVISIONAL_STANDARDS})
    manifest.setdefault("figure_width_mm", {}).update({k: CONTEXT_WIDTH_MM[k] for k in made})
    manifest.setdefault("inputs", {}).update({k: {"path": p.as_posix(), "sha256": fg.sha256_of(p)} for k, p in inputs.items()})
    manifest.setdefault("figures", {}).update({fid: {k: {"file": p.name, "sha256": fg.sha256_of(p)} for k, p in files.items()} for fid, files in made.items()})
    manifest_path.write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    from curtailmit import context_data as cd

    ap = argparse.ArgumentParser(description="Generate the context figures C1, C1S, C2 (Task 17). Needs the local database and the provisioned GADM boundary files (decision D36).")
    ap.add_argument("--only", default="", help=f"comma-separated ids from {','.join(CONTEXT_IDS)} (default: all)")
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument("--dpi", type=int, default=fg.PNG_DPI)
    ap.add_argument("--force-table", action="store_true", help="rebuild the cached state-year table first")
    args = ap.parse_args(argv)
    only = [s.strip() for s in args.only.split(",") if s.strip()]
    try:
        manifest = build(only, args.out_dir, args.dpi, args.force_table)
    except (ContextFigureError, fg.FigureInputError, fg.FigureTextError, cd.ContextDataError, sp.SpatialError) as exc:
        print(f"context figures: refused: {exc}", file=sys.stderr)
        return 2
    print(f"context figures written: {', '.join(sorted(k for k in manifest['figures'] if k in CONTEXT_IDS))} (matplotlib {manifest['matplotlib']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
