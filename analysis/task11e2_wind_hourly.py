"""Task 11E2-c throwaway analysis (NOT part of the installed package; no src/ change): the hourly VRE-share-of-load dose-response for WIND, versus solar, and a unified driver.

1. Wind and solar curves side by side (free L, month-resampling bootstrap; paired differences on the common 2024-04..2026-09 window).
2. Wind 2030/2040/2050 projection from the hourly curve (central = free L; low = r capped at the populated support; high = L pinned at 1; bootstrap p05-p95 of the central curve)
   compared with the Task 11B national extrapolation, the Task 11D regional point estimate and the Task 11E envelope; flexibility sensitivity r/phi; share of the projected curtailment
   coming from hours outside the populated support (11E2-a).
3. Unified driver: ONE curve for total VRE curtailment (wind + solar potential) vs r, fitted on 2024-04..2026-09; compared with the sum of the two technology curves on the monthly total,
   the annual total, and the wind/solar split (technology accounting is still needed downstream for the OM/CM split).
Run (after task11e_wind_envelope.py and task11e2_insample_coverage.py):  python analysis/task11e2_wind_hourly.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import task11e2_common as c2
import task11e_common as cm

pd.set_option("display.width", 230)
pd.set_option("display.max_columns", 50)
BOOT = 300
PHI = (1.0, 1.25, 1.5)
GRID = (20, 30, 40, 50, 60, 70)


def curve_table(h: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    common = c2.window(h, "2024-04-01")
    specs = {"wind (2022-01..2026-09)": (h, *c2.TECH["wind"]), "wind (2024-04..2026-09, solar window)": (common, *c2.TECH["wind"]), "solar (2024-04..2026-09)": (common, *c2.TECH["solar"])}
    rows, fits = [], {}
    for name, (d, real, curt) in specs.items():
        mb = c2.MonthBins(d, real, curt)
        p = c2.fit_logistic(mb.bins())
        bs = c2.bootstrap_params(mb, BOOT, seed=7)
        row = {"curve": name, "L": p[0], "k": p[1], "x0": p[2], "L_p05": np.percentile(bs[:, 0], 5), "L_p95": np.percentile(bs[:, 0], 95), "k_p05": np.percentile(bs[:, 1], 5), "k_p95": np.percentile(bs[:, 1], 95),
               "x0_p05": np.percentile(bs[:, 2], 5), "x0_p95": np.percentile(bs[:, 2], 95), "r_cap15": c2.r_cap_of(mb.bins(), 15)}
        for g in GRID:
            row[f"f({g})"] = float(cm.logistic_w(g, *p))
        # r at which the curve reaches 10 % / 50 % of its asymptote
        row["r_at_10pct_of_L"] = p[2] + np.log(0.1 / 0.9) / p[1]
        row["r_at_50pct_of_L"] = p[2]
        row["r_at_90pct_of_L"] = p[2] + np.log(0.9 / 0.1) / p[1]
        rows.append(row)
        fits[name] = (p, mb, bs)
    return pd.DataFrame(rows), fits


def paired_difference(h: pd.DataFrame, n: int = BOOT) -> pd.DataFrame:
    """Wind minus solar curve on the common window, same bootstrap draws of months (so the difference interval is paired)."""
    d = c2.window(h, "2024-04-01")
    mw, ms = c2.MonthBins(d, *c2.TECH["wind"]), c2.MonthBins(d, *c2.TECH["solar"])
    rng = np.random.default_rng(11)
    nm = len(mw.months)
    diffs = []
    for _ in range(n):
        w = np.bincount(rng.integers(0, nm, nm), minlength=nm).astype(float)
        try:
            pw, ps = c2.fit_logistic(mw.bins(w)), c2.fit_logistic(ms.bins(w))
        except Exception:  # noqa: BLE001
            continue
        diffs.append([cm.logistic_w(g, *pw) - cm.logistic_w(g, *ps) for g in GRID] + [pw[0] - ps[0], pw[2] - ps[2]])
    a = np.array(diffs)
    p0w, p0s = c2.fit_logistic(mw.bins()), c2.fit_logistic(ms.bins())
    rows = []
    for j, g in enumerate(list(GRID) + ["L", "x0"]):
        pt = (cm.logistic_w(g, *p0w) - cm.logistic_w(g, *p0s)) if isinstance(g, int) else ((p0w[0] - p0s[0]) if g == "L" else (p0w[2] - p0s[2]))
        rows.append({"quantity": f"wind - solar at r={g}" if isinstance(g, int) else f"wind - solar {g}", "point": pt, "p05": np.percentile(a[:, j], 5), "p95": np.percentile(a[:, j], 95)})
    return pd.DataFrame(rows)


def projection(h: pd.DataFrame, fits: dict, cov: pd.DataFrame) -> pd.DataFrame:
    prof = c2.base_profile(h)
    pte = c2.load_pte()
    pw, mbw, bsw = fits["wind (2022-01..2026-09)"]
    p_hi = c2.fit_logistic(mbw.bins(), L_fixed=1.0)
    cap = c2.r_cap_of(mbw.bins(), 15)
    pw24, _, _ = fits["wind (2024-04..2026-09, solar window)"]
    d11b = c2.load_pte().set_index(["scenario", "year"])
    d11d = pd.read_csv(cm.tables_dir() / "task11d_projection_regional_proxy.csv")
    d11d = d11d[d11d.proxy.str.startswith("NE_wind_share=2025")].set_index(["scenario", "year"])
    d11e = pd.read_csv(cm.tables_dir() / "task11e_wind_envelope.csv").set_index(["scenario", "year"])
    rows = []
    for sc in c2.SCENARIOS:
        for year in c2.YEARS:
            f = c2.scale_factors(pte, sc, year)
            pot = prof["W"] * f["a_wind"]
            gen = f["wind_gen_twh"]
            for phi in PHI:
                r = c2.projected_r(prof, f, phi)
                row = {"scenario": sc, "year": year, "phi": phi, "wind_pte_twh": gen, "r_mean": r.mean(), "share_hours_beyond_cap": float((r > cap).mean())}
                row["central_rate"] = c2.projected_rate(r, pot, pw)
                row["low_rate"] = c2.projected_rate(r, pot, pw, r_cap=cap)
                row["high_rate"] = c2.projected_rate(r, pot, p_hi)
                row["window2024_rate"] = c2.projected_rate(r, pot, pw24)
                bt = np.array([c2.projected_rate(r, pot, tuple(b)) for b in bsw])
                row["boot_p05_rate"], row["boot_p50_rate"], row["boot_p95_rate"] = np.percentile(bt, [5, 50, 95])
                for k in ("central", "low", "high", "window2024", "boot_p05", "boot_p50", "boot_p95"):
                    row[f"wind_{k}_twh"] = row[f"{k}_rate"] * gen
                row["curt_share_beyond_cap"] = float((cm.logistic_w(r, *pw) * pot)[r > cap].sum() / (cm.logistic_w(r, *pw) * pot).sum())
                if phi == 1.0:
                    key = (sc, year)
                    row["11B_national_low"], row["11B_national_central"], row["11B_national_high"] = (d11b.loc[key, f"wind_curtailed_twh_{k}"] for k in ("low", "central", "high"))
                    row["11D_regional_central"], row["11D_regional_lo"], row["11D_regional_hi"] = d11d.loc[key, "wind_curtailed_twh_regional"], d11d.loc[key, "wind_curtailed_twh_regional_lo"], d11d.loc[key, "wind_curtailed_twh_regional_hi"]
                    row["11E_envelope_low"], row["11E_envelope_central"], row["11E_envelope_high"] = d11e.loc[key, "low_capacity_grounded"], d11e.loc[key, "central"], d11e.loc[key, "high"]
                    row["11E_envelope_low_statistical"] = d11e.loc[key, "low_statistical"]
                rows.append(row)
    return pd.DataFrame(rows)


def unified(h: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    d = c2.window(h, "2024-04-01").copy()
    d["vre_real"] = d.wind + d.solar_disp
    d["curt_vre"] = d.curt_wind + d.curt_solar
    out = {}
    pu = c2.fit_logistic(c2.MonthBins(d, "vre_real", "curt_vre").bins())
    pw = c2.fit_logistic(c2.MonthBins(d, *c2.TECH["wind"]).bins())
    ps = c2.fit_logistic(c2.MonthBins(d, *c2.TECH["solar"]).bins())
    out["params"] = {"unified": pu, "wind_same_window": pw, "solar": ps}
    # annual: in-sample and leave-one-year-out for the totals and the technology split
    rows = []
    for scheme, years in (("in-sample", sorted(set(d.index.year))), ("leave-one-year-out", sorted(set(d.index.year)))):
        for y in years:
            tr = d if scheme == "in-sample" else d[d.index.year != y]
            pu_, pw_, ps_ = (c2.fit_logistic(c2.MonthBins(tr, a, b).bins()) for a, b in (("vre_real", "curt_vre"), c2.TECH["wind"], c2.TECH["solar"]))
            te = d[d.index.year == y]
            obs_w, obs_s = te.curt_wind.sum() / 1e6, te.curt_solar.sum() / 1e6
            pot_w, pot_s = (te.wind + te.curt_wind), (te.solar_disp + te.curt_solar)
            sep_w = float((cm.logistic_w(te.r, *pw_) * pot_w).sum() / 1e6)
            sep_s = float((cm.logistic_w(te.r, *ps_) * pot_s).sum() / 1e6)
            uni_rate = cm.logistic_w(te.r, *pu_)
            uni_w, uni_s = float((uni_rate * pot_w).sum() / 1e6), float((uni_rate * pot_s).sum() / 1e6)
            uni_tot = float((uni_rate * (pot_w + pot_s)).sum() / 1e6)
            rows.append({"scheme": scheme, "year": y, "obs_wind": obs_w, "obs_solar": obs_s, "obs_total": obs_w + obs_s, "separate_wind": sep_w, "separate_solar": sep_s, "separate_total": sep_w + sep_s,
                         "unified_total": uni_tot, "unified_wind_assigned": uni_w, "unified_solar_assigned": uni_s,
                         "err_pct_total_separate": 100 * (sep_w + sep_s - obs_w - obs_s) / (obs_w + obs_s), "err_pct_total_unified": 100 * (uni_tot - obs_w - obs_s) / (obs_w + obs_s),
                         "err_pct_wind_separate": 100 * (sep_w - obs_w) / obs_w, "err_pct_wind_unified": 100 * (uni_w - obs_w) / obs_w,
                         "err_pct_solar_separate": 100 * (sep_s - obs_s) / obs_s, "err_pct_solar_unified": 100 * (uni_s - obs_s) / obs_s})
    ann = pd.DataFrame(rows)
    # monthly total rate
    pm_sep = (cm.predict_monthly(d, pw, "r", *c2.TECH["wind"]) * (d.wind + d.curt_wind).groupby(d.index.to_period("M")).sum() + cm.predict_monthly(d, ps, "r", *c2.TECH["solar"]) * (d.solar_disp + d.curt_solar).groupby(d.index.to_period("M")).sum())
    den = (d.vre_real + d.curt_vre).groupby(d.index.to_period("M")).sum()
    pm_sep = pm_sep / den
    pm_uni = cm.predict_monthly(d, pu, "r", "vre_real", "curt_vre")
    obs = d.curt_vre.groupby(d.index.to_period("M")).sum() / den
    mon = pd.DataFrame({"model": ["separate (wind + solar curves)", "unified (one curve)"], "R2": [1 - ((obs - pm_sep) ** 2).sum() / ((obs - obs.mean()) ** 2).sum(), 1 - ((obs - pm_uni) ** 2).sum() / ((obs - obs.mean()) ** 2).sum()],
                        "RMSE_pp": [100 * float(np.sqrt(((obs - pm_sep) ** 2).mean())), 100 * float(np.sqrt(((obs - pm_uni) ** 2).mean()))]})
    # projection: totals under separate vs unified, 2030/2040/2050
    prof = c2.base_profile(h)
    pte = c2.load_pte()
    prow = []
    for sc in c2.SCENARIOS:
        for year in c2.YEARS:
            f = c2.scale_factors(pte, sc, year)
            r = c2.projected_r(prof, f)
            pw_t, ps_t = prof["W"] * f["a_wind"], prof["S"] * f["a_solar"]
            w_sep = c2.projected_rate(r, pw_t, pw) * f["wind_gen_twh"]
            s_sep = c2.projected_rate(r, ps_t, ps) * f["solar_gen_twh"]
            u_rate = cm.logistic_w(r, *pu)
            u_w, u_s = float((u_rate * pw_t).sum() / pw_t.sum()) * f["wind_gen_twh"], float((u_rate * ps_t).sum() / ps_t.sum()) * f["solar_gen_twh"]
            prow.append({"scenario": sc, "year": year, "separate_wind": w_sep, "separate_solar": s_sep, "separate_total": w_sep + s_sep, "unified_wind": u_w, "unified_solar": u_s, "unified_total": u_w + u_s,
                         "unified_minus_separate_pct": 100 * (u_w + u_s - w_sep - s_sep) / (w_sep + s_sep)})
    return ann, mon, {**out, "projection": pd.DataFrame(prow)}


def main() -> None:
    h = cm.sin_hourly("2022-01-01")
    T = cm.tables_dir()
    ct, fits = curve_table(h)
    ct.to_csv(T / "task11e2_wind_solar_curves.csv", index=False)
    print("==== Wind vs solar hourly dose-response (free L; bootstrap over months, 5-95 %) ====\n", ct.round(3).T.to_string())
    pdif = paired_difference(h)
    pdif.to_csv(T / "task11e2_wind_minus_solar.csv", index=False)
    print("\nPaired difference wind - solar on 2024-04..2026-09 (curtailment rate, absolute):\n", pdif.round(3).to_string(index=False))

    cov = pd.read_csv(T / "task11e2_coverage_table.csv")
    pr = projection(h, fits, cov)
    pr.to_csv(T / "task11e2_wind_projection.csv", index=False)
    s = pr[pr.phi == 1.0]
    print("\n==== Wind curtailment projection, TWh (phi = 1) ====")
    print(s[["scenario", "year", "wind_pte_twh", "share_hours_beyond_cap", "curt_share_beyond_cap", "wind_low_twh", "wind_central_twh", "wind_high_twh", "wind_boot_p05_twh", "wind_boot_p95_twh", "wind_window2024_twh"]].round(2).to_string(index=False))
    print("\nComparison with earlier formulations (TWh; 11B national low/central/high, 11D regional point (lo-hi), 11E envelope low/central/high):")
    print(s[["scenario", "year", "11B_national_low", "11B_national_central", "11B_national_high", "11D_regional_central", "11D_regional_lo", "11D_regional_hi", "11E_envelope_low", "11E_envelope_central",
             "11E_envelope_high", "wind_low_twh", "wind_central_twh", "wind_high_twh"]].round(1).to_string(index=False))
    fx = pr[(pr.scenario == "TA") & (pr.year == 2050)][["phi", "r_mean", "share_hours_beyond_cap", "curt_share_beyond_cap", "wind_low_twh", "wind_central_twh", "wind_high_twh"]]
    print("\nTA 2050 flexibility sensitivity (r/phi):\n", fx.round(2).to_string(index=False))
    w50 = s[s.year == 2050]
    print("\nEnvelope width 2050 (high/low): 11E", (w50["11E_envelope_high"] / w50["11E_envelope_low"]).round(2).tolist(), " hourly", (w50["wind_high_twh"] / w50["wind_low_twh"]).round(2).tolist(),
          " hourly bootstrap p95/p05", (w50["wind_boot_p95_twh"] / w50["wind_boot_p05_twh"]).round(2).tolist())

    ann, mon, un = unified(h)
    ann.to_csv(T / "task11e2_unified_annual.csv", index=False)
    mon.to_csv(T / "task11e2_unified_monthly.csv", index=False)
    un["projection"].to_csv(T / "task11e2_unified_projection.csv", index=False)
    print("\n==== Unified driver (one curve for total VRE curtailment) ====")
    print({k: tuple(round(x, 3) for x in v) for k, v in un["params"].items()})
    print("\nAnnual (TWh and % error):\n", ann.round(2).to_string(index=False))
    print("\nMonthly total rate, in-sample:\n", mon.round(4).to_string(index=False))
    print("\nProjection, separate vs unified (phi = 1):\n", un["projection"].round(1).to_string(index=False))


if __name__ == "__main__":
    main()
