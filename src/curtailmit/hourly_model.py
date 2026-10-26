"""Option E (D24): hourly dose-response model of the curtailment rate, production version (Task 11F-2).

The curtailment rate of a technology in an hour is a bounded logistic of r, the hourly SIN-wide POTENTIAL VRE share of load (%):

    r_h  = 100 x (wind_h + curt_wind_h + solar_h + curt_solar_h) / load_h
    rate = L / (1 + exp(-k (r - x0)))                       curtailed_h = rate(r_h) x (realized_h + curtailed_h)

fitted on 2-pp bins of r (potential-energy weighted, bins with >= 15 hours), projected by scaling the 2025 hourly profile with the PTE annual totals
(wind x W_t/W_2025, solar x S_t/S_2025, load x T_t/T_2025) and applying the curve to the scaled potential generation (D23: PTE generation read as gross).
Support: bins of r with >= MIN_HOURS observed hours (r_cap = the last such bin); beyond r_cap the curve is an extrapolation (E_out / H_out / D_pp measure how much).

This is a faithful migration of the validated prototypes analysis/task11e_common.py, task11e2_common.py and task11e3_error_growth.py (regression-tested against them).
The monthly national-P and regional formulations of Tasks 7-11D stay in calibration.py as labelled reference outputs.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

logger = logging.getLogger(__name__)

WIDTH = 2.0
MIN_HOURS = 15
XMAX = 102.0
SUBSYSTEMS = ("N", "NE", "S", "SE")
END_EXCLUSIVE = "2026-10-01"  # October 2026 is incomplete in the raw files
TECH_COLUMNS = {"wind": ("wind", "curt_wind"), "solar": ("solar_disp", "curt_solar")}  # (realized, curtailed) hourly MWh
TECH_START = {"wind": "2022-01-01", "solar": "2024-04-01"}  # the first complete solar month of the dispatched-generation series
CURVE_FILENAME = "hourly_curve_{name}.json"  # name: wind | solar | unified
HOURLY_PANEL_FILENAME = "hourly_sin_panel.parquet"


class HourlyModelError(RuntimeError):
    pass


def logistic_rate(x, L: float, k: float, x0: float):
    """Bounded logistic curtailment rate (same formula as calibration.logistic, argument order of the hourly model)."""
    return L / (1 + np.exp(-k * (np.asarray(x, float) - x0)))


# ----------------------------------------------------------------------------------------------- hourly SIN panel
def assemble_sin_panel(balance: pd.DataFrame, solar_disp: pd.DataFrame, curtailment: pd.DataFrame, start: str = "2022-01-01") -> pd.DataFrame:
    """SIN-wide hourly frame from the three subsystem-hour tables.

    balance: [ts, sub, wind, load] (MWh); solar_disp: [ts, sub, solar_disp] (dispatched/verified solar MWh); curtailment: [ts, sub, curt_wind, curt_solar] (MWh).
    Returns an hourly-indexed frame with wind, solar_disp, curt_wind, curt_solar, load and r (%), restricted to start <= ts < END_EXCLUSIVE.
    """
    h = balance.merge(solar_disp, on=["ts", "sub"], how="left").merge(curtailment, on=["ts", "sub"], how="left")
    for col in ("solar_disp", "curt_wind", "curt_solar"):
        h[col] = h[col].fillna(0.0)
    g = h.groupby("ts")[["wind", "solar_disp", "curt_wind", "curt_solar", "load"]].sum()
    g["r"] = 100 * (g.wind + g.solar_disp + g.curt_wind + g.curt_solar) / g["load"]
    return g[(g.index >= start) & (g.index < END_EXCLUSIVE)].copy()


def load_sin_panel(refresh: bool = False, start: str = "2022-01-01") -> pd.DataFrame:
    """Build (or read the cache of) the SIN hourly panel from the raw ONS files (generation_by_source, capacity_factor, curtailment_wind / _solar)."""
    from curtailmit.paths import get_interim_dir, get_raw_dir

    cache = get_interim_dir() / HOURLY_PANEL_FILENAME
    if cache.exists() and not refresh:
        return pd.read_parquet(cache)
    frames = []
    for f in sorted(get_raw_dir("ons/generation_by_source").glob("Balanco_de_Energia_Subsistema-*.parquet")):
        if int(f.stem[-4:]) < 2021:
            continue
        df = pd.read_parquet(f)
        df["sub"] = df["id_subsistema"].astype(str).str.strip()
        df = df[df["sub"].isin(SUBSYSTEMS)].copy()
        df["ts"] = pd.to_datetime(df["din_instante"])
        for c in ("val_gereolica", "val_carga"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        frames.append(df[["ts", "sub", "val_gereolica", "val_carga"]])
    if not frames:
        raise HourlyModelError("no ONS balance files under raw/ons/generation_by_source - run Stage 1 acquisition first.")
    balance = pd.concat(frames, ignore_index=True).rename(columns={"val_gereolica": "wind", "val_carga": "load"}).groupby(["ts", "sub"], as_index=False).sum(numeric_only=True)

    frames = []
    for f in sorted(get_raw_dir("ons/capacity_factor").glob("*.parquet")):
        df = pd.read_parquet(f, columns=["id_subsistema", "nom_tipousina", "din_instante", "val_geracaoverificada"])
        df = df[df["nom_tipousina"].astype(str).str.lower().str.startswith("solar")].copy()
        df["sub"] = df["id_subsistema"].astype(str).str.strip()
        df["ts"] = pd.to_datetime(df["din_instante"]).dt.floor("h")
        df["mwh"] = pd.to_numeric(df["val_geracaoverificada"], errors="coerce").fillna(0.0)
        frames.append(df.groupby(["ts", "sub"], as_index=False)["mwh"].sum())
    solar = pd.concat(frames, ignore_index=True).groupby(["ts", "sub"], as_index=False)["mwh"].sum().rename(columns={"mwh": "solar_disp"})

    frames = []
    for tech, d in (("wind", "curtailment_wind"), ("solar", "curtailment_solar")):
        for f in sorted(get_raw_dir(f"ons/{d}").glob("*.parquet")):
            df = pd.read_parquet(f, columns=["id_subsistema", "din_instante", "val_geracaonaorealizadaapurada"])
            ts = pd.to_datetime(df["din_instante"])
            step_h = ts.drop_duplicates().sort_values().diff().dropna().median().total_seconds() / 3600  # rows are MW per step: MWh = MW x step
            df["sub"] = df["id_subsistema"].astype(str).str.strip()
            df["ts"] = ts.dt.floor("h")
            df["mwh"] = pd.to_numeric(df["val_geracaonaorealizadaapurada"], errors="coerce").fillna(0.0) * step_h
            g = df.groupby(["ts", "sub"], as_index=False)["mwh"].sum()
            g["tech"] = tech
            frames.append(g)
    curt = pd.concat(frames, ignore_index=True).groupby(["ts", "sub", "tech"], as_index=False)["mwh"].sum()
    curt = curt.pivot_table(index=["ts", "sub"], columns="tech", values="mwh", aggfunc="sum").reset_index().rename(columns={"wind": "curt_wind", "solar": "curt_solar"})
    for col in ("curt_wind", "curt_solar"):
        if col not in curt:
            curt[col] = 0.0
    panel = assemble_sin_panel(balance, solar, curt, start)
    panel.to_parquet(cache)
    return panel


def technology_frame(h: pd.DataFrame, tech: str) -> tuple[pd.DataFrame, str, str]:
    """Hourly frame restricted to the technology's window with the (realized, curtailed) column pair; 'unified' = wind + solar totals (window of the solar record)."""
    if tech == "unified":
        d = h[h.index >= TECH_START["solar"]].copy()
        d["vre_real"] = d.wind + d.solar_disp
        d["curt_vre"] = d.curt_wind + d.curt_solar
        return d, "vre_real", "curt_vre"
    real, curt = TECH_COLUMNS[tech]
    return h[h.index >= TECH_START[tech]].copy(), real, curt


