"""Task 11E2-b throwaway analysis (NOT part of the installed package; no src/ change): backtest, out-of-sample validation, stability and time-confound test of the hourly dose-response model.

1. Annual backtest: curtailed energy per calendar year predicted by the fixed hourly curve f(r_h) x potential_h vs ONS observed (SIN), wind (2022..2026-09) and solar (2024-04..2026-09).
   Benchmarks refitted on the same training months: national-P logistic (D22 family: bounded logistic of the monthly national P) and a linear time trend of the monthly rate.
   Reference to beat (Task 11D regional wind prototype, 2025): 16.4 TWh predicted vs 26.2 observed.
2. Out-of-sample: train/test splits by year and leave-one-year-out.
3. Stability of the curve across years, subsystems (NE vs rest; own-subsystem r vs SIN r) and seasons / hours of day (L pinned at the pooled value; k, x0 refitted).
4. Time-confound test (Task 11D-b style) on monthly C: partial correlation of the hourly-model rate with C given t, against national P and P_NE, plus incremental R2 and what is left for t.
Run:  python analysis/task11e2_backtest.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats
from scipy.optimize import curve_fit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import task11d_regional_recalibration as ra
import task11e2_common as c2
import task11e_common as cm

pd.set_option("display.width", 230)
pd.set_option("display.max_columns", 50)
HAC = 6
BOOT = 300


# ----------------------------------------------------------------------------------------------- monthly observed and benchmarks
def monthly_obs(h: pd.DataFrame, tech: str) -> pd.DataFrame:
    real, curt = c2.TECH[tech]
    m = h.index.to_period("M")
    g = h.groupby(m)[[real, curt]].sum()
    out = pd.DataFrame({"pot": g[real] + g[curt], "curt": g[curt]})
    out["C"] = out.curt / out.pot
    out["t"] = np.arange(len(out))
    return out


def national_P(months: pd.PeriodIndex) -> pd.Series:
    f = pd.read_parquet(ra.get_processed_dir() / "calibration_frame.parquet")
    f.index = pd.PeriodIndex([pd.Period(year=y, month=m, freq="M") for y, m in zip(f.year, f.month, strict=True)], freq="M")
    return f["P"].reindex(months)


def bench_predictions(mo: pd.DataFrame, P: pd.Series, train: pd.Series) -> pd.DataFrame:
    """Monthly predicted curtailed MWh of the two benchmarks refitted on the training months (mask `train`, aligned to mo.index)."""
    tr = mo[train]
    popt, _ = curve_fit(cm.logistic_w, P[train].to_numpy(), tr.C.to_numpy(), p0=(0.8, 0.1, 40.0), bounds=([1e-9, 1e-3, -np.inf], [1.0, np.inf, np.inf]), maxfev=40000)
    c_p = np.clip(cm.logistic_w(P.to_numpy(), *popt), 0, 1)
    ols = sm.OLS(tr.C, sm.add_constant(tr[["t"]])).fit()
    c_t = np.clip(ols.params["const"] + ols.params["t"] * mo.t, 0, 1)
    return pd.DataFrame({"nationalP": c_p * mo.pot, "time_trend": c_t * mo.pot}, index=mo.index)


# ----------------------------------------------------------------------------------------------- 1-2 backtest and out-of-sample
def backtest(h: pd.DataFrame, tech: str) -> pd.DataFrame:
    real, curt = c2.TECH[tech]
    d = c2.window(h, c2.TECH_START[tech])
    mo = monthly_obs(d, tech)
    P = national_P(mo.index)
    years = sorted(set(d.index.year))
    yr = pd.Series(mo.index.year, index=mo.index)
    schemes: list[tuple[str, pd.Series, list[int]]] = [("in-sample (all months)", pd.Series(True, index=mo.index), years)]
    if tech == "wind":
        schemes += [("train 2022-23 -> test 2024, 2025, 2026", yr <= 2023, [2024, 2025, 2026]), ("train 2022-24 -> test 2025, 2026", yr <= 2024, [2025, 2026]),
                    ("train 2023-24 -> test 2025, 2026 (2022 left out)", yr.isin([2023, 2024]), [2025, 2026])]
        schemes += [(f"leave-one-year-out {y}", yr != y, [y]) for y in (2023, 2024, 2025)]
    else:
        pr = mo.index
        schemes += [("train 2024-04..2025-06 -> test 2025-07..2026-09", pd.Series(pr <= pd.Period("2025-06", freq="M"), index=mo.index), [2025, 2026]),
                    ("leave-one-year-out 2025", yr != 2025, [2025]), ("leave-one-year-out 2026", yr != 2026, [2026])]
    rows = []
    for name, train, test_years in schemes:
        hd = d[d.index.to_period("M").isin(mo.index[train])]
        mb = c2.MonthBins(hd, real, curt)
        params = c2.fit_logistic(mb.bins())
        pred_h = c2.curtailed_by_hour(d, params, real, curt)
        bm = bench_predictions(mo, P, train)
        for y in test_years:
            sel_h = d.index.year == y
            if "2025-07" in name and y == 2025:
                sel_h &= d.index >= "2025-07-01"
            obs = float(d.loc[sel_h, curt].sum()) / 1e6
            row = {"tech": tech, "scheme": name, "period": f"{y}" + (" (Jul-Dec)" if "2025-07" in name and y == 2025 else (" (Jan-Sep)" if y == 2026 else (" (Apr-Dec)" if (tech == "solar" and y == 2024) else ""))),
                   "fit_L": params[0], "fit_k": params[1], "fit_x0": params[2], "obs_twh": obs, "hourly_twh": float(pred_h[sel_h].sum()) / 1e6}
            mm = mo.index.year == y
            if "2025-07" in name and y == 2025:
                mm &= mo.index >= pd.Period("2025-07", freq="M")
            row["nationalP_twh"] = float(bm.loc[mm, "nationalP"].sum()) / 1e6
            row["time_twh"] = float(bm.loc[mm, "time_trend"].sum()) / 1e6
            for k in ("hourly", "nationalP", "time"):
                row[f"{k}_err_twh"] = row[f"{k}_twh"] - obs
                row[f"{k}_err_pct"] = 100 * (row[f"{k}_twh"] - obs) / obs
            # monthly rate error of the hourly model in the evaluated months
            pm = cm.predict_monthly(d, params, "r", real, curt)
            row["hourly_monthly_rmse_pp"] = 100 * float(np.sqrt(((pm[mm] - mo.C[mm]) ** 2).mean()))
            rows.append(row)
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------------------------- 3 stability
def rate_grid(params: tuple, grid=(20, 30, 40, 50, 60)) -> dict:
    return {f"f({g})": float(cm.logistic_w(g, *params)) for g in grid}


def fit_group(d: pd.DataFrame, real: str, curt: str, L: float, xcol: str = "r", width: float = c2.WIDTH, xmax: float = 102.0, label: str = "") -> dict | None:
    if len(d) < 200 or (d[curt].sum() <= 0):
        return None
    mb = c2.MonthBins(d, real, curt, xcol=xcol, width=width, xmax=xmax)
    b = mb.bins()
    try:
        p = c2.fit_logistic(b, L_fixed=L)
    except Exception:  # noqa: BLE001
        return None
    dd = b[b.hours >= c2.MIN_HOURS]
    w = dd["pot"] / dd["pot"].max()
    sse = float((w * (dd.rate - cm.logistic_w(dd.x, *p)) ** 2).sum())
    return {"group": label, "hours": len(d), "curt_twh": float(d[curt].sum() / 1e6), "k": p[1], "x0": p[2], **rate_grid(p), "bins": len(dd), "sse_w": sse, "_bins": dd, "_params": p}


def equality_test(groups: list[dict], pooled: tuple) -> dict:
    """Weighted F-type test that every group shares the pooled (k, x0) (L pinned): indicative only (binned data, heteroskedastic); the effect size is what matters."""
    sse_sep = sum(g["sse_w"] for g in groups)
    sse_pool = sum(float((g["_bins"]["pot"] / g["_bins"]["pot"].max() * (g["_bins"]["rate"] - cm.logistic_w(g["_bins"]["x"], *pooled)) ** 2).sum()) for g in groups)
    n = sum(g["bins"] for g in groups)
    df1, df2 = 2 * (len(groups) - 1), n - 2 * len(groups)
    F = ((sse_pool - sse_sep) / df1) / (sse_sep / df2)
    return {"F": F, "df1": df1, "df2": df2, "p": float(1 - stats.f.cdf(F, df1, df2))}


def max_gap(g: dict, pooled: tuple, lo: float = 20.0, hi: float = 60.0) -> float:
    """Largest absolute difference (pp of curtailment rate) between the group curve and the pooled curve over r in [lo, hi] clipped to the group's populated support."""
    top = min(hi, float(g["_bins"]["x"].max()))
    x = np.linspace(lo, top, 81)
    return 100 * float(np.abs(cm.logistic_w(x, *g["_params"]) - cm.logistic_w(x, *pooled)).max())


