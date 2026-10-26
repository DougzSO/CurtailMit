"""Shared helpers for the Task 11E2 analysis scripts (throwaway, outside the package, no src/ change).

Builds on task11e_common (hourly SIN panel, binned logistic fit). Adds: a fast month-resampling bin table (block bootstrap of the hourly dose-response curve), a fixed-L fit,
and the PTE-scaled hourly profile used to project r for 2030/2040/2050 (same construction as task11e_wind_envelope.hourly_projection: 2025 hourly shape, wind x W_t/W_2025,
solar x S_t/S_2025, load x T_t/T_2025 with the PTE annual totals).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import task11e_common as cm
from curtailmit.paths import get_processed_dir

WIDTH = 2.0
MIN_HOURS = 15
SCENARIOS = ("TB", "TA", "TG")
YEARS = (2030, 2040, 2050)
TECH = {"wind": ("wind", "curt_wind"), "solar": ("solar_disp", "curt_solar")}
TECH_START = {"wind": "2022-01-01", "solar": "2024-04-01"}


def window(h: pd.DataFrame, start: str | None = None, end: str | None = None) -> pd.DataFrame:
    """Rows with start <= ts < end (end exclusive; strings are dates)."""
    out = h
    if start is not None:
        out = out[out.index >= start]
    if end is not None:
        out = out[out.index < end]
    return out


class MonthBins:
    """Per-month x per-bin sufficient statistics of the hourly dose-response, so that a bootstrap over months is a weighted sum (no refit of the binning)."""

    def __init__(self, h: pd.DataFrame, real: str, curt: str, xcol: str = "r", width: float = WIDTH, xmax: float = 102.0):
        self.edges = np.arange(0.0, xmax + width, width)
        nb = len(self.edges) - 1
        x = h[xcol].to_numpy()
        pot = (h[real] + h[curt]).to_numpy()
        c = h[curt].to_numpy()
        b = np.clip(np.searchsorted(self.edges, x, side="left") - 1, 0, nb - 1)  # bins are (a, b], as pandas.cut in task11e_common.binned
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
    """Weighted bounded logistic (L, k, x0) on a bin table; L_fixed pins the asymptote (k, x0 refitted)."""
    if L_fixed is None:
        return cm.fit_binned(bins, min_hours)
    d = bins[bins["hours"] >= min_hours]
    w = d["pot"] / d["pot"].max()
    popt, _ = curve_fit(lambda x, k, x0: cm.logistic_w(x, L_fixed, k, x0), d["x"], d["rate"], p0=(0.1, 40.0), sigma=1 / np.sqrt(w.clip(lower=1e-6)), bounds=([1e-3, -np.inf], [np.inf, np.inf]), maxfev=20000)
    return (float(L_fixed), float(popt[0]), float(popt[1]))


def r_cap_of(bins: pd.DataFrame, min_hours: int = MIN_HOURS) -> float:
    """Largest bin centre (potential-weighted x) with at least `min_hours` observed hours: the edge of the populated support."""
    return float(bins[bins["hours"] >= min_hours]["x"].max())


def curtailed_by_hour(h: pd.DataFrame, params: tuple, real: str, curt: str) -> pd.Series:
    """Curtailed MWh predicted for each hour by a fixed curve: f(r_h) x (realized + curtailed)."""
    return pd.Series(cm.logistic_w(h["r"].to_numpy(), *params) * (h[real] + h[curt]).to_numpy(), index=h.index)


def annual_twh(s: pd.Series) -> pd.Series:
    return s.groupby(s.index.year).sum() / 1e6


def bootstrap_params(mb: MonthBins, n: int, seed: int = 0, L_fixed: float | None = None) -> np.ndarray:
    """Month-resampling bootstrap of the (L, k, x0) fit; failed fits are dropped. Returns an (m, 3) array."""
    rng = np.random.default_rng(seed)
    nm = len(mb.months)
    out = []
    for _ in range(n):
        w = np.bincount(rng.integers(0, nm, nm), minlength=nm).astype(float)
        try:
            out.append(fit_logistic(mb.bins(w), L_fixed))
        except Exception:  # noqa: BLE001 - a degenerate resample is simply skipped
            continue
    return np.array(out)


# ----------------------------------------------------------------------------------------------- PTE-scaled hourly profile
def load_pte() -> pd.DataFrame:
    return pd.read_parquet(get_processed_dir() / "pte_curtailment_two_curves.parquet")


def base_profile(h: pd.DataFrame, year: int = 2025) -> dict[str, np.ndarray]:
    """Hourly potentials (MWh) and load of the base year, SIN-wide."""
    b = h[h.index.year == year]
    return {"W": (b.wind + b.curt_wind).to_numpy(), "S": (b.solar_disp + b.curt_solar).to_numpy(), "LD": b["load"].to_numpy(), "index": b.index}


def scale_factors(pte: pd.DataFrame, scenario: str, year: int, base_year: int = 2025) -> dict[str, float]:
    g = pte[pte.scenario == scenario].set_index("year")
    return {"a_wind": float(g.loc[year, "wind_gen_twh"] / g.loc[base_year, "wind_gen_twh"]), "a_solar": float(g.loc[year, "solar_gen_twh"] / g.loc[base_year, "solar_gen_twh"]),
            "a_load": float(g.loc[year, "total_generation_twh"] / g.loc[base_year, "total_generation_twh"]),
            "wind_gen_twh": float(g.loc[year, "wind_gen_twh"]), "solar_gen_twh": float(g.loc[year, "solar_gen_twh"])}


def projected_r(prof: dict[str, np.ndarray], f: dict[str, float], phi: float = 1.0) -> np.ndarray:
    """Hourly potential VRE share of load (%) of a PTE scenario/year: (a_wind W + a_solar S) / (a_load LD) / phi."""
    return 100 * (f["a_wind"] * prof["W"] + f["a_solar"] * prof["S"]) / (f["a_load"] * prof["LD"]) / phi


def projected_rate(r: np.ndarray, pot: np.ndarray, params: tuple, r_cap: float | None = None) -> float:
    """Energy-weighted curtailment rate of a technology in a projected year (curve evaluated on r, optionally with r capped at the populated support)."""
    x = r if r_cap is None else np.minimum(r, r_cap)
    return float((cm.logistic_w(x, *params) * pot).sum() / pot.sum())


def partial_corr(df: pd.DataFrame, x: str, y: str, controls: list[str]) -> float:
    import statsmodels.api as sm

    Z = sm.add_constant(df[controls])
    return float(np.corrcoef(sm.OLS(df[x], Z).fit().resid, sm.OLS(df[y], Z).fit().resid)[0, 1])