# ----------------------------------------------------------------------------------------------- binning and fit
class MonthBins:
    """Per-month x per-bin sufficient statistics of the hourly dose-response, so that a month-resampling bootstrap or a train/test split is a weighted sum.

    Bins are (a, b] of width `width` in x (as pandas.cut in the prototype); a bin's x is the potential-weighted mean of x, its rate curtailed / potential.
    """

    def __init__(self, h: pd.DataFrame, real: str, curt: str, xcol: str = "r", width: float = WIDTH, xmax: float = XMAX):
        self.edges = np.arange(0.0, xmax + width, width)
        nb = len(self.edges) - 1
        x = h[xcol].to_numpy()
        pot = (h[real] + h[curt]).to_numpy()
        c = h[curt].to_numpy()
        b = np.clip(np.searchsorted(self.edges, x, side="left") - 1, 0, nb - 1)
        m, uniq = pd.factorize(h.index.to_period("M"), sort=True)
        self.months = pd.PeriodIndex(uniq)
        nm = len(uniq)
        flat = m * nb + b
        self.sxp = np.bincount(flat, x * pot, nm * nb).reshape(nm, nb)
        self.pot = np.bincount(flat, pot, nm * nb).reshape(nm, nb)
        self.curt = np.bincount(flat, c, nm * nb).reshape(nm, nb)
        self.hours = np.bincount(flat, None, nm * nb).reshape(nm, nb)

    def bins(self, w: np.ndarray | None = None) -> pd.DataFrame:
        """Bin table (x, pot, rate, hours) for month weights w (counts; None = every month once)."""
        if w is None:
            w = np.ones(len(self.months))
        pot, sxp, cur, hrs = w @ self.pot, w @ self.sxp, w @ self.curt, w @ self.hours
        ok = pot > 0
        return pd.DataFrame({"x": sxp[ok] / pot[ok], "pot": pot[ok], "rate": cur[ok] / pot[ok], "hours": hrs[ok]})


