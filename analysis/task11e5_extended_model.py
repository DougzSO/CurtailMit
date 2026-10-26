"""Task 11E5-c throwaway analysis (NOT part of the installed package; no src/ change; no new data): does an explicit residual-trend term improve the hourly wind model safely?

Models (wind, SIN; fitted on month x 2-pp-bin cells of the hourly dose-response, weights = potential energy; t in years since 2022-01-01):
  base      f = L sigma(k (x - x0))                                          (option E, as adopted in D24)
  linear    f = L sigma(k (x - x0) + beta t)                                  left shift of the curve growing linearly in time
  saturate  f = L sigma(k (x - x0) + beta (1 - exp(-t / tau)))                 tau in {1, 2, 3, 5} years (best by weighted SSE)
  step      f = L sigma(k (x - x0) + beta 1[month >= 2025-01])                step at the break found in 11E5-b
  ktrend    f = L sigma((k + kappa t)(x - x0))                                the slope of the curve changes with time (the drift sits at low r)
PRE-REGISTERED SAFETY / WORTH CRITERIA (fixed before the results):
  S1 the r-driven component must keep its explanatory power: partial correlation of monthly C with the r-component (trend term held at its sample mean) given t >= 0.5 (base 0.70) and its incremental R2 over t >= 0.08 (base 0.13);
  S2 no confound: the month-bootstrap 90 % interval of k and of x0 not wider than 1.5 x the base one;
  S3 worth: the absolute annual error of the held-out period falls by >= 5 percentage points against base in at least 2 of the held-out periods (S1 train 2022-24 -> 2025, 2026; S2 train 2022-01..2025-06 -> 2025-07..2026-09 in two pieces);
  S4 bounded: the extrapolation of the trend term to 2040 / 2050 must be bounded by construction (step, saturating) or flagged unsafe.
Run (after task11e5_drift_characterization.py):  python analysis/task11e5_extended_model.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.optimize import least_squares

sys.path.insert(0, str(Path(__file__).resolve().parent))
import task11e2_backtest as bt
import task11e2_common as c2
import task11e5_drift_characterization as ch
import task11e_common as cm

pd.set_option("display.width", 230)
pd.set_option("display.max_columns", 50)
REAL, CURT = c2.TECH["wind"]
STEP_MONTH = pd.Period("2025-01", freq="M")
TAUS = (1.0, 2.0, 3.0, 5.0)
N_BOOT = 150


def sig(z: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-np.clip(z, -60, 60)))


def f_model(name: str, th: np.ndarray, x: np.ndarray, t: np.ndarray, step: np.ndarray, tau: float = 3.0) -> np.ndarray:
    L, k, x0 = th[0], th[1], th[2]
    if name == "base":
        return L * sig(k * (x - x0))
    b = th[3]
    if name == "linear":
        return L * sig(k * (x - x0) + b * t)
    if name == "saturate":
        return L * sig(k * (x - x0) + b * (1 - np.exp(-t / tau)))
    if name == "step":
        return L * sig(k * (x - x0) + b * step)
    if name == "ktrend":
        return L * sig(np.maximum(k + b * t, 1e-3) * (x - x0))
    raise ValueError(name)


class Cells:
    """Month x bin cells of the wind dose-response, with time covariates."""

    def __init__(self, h: pd.DataFrame):
        self.mb = c2.MonthBins(h, REAL, CURT)
        mb = self.mb
        self.months = mb.months
        self.t_month = np.asarray((self.months.year - 2022) + (self.months.month - 0.5) / 12, float)
        self.step_month = np.array([m >= STEP_MONTH for m in self.months], float)

    def arrays(self, month_mask: np.ndarray) -> dict:
        mb = self.mb
        ok = (mb.hours >= 10) & (mb.pot > 0) & month_mask[:, None]
        mi, bi = np.where(ok)
        pot = mb.pot[mi, bi]
        return {"x": mb.sxp[mi, bi] / pot, "rate": mb.curt[mi, bi] / pot, "w": pot, "t": self.t_month[mi], "step": self.step_month[mi], "m": mi}


def fit(name: str, cells: Cells, month_mask: np.ndarray, tau: float = 3.0, start: np.ndarray | None = None) -> tuple[np.ndarray, float]:
    a = cells.arrays(month_mask)
    sw = np.sqrt(a["w"] / a["w"].max())
    base0 = np.array([0.73, 0.14, 41.0]) if start is None else start[:3]
    th0 = base0 if name == "base" else np.r_[base0, 0.0]
    lo = np.r_[1e-6, 1e-3, -np.inf] if name == "base" else np.r_[1e-6, 1e-3, -np.inf, -np.inf]
    hi = np.r_[1.0, np.inf, np.inf] if name == "base" else np.r_[1.0, np.inf, np.inf, np.inf]
    if name == "ktrend":
        th0[3] = 0.0
    r = least_squares(lambda th: sw * (a["rate"] - f_model(name, th, a["x"], a["t"], a["step"], tau)), th0, bounds=(lo, hi), x_scale=np.r_[0.1, 0.05, 5.0, 0.5][: len(th0)], max_nfev=2000)
    return r.x, float(((sw * (a["rate"] - f_model(name, r.x, a["x"], a["t"], a["step"], tau))) ** 2).sum())


def fit_all(cells: Cells, month_mask: np.ndarray) -> dict:
    out = {"base": (fit("base", cells, month_mask)[0], 3.0)}
    for nm in ("linear", "step", "ktrend"):
        out[nm] = (fit(nm, cells, month_mask, start=out["base"][0])[0], 3.0)
    best = None
    for tau in TAUS:
        th, sse = fit("saturate", cells, month_mask, tau, start=out["base"][0])
        if best is None or sse < best[2]:
            best = (th, tau, sse)
    out["saturate"] = (best[0], best[1])
    return out


def hourly_pred(h: pd.DataFrame, name: str, th: np.ndarray, tau: float) -> pd.Series:
    t = (h.index.year - 2022) + (h.index.dayofyear - 0.5) / 365.25
    step = (h.index >= STEP_MONTH.to_timestamp()).astype(float)
    f = f_model(name, th, h["r"].to_numpy(), np.asarray(t, float), np.asarray(step, float), tau)
    return pd.Series(f * (h[REAL] + h[CURT]).to_numpy(), index=h.index)


def evaluate_period(h: pd.DataFrame, fits: dict, sel: np.ndarray) -> pd.DataFrame:
    obs = float(h.loc[sel, CURT].sum() / 1e6)
    rows = []
    for nm, (th, tau) in fits.items():
        p = float(hourly_pred(h, nm, th, tau)[sel].sum() / 1e6)
        rows.append({"model": nm, "obs_twh": obs, "pred_twh": p, "err_pct": 100 * (p - obs) / obs})
    return pd.DataFrame(rows)


def r_component_check(h: pd.DataFrame, fits: dict, mr0: pd.DataFrame) -> pd.DataFrame:
    """Time-confound safety: monthly C against the r-component of every model (trend term fixed at its sample mean), given t."""
    rows = []
    t_h = (h.index.year - 2022) + (h.index.dayofyear - 0.5) / 365.25
    step_h = (h.index >= STEP_MONTH.to_timestamp()).astype(float)
    for nm, (th, tau) in fits.items():
        th_c = th.copy()
        t_use, step_use = np.asarray(t_h, float), np.asarray(step_h, float)
        if nm == "linear":
            th_c[3] = th[3] * float(np.mean(t_use))
            f = f_model("linear", np.r_[th_c[:3], th_c[3]], h["r"].to_numpy(), np.ones(len(h)), step_use)
        elif nm == "saturate":
            f = f_model("saturate", th, h["r"].to_numpy(), np.full(len(h), float(np.mean(t_use))), step_use, tau)
        elif nm == "step":
            f = f_model("step", th, h["r"].to_numpy(), t_use, np.full(len(h), float(step_use.mean())))
        elif nm == "ktrend":
            f = f_model("ktrend", th, h["r"].to_numpy(), np.full(len(h), float(np.mean(t_use))), step_use)
        else:
            f = f_model("base", th, h["r"].to_numpy(), t_use, step_use)
        pot = (h[REAL] + h[CURT]).to_numpy()
        g = pd.Series(f * pot, index=h.index).groupby(h.index.to_period("M")).sum() / pd.Series(pot, index=h.index).groupby(h.index.to_period("M")).sum()
        df = pd.DataFrame({"C": mr0["obs"], "t": np.arange(len(mr0)), "Hr": g})
        mx, mt, mxt = bt.hac_fit(df, ["Hr"]), bt.hac_fit(df, ["t"]), bt.hac_fit(df, ["Hr", "t"])
        rows.append({"model": nm, "partial_C_Hr_given_t": c2.partial_corr(df, "Hr", "C", ["t"]), "corr_Hr_t": float(df.Hr.corr(df.t)), "R2_Hr": mx.rsquared, "R2_t": mt.rsquared, "R2_Hr+t": mxt.rsquared, "dR2_Hr_over_t": mxt.rsquared - mt.rsquared})
    return pd.DataFrame(rows)


def bootstrap_params(cells: Cells, name: str, tau: float, base_th: np.ndarray, n: int = N_BOOT, seed: int = 5) -> np.ndarray:
    rng = np.random.default_rng(seed)
    nm_ = len(cells.months)
    out = []
    for _ in range(n):
        idx = rng.integers(0, nm_, nm_)
        w = np.bincount(idx, minlength=nm_) > 0
        try:
            th, _ = fit(name, cells, w, tau, start=base_th)
            out.append(th)
        except Exception:  # noqa: BLE001
            continue
    return np.array(out)


def projections(h: pd.DataFrame, fits: dict) -> pd.DataFrame:
    prof = c2.base_profile(h)
    pte = c2.load_pte()
    rows = []
    for sc in c2.SCENARIOS:
        for year in c2.YEARS:
            f = c2.scale_factors(pte, sc, year)
            r = c2.projected_r(prof, f)
            pot = prof["W"] * f["a_wind"]
            tf = year - 2022 + 0.5
            for nm, (th, tau) in fits.items():
                rate = float((f_model(nm, th, r, np.full(len(r), tf), np.ones(len(r)), tau) * pot).sum() / pot.sum())
                rows.append({"scenario": sc, "year": year, "model": nm, "rate_pct": 100 * rate, "wind_twh": rate * f["wind_gen_twh"]})
    t = pd.DataFrame(rows)
    base = t[t.model == "base"].set_index(["scenario", "year"])["wind_twh"]
    t["vs_base_twh"] = t.apply(lambda r: r.wind_twh - base[(r.scenario, r.year)], axis=1)
    t["vs_base_pct"] = 100 * t["vs_base_twh"] / t.apply(lambda r: base[(r.scenario, r.year)], axis=1)
    return t


def main() -> None:
    h = cm.sin_hourly("2022-01-01")
    T = cm.tables_dir()
    cells = Cells(h)
    allm = np.ones(len(cells.months), bool)
    fits = fit_all(cells, allm)
    print("Full-sample fits (L, k, x0, trend term):")
    for nm, (th, tau) in fits.items():
        print(f"  {nm:9s}", np.round(th, 4), "tau" if nm == "saturate" else "", tau if nm == "saturate" else "")
    mr0 = ch.monthly_residual(h, fits["base"][0][:3])
    # in-sample monthly fit and residual trend of every model
    rows = []
    for nm, (th, tau) in fits.items():
        pred = hourly_pred(h, nm, th, tau)
        gp = pred.groupby(h.index.to_period("M")).sum()
        pot = (h[REAL] + h[CURT]).groupby(h.index.to_period("M")).sum()
        obs = h[CURT].groupby(h.index.to_period("M")).sum()
        res = pd.DataFrame({"res_pp": 100 * (obs - gp) / pot})
        res["t_years"] = (res.index.year - 2022) + (res.index.month - 0.5) / 12
        tr = ch.trend_with_ci(res, n_boot=300)
        rate_o, rate_p = obs / pot, gp / pot
        rows.append({"model": nm, "monthly_R2": 1 - float(((rate_o - rate_p) ** 2).sum() / ((rate_o - rate_o.mean()) ** 2).sum()), "monthly_RMSE_pp": 100 * float(np.sqrt(((rate_o - rate_p) ** 2).mean())),
                     "residual_trend_pp_per_year": tr["slope_pp_per_year"], "res_trend_CI": f"{tr['NW_CI_lo']:.2f}..{tr['NW_CI_hi']:.2f}"})
    insample = pd.DataFrame(rows)
    insample.to_csv(T / "task11e5_extended_insample.csv", index=False)
    print("\nIn-sample (57 months):\n", insample.round(3).to_string(index=False))

    # held-out validation
    mths = cells.months
    y = np.array([m.year for m in mths])
    sch = {"S1 train 2022-24": (y <= 2024, [("2025", (h.index.year == 2025)), ("2026 Jan-Sep", (h.index.year == 2026))]),
           "S2 train 2022-01..2025-06": (np.array([m <= pd.Period("2025-06", freq="M") for m in mths]), [("2025 Jul-Dec", (h.index >= "2025-07-01") & (h.index.year == 2025)), ("2026 Jan-Sep", (h.index.year == 2026))])}
    ev = []
    for sname, (mask, tests) in sch.items():
        fts = fit_all(cells, mask)
        for lab, sel in tests:
            e = evaluate_period(h, fts, np.asarray(sel))
            e.insert(0, "period", f"{sname} -> {lab}")
            ev.append(e)
    ev = pd.concat(ev, ignore_index=True)
    ev.to_csv(T / "task11e5_extended_heldout.csv", index=False)
    print("\nHeld-out annual error (pred - obs) / obs, %:\n", ev.pivot_table(index="model", columns="period", values="err_pct").round(1).to_string())

    chk = r_component_check(h, fits, mr0)
    chk.to_csv(T / "task11e5_extended_safety_r_component.csv", index=False)
    print("\nS1: r-component vs monthly C given t:\n", chk.round(3).to_string(index=False))

    rows = []
    for nm in ("base", "linear", "step", "ktrend", "saturate"):
        th, tau = fits[nm]
        bs = bootstrap_params(cells, nm, tau, fits["base"][0])
        w_k, w_x0 = np.percentile(bs[:, 1], 95) - np.percentile(bs[:, 1], 5), np.percentile(bs[:, 2], 95) - np.percentile(bs[:, 2], 5)
        row = {"model": nm, "n_boot": len(bs), "k": th[1], "k_width90": w_k, "x0": th[2], "x0_width90": w_x0, "L": th[0], "L_width90": np.percentile(bs[:, 0], 95) - np.percentile(bs[:, 0], 5)}
        if len(th) > 3:
            row["trend_term"] = th[3]
            row["trend_CI90"] = f"{np.percentile(bs[:, 3], 5):.3f}..{np.percentile(bs[:, 3], 95):.3f}"
        rows.append(row)
    bsd = pd.DataFrame(rows)
    b0 = bsd.loc[bsd.model == "base"].iloc[0]
    bsd["k_width_ratio"], bsd["x0_width_ratio"] = bsd.k_width90 / b0.k_width90, bsd.x0_width90 / b0.x0_width90
    bsd.to_csv(T / "task11e5_extended_bootstrap.csv", index=False)
    print("\nS2: month-bootstrap (5-95 %) widths of k, x0 and the trend term:\n", bsd.round(3).to_string(index=False))

    pr = projections(h, fits)
    pr.to_csv(T / "task11e5_extended_projection.csv", index=False)
    print("\nWind curtailment under each model, TWh (and difference to base):\n", pr[pr.year.isin([2030, 2040, 2050])].pivot_table(index=["scenario", "year"], columns="model", values="wind_twh").round(0).to_string())
    print(pr[pr.year.isin([2040, 2050])].pivot_table(index=["scenario", "year"], columns="model", values="vs_base_pct").round(1).to_string())


if __name__ == "__main__":
    main()
