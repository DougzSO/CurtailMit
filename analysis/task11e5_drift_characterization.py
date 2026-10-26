"""Task 11E5-a throwaway analysis (NOT part of the installed package; no src/ change): characterise and quantify the residual wind curtailment drift of the hourly model (option E).

Residual = observed minus predicted wind curtailment rate (pp of potential) of the pooled hourly curve fitted on the full 2022-01..2026-09 sample (in sample, so the pooled curve is the best case for the drift:
whatever trend survives is not an out-of-sample artefact). Steps: (1) residual by calendar year and its trend over the 57 months with Newey-West and moving-block-bootstrap intervals (all months and excluding 2022, the outlier first year);
(2) WHERE the drift sits: yearly observed rate by class of r and its slope (the drift at fixed r); (3) compounding to 2030 / 2040 / 2050 under explicit assumptions (linear, saturating, none), applied to the PTE-scaled hourly projection with the
rate capped at the asymptote L (a rate cannot exceed it); (4) NE vs the rest of the system.
Run:  python analysis/task11e5_drift_characterization.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

sys.path.insert(0, str(Path(__file__).resolve().parent))
import task11e2_common as c2
import task11e_common as cm

pd.set_option("display.width", 230)
pd.set_option("display.max_columns", 50)
HAC = 6
REAL, CURT = c2.TECH["wind"]
BINS_R = [0, 15, 20, 25, 30, 35, 40, 45, 50, 60, 100]


def monthly_residual(h: pd.DataFrame, params: tuple) -> pd.DataFrame:
    g = h.groupby(h.index.to_period("M"))
    pot = g[[REAL, CURT]].sum().sum(axis=1)
    obs = g[CURT].sum() / pot
    pred = cm.predict_monthly(h, params, "r", REAL, CURT)
    out = pd.DataFrame({"pot": pot, "obs": obs, "pred": pred})
    out["res_pp"] = 100 * (out.obs - out.pred)
    out["t_years"] = (out.index.year - 2022) + (out.index.month - 0.5) / 12
    return out


def trend_with_ci(df: pd.DataFrame, col: str = "res_pp", n_boot: int = 2000, block: int = 6, seed: int = 8) -> dict:
    """Slope of the monthly residual on time (pp per year) with Newey-West, OLS and moving-block-bootstrap 95 % intervals."""
    X = sm.add_constant(df[["t_years"]])
    m = sm.OLS(df[col], X).fit(cov_type="HAC", cov_kwds={"maxlags": HAC})
    ci = m.conf_int().loc["t_years"].to_numpy()
    rng = np.random.default_rng(seed)
    y, t = df[col].to_numpy(), df["t_years"].to_numpy()
    n = len(y)
    starts = np.arange(n - block + 1)
    slopes = []
    for _ in range(n_boot):
        idx = np.concatenate([np.arange(s, s + block) for s in rng.choice(starts, int(np.ceil(n / block)))])[:n]
        tt, yy = t[idx], y[idx]
        slopes.append(np.polyfit(tt, yy, 1)[0])
    return {"n": n, "slope_pp_per_year": float(m.params["t_years"]), "NW_CI_lo": float(ci[0]), "NW_CI_hi": float(ci[1]), "NW_p": float(m.pvalues["t_years"]), "boot_CI_lo": float(np.percentile(slopes, 2.5)),
            "boot_CI_hi": float(np.percentile(slopes, 97.5)), "intercept_at_2026": float(m.params["const"] + m.params["t_years"] * 4.5)}


def annual_table(h: pd.DataFrame, params: tuple) -> pd.DataFrame:
    pot = (h[REAL] + h[CURT]).to_numpy()
    pred = pd.Series(cm.logistic_w(h["r"].to_numpy(), *params) * pot, index=h.index)
    rows = []
    for y, g in h.groupby(h.index.year):
        p = float(pot[h.index.year == y].sum())
        obs, pr = float(g[CURT].sum()), float(pred[h.index.year == y].sum())
        rows.append({"year": y, "obs_twh": obs / 1e6, "pred_twh": pr / 1e6, "resid_twh": (obs - pr) / 1e6, "obs_rate_pct": 100 * obs / p, "pred_rate_pct": 100 * pr / p, "resid_pp": 100 * (obs - pr) / p})
    return pd.DataFrame(rows)


def drift_by_r(h: pd.DataFrame) -> pd.DataFrame:
    """Observed wind curtailment rate (pct of potential) by class of r and year; slope per class over the years with >= 25 hours per cell (weighted by potential)."""
    d = h.copy()
    d["pot"] = d[REAL] + d[CURT]
    d["bin"] = pd.cut(d["r"], BINS_R)
    d["year"] = d.index.year
    g = d.groupby(["bin", "year"], observed=True).agg(curt=(CURT, "sum"), pot=("pot", "sum"), hours=("r", "size"))
    g["rate_pct"] = 100 * g.curt / g.pot
    rows = []
    for b, sub in g.groupby(level=0, observed=True):
        s = sub.reset_index()
        s = s[(s.hours >= 25) & (s.year >= 2023)]
        row = {"r_class": str(b)}
        for _, r in sub.reset_index().iterrows():
            row[f"rate_{int(r.year)}"] = r.rate_pct
            row[f"hours_{int(r.year)}"] = r.hours
        if s.year.nunique() >= 3:
            m = sm.WLS(s.rate_pct, sm.add_constant(s.year), weights=s.pot / s.pot.max()).fit()
            row["slope_pp_per_year_2023on"] = float(m.params["year"])
            row["slope_p"] = float(m.pvalues["year"])
            row["slope_CI_lo"], row["slope_CI_hi"] = (float(x) for x in m.conf_int().loc["year"])
        rows.append(row)
    return pd.DataFrame(rows)


def compounding(h: pd.DataFrame, params: tuple, slope: float) -> pd.DataFrame:
    """Effect on the projected wind curtailment of an additive rate drift delta(year) pp (relative to 2026), capped so that rate <= L; central curve, phi = 1, PTE-scaled 2025 profile."""
    prof = c2.base_profile(h)
    pte = c2.load_pte()
    L = params[0]
    rows = []
    for sc in c2.SCENARIOS:
        for year in c2.YEARS:
            f = c2.scale_factors(pte, sc, year)
            r = c2.projected_r(prof, f)
            pot = prof["W"] * f["a_wind"]
            base = cm.logistic_w(r, *params)
            dt = year - 2026
            variants = {"none": 0.0, "linear": slope * dt, "saturating tau=3": slope * 3 * (1 - np.exp(-dt / 3)), "saturating tau=6": slope * 6 * (1 - np.exp(-dt / 6)), "saturating tau=12": slope * 12 * (1 - np.exp(-dt / 12))}
            for name, delta_pp in variants.items():
                rate_u = float(((np.minimum(base + delta_pp / 100, L)) * pot).sum() / pot.sum())
                rows.append({"scenario": sc, "year": year, "assumption": name, "delta_pp": delta_pp, "base_rate_pct": 100 * float((base * pot).sum() / pot.sum()), "rate_pct": 100 * rate_u, "wind_twh": rate_u * f["wind_gen_twh"],
                             "extra_twh": (rate_u - float((base * pot).sum() / pot.sum())) * f["wind_gen_twh"], "headroom_to_L_pp": 100 * (L - float((base * pot).sum() / pot.sum()))})
    return pd.DataFrame(rows)


def subsystem_residuals(h: pd.DataFrame, params: tuple) -> pd.DataFrame:
    hp = cm.hourly_panel()
    hp = hp[(hp.ts >= "2022-01-01") & (hp.ts < cm.END_EXCLUSIVE)]
    rows = []
    for lab, df in (("NE", hp[hp["sub"] == "NE"].set_index("ts")), ("N+S+SE", hp[hp["sub"] != "NE"].groupby("ts")[["wind", "curt_wind"]].sum())):
        d = df.join(h["r"], how="inner")
        # own pooled curve of the group (so that the residual measures drift, not a level offset)
        p = c2.fit_logistic(c2.MonthBins(d, REAL, CURT).bins())
        mr = monthly_residual(d, p)
        for lab2, sub in (("2022-26", mr), ("2023-26", mr[mr.index.year >= 2023])):
            tr = trend_with_ci(sub, n_boot=500)
            rows.append({"group": lab, "window": lab2, "curt_twh_total": float(d[CURT].sum() / 1e6), **{k: v for k, v in tr.items() if k in ("n", "slope_pp_per_year", "NW_CI_lo", "NW_CI_hi", "NW_p", "boot_CI_lo", "boot_CI_hi")}})
    return pd.DataFrame(rows)


def main() -> None:
    h = cm.sin_hourly("2022-01-01")
    T = cm.tables_dir()
    params = c2.fit_logistic(c2.MonthBins(h, REAL, CURT).bins())
    print(f"pooled wind curve: L={params[0]:.3f} k={params[1]:.3f} x0={params[2]:.1f}")
    ann = annual_table(h, params)
    ann.to_csv(T / "task11e5_residual_by_year.csv", index=False)
    print("\nResidual by year (SIN wind):\n", ann.round(2).to_string(index=False))
    mr = monthly_residual(h, params)
    mr.to_csv(T / "task11e5_monthly_residual.csv")
    res = []
    for lab, d in (("all 57 months", mr), ("2023-01..2026-09 (46 months)", mr[mr.index.year >= 2023]), ("2024-01..2026-09 (33 months)", mr[mr.index.year >= 2024])):
        res.append({"window": lab, **trend_with_ci(d)})
    tr = pd.DataFrame(res)
    tr.to_csv(T / "task11e5_drift_trend.csv", index=False)
    print("\nTrend of the monthly residual (pp of rate per year), 95 % intervals:\n", tr.round(3).to_string(index=False))

    byr = drift_by_r(h)
    byr.to_csv(T / "task11e5_drift_by_r.csv", index=False)
    cols = ["r_class"] + [c for c in byr.columns if c.startswith("rate_")] + ["slope_pp_per_year_2023on", "slope_CI_lo", "slope_CI_hi", "slope_p"]
    print("\nObserved wind curtailment rate (% of potential) by class of r and year, and the slope of the drift at fixed r (2023-26, pp / year):\n", byr[[c for c in cols if c in byr.columns]].round(2).to_string(index=False))

    slope = float(tr.loc[tr.window.str.startswith("2023"), "slope_pp_per_year"].iloc[0])
    comp = compounding(h, params, slope)
    comp.to_csv(T / "task11e5_compounding.csv", index=False)
    print(f"\nCompounding of an additive drift of {slope:.2f} pp/year (central slope 2023-26), capped at L = {params[0]:.2f}; wind TWh and extra TWh vs no drift:")
    print(comp[comp.year.isin([2040, 2050])].pivot_table(index=["scenario", "year", "base_rate_pct", "headroom_to_L_pp"], columns="assumption", values="extra_twh").round(1).to_string())
    naive = {"naive scalar 2025->2050 at slope": 25 * slope, "naive scalar 2026->2050": 24 * slope}
    print("naive uncapped scalar compounding (pp):", {k: round(v, 1) for k, v in naive.items()}, " with the 95 % interval of the slope:", [round(24 * x, 1) for x in (tr.loc[tr.window.str.startswith('2023'), 'NW_CI_lo'].iloc[0], tr.loc[tr.window.str.startswith('2023'), 'NW_CI_hi'].iloc[0])])

    sub = subsystem_residuals(h, params)
    sub.to_csv(T / "task11e5_drift_subsystem.csv", index=False)
    print("\nDrift by subsystem group (own pooled curve):\n", sub.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
