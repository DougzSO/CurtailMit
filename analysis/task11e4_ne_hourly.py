"""Task 11E4-b throwaway analysis (NOT part of the installed package; no src/ change): does a NORTHEAST hourly driver extend the in-sample support toward 2050 conditions?

Data: the hourly subsystem panel of Task 11E (ONS balance + dispatched solar + COFF curtailment), subsystem NE only, 2022-01..2026-09; nothing re-acquired.
Driver: r_NE = (NE wind + solar + NE curtailed) / NE load (%). NE exports most of its VRE (balance export is the difference), so r_NE is routinely above 100 % (median ~128 %); its level is not comparable with the SIN-wide r,
only its relative position within its own observed range is.
Steps: (1) distribution of r_NE against the SIN-wide r (extreme / median ratios, upper quantiles); (2) refit of the dose-response of NE wind (2022+) and NE solar (2024-04+) on r_NE with the 11E2-b validation discipline
(annual backtest, leave-one-year-out and trained-on-2022-24 schemes against the SIN-r curve applied to the same NE targets; stability by year; time-confound test); (3) in-sample coverage of the PTE 2030/2040/2050 conditions with the
Task 11D-0 / 11E proxy (NE keeps its 2025 share of every PTE total: NE hours scale like the SIN ones, wind x W_t/W_2025, solar x S_t/S_2025, load x T_t/T_2025) against r_NE's own populated support (>= 15 hours per 10-pp bin).
Run:  python analysis/task11e4_ne_hourly.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import task11e2_backtest as bt
import task11e2_common as c2
import task11e_common as cm

pd.set_option("display.width", 230)
pd.set_option("display.max_columns", 50)
WIDTH, XMAX = 10.0, 400.0
TECHS = {"wind": ("wind", "curt_wind", "2022-01-01"), "solar": ("solar_disp", "curt_solar", "2024-04-01")}


def ne_frame(h_sin: pd.DataFrame) -> pd.DataFrame:
    hp = cm.hourly_panel()
    ne = hp[(hp["sub"] == "NE") & (hp.ts >= "2022-01-01") & (hp.ts < cm.END_EXCLUSIVE)].set_index("ts").sort_index().copy()
    ne["rne"] = 100 * (ne.wind + ne.curt_wind + ne.solar_disp + ne.curt_solar) / ne["load"]
    ne["r"] = h_sin["r"].reindex(ne.index)
    return ne


def distribution(ne: pd.DataFrame, h_sin: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for lab, s in (("SIN r", h_sin["r"]), ("NE r_NE", ne["rne"])):
        q = s.quantile([0.5, 0.95, 0.99, 0.999])
        rows.append({"metric": lab, "mean": s.mean(), "p50": q[0.5], "p95": q[0.95], "p99": q[0.99], "p999": q[0.999], "max": s.max(), "max_over_p50": s.max() / q[0.5], "p999_over_p50": q[0.999] / q[0.5],
                     "p95_2025": s[s.index.year == 2025].quantile(0.95), "max_2025": s[s.index.year == 2025].max()})
    return pd.DataFrame(rows)


def fit_curve(d: pd.DataFrame, real: str, curt: str, xcol: str, mask_months: np.ndarray | None = None) -> tuple[tuple, float, c2.MonthBins]:
    width, xmax = (WIDTH, XMAX) if xcol == "rne" else (c2.WIDTH, 102.0)
    mb = c2.MonthBins(d, real, curt, xcol=xcol, width=width, xmax=xmax)
    b = mb.bins(None if mask_months is None else mask_months.astype(float))
    return c2.fit_logistic(b), c2.r_cap_of(b, c2.MIN_HOURS), mb


def annual_backtest(ne: pd.DataFrame, tech: str) -> pd.DataFrame:
    real, curt, start = TECHS[tech]
    d = c2.window(ne, start)
    months = pd.PeriodIndex(sorted(set(d.index.to_period("M"))))
    yr = pd.Series(months.year, index=months)
    schemes = [("in sample", yr > 0, sorted(set(yr)))]
    if tech == "wind":
        schemes += [("train 2022-24", yr <= 2024, [2025, 2026]), ("leave-one-year-out 2025", yr != 2025, [2025]), ("leave-one-year-out 2024", yr != 2024, [2024])]
    else:
        schemes += [("train 2024-04..2025-06", pd.Series(months <= pd.Period("2025-06", freq="M"), index=months), [2025, 2026]), ("leave-one-year-out 2025", yr != 2025, [2025])]
    rows = []
    for name, train, years in schemes:
        for xcol in ("rne", "r"):
            tr_months = months[train.to_numpy()]
            mask = np.isin(months, tr_months)
            params, cap, mb = fit_curve(d, real, curt, xcol, mask)
            f = cm.logistic_w(d[xcol].to_numpy(), *params)
            pred = pd.Series(f * (d[real] + d[curt]).to_numpy(), index=d.index)
            for y in years:
                sel = d.index.year == y
                obs = float(d.loc[sel, curt].sum() / 1e6)
                if obs <= 0:
                    continue
                p = float(pred[sel].sum() / 1e6)
                rows.append({"tech": tech, "scheme": name, "driver": "r_NE" if xcol == "rne" else "SIN r", "year": y, "obs_twh": obs, "pred_twh": p, "err_pct": 100 * (p - obs) / obs, "L": params[0], "k": params[1], "x0": params[2], "r_cap": cap})
    return pd.DataFrame(rows)


def stability_by_year(ne: pd.DataFrame, tech: str) -> pd.DataFrame:
    real, curt, start = TECHS[tech]
    d = c2.window(ne, start)
    p_all, _, _ = fit_curve(d, real, curt, "rne")
    pooled = c2.fit_logistic(c2.MonthBins(d, real, curt, xcol="rne", width=WIDTH, xmax=XMAX).bins(), L_fixed=p_all[0])
    lo, hi = float(d["rne"].quantile(0.25)), float(d["rne"].quantile(0.99))
    rows = []
    for y, g in d.groupby(d.index.year):
        if len(g) < 24 * 60:
            continue
        gp = bt.fit_group(g, real, curt, p_all[0], xcol="rne", width=WIDTH, xmax=XMAX, label=str(y))
        if gp is None:
            continue
        top = min(hi, float(gp["_bins"]["x"].max()))
        x = np.linspace(lo, top, 81)
        rows.append({"tech": tech, "year": y, "k": gp["k"], "x0": gp["x0"], "gap_pp_over_q25_q99": 100 * float(np.abs(cm.logistic_w(x, *gp["_params"]) - cm.logistic_w(x, *pooled)).max()), "curt_twh": gp["curt_twh"]})
    return pd.DataFrame(rows)


def time_confound(ne: pd.DataFrame) -> pd.DataFrame:
    real, curt, _ = TECHS["wind"]
    mo = bt.monthly_obs(ne, "wind")[["C", "t"]].copy()
    out = {}
    for xcol, lab in (("rne", "r_NE"), ("r", "SIN r")):
        p, _, _ = fit_curve(ne, real, curt, xcol)
        mo[f"H_{lab}"] = cm.predict_monthly(ne, p, xcol, real, curt)
        loy = []
        for y in sorted(set(ne.index.year)):
            tr = ne[ne.index.year != y]
            py, _, _ = fit_curve(tr, real, curt, xcol)
            loy.append(cm.predict_monthly(ne[ne.index.year == y], py, xcol, real, curt))
        mo[f"H_{lab}_loyo"] = pd.concat(loy)
    g = ne.groupby(ne.index.to_period("M"))["rne"]
    mo["rne_p95"] = g.quantile(0.95)
    return pd.DataFrame(bt.confound_rows(mo, ["H_r_NE", "H_r_NE_loyo", "H_SIN r", "H_SIN r_loyo", "rne_p95"], "NE wind, 57 months"))


def coverage(ne: pd.DataFrame, h_sin: pd.DataFrame) -> pd.DataFrame:
    pte = c2.load_pte()
    b = ne[ne.index.year == 2025]
    W, S, LD = (b.wind + b.curt_wind).to_numpy(), (b.solar_disp + b.curt_solar).to_numpy(), b["load"].to_numpy()
    rows = []
    sin_prof = c2.base_profile(h_sin)
    for tech, (real, curt, start) in TECHS.items():
        d = c2.window(ne, start)
        pne, cap_ne, _ = fit_curve(d, real, curt, "rne")
        ds = c2.window(h_sin, start)
        psin, cap_sin, _ = fit_curve(ds, real, curt, "r")
        rne_max, sin_max = float(d["rne"].max()), float(ds["r"].max())
        for sc in c2.SCENARIOS:
            for year in (2030, 2040, 2050):
                f = c2.scale_factors(pte, sc, year)
                rne = 100 * (f["a_wind"] * W + f["a_solar"] * S) / (f["a_load"] * LD)
                pot_ne = (W if tech == "wind" else S) * (f["a_wind"] if tech == "wind" else f["a_solar"])
                curve_ne = cm.logistic_w(rne, *pne) * pot_ne
                rs = c2.projected_r(sin_prof, f)
                pot_s = sin_prof["W" if tech == "wind" else "S"] * (f["a_wind"] if tech == "wind" else f["a_solar"])
                curve_s = cm.logistic_w(rs, *psin) * pot_s
                rows.append({"tech": tech, "scenario": sc, "year": year,
                             "NE_hours_inside_support": float((rne <= cap_ne).mean()), "NE_hours_inside_max": float((rne <= rne_max).mean()), "NE_curt_beyond_support": float(curve_ne[rne > cap_ne].sum() / curve_ne.sum()),
                             "SIN_hours_inside_support": float((rs <= cap_sin).mean()), "SIN_hours_inside_max": float((rs <= sin_max).mean()), "SIN_curt_beyond_support": float(curve_s[rs > cap_sin].sum() / curve_s.sum()),
                             "NE_p95_over_support": float(np.percentile(rne, 95) / cap_ne), "SIN_p95_over_support": float(np.percentile(rs, 95) / cap_sin), "NE_cap": cap_ne, "SIN_cap": cap_sin, "NE_obs_max": rne_max, "SIN_obs_max": sin_max})
    return pd.DataFrame(rows)


def main() -> None:
    h = cm.sin_hourly("2022-01-01")
    T = cm.tables_dir()
    ne = ne_frame(h)
    print(f"NE hourly frame: {len(ne)} h {ne.index.min()}..{ne.index.max()}")
    dist = distribution(ne, h)
    dist.to_csv(T / "task11e4_ne_distribution.csv", index=False)
    print("\nDistribution of r_NE vs the SIN-wide r (%):\n", dist.round(2).T.to_string())

    bts = pd.concat([annual_backtest(ne, "wind"), annual_backtest(ne, "solar")], ignore_index=True)
    bts.to_csv(T / "task11e4_ne_backtest.csv", index=False)
    print("\nAnnual backtest on NE targets (curtailed TWh; err % = (pred - obs) / obs), driver r_NE vs SIN r:\n", bts.pivot_table(index=["tech", "scheme", "year", "obs_twh"], columns="driver", values="err_pct").round(1).to_string())
    fit_tab = bts[bts.scheme == "in sample"].drop_duplicates(["tech", "driver"])[["tech", "driver", "L", "k", "x0", "r_cap"]]
    print("\nIn-sample curves:\n", fit_tab.round(3).to_string(index=False))

    stab = pd.concat([stability_by_year(ne, "wind"), stability_by_year(ne, "solar")], ignore_index=True)
    stab.to_csv(T / "task11e4_ne_stability.csv", index=False)
    print("\nStability of the r_NE curve by year (L pinned):\n", stab.round(3).to_string(index=False))

    tc = time_confound(ne)
    tc.to_csv(T / "task11e4_ne_time_confound.csv", index=False)
    print("\nTime-confound test (NE wind, monthly C):\n", tc[["driver", "corr_C", "partial_C_given_t", "R2_x", "R2_x+t", "dR2_x_over_t", "p_t_given_x"]].round(3).to_string(index=False))

    cov = coverage(ne, h)
    cov.to_csv(T / "task11e4_ne_coverage.csv", index=False)
    show = cov[cov.year.isin([2040, 2050])]
    print("\nIn-sample coverage, NE-hourly (r_NE, own support) vs SIN-wide hourly (r, own support):\n",
          show[["tech", "scenario", "year", "NE_hours_inside_support", "SIN_hours_inside_support", "NE_curt_beyond_support", "SIN_curt_beyond_support", "NE_hours_inside_max", "SIN_hours_inside_max", "NE_p95_over_support", "SIN_p95_over_support"]].round(3).to_string(index=False))
    print("\nSupport edges (%):", cov.drop_duplicates("tech")[["tech", "NE_cap", "NE_obs_max", "SIN_cap", "SIN_obs_max"]].round(1).to_dict("records"))


if __name__ == "__main__":
    main()