def fit_logistic(bins: pd.DataFrame, L_fixed: float | None = None, min_hours: int = MIN_HOURS) -> tuple[float, float, float]:
    """Potential-weighted bounded logistic (L, k, x0) on a bin table; L_fixed pins the asymptote (k, x0 refitted)."""
    d = bins[bins["hours"] >= min_hours]
    if len(d) < 4:
        raise HourlyModelError(f"only {len(d)} populated bins (>= {min_hours} hours): not enough to fit (L, k, x0).")
    w = d["pot"] / d["pot"].max()
    sigma = 1 / np.sqrt(w.clip(lower=1e-6))
    if L_fixed is None:
        popt, _ = curve_fit(logistic_rate, d["x"], d["rate"], p0=(0.9, 0.1, 40.0), sigma=sigma, bounds=([1e-9, 1e-3, -np.inf], [1.0, np.inf, np.inf]), maxfev=20000)
        return tuple(float(v) for v in popt)
    popt, _ = curve_fit(lambda x, k, x0: logistic_rate(x, L_fixed, k, x0), d["x"], d["rate"], p0=(0.1, 40.0), sigma=sigma, bounds=([1e-3, -np.inf], [np.inf, np.inf]), maxfev=20000)
    return (float(L_fixed), float(popt[0]), float(popt[1]))


def r_cap_of(bins: pd.DataFrame, min_hours: int = MIN_HOURS) -> float:
    """Largest bin centre (potential-weighted x) with at least `min_hours` observed hours: the edge of the populated support."""
    return float(bins[bins["hours"] >= min_hours]["x"].max())


@dataclass(frozen=True)
class HourlyCurve:
    """A fitted hourly dose-response curve with its populated support."""

    technology: str
    L: float
    k: float
    x0: float
    r_cap: float
    n_months: int
    n_hours: int
    window_start: str

    @property
    def params(self) -> tuple[float, float, float]:
        return (self.L, self.k, self.x0)

    def rate(self, r, cap: bool = False):
        """Curtailment rate at r (%); with cap=True the curve is not extrapolated beyond the populated support (r clipped at r_cap)."""
        x = np.minimum(np.asarray(r, float), self.r_cap) if cap else r
        return logistic_rate(x, self.L, self.k, self.x0)

    def with_L(self, L: float) -> HourlyCurve:
        return HourlyCurve(self.technology, L, self.k, self.x0, self.r_cap, self.n_months, self.n_hours, self.window_start)


