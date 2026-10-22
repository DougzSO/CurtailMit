"""Task 11E-a throwaway analysis (NOT part of the installed package; no src/ change): is the solar curtailment signal hidden in temporal aggregation?

Data availability (11E-a step 1): NO new acquisition was needed. Already in DATABASE_ROOT/raw: ONS balance by subsystem (hourly load, wind, solar), per-plant capacity-factor files
(hourly dispatched solar, D20 basis) and COFF solar curtailment (half-hourly per plant, subsystem-tagged; published from 2024-04). task11e_common.hourly_panel() builds one hourly
subsystem panel from them.

Metrics (all on a POTENTIAL basis = realized + curtailed, so the regressor does not fall when curtailment rises):
  P_nat           monthly national P used in Tasks 7-7D (calibration_frame.P, realized basis)           [the original driver]
  solar_pct       monthly dispatched-solar share of generation (calibration_frame.solar_pct)
  mid_solar_share mean over 10:00-14:59 hours of solar potential / load, SIN        (the "duck-curve" metric)
  mid_vre_share   same with wind + solar potential
  r_p95 / r_max   monthly 95th percentile / max of the hourly SIN potential VRE share of load
Tests: correlation and partial correlation with C_solar (national, 30 months 2024-04..2026-09) controlling for time; HAC regressions; subsystem panel with fixed effects;
hourly dose-response curve and its stability across years; monthly prediction from a fixed hourly curve, including an out-of-sample split.
Run:  python analysis/task11e_solar_intraday.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

sys.path.insert(0, str(Path(__file__).resolve().parent))
import task11d_regional_recalibration as ra
import task11e_common as cm

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 40)
MIDDAY = range(10, 15)
HAC = 4


def monthly_metrics(h: pd.DataFrame, real_w="wind", real_s="solar_disp", cw="curt_wind", cs="curt_solar", load="load") -> pd.DataFrame:
    """Per-month intraday metrics from an hourly frame (any scope: SIN or one subsystem)."""
    d = h.copy()
    d["sol_pot"] = d[real_s] + d[cs]
    d["vre_pot"] = d[real_s] + d[cs] + d[real_w] + d[cw]
    d["r"] = 100 * d["vre_pot"] / d[load]
    mid = d[d.index.hour.isin(MIDDAY)]
    m = d.index.to_period("M")
    mm = mid.index.to_period("M")
    out = pd.DataFrame({"mid_solar_share": 100 * mid.groupby(mm)["sol_pot"].sum() / mid.groupby(mm)[load].sum(), "mid_vre_share": 100 * mid.groupby(mm)["vre_pot"].sum() / mid.groupby(mm)[load].sum(),
                        "r_p95": d.groupby(m)["r"].quantile(0.95), "r_max": d.groupby(m)["r"].max(), "r_mean": d.groupby(m)["r"].mean(),
                        "C_solar_h": d.groupby(m)[cs].sum() / d.groupby(m)["sol_pot"].sum()})
    return out


def national_frame() -> pd.DataFrame:
    f = pd.read_parquet(ra.get_processed_dir() / "calibration_frame.parquet")
    f["month"] = pd.PeriodIndex([pd.Period(year=y, month=m, freq="M") for y, m in zip(f.year, f.month, strict=True)], freq="M")
    f = f.set_index("month")
    f["t"] = np.arange(len(f))
    f["C_solar"] = np.where(f.scope == "wind_solar", f.curt_solar_mwh / (f.solar_gen_mwh + f.curt_solar_mwh), np.nan)
    return f


def pcorr(df, x, y, controls):
    Z = sm.add_constant(df[controls])
    rx, ry = sm.OLS(df[x], Z).fit().resid, sm.OLS(df[y], Z).fit().resid
    return float(np.corrcoef(rx, ry)[0, 1])


def fit_ols(df, cols, y="C_solar"):
    return sm.OLS(df[y], sm.add_constant(df[cols])).fit(cov_type="HAC", cov_kwds={"maxlags": HAC})


def main() -> None:
    nat = national_frame()
    h = cm.sin_hourly("2021-01-01")
    sin = monthly_metrics(h)
    df = nat.join(sin, how="inner")
    s = df[df.scope == "wind_solar"].copy()
    s["t"] = np.arange(len(s))
    print(f"National solar sample: {len(s)} months {s.index.min()}..{s.index.max()}; C_solar {s.C_solar.min():.3f}-{s.C_solar.max():.3f}; check hourly-vs-monthly C_solar: max abs diff {np.abs(s.C_solar_h - s.C_solar).max():.4f}")
    print(s[["P", "solar_pct", "mid_solar_share", "mid_vre_share", "r_p95", "r_max", "C_solar", "t"]].describe().round(2).loc[["min", "max", "mean"]].to_string())

    # ---- 1. correlations and partials
    cols = ["P", "solar_pct", "mid_solar_share", "mid_vre_share", "r_mean", "r_p95", "r_max", "t"]
    tab = pd.DataFrame({c: {"corr_C": s[c].corr(s.C_solar), "spearman_C": s[c].corr(s.C_solar, method="spearman"), "corr_t": s[c].corr(s.t),
                           "partial_C_given_t": pcorr(s, c, "C_solar", ["t"]) if c != "t" else np.nan} for c in cols}).T
    print("\nSolar curtailment rate (national, 30 months) vs candidate drivers:\n", tab.round(3).to_string())
    tab.to_csv(ra.tables_dir() / "task11e_solar_driver_correlations.csv")

    # ---- 2. regressions
    rows = []
    for name, cs in (("t", ["t"]), ("P_nat", ["P"]), ("solar_pct", ["solar_pct"]), ("mid_solar_share", ["mid_solar_share"]), ("mid_vre_share", ["mid_vre_share"]), ("r_p95", ["r_p95"]),
                     ("P_nat + t", ["P", "t"]), ("mid_solar_share + t", ["mid_solar_share", "t"]), ("mid_vre_share + t", ["mid_vre_share", "t"]), ("r_p95 + t", ["r_p95", "t"]), ("r_p95 + P_nat", ["r_p95", "P"])):
        m = fit_ols(s, cs)
        n, k = int(m.nobs), len(m.params)
        row = {"model": name, "n": n, "R2": m.rsquared, "adjR2": m.rsquared_adj, "AIC": n * np.log((m.resid**2).sum() / n) + 2 * k, "RMSE": float(np.sqrt((m.resid**2).mean()))}
        for c in cs:
            row[f"b[{c}]"], row[f"p[{c}]"] = float(m.params[c]), float(m.pvalues[c])
        rows.append(row)
    reg = pd.DataFrame(rows)
    reg.to_csv(ra.tables_dir() / "task11e_solar_regressions.csv", index=False)
    print("\nRegressions of C_solar (OLS, Newey-West 4 lags):\n", reg[["model", "n", "R2", "adjR2", "AIC", "RMSE"] + [c for c in reg.columns if c.startswith(("b[", "p["))]].round(4).to_string())

    # ---- 3. subsystem panel (NE, SE, S) with subsystem fixed effects
    hp = cm.hourly_panel()
    recs = []
    for sub in ("NE", "SE"):  # the South has no centralized solar in the dispatched series (mid_solar_share = 0), so it carries no information
        hs = hp[hp["sub"] == sub].set_index("ts").sort_index()
        hs = hs[hs.index >= "2024-04-01"]
        mt = monthly_metrics(hs)
        mt["C_solar"] = mt["C_solar_h"]
        mt["sub"] = sub
        mt["t"] = np.arange(len(mt))
        mt["solar_share_gen"] = 100 * hs.groupby(hs.index.to_period("M"))["solar_disp"].sum() / hs.groupby(hs.index.to_period("M")).apply(lambda d: (d.hydro + d.thermal + d.wind + d.solar_disp).sum(), include_groups=False)
        recs.append(mt.rename_axis("month").reset_index())
    pan = pd.concat(recs, ignore_index=True)
    pan = pan[(pan.month <= pd.Period("2026-09", freq="M")) & pan["C_solar"].notna() & pan["solar_share_gen"].notna()].copy()
    pan.to_csv(ra.tables_dir() / "task11e_solar_subsystem_panel.csv", index=False)
    print(f"\nSubsystem panel: {len(pan)} obs; mean C_solar by subsystem: {pan.groupby('sub')['C_solar'].mean().round(3).to_dict()}; mid_solar_share range by sub: "
          f"{pan.groupby('sub')['mid_solar_share'].agg(['min', 'max']).round(1).to_dict('index')}")
    fe = pd.get_dummies(pan["sub"], drop_first=True).astype(float)
    for name, cs in (("solar_share_gen", ["solar_share_gen"]), ("mid_solar_share", ["mid_solar_share"]), ("mid_vre_share", ["mid_vre_share"]), ("r_p95", ["r_p95"]),
                     ("mid_solar_share + t", ["mid_solar_share", "t"]), ("r_p95 + t", ["r_p95", "t"]), ("solar_share_gen + t", ["solar_share_gen", "t"])):
        X = sm.add_constant(pd.concat([pan[cs], fe], axis=1))
        m = sm.OLS(pan["C_solar"], X).fit(cov_type="cluster", cov_kwds={"groups": pd.factorize(pan["sub"])[0]})
        # clusters = 3 subsystems: p-values are indicative only; use HAC on pooled residual correlation as a cross-check
        m2 = sm.OLS(pan["C_solar"], X).fit(cov_type="HAC", cov_kwds={"maxlags": 4})
        print(f"  FE panel C_solar ~ {name:24s} R2={m.rsquared:.3f}  " + "  ".join(f"b[{c}]={m.params[c]:.4f} (HAC p={m2.pvalues[c]:.3g})" for c in cs))

    # ---- 4. hourly dose-response for solar (SIN-wide r, 2024-04 onward)
    hh = h[h.index >= "2024-04-01"].copy()
    hh["sol_pot"] = hh.solar_disp + hh.curt_solar
    hh["year"] = hh.index.year
    edges = [0, 15, 20, 25, 30, 35, 40, 45, 50, 60, 100]
    hh["bin"] = pd.cut(hh["r"], edges)
    g = hh.groupby(["bin", "year"], observed=True).apply(lambda d: pd.Series({"rate": 100 * d.curt_solar.sum() / max(d.sol_pot.sum(), 1e-9), "hours": len(d)}), include_groups=False)
    print("\nSolar curtailment rate (% of potential) by hourly SIN VRE share of load and year:\n", g["rate"].unstack("year").round(1).to_string())
    print(g["hours"].unstack("year").fillna(0).astype(int).to_string())
    g["rate"].unstack("year").to_csv(ra.tables_dir() / "task11e_solar_hourly_dose_response_by_year.csv")
    mid = hh[hh.index.hour.isin(MIDDAY)]
    print(f"midday hours: share of solar curtailment {100 * mid.curt_solar.sum() / hh.curt_solar.sum():.1f} % ; solar potential share {100 * mid.sol_pot.sum() / hh.sol_pot.sum():.1f} %")
    by_hour = hh.groupby("hour").apply(lambda d: 100 * d.curt_solar.sum() / max(d.sol_pot.sum(), 1e-9), include_groups=False)
    print("solar curtailment rate by hour of day (%):", by_hour.round(1).to_dict())

    # ---- 5. fixed hourly curve -> monthly prediction (all, and out-of-sample)
    hs_ = h[h.index >= "2024-04-01"].copy()  # h is already cut at 2026-09
    hs_["sol_pot"] = hs_.solar_disp + hs_.curt_solar
    obs = hs_.groupby(hs_.index.to_period("M"))["curt_solar"].sum() / hs_.groupby(hs_.index.to_period("M"))["sol_pot"].sum()
    for label, train in (("all 30 months", None), ("train 2024-04..2025-06 -> test 2025-07..", "2025-06"), ("train 2025-01..2026-09 -> test 2024-04..2024-12", "rev")):
        if train is None:
            trn = hs_
        elif train == "rev":
            trn = hs_[hs_.index >= "2025-01-01"]
        else:
            trn = hs_[hs_.index <= f"{train}-30 23:00"]
        b = cm.binned(trn, "r", "solar_disp", "curt_solar")
        p = cm.fit_binned(b)
        pred = cm.predict_monthly(hs_, p, "r", "solar_disp", "curt_solar")
        d = pd.DataFrame({"obs": obs, "pred": pred})
        if train == "2025-06":
            te = d[d.index >= pd.Period("2025-07", freq="M")]
        elif train == "rev":
            te = d[d.index <= pd.Period("2024-12", freq="M")]
        else:
            te = d
        r2 = 1 - ((te.obs - te.pred) ** 2).sum() / ((te.obs - te.obs.mean()) ** 2).sum()
        print(f"hourly solar curve [{label}]: L={p[0]:.3f} k={p[1]:.3f} x0={p[2]:.1f}; eval n={len(te)} RMSE={np.sqrt(((te.obs - te.pred) ** 2).mean()):.4f} R2={r2:.3f}; mean error (obs-pred) {float((te.obs - te.pred).mean()):.3f}")
        if train is None:
            pd.DataFrame({"obs": obs, "pred": pred}).to_csv(ra.tables_dir() / "task11e_solar_hourly_curve_monthly_prediction.csv")
            pd.DataFrame([{"L": p[0], "k": p[1], "x0": p[2]}]).to_csv(ra.tables_dir() / "task11e_solar_hourly_curve_params.csv", index=False)
    print(f"observed monthly C_solar RMSE of the national P logistic (Task 7D) in-sample for reference: see docs/task9_calibration_report.md; t-only OLS RMSE here: {float(np.sqrt((fit_ols(s, ['t']).resid ** 2).mean())):.4f}")


if __name__ == "__main__":
    main()
