"""Task 11D-0 / 11D-a throwaway analysis (NOT part of the installed package; no src/ file is modified).

11D-0  Does the PTE report give wind/solar by region?  (documented below; answer: no -> labelled proxy)
11D-a  Refit C_wind on the Northeast (NE) subsystem penetration P_NE, compare with the national curve, prototype the Task 11B projection with
       P_NE-derived rates (proxy-based), and check whether a regional solar fit is identifiable.

Definitions (same operational definition as the national P of Tasks 7-7D, only the geographic scope changes):
    P_NE   = (wind_NE + dispatched_solar_NE) / (hydro_NE + thermal_NE + wind_NE + dispatched_solar_NE)   [realized generation, ONS balance by subsystem]
    P_nat  = (wind + dispatched_solar)       / (hydro + thermal + wind + dispatched_solar)               [same, SIN]
    C_wind = curtailed / (realized + curtailed), technology-specific, monthly (D22).
Unavoidable difference: the NE is a net exporter/importer, so its local generation is not its load; P_NE is a generation share, not a load share.

Reuses the Task 11C artifact outputs/tables/task11c_subsystem_monthly.csv (regenerated from analysis/task11c_diagnostics.py if missing).
Run:  python analysis/task11d_regional_recalibration.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from curtailmit.calibration import bootstrap_calibration_ci, fit_calibration, logistic
from curtailmit.paths import get_outputs_dir, get_processed_dir

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 40)
PANEL_CSV = "task11c_subsystem_monthly.csv"
PROJ_YEARS = (2025, 2030, 2040, 2050)
N_BOOT = 1000


def tables_dir() -> Path:
    return get_outputs_dir("tables")


def figs_dir() -> Path:
    return get_outputs_dir("figures")


# ----------------------------------------------------------------------------------------------- loaders (reused by the other 11D scripts)
def load_subsystem_panel() -> pd.DataFrame:
    """Monthly x subsystem panel of the 57 calibration months (Task 11C artifact)."""
    path = tables_dir() / PANEL_CSV
    if not path.exists():
        import task11c_diagnostics as t11c

        t11c.part_region()
    z = pd.read_csv(path)
    z["month"] = pd.PeriodIndex(z["month"], freq="M")
    return z


def ne_panel() -> pd.DataFrame:
    """NE monthly panel with wind and solar curtailment rates and P_NE."""
    z = load_subsystem_panel()
    ne = z[z.id_subsistema == "NE"].sort_values("month").reset_index(drop=True).copy()
    ne["P"] = ne["P_sub"]
    ne["C_wind"] = ne["curt_wind"] / (ne["wind"] + ne["curt_wind"])
    ne["has_solar_curt"] = ne["month"] >= pd.Period("2024-04", freq="M")  # first month of published solar curtailment (scope wind_solar)
    sol_den = ne["solar_dispatched"] + ne["curt_solar"]
    ne["C_solar"] = np.where(ne["has_solar_curt"], ne["curt_solar"] / sol_den, np.nan)
    ne["t"] = np.arange(len(ne))
    return ne


def national_frame_wind() -> pd.DataFrame:
    """National wind calibration frame (Task 7D inputs): P national and C_wind per month."""
    f = pd.read_parquet(get_processed_dir() / "calibration_frame.parquet")
    f["C"] = f["curt_wind_mwh"] / (f["wind_gen_mwh"] + f["curt_wind_mwh"])
    return f[["year", "month", "P", "C"]].reset_index(drop=True)


def annual_shares() -> pd.DataFrame:
    """NE share of national wind, dispatched solar, hydro+thermal and total generation, per year (ONS balance by subsystem)."""
    import task11c_diagnostics as t11c

    bal = t11c.load_balance_by_subsystem()
    disp = t11c.load_dispatched_solar_by_subsystem()
    b = bal.merge(disp, on=["month", "id_subsistema"], how="left").fillna({"solar_dispatched": 0.0})
    b["year"] = b.month.dt.year
    b["months"] = 1
    a = b.groupby(["year", "id_subsistema"])[["hydro", "thermal", "wind", "solar_dispatched", "load", "months"]].sum()
    rows = []
    for y in sorted(b.year.unique()):
        s, ne = a.loc[y], a.loc[y].loc["NE"]
        tot = s.sum()
        rows.append({"year": int(y), "months": int(b[b.year == y].month.nunique()), "ne_share_wind": ne.wind / tot.wind, "ne_share_solar": ne.solar_dispatched / tot.solar_dispatched,
                     "ne_share_hydro_thermal": (ne.hydro + ne.thermal) / (tot.hydro + tot.thermal),
                     "ne_share_total_gen": (ne.hydro + ne.thermal + ne.wind + ne.solar_dispatched) / (tot.hydro + tot.thermal + tot.wind + tot.solar_dispatched),
                     "ne_gen_twh": (ne.hydro + ne.thermal + ne.wind + ne.solar_dispatched) / 1e6, "ne_load_twh": ne["load"] / 1e6, "ne_wind_twh": ne.wind / 1e6})
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------------------------- 11D-0
def part_0() -> dict:
    print("\n==== 11D-0  regional PTE wind/solar data? ====")
    print("PTE2 report (CEBRI, 112 pp.) text search ('Nordeste', 'subsistema', 'regional', 'transmiss'): regional content is macroeconomic only")
    print("  (GDP / per-capita income by macro-region, Grafico 22; TERM inter-regional CGE). No wind/solar capacity or generation by region/subsystem.")
    print("  NEWAVE step uses SIN and subsystem *criteria* (5 % demand, 800 R$/MWh) but publishes no subsystem generation. config/scenarios.yaml holds national shares only.")
    sh = annual_shares()
    print("NE shares by year (ONS balance; 2026 = Jan-Oct, partial):\n", sh.round(3).to_string())
    sh.to_csv(tables_dir() / "task11d_ne_shares_by_year.csv", index=False)
    return {"gap": "no regional wind/solar in PTE sources; labelled proxy used"}


# ----------------------------------------------------------------------------------------------- 11D-a
def compare_curves(ne: pd.DataFrame, nat_wind_params: dict, ne_params: dict, ci: pd.DataFrame) -> pd.DataFrame:
    grid = np.array([10, 20, 25, 30, 35, 40, 50, 60, 70, 80, 90, 100], dtype=float)
    out = pd.DataFrame({"P": grid, "C_national": logistic(grid, **nat_wind_params), "C_NE": logistic(grid, **ne_params)})
    out["NE_in_sample"] = (grid >= ne.P.min()) & (grid <= ne.P.max())
    out["national_in_sample"] = (grid >= 10.3) & (grid <= 29.4)
    return out.merge(ci.rename(columns={"point": "C_NE_ci_point", "lo": "C_NE_lo", "hi": "C_NE_hi"})[["P", "C_NE_lo", "C_NE_hi"]], on="P", how="left")


def project_proxy(shares: pd.DataFrame, ne: pd.DataFrame, ne_params: dict, ci: pd.DataFrame, nonne_rate: float) -> pd.DataFrame:
    """Prototype of the Task 11B logic with P_NE and proxies. Formula unchanged (wind_curtailed = wind_gen x C; D23 pending)."""
    proj = pd.read_parquet(get_processed_dir() / "pte_curtailment_two_curves.parquet")
    last = shares[shares.months == 12].iloc[-1]  # 2025
    sw_variants = {"NE_wind_share=2025 (0.93)": float(last.ne_share_wind), "NE_wind_share=0.80 (stress: diversification)": 0.80}
    ss, sh = float(last.ne_share_solar), float(last.ne_share_hydro_thermal)
    p_obs_max = float(ne.P.max())
    rows = []
    for r in proj[proj.year.isin(PROJ_YEARS)].itertuples():
        other = r.total_generation_twh - r.wind_gen_twh - r.solar_gen_twh
        for label, sw in sw_variants.items():
            w_ne, s_ne, o_ne = sw * r.wind_gen_twh, ss * r.solar_gen_twh, sh * other
            p_ne = 100 * (w_ne + s_ne) / (w_ne + s_ne + o_ne)
            c_ne = float(logistic(np.array([p_ne]), **ne_params)[0])
            lo_c = float(np.interp(min(p_ne, ci.P.max()), ci.P, ci.lo))
            hi_c = float(np.interp(min(p_ne, ci.P.max()), ci.P, ci.hi))
            w_other = r.wind_gen_twh - w_ne
            wind_curt = w_ne * c_ne + w_other * nonne_rate
            wind_curt_lo = w_ne * lo_c + w_other * nonne_rate
            wind_curt_hi = w_ne * hi_c + w_other * nonne_rate
            rows.append({"scenario": r.scenario, "year": r.year, "proxy": label, "P_national": r.P, "P_NE_proxy": p_ne, "P_NE_extrapolated": p_ne > p_obs_max,
                         "NE_wind_twh_proxy": w_ne, "C_wind_NE": c_ne, "wind_curtailed_twh_regional": wind_curt, "wind_curtailed_twh_regional_lo": wind_curt_lo,
                         "wind_curtailed_twh_regional_hi": wind_curt_hi, "wind_curtailed_twh_11B_national": r.wind_curtailed_twh_central,
                         "wind_curtailed_twh_11B_low": r.wind_curtailed_twh_low, "wind_curtailed_twh_11B_high": r.wind_curtailed_twh_high,
                         "wind_rate_regional_pct": 100 * wind_curt / r.wind_gen_twh, "wind_rate_11B_pct": 100 * r.C_wind_central,
                         "solar_curtailed_twh_11B_national_curve": r.solar_curtailed_twh_central, "total_regional_wind_plus_national_solar": wind_curt + r.solar_curtailed_twh_central,
                         "total_11B": r.total_curtailed_twh_central})
    return pd.DataFrame(rows)


def part_a() -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    print("\n==== 11D-a  regional recalibration of C_wind(P_NE) ====")
    ne = ne_panel()
    print(f"NE panel: {len(ne)} months {ne.month.min()}..{ne.month.max()}; P_NE {ne.P.min():.1f}-{ne.P.max():.1f} (mean {ne.P.mean():.1f}); C_wind {ne.C_wind.min():.3f}-{ne.C_wind.max():.3f}")
    print("annual means:\n", ne.groupby(ne.month.dt.year)[["P", "C_wind"]].mean().round(3).to_string())
    fr = ne[["P", "C_wind"]].rename(columns={"C_wind": "C"})
    cal = fit_calibration(fr)
    ne_params = cal.params
    resid = fr.C - logistic(fr.P.to_numpy(), **ne_params)
    rmse = float(np.sqrt((resid**2).mean()))
    res_year = pd.DataFrame({"year": ne.month.dt.year, "observed": fr.C, "fitted": logistic(fr.P.to_numpy(), **ne_params)}).groupby("year").mean()
    res_year["residual"] = res_year.observed - res_year.fitted
    print("in-sample mean observed vs fitted C_wind by year (shows how much of the time trend the P-only curve misses):\n", res_year.round(3).to_string())
    res_year.to_csv(tables_dir() / "task11d_ne_wind_residual_by_year.csv")
    grid = [float(x) for x in np.arange(10, 101, 5)]
    ci = bootstrap_calibration_ci(fr, grid, n_boot=N_BOOT, seed=0)
    nat = json.loads((get_processed_dir() / "calibration_params_wind.json").read_text(encoding="utf-8"))["params"]
    print(f"NE wind fit: L={ne_params['L']:.3f} k={ne_params['k']:.3f} P0={ne_params['P0']:.1f} RMSE={rmse:.4f} (n={len(fr)})")
    print(f"national wind fit (Task 7D): L={nat['L']:.3f} k={nat['k']:.3f} P0={nat['P0']:.1f}")
    boots = ci.copy()
    print("NE CI columns:", boots.columns.tolist())
    # parameter-level bootstrap for L, k, P0 of the NE fit
    rng = np.random.default_rng(0)
    pars = []
    for _ in range(N_BOOT):
        idx = rng.integers(0, len(fr), len(fr))
        try:
            pars.append(list(fit_calibration(fr.iloc[idx].reset_index(drop=True)).params.values()))
        except Exception:  # noqa: BLE001 - failed refits counted below
            continue
    pars = np.array(pars)
    pci = {n: (float(np.percentile(pars[:, i], 2.5)), float(np.percentile(pars[:, i], 97.5))) for i, n in enumerate(("L", "k", "P0"))}
    print(f"NE bootstrap parameter 95% intervals ({len(pars)}/{N_BOOT} refits ok):", {k: (round(a, 3), round(b, 3)) for k, (a, b) in pci.items()})

    cmp_ = compare_curves(ne, nat, ne_params, ci)
    cmp_.to_csv(tables_dir() / "task11d_curve_comparison_national_vs_NE.csv", index=False)
    print(cmp_.round(3).to_string())

    # ---- identifiability: is the NE asymptote supported or just the last observed level? Fit on halves
    first, second = ne.iloc[:28], ne.iloc[28:]
    for nm, d in (("first 28 months", first), ("last 29 months", second)):
        try:
            p = fit_calibration(d[["P", "C_wind"]].rename(columns={"C_wind": "C"}).reset_index(drop=True)).params
            print(f"NE sub-sample fit {nm}: L={p['L']:.3f} k={p['k']:.3f} P0={p['P0']:.1f}; P range {d.P.min():.0f}-{d.P.max():.0f}; C range {d.C_wind.min():.3f}-{d.C_wind.max():.3f}")
        except Exception as exc:  # noqa: BLE001
            print("sub-sample fit failed", nm, exc)

    # ---- proxy projection
    shares = annual_shares()
    nat_frame = pd.read_csv(tables_dir() / PANEL_CSV)
    nat_frame["month"] = pd.PeriodIndex(nat_frame["month"], freq="M")
    y25 = nat_frame[(nat_frame.month.dt.year == 2025) & (nat_frame.id_subsistema != "NE")]
    nonne_rate = float(y25.curt_wind.sum() / (y25.wind.sum() + y25.curt_wind.sum()))
    nonne_all = nat_frame[nat_frame.id_subsistema != "NE"]
    print(f"non-NE wind curtailment rate 2025 = {nonne_rate:.3f} (all 57 months {nonne_all.curt_wind.sum() / (nonne_all.wind.sum() + nonne_all.curt_wind.sum()):.3f}); held constant in the proxy")
    ci_f = ci.rename(columns={"point": "pt"})
    proj = project_proxy(shares, ne, ne_params, ci_f, nonne_rate)
    proj.to_csv(tables_dir() / "task11d_projection_regional_proxy.csv", index=False)
    show = proj[["scenario", "year", "proxy", "P_national", "P_NE_proxy", "P_NE_extrapolated", "C_wind_NE", "wind_curtailed_twh_regional", "wind_curtailed_twh_regional_lo", "wind_curtailed_twh_regional_hi",
                 "wind_curtailed_twh_11B_national", "wind_rate_regional_pct", "wind_rate_11B_pct", "total_regional_wind_plus_national_solar", "total_11B"]]
    print(show.round(2).to_string())

    # ---- regional solar feasibility
    s = ne[ne.has_solar_curt]
    print(f"\nNE solar: {len(s)} months with published solar curtailment, P_NE {s.P.min():.1f}-{s.P.max():.1f}, C_solar {s.C_solar.min():.3f}-{s.C_solar.max():.3f}; "
          f"corr(C_solar,t)={np.corrcoef(s.t, s.C_solar)[0, 1]:.2f} corr(C_solar,P)={np.corrcoef(s.P, s.C_solar)[0, 1]:.2f}; corr(P,t)={np.corrcoef(s.t, s.P)[0, 1]:.2f}")
    try:
        ps = fit_calibration(s[["P", "C_solar"]].rename(columns={"C_solar": "C"}).reset_index(drop=True)).params
        print("NE solar exploratory fit (NOT used for projection):", {k: round(v, 3) for k, v in ps.items()})
    except Exception as exc:  # noqa: BLE001
        print("NE solar fit failed:", exc)

    out = {"ne_wind_fit": {**ne_params, "rmse": rmse, "n": len(fr), "p_min": float(ne.P.min()), "p_max": float(ne.P.max()), "param_ci95": pci},
           "national_wind_fit": nat, "non_ne_wind_rate_2025": nonne_rate}
    (tables_dir() / "task11d_ne_wind_fit.json").write_text(json.dumps(out, indent=2), encoding="utf-8")

    # ---- figure
    fig, ax = plt.subplots(1, 2, figsize=(13, 4.6))
    pg = np.linspace(5, 100, 200)
    ax[0].scatter(ne.P, ne.C_wind, c=ne.t, cmap="viridis", s=18, label="NE monthly (colour = time)")
    ax[0].plot(pg, logistic(pg, **ne_params), "r-", label="NE fit")
    ax[0].plot(pg, logistic(pg, **nat), "k--", label="national fit (Task 7D)")
    wf = pd.read_parquet(get_processed_dir() / "calibration_frame.parquet")
    ax[0].scatter(wf.P, wf.wind_gen_mwh * 0 + wf.curt_wind_mwh / (wf.wind_gen_mwh + wf.curt_wind_mwh), s=10, color="gray", alpha=0.6, label="national monthly")
    ax[0].set(xlabel="penetration P (%)", ylabel="wind curtailment rate", title="C_wind: NE vs national", ylim=(0, 1.02))
    ax[0].legend(fontsize=8)
    for sc, mk in (("TB", "o"), ("TA", "s"), ("TG", "^")):
        d = proj[(proj.scenario == sc) & (proj.proxy.str.startswith("NE_wind_share=2025"))]
        ax[1].plot(d.year, d.wind_curtailed_twh_11B_national, mk + "--", color="tab:red", label=f"11B national {sc}")
        ax[1].plot(d.year, d.wind_curtailed_twh_regional, mk + "-", color="tab:blue", label=f"NE-regional proxy {sc}")
    ax[1].set(xlabel="year", ylabel="wind curtailed (TWh)", title="Wind curtailment projection: 11B vs NE-regional proxy")
    ax[1].legend(fontsize=7, ncol=2)
    fig.tight_layout()
    fig.savefig(figs_dir() / "task11d_regional_recalibration.png", dpi=130)
    print("figure:", figs_dir() / "task11d_regional_recalibration.png")


if __name__ == "__main__":
    part_0()
    part_a()