def stability(h: pd.DataFrame, tech: str) -> pd.DataFrame:
    real, curt = c2.TECH[tech]
    d = c2.window(h, c2.TECH_START[tech])
    pooled_all = c2.fit_logistic(c2.MonthBins(d, real, curt).bins())
    L = pooled_all[0]
    pooled = c2.fit_logistic(c2.MonthBins(d, real, curt).bins(), L_fixed=L)
    out = []

    def block(name: str, masks: dict[str, pd.Series]):
        gs = []
        for lab, m in masks.items():
            g = fit_group(d[m], real, curt, L, label=lab)
            if g:
                g["gap_pp"] = max_gap(g, pooled)
                gs.append(g)
        if len(gs) >= 2:
            eq = equality_test(gs, pooled)
            for g in gs:
                out.append({"tech": tech, "dimension": name, **{k: v for k, v in g.items() if not k.startswith("_")}, "F": eq["F"], "F_p": eq["p"]})

    yrs = d.index.year
    block("year", {str(y): pd.Series(yrs == y, index=d.index) for y in sorted(set(yrs)) if (yrs == y).sum() > 24 * 60})
    mon = d.index.month
    block("season (dry May-Oct vs wet Nov-Apr)", {"dry": pd.Series((mon >= 5) & (mon <= 10), index=d.index), "wet": pd.Series((mon >= 11) | (mon <= 4), index=d.index)})
    block("quarter", {f"Q{q}": pd.Series(((mon - 1) // 3 + 1) == q, index=d.index) for q in (1, 2, 3, 4)})
    hr = d.index.hour
    block("hour of day (day 07-17 vs rest)", {"day": pd.Series((hr >= 7) & (hr <= 17), index=d.index), "night/other": pd.Series((hr < 7) | (hr > 17), index=d.index)})
    # bootstrap interval of the pooled curve at r = 40 and of x0 (month resampling)
    bs = c2.bootstrap_params(c2.MonthBins(d, real, curt), BOOT, seed=1)
    out.append({"tech": tech, "dimension": "pooled (free L), month bootstrap", "group": f"L={pooled_all[0]:.2f} k={pooled_all[1]:.3f} x0={pooled_all[2]:.1f}",
                "hours": len(d), "k": pooled_all[1], "x0": pooled_all[2], "f(40)": float(cm.logistic_w(40, *pooled_all)),
                "L_p05": float(np.percentile(bs[:, 0], 5)), "L_p95": float(np.percentile(bs[:, 0], 95)), "x0_p05": float(np.percentile(bs[:, 2], 5)), "x0_p95": float(np.percentile(bs[:, 2], 95)),
                "f40_p05": float(np.percentile(cm.logistic_w(40, bs[:, 0], bs[:, 1], bs[:, 2]), 5)), "f40_p95": float(np.percentile(cm.logistic_w(40, bs[:, 0], bs[:, 1], bs[:, 2]), 95))})
    return pd.DataFrame(out)


def drift_regression(h: pd.DataFrame, tech: str, first_year: int = 0) -> dict:
    """Do binned rates drift with time at a given r? Weighted regression of (bin rate in a year - pooled curve) on year over the populated bins."""
    real, curt = c2.TECH[tech]
    d = c2.window(h, c2.TECH_START[tech])
    pooled = c2.fit_logistic(c2.MonthBins(d, real, curt).bins())
    rows = []
    for y, g in d.groupby(d.index.year):
        if len(g) < 24 * 60 or y < first_year:
            continue
        b = c2.MonthBins(g, real, curt).bins()
        b = b[(b.hours >= 25) & (b.x >= 25) & (b.x <= 55)]
        for _, r in b.iterrows():
            rows.append({"year": y + (0.5 if (tech == "solar" and y == 2024) else 0), "res": r.rate - float(cm.logistic_w(r.x, *pooled)), "w": r.pot})
    df = pd.DataFrame(rows)
    m = sm.WLS(df.res, sm.add_constant(df.year), weights=df.w / df.w.max()).fit()
    return {"tech": tech, "years_from": first_year or "all", "slope_pp_per_year": 100 * float(m.params["year"]), "p": float(m.pvalues["year"]), "n_bins": len(df)}


def subsystem_stability(h: pd.DataFrame) -> pd.DataFrame:
    hp = cm.hourly_panel()
    hp = hp[(hp.ts >= "2022-01-01") & (hp.ts < cm.END_EXCLUSIVE)]
    rsin = h["r"]
    rows = []
    real, curt = c2.TECH["wind"]
    ne = hp[hp["sub"] == "NE"].set_index("ts").sort_index()
    rest = hp[hp["sub"] != "NE"].groupby("ts")[["wind", "curt_wind", "solar_disp", "curt_solar", "load"]].sum()
    for lab, df in (("NE (SIN r)", ne), ("N+S+SE (SIN r)", rest)):
        d = df.join(rsin, how="inner")
        mb = c2.MonthBins(d, real, curt)
        p = c2.fit_logistic(mb.bins())
        pm = cm.predict_monthly(d, p, "r", real, curt)
        obs = d.groupby(d.index.to_period("M"))[curt].sum() / d.groupby(d.index.to_period("M"))[[real, curt]].sum().sum(axis=1)
        rows.append({"tech": "wind", "group": lab, "hours": len(d), "curt_twh": d[curt].sum() / 1e6, "L": p[0], "k": p[1], "x0": p[2], "f(30)": cm.logistic_w(30, *p), "f(40)": cm.logistic_w(40, *p), "f(50)": cm.logistic_w(50, *p),
                     "monthly_R2": 1 - float(((obs - pm) ** 2).sum() / ((obs - obs.mean()) ** 2).sum()), "monthly_RMSE_pp": 100 * float(np.sqrt(((obs - pm) ** 2).mean()))})
    d = ne.copy()
    d["rne"] = 100 * (d.wind + d.curt_wind + d.solar_disp + d.curt_solar) / d["load"]
    mb = c2.MonthBins(d, real, curt, xcol="rne", width=10.0, xmax=400.0)
    try:
        p = c2.fit_logistic(mb.bins())
        pm = cm.predict_monthly(d, p, "rne", real, curt)
        obs = d.groupby(d.index.to_period("M"))[curt].sum() / d.groupby(d.index.to_period("M"))[[real, curt]].sum().sum(axis=1)
        rows.append({"tech": "wind", "group": "NE (own r_NE)", "hours": len(d), "curt_twh": d[curt].sum() / 1e6, "L": p[0], "k": p[1], "x0": p[2], "f(30)": np.nan, "f(40)": np.nan, "f(50)": np.nan,
                     "monthly_R2": 1 - float(((obs - pm) ** 2).sum() / ((obs - obs.mean()) ** 2).sum()), "monthly_RMSE_pp": 100 * float(np.sqrt(((obs - pm) ** 2).mean()))})
    except Exception as e:  # noqa: BLE001
        rows.append({"tech": "wind", "group": f"NE (own r_NE): fit failed ({type(e).__name__})"})
    # solar: NE vs SE with SIN r (2024-04 onward)
    real, curt = c2.TECH["solar"]
    for sub in ("NE", "SE"):
        d = hp[(hp["sub"] == sub) & (hp.ts >= "2024-04-01")].set_index("ts").sort_index().join(rsin, how="inner")
        mb = c2.MonthBins(d, real, curt)
        try:
            p = c2.fit_logistic(mb.bins())
            pm = cm.predict_monthly(d, p, "r", real, curt)
            obs = d.groupby(d.index.to_period("M"))[curt].sum() / d.groupby(d.index.to_period("M"))[[real, curt]].sum().sum(axis=1)
            rows.append({"tech": "solar", "group": f"{sub} (SIN r)", "hours": len(d), "curt_twh": d[curt].sum() / 1e6, "L": p[0], "k": p[1], "x0": p[2], "f(30)": cm.logistic_w(30, *p), "f(40)": cm.logistic_w(40, *p),
                         "f(50)": cm.logistic_w(50, *p), "monthly_R2": 1 - float(((obs - pm) ** 2).sum() / ((obs - obs.mean()) ** 2).sum()), "monthly_RMSE_pp": 100 * float(np.sqrt(((obs - pm) ** 2).mean()))})
        except Exception as e:  # noqa: BLE001
            rows.append({"tech": "solar", "group": f"{sub} (SIN r): fit failed ({type(e).__name__})"})
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------------------------- 4 time confound
def hac_fit(df: pd.DataFrame, cols: list[str], y: str = "C"):
    return sm.OLS(df[y], sm.add_constant(df[cols])).fit(cov_type="HAC", cov_kwds={"maxlags": HAC})


def confound_rows(df: pd.DataFrame, drivers: list[str], label: str) -> list[dict]:
    rows = []
    for x in drivers:
        mx, mt, mxt = hac_fit(df, [x]), hac_fit(df, ["t"]), hac_fit(df, [x, "t"])
        rows.append({"sample": label, "driver": x, "n": len(df), "corr_C": df[x].corr(df.C), "corr_t": df[x].corr(df.t), "partial_C_given_t": c2.partial_corr(df, x, "C", ["t"]),
                     "partial_t_given_x": c2.partial_corr(df, "t", "C", [x]), "R2_x": mx.rsquared, "R2_t": mt.rsquared, "R2_x+t": mxt.rsquared, "dR2_x_over_t": mxt.rsquared - mt.rsquared,
                     "dR2_t_over_x": mxt.rsquared - mx.rsquared, "p_x_given_t": float(mxt.pvalues[x]), "p_t_given_x": float(mxt.pvalues["t"]), "b_t_given_x": float(mxt.params["t"])})
    return rows


def time_confound(h: pd.DataFrame) -> pd.DataFrame:
    rows = []
    # ---- wind, national (57 months) and last 30 months; drivers: hourly-model rates (in-sample and leave-one-year-out), summaries of r, national P
    real, curt = c2.TECH["wind"]
    mo = monthly_obs(h, "wind")
    params = c2.fit_logistic(c2.MonthBins(h, real, curt).bins())
    df = mo[["C", "t"]].copy()
    df["H_insample"] = cm.predict_monthly(h, params, "r", real, curt)
    loy = []
    for y in sorted(set(h.index.year)):
        p_y = c2.fit_logistic(c2.MonthBins(h[h.index.year != y], real, curt).bins())
        sub = h[h.index.year == y]
        loy.append(cm.predict_monthly(sub, p_y, "r", real, curt))
    df["H_leave_year_out"] = pd.concat(loy)
    g = h.groupby(h.index.to_period("M"))["r"]
    df["r_p95"], df["r_mean"] = g.quantile(0.95), g.mean()
    df["P_national"] = national_P(df.index)
    drivers = ["H_insample", "H_leave_year_out", "r_p95", "r_mean", "P_national"]
    rows += confound_rows(df, drivers, "wind national, 57 months")
    rows += confound_rows(df[df.index >= pd.Period("2024-04", freq="M")].assign(t=lambda x: np.arange(len(x))), drivers, "wind national, last 30 months")
    # ---- wind, NE (57 months): own NE curve on SIN r; reference P_NE of Task 11D
    hp = cm.hourly_panel()
    ne = hp[(hp["sub"] == "NE") & (hp.ts >= "2022-01-01") & (hp.ts < cm.END_EXCLUSIVE)].set_index("ts").sort_index().join(h["r"], how="inner")
    pn = c2.fit_logistic(c2.MonthBins(ne, real, curt).bins())
    dn = monthly_obs(ne, "wind")[["C", "t"]].copy()
    dn["H_insample"] = cm.predict_monthly(ne, pn, "r", real, curt)
    loy = []
    for y in sorted(set(ne.index.year)):
        p_y = c2.fit_logistic(c2.MonthBins(ne[ne.index.year != y], real, curt).bins())
        loy.append(cm.predict_monthly(ne[ne.index.year == y], p_y, "r", real, curt))
    dn["H_leave_year_out"] = pd.concat(loy)
    nep = ra.ne_panel()
    nep.index = pd.PeriodIndex(nep["month"], freq="M")
    dn["P_NE"] = nep["P"].reindex(dn.index)
    rows += confound_rows(dn, ["H_insample", "H_leave_year_out", "P_NE"], "wind NE, 57 months (reference: Task 11D P_NE partial 0.14)")
    # ---- solar national (30 months)
    rs, cs = c2.TECH["solar"]
    hs = c2.window(h, c2.TECH_START["solar"])
    ms = monthly_obs(hs, "solar")
    ps = c2.fit_logistic(c2.MonthBins(hs, rs, cs).bins())
    ds = ms[["C", "t"]].copy()
    ds["H_insample"] = cm.predict_monthly(hs, ps, "r", rs, cs)
    loy = []
    for y in sorted(set(hs.index.year)):
        p_y = c2.fit_logistic(c2.MonthBins(hs[hs.index.year != y], rs, cs).bins())
        loy.append(cm.predict_monthly(hs[hs.index.year == y], p_y, "r", rs, cs))
    ds["H_leave_year_out"] = pd.concat(loy)
    g = hs.groupby(hs.index.to_period("M"))["r"]
    ds["r_p95"], ds["r_mean"] = g.quantile(0.95), g.mean()
    ds["P_national"] = national_P(ds.index)
    rows += confound_rows(ds, ["H_insample", "H_leave_year_out", "r_p95", "r_mean", "P_national"], "solar national, 30 months")
    out = pd.DataFrame(rows)
    return out


def residual_drift_controls(h: pd.DataFrame) -> pd.DataFrame:
    """Is the leftover time effect (hourly curve + t) absorbed by system-state covariates? Monthly national wind C ~ H + t + {thermal share, hydro share}."""
    real, curt = c2.TECH["wind"]
    hp = cm.hourly_panel()
    hp = hp[(hp.ts >= "2022-01-01") & (hp.ts < cm.END_EXCLUSIVE)]
    g = hp.groupby(hp.ts.dt.to_period("M"))[["hydro", "thermal", "wind", "solar_disp", "load"]].sum()
    tot = g.hydro + g.thermal + g.wind + g.solar_disp
    mo = monthly_obs(h, "wind")[["C", "t"]].copy()
    params = c2.fit_logistic(c2.MonthBins(h, real, curt).bins())
    mo["H"] = cm.predict_monthly(h, params, "r", real, curt)
    mo["thermal_share"], mo["hydro_share"] = 100 * g.thermal / tot, 100 * g.hydro / tot
    rows = []
    for name, cols in (("H", ["H"]), ("H + t", ["H", "t"]), ("H + thermal_share", ["H", "thermal_share"]), ("H + hydro_share", ["H", "hydro_share"]), ("H + thermal + hydro", ["H", "thermal_share", "hydro_share"]),
                       ("H + t + thermal + hydro", ["H", "t", "thermal_share", "hydro_share"])):
        m = hac_fit(mo, cols)
        rows.append({"model": name, "R2": m.rsquared, "RMSE_pp": 100 * float(np.sqrt((m.resid**2).mean())), **{f"b[{c}]": float(m.params[c]) for c in cols}, **{f"p[{c}]": float(m.pvalues[c]) for c in cols}})
    return pd.DataFrame(rows)


def main() -> None:
    h = cm.sin_hourly("2022-01-01")
    T = cm.tables_dir()
    bt = pd.concat([backtest(h, "wind"), backtest(h, "solar")], ignore_index=True)
    bt.to_csv(T / "task11e2_backtest_annual.csv", index=False)
    cols = ["scheme", "period", "obs_twh", "hourly_twh", "hourly_err_pct", "nationalP_twh", "nationalP_err_pct", "time_twh", "time_err_pct", "hourly_monthly_rmse_pp"]
    for tech in ("wind", "solar"):
        print(f"\n==== {tech}: annual backtest (curtailed TWh, SIN; err % = (pred - obs)/obs) ====")
        print(bt[bt.tech == tech][cols].round(2).to_string(index=False))
    print("\nReference (Task 11D regional wind prototype, 2025): 16.4 TWh predicted vs 26.2 observed (-37.4 %).")

    st = pd.concat([stability(h, "wind"), stability(h, "solar")], ignore_index=True)
    st.to_csv(T / "task11e2_stability.csv", index=False)
    show = ["tech", "dimension", "group", "hours", "curt_twh", "k", "x0", "f(20)", "f(30)", "f(40)", "f(50)", "f(60)", "gap_pp", "F", "F_p"]
    print("\n==== Stability of the hourly curve (L pinned at the pooled value; gap_pp = max |curve - pooled| over r in 20..60 within support) ====")
    print(st[[c for c in show if c in st.columns]].round(3).to_string(index=False))
    print("\nPooled curve, month-bootstrap:\n", st[st.dimension.str.startswith("pooled")].round(3).to_string(index=False))
    dr = pd.DataFrame([drift_regression(h, "wind"), drift_regression(h, "wind", 2023), drift_regression(h, "solar")])
    print("\nDrift of binned yearly rates against the pooled curve (r 25-55):\n", dr.round(4).to_string(index=False))
    dr.to_csv(T / "task11e2_drift.csv", index=False)

    ss = subsystem_stability(h)
    ss.to_csv(T / "task11e2_stability_subsystem.csv", index=False)
    print("\nSubsystem stability (own fit, free L):\n", ss.round(3).to_string(index=False))

    tc = time_confound(h)
    tc.to_csv(T / "task11e2_time_confound.csv", index=False)
    print("\n==== Time-confound test on monthly C (OLS, Newey-West 6 lags) ====")
    print(tc.round(3).to_string(index=False))
    rc = residual_drift_controls(h)
    rc.to_csv(T / "task11e2_residual_drift_controls.csv", index=False)
    print("\nResidual drift vs system-state covariates (national wind C, 57 months):\n", rc.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