def fit_hourly_curve(h: pd.DataFrame, tech: str, L_fixed: float | None = None) -> HourlyCurve:
    """Option E curve of a technology ('wind', 'solar' or 'unified') on the SIN hourly panel, in the technology's own sample window."""
    d, real, curt = technology_frame(h, tech)
    if d.empty:
        raise HourlyModelError(f"no hourly data in the {tech} window (from {TECH_START.get(tech, TECH_START['solar'])}).")
    mb = MonthBins(d, real, curt)
    bins = mb.bins()
    L, k, x0 = fit_logistic(bins, L_fixed)
    return HourlyCurve(tech, L, k, x0, r_cap_of(bins), len(mb.months), len(d), str(d.index.min().date()))


def bootstrap_curve_params(mb: MonthBins, n: int, seed: int = 0, L_fixed: float | None = None) -> np.ndarray:
    """Month-resampling bootstrap of the (L, k, x0) fit; failed fits are dropped. Returns an (m, 3) array."""
    rng = np.random.default_rng(seed)
    nm = len(mb.months)
    out = []
    for _ in range(n):
        w = np.bincount(rng.integers(0, nm, nm), minlength=nm).astype(float)
        try:
            out.append(fit_logistic(mb.bins(w), L_fixed))
        except Exception as exc:  # noqa: BLE001 - a degenerate resample is simply skipped
            logger.debug("bootstrap refit skipped: %s", exc)
    return np.array(out)


# ----------------------------------------------------------------------------------------------- extrapolation distance
def extrapolation_metrics(r: np.ndarray, pot: np.ndarray, params: tuple, r_cap: float) -> dict:
    """E_out, H_out, D_pp of a set of hours (r %, potential MWh) with respect to the support edge r_cap and a fitted curve.

    E_out: share of the predicted curtailed energy produced by hours with r > r_cap (primary, 0-1); H_out: share of hours beyond r_cap;
    D_pp: curtailment-weighted mean excess (r - r_cap) over the beyond-support hours, in pp of r.
    """
    r, pot = np.asarray(r, float), np.asarray(pot, float)
    curt = logistic_rate(r, *params) * pot
    out = r > r_cap
    tot = curt.sum()
    e_out = float(curt[out].sum() / tot) if tot > 0 else 0.0
    d_pp = float(np.average(r[out] - r_cap, weights=np.maximum(curt[out], 1e-12))) if out.any() else 0.0
    return {"E_out": e_out, "H_out": float(out.mean()), "D_pp": d_pp}


# ----------------------------------------------------------------------------------------------- PTE-scaled hourly profile
@dataclass(frozen=True)
class BaseProfile:
    """Hourly potentials (MWh) and load of the base year, SIN-wide."""

    wind: np.ndarray
    solar: np.ndarray
    load: np.ndarray
    year: int

    @classmethod
    def from_panel(cls, h: pd.DataFrame, year: int = 2025) -> BaseProfile:
        b = h[h.index.year == year]
        if b.empty:
            raise HourlyModelError(f"the hourly panel has no data for the base year {year}.")
        return cls((b.wind + b.curt_wind).to_numpy(), (b.solar_disp + b.curt_solar).to_numpy(), b["load"].to_numpy(), year)


@dataclass(frozen=True)
class ScaleFactors:
    """PTE annual totals of a (scenario, year) relative to the base year, and the PTE generation of each technology (TWh)."""

    a_wind: float
    a_solar: float
    a_load: float
    wind_gen_twh: float
    solar_gen_twh: float


def scale_factors(pte: pd.DataFrame, scenario: str, year: int, base_year: int = 2025) -> ScaleFactors:
    """Factors from a PTE table with columns scenario, year, wind_gen_twh, solar_gen_twh, total_generation_twh."""
    g = pte[pte["scenario"] == scenario].set_index("year")
    for y in (year, base_year):
        if y not in g.index:
            raise HourlyModelError(f"PTE table has no {y} entry for scenario {scenario}.")
    return ScaleFactors(float(g.loc[year, "wind_gen_twh"] / g.loc[base_year, "wind_gen_twh"]), float(g.loc[year, "solar_gen_twh"] / g.loc[base_year, "solar_gen_twh"]),
                        float(g.loc[year, "total_generation_twh"] / g.loc[base_year, "total_generation_twh"]), float(g.loc[year, "wind_gen_twh"]), float(g.loc[year, "solar_gen_twh"]))


def projected_r(prof: BaseProfile, f: ScaleFactors, phi: float = 1.0) -> np.ndarray:
    """Hourly potential VRE share of load (%) of a PTE scenario/year: (a_wind W + a_solar S) / (a_load LD) / phi; phi > 1 is the flexibility sensitivity (r_eff = r / phi)."""
    return 100 * (f.a_wind * prof.wind + f.a_solar * prof.solar) / (f.a_load * prof.load) / phi


def projected_rate(r: np.ndarray, pot: np.ndarray, curve: HourlyCurve, cap: bool = False) -> float:
    """Energy-weighted curtailment rate of a technology in a projected year (optionally with r capped at the populated support)."""
    return float((curve.rate(r, cap=cap) * pot).sum() / pot.sum())


# ----------------------------------------------------------------------------------------------- persistence
def save_curve(curve: HourlyCurve, dest: Path) -> None:
    dest.write_text(json.dumps(asdict(curve), indent=2), encoding="utf-8")


def load_curve(src: Path) -> HourlyCurve:
    return HourlyCurve(**json.loads(src.read_text(encoding="utf-8")))


# ----------------------------------------------------------------------------------------------- calibration bundle
BASE_PROFILE_FILENAME = "hourly_base_profile.parquet"
HORIZON_BANDS_FILENAME = "hourly_horizon_bands.json"


@dataclass(frozen=True)
class HourlyCalibration:
    """Everything the projection needs from the hourly calibration: the free-L curves, the L = 1 curves (upper scenario of the 2050 conditional range), the 2025 profile and the frozen bands."""

    wind: HourlyCurve
    solar: HourlyCurve
    wind_L1: HourlyCurve
    solar_L1: HourlyCurve
    profile: BaseProfile
    bands: HorizonBands  # noqa: F821 - defined in hourly_uncertainty (imported lazily to avoid a cycle)


def run_hourly_calibration(h: pd.DataFrame | None = None, processed_dir: Path | None = None, base_year: int = 2025, write: bool = True) -> HourlyCalibration:
    """Fit the option-E curves on the SIN hourly panel, freeze the horizon bands and (write=True) persist everything in processed/.

    Writes hourly_curve_{wind,solar,wind_L1,solar_L1}.json, hourly_base_profile.parquet and hourly_horizon_bands.json.
    """
    from curtailmit.hourly_uncertainty import build_horizon_bands
    from curtailmit.paths import get_processed_dir

    h = load_sin_panel() if h is None else h
    cal = HourlyCalibration(fit_hourly_curve(h, "wind"), fit_hourly_curve(h, "solar"), fit_hourly_curve(h, "wind", L_fixed=1.0), fit_hourly_curve(h, "solar", L_fixed=1.0),
                            BaseProfile.from_panel(h, base_year), build_horizon_bands(h))
    if write:
        out = processed_dir or get_processed_dir()
        for name, curve in (("wind", cal.wind), ("solar", cal.solar), ("wind_L1", cal.wind_L1), ("solar_L1", cal.solar_L1)):
            save_curve(curve, out / CURVE_FILENAME.format(name=name))
        pd.DataFrame({"wind": cal.profile.wind, "solar": cal.profile.solar, "load": cal.profile.load}).assign(year=cal.profile.year).to_parquet(out / BASE_PROFILE_FILENAME, index=False)
        cal.bands.save(out / HORIZON_BANDS_FILENAME)
    return cal


def load_hourly_calibration(processed_dir: Path | None = None) -> HourlyCalibration:
    """Read back what run_hourly_calibration wrote."""
    from curtailmit.hourly_uncertainty import HorizonBands
    from curtailmit.paths import get_processed_dir

    out = processed_dir or get_processed_dir()
    prof = pd.read_parquet(out / BASE_PROFILE_FILENAME)
    return HourlyCalibration(*(load_curve(out / CURVE_FILENAME.format(name=n)) for n in ("wind", "solar", "wind_L1", "solar_L1")),
                             BaseProfile(prof["wind"].to_numpy(), prof["solar"].to_numpy(), prof["load"].to_numpy(), int(prof["year"].iloc[0])), HorizonBands.load(out / HORIZON_BANDS_FILENAME))
