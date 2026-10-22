"""Task 11E-b throwaway analysis (NOT part of the installed package; no src/ change): wind asymptote L as a scenario envelope + the numbers behind the D24 options.

Part 1  L-envelope of the Northeast wind curve (Task 11D-a): L fixed at 0.25 / 0.5 / 1.0, k and P0 refitted on the same 57 months; same PTE proxy as 11D-a; the
        energy-balance FLOOR of 11E-c (export capacity + load) is added as a capacity-grounded refinement of the low bound.
Part 2  Hourly dose-response ("structure-grounded") projection for wind AND solar: fixed curve f(r) of the hourly SIN potential-VRE share of load r, applied to the
        2025 hourly profile scaled to each PTE scenario/year (wind x W_t/W_2025, solar x S_t/S_2025, load x T_t/T_2025, all from the PTE table).
Part 3  Totals (wind + solar) under the D24 options A / B / C / D and the hourly alternative E, for 2040 and 2050.
Gross formula of Task 11B kept everywhere: curtailed = PTE generation x rate (D23 pending: every number shifts if D23 is decided otherwise).
Run (after task11e_transmission_confound.py, which writes the floor table):  python analysis/task11e_wind_envelope.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

from curtailmit.calibration import logistic

sys.path.insert(0, str(Path(__file__).resolve().parent))
import task11d_regional_recalibration as ra
import task11e_common as cm

pd.set_option("display.width", 230)
pd.set_option("display.max_columns", 50)
L_GRID = (0.25, 0.5, 1.0)
YEARS = (2030, 2040, 2050)
PHI = (1.0, 1.25, 1.5)  # flexibility sensitivity: effective absorptive capacity relative to today (r_eff = r / phi)


def fit_fixed_L(df: pd.DataFrame, L: float) -> dict:
    popt, _ = curve_fit(lambda x, k, x0: cm.logistic_w(x, L, k, x0), df["P"], df["C"], p0=(0.15, 70.0), bounds=([1e-3, -np.inf], [np.inf, np.inf]), maxfev=20000)
    return {"L": L, "k": float(popt[0]), "P0": float(popt[1])}


def part1() -> tuple[pd.DataFrame, pd.DataFrame]:
    print("\n==== Part 1: L-envelope of the NE wind curve ====")
    ne = ra.ne_panel()
    fr = ne[["P", "C_wind"]].rename(columns={"C_wind": "C"})
    fits = []
    for L in L_GRID:
        p = fit_fixed_L(fr, L)
        rmse = float(np.sqrt(((fr.C - logistic(fr.P.to_numpy(), **p)) ** 2).mean()))
        # half-sample stability of the profile fit
        half = []
        for part in (fr.iloc[:28], fr.iloc[28:]):
            try:
                q = fit_fixed_L(part.reset_index(drop=True), L)
                half.append(f"k={q['k']:.2f},P0={q['P0']:.0f}")
            except Exception:  # noqa: BLE001
                half.append("fit failed")
        fits.append({**p, "rmse": rmse, "C_at_P70": float(logistic(70.0, **p)), "C_at_P80": float(logistic(80.0, **p)), "C_at_P90": float(logistic(90.0, **p)),
                     "C_at_P100": float(logistic(100.0, **p)), "first_half": half[0], "second_half": half[1]})
    fits = pd.DataFrame(fits)
    print("NE wind logistic with L fixed (k, P0 refitted; 57 months, P_NE 49-84):\n", fits.round(3).to_string())
    fits.to_csv(ra.tables_dir() / "task11e_wind_L_envelope_fits.csv", index=False)

    shares = ra.annual_shares()
    nat = pd.read_csv(ra.tables_dir() / ra.PANEL_CSV)
    nat["month"] = pd.PeriodIndex(nat["month"], freq="M")
    y25 = nat[(nat.month.dt.year == 2025) & (nat.id_subsistema != "NE")]
    nonne = float(y25.curt_wind.sum() / (y25.wind.sum() + y25.curt_wind.sum()))
    rows = []
    grid = np.arange(10, 101, 5.0)
    for _, f in fits.iterrows():
        params = {"L": f.L, "k": f.k, "P0": f.P0}
        ci = pd.DataFrame({"P": grid, "lo": logistic(grid, **params), "hi": logistic(grid, **params)})  # no bootstrap here: the envelope IS the uncertainty
        pr = ra.project_proxy(shares, ne, params, ci, nonne)
        pr["L"] = f.L
        rows.append(pr)
    proj = pd.concat(rows, ignore_index=True)
    keep = ["scenario", "year", "proxy", "L", "P_national", "P_NE_proxy", "P_NE_extrapolated", "C_wind_NE", "wind_curtailed_twh_regional", "wind_rate_regional_pct", "wind_curtailed_twh_11B_national"]
    proj[keep].to_csv(ra.tables_dir() / "task11e_wind_L_envelope_projection.csv", index=False)
    main = proj[proj.proxy.str.startswith("NE_wind_share=2025")]
    piv = main[main.year.isin(YEARS)].pivot_table(index=["scenario", "year"], columns="L", values="wind_curtailed_twh_regional")
    print("\nWind curtailment TWh, NE-regional proxy (share 0.93), by L:\n", piv.round(1).to_string())
    piv_rate = main[main.year.isin(YEARS)].pivot_table(index=["scenario", "year"], columns="L", values="wind_rate_regional_pct")
    print("wind curtailment rate % of PTE wind:\n", piv_rate.round(1).to_string())

    # capacity-grounded floor (11E-c): linear export-capacity trend, must-run O = 0; the floor applies to the NE VRE joint, apportioned to wind pro rata
    fl_path = ra.tables_dir() / "task11e_capacity_floor_projection.csv"
    floor = pd.read_csv(fl_path)
    fsel = floor[(floor.K_path == "K linear trend") & (floor.must_run_case == "O=0")][["scenario", "year", "floor_wind_twh_prorata", "floor_wind_pct_of_NE_wind"]]
    fsel2 = floor[(floor.K_path == "K const (no expansion)") & (floor.must_run_case == "O=0")][["scenario", "year", "floor_wind_twh_prorata"]].rename(columns={"floor_wind_twh_prorata": "floor_wind_twh_Kconst"})
    fsel3 = floor[(floor.K_path == "K 2x linear trend") & (floor.must_run_case == "O=0")][["scenario", "year", "floor_wind_twh_prorata"]].rename(columns={"floor_wind_twh_prorata": "floor_wind_twh_K2x"})
    fsel = fsel.rename(columns={"floor_wind_twh_prorata": "floor_wind_twh_Klinear"}).merge(fsel2, on=["scenario", "year"]).merge(fsel3, on=["scenario", "year"])
    env = piv.reset_index().merge(fsel, on=["scenario", "year"], how="left")
    env.columns = [str(c) for c in env.columns]
    env = env.rename(columns={"0.25": "wind_L025", "0.5": "wind_L050", "1.0": "wind_L100"})
    env["low_statistical"] = env["wind_L025"]
    env["low_capacity_grounded"] = env[["wind_L025", "floor_wind_twh_Klinear"]].max(axis=1)
    env["central"] = env[["wind_L050", "floor_wind_twh_Klinear"]].max(axis=1)
    env["high"] = env["wind_L100"]
    env.to_csv(ra.tables_dir() / "task11e_wind_envelope.csv", index=False)
    print("\nWind envelope (TWh): statistical L = 0.25 / 0.5 / 1.0, and energy-balance floors (export capacity paths; NE share 0.93, must-run 0):\n", env.round(1).to_string())
    return env, proj


# ----------------------------------------------------------------------------------------------- Part 2
def fit_curve(h: pd.DataFrame, real: str, curt: str, L_fixed: float | None = None) -> tuple:
    b = cm.binned(h, "r", real, curt)
    if L_fixed is None:
        return cm.fit_binned(b), b
    d = b[b["hours"] >= 15]
    w = d["pot"] / d["pot"].max()
    popt, _ = curve_fit(lambda x, k, x0: cm.logistic_w(x, L_fixed, k, x0), d["x"], d["rate"], p0=(0.1, 40.0), sigma=1 / np.sqrt(w.clip(lower=1e-6)), bounds=([1e-3, -np.inf], [np.inf, np.inf]), maxfev=20000)
    return (L_fixed, float(popt[0]), float(popt[1])), b


def hourly_projection() -> pd.DataFrame:
    print("\n==== Part 2: hourly dose-response projection (wind and solar) ====")
    h = cm.sin_hourly("2022-01-01")
    hw = h
    hs = h[h.index >= "2024-04-01"]
    curves = {}
    for tech, hh, real, curt in (("wind", hw, "wind", "curt_wind"), ("solar", hs, "solar_disp", "curt_solar")):
        pc, b = fit_curve(hh, real, curt)
        p1, _ = fit_curve(hh, real, curt, L_fixed=1.0)
        r_cap = float(b[b["hours"] >= 15]["x"].max())
        curves[tech] = {"central": pc, "L1": p1, "r_cap": r_cap, "r_max": float(hh["r"].max())}
        print(f"{tech}: central L={pc[0]:.3f} k={pc[1]:.3f} x0={pc[2]:.1f}; L=1 variant k={p1[1]:.3f} x0={p1[2]:.1f}; observed hourly r max {hh['r'].max():.1f} (last bin with >=15 h at {r_cap:.1f})")
    base = h[h.index.year == 2025]
    W, S, LD = (base.wind + base.curt_wind).to_numpy(), (base.solar_disp + base.curt_solar).to_numpy(), base["load"].to_numpy()
    print(f"2025 base profile: wind pot {W.sum() / 1e6:.1f} TWh, solar pot {S.sum() / 1e6:.1f}, load {LD.sum() / 1e6:.1f}; mean r {100 * (W + S).sum() / LD.sum():.1f} %, p95 {np.percentile(100 * (W + S) / LD, 95):.1f} %")
    pte = pd.read_parquet(ra.get_processed_dir() / "pte_curtailment_two_curves.parquet")
    rows = []
    for sc, g in pte.groupby("scenario"):
        g = g.set_index("year")
        w0, s0, t0 = g.loc[2025, "wind_gen_twh"], g.loc[2025, "solar_gen_twh"], g.loc[2025, "total_generation_twh"]
        for year in (2025, 2030, 2040, 2050):
            aw, as_, al = g.loc[year, "wind_gen_twh"] / w0, g.loc[year, "solar_gen_twh"] / s0, g.loc[year, "total_generation_twh"] / t0
            for phi in PHI:
                r = 100 * (aw * W + as_ * S) / (al * LD) / phi
                row = {"scenario": sc, "year": year, "phi": phi, "a_wind": aw, "a_solar": as_, "a_load": al, "r_mean": float(r.mean()), "r_p95": float(np.percentile(r, 95)),
                       "share_hours_beyond_observed_wind": float((r > curves["wind"]["r_max"]).mean())}
                for tech, pot in (("wind", W * aw), ("solar", S * as_)):
                    c = curves[tech]
                    f_c = cm.logistic_w(r, *c["central"])
                    f_hi = cm.logistic_w(r, *c["L1"])
                    f_lo = cm.logistic_w(np.minimum(r, c["r_cap"]), *c["central"])
                    for nm, f in (("low", f_lo), ("central", f_c), ("high", f_hi)):
                        rate = float((f * pot).sum() / pot.sum())
                        gen = g.loc[year, "wind_gen_twh" if tech == "wind" else "solar_gen_twh"]
                        row[f"{tech}_rate_{nm}"] = rate
                        row[f"{tech}_twh_{nm}"] = rate * gen
                for nm in ("low", "central", "high"):
                    row[f"total_twh_{nm}"] = row[f"wind_twh_{nm}"] + row[f"solar_twh_{nm}"]
                rows.append(row)
    out = pd.DataFrame(rows)
    out.to_csv(ra.tables_dir() / "task11e_hourly_projection.csv", index=False)
    sel = out[out.phi == 1.0][["scenario", "year", "r_mean", "r_p95", "share_hours_beyond_observed_wind", "wind_rate_low", "wind_rate_central", "wind_rate_high", "solar_rate_low", "solar_rate_central", "solar_rate_high",
                              "total_twh_low", "total_twh_central", "total_twh_high"]]
    print("Hourly dose-response projection (phi = 1: today's flexibility):\n", sel.round(2).to_string())
    flex = out[(out.year == 2050) & (out.scenario == "TA")][["phi", "r_mean", "wind_rate_central", "solar_rate_central", "total_twh_low", "total_twh_central", "total_twh_high"]]
    print("TA 2050 flexibility sensitivity (r_eff = r / phi):\n", flex.round(2).to_string())
    return out


# ----------------------------------------------------------------------------------------------- Part 3
def part3(env: pd.DataFrame, hourly: pd.DataFrame) -> pd.DataFrame:
    print("\n==== Part 3: totals (wind + solar) under the D24 options, TWh ====")
    pte = pd.read_parquet(ra.get_processed_dir() / "pte_curtailment_two_curves.parquet")
    p11 = pd.read_csv(ra.tables_dir() / "task11d_projection_regional_proxy.csv")
    hs = hourly[hourly.phi == 1.0].set_index(["scenario", "year"])
    rows = []
    for sc in ("TB", "TA", "TG"):
        for year in (2040, 2050):
            n = pte[(pte.scenario == sc) & (pte.year == year)].iloc[0]
            e = env[(env.scenario == sc) & (env.year == year)].iloc[0]
            h = hs.loc[(sc, year)]
            solar_lo, solar_c, solar_hi = h.solar_twh_low, h.solar_twh_central, h.solar_twh_high
            rows.append({
                "scenario": sc, "year": year,
                "C_national_low": n.total_curtailed_twh_low, "C_national_central": n.total_curtailed_twh_central, "C_national_high": n.total_curtailed_twh_high,
                "A_wind_low": e.low_capacity_grounded, "A_wind_central": e.central, "A_wind_high": e.high,
                "A_solar_low": solar_lo, "A_solar_central": solar_c, "A_solar_high": solar_hi,
                "A_total_low": e.low_capacity_grounded + solar_lo, "A_total_central": e.central + solar_c, "A_total_high": e.high + solar_hi,
                "A_total_low_statistical": e.low_statistical + solar_lo,
                "E_total_low": h.total_twh_low, "E_total_central": h.total_twh_central, "E_total_high": h.total_twh_high,
                "E_wind_central": h.wind_twh_central, "E_solar_central": h.solar_twh_central,
                "11D_NE_curve_wind_plus_national_solar": float(p11[(p11.scenario == sc) & (p11.year == year) & p11.proxy.str.startswith("NE_wind_share=2025")].total_regional_wind_plus_national_solar.iloc[0]),
                "PTE_wind_twh": n.wind_gen_twh, "PTE_solar_twh": n.solar_gen_twh})
    t = pd.DataFrame(rows)
    # Option D (defer): the bracket across every approach computed
    t["D_bracket_low"] = t[["C_national_low", "A_total_low", "E_total_low"]].min(axis=1)
    t["D_bracket_high"] = t[["C_national_high", "A_total_high", "E_total_high"]].max(axis=1)
    t.to_csv(ra.tables_dir() / "task11e_option_totals.csv", index=False)
    show = t[["scenario", "year", "C_national_low", "C_national_central", "C_national_high", "A_total_low", "A_total_central", "A_total_high", "E_total_low", "E_total_central", "E_total_high", "D_bracket_low", "D_bracket_high"]]
    print(show.round(0).to_string())
    return t


def figure() -> None:
    """Hourly dose-response by year (wind, solar) and the options totals."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    h = cm.sin_hourly("2022-01-01")
    edges = [0, 15, 20, 25, 30, 35, 40, 45, 50, 60, 100]
    fig, ax = plt.subplots(1, 3, figsize=(17, 4.8))
    for k, (tech, real, curt, start) in enumerate((("wind", "wind", "curt_wind", "2022-01-01"), ("solar", "solar_disp", "curt_solar", "2024-04-01"))):
        d = h[h.index >= start].copy()
        d["bin"] = pd.cut(d["r"], edges)
        for y, g in d.groupby(d.index.year):
            t = g.groupby("bin", observed=True).apply(lambda x, real=real, curt=curt: pd.Series({"x": x["r"].mean(), "rate": x[curt].sum() / max((x[real] + x[curt]).sum(), 1e-9), "n": len(x)}), include_groups=False)
            t = t[t["n"] >= 15]
            ax[k].plot(t["x"], 100 * t["rate"], "o-", label=str(y), ms=4)
        ax[k].set(xlabel="hourly SIN potential VRE share of load r (%)", ylabel=f"{tech} curtailment rate (%)", title=f"{tech}: hourly dose-response by year")
        ax[k].legend(fontsize=8)
    t = pd.read_csv(ra.tables_dir() / "task11e_option_totals.csv")
    x = np.arange(len(t))
    ax[2].bar(x - 0.27, t["C_national_central"], 0.27, yerr=[t["C_national_central"] - t["C_national_low"], t["C_national_high"] - t["C_national_central"]], label="C: national curves (11B)", color="tab:red", alpha=0.7)
    ax[2].bar(x, t["A_total_central"], 0.27, yerr=[t["A_total_central"] - t["A_total_low"], t["A_total_high"] - t["A_total_central"]], label="A: regional wind envelope + hourly solar", color="tab:blue", alpha=0.7)
    ax[2].bar(x + 0.27, t["E_total_central"], 0.27, yerr=[t["E_total_central"] - t["E_total_low"], t["E_total_high"] - t["E_total_central"]], label="E: hourly curves (wind + solar)", color="tab:green", alpha=0.7)
    ax[2].set_xticks(x, [f"{a} {b}" for a, b in zip(t.scenario, t.year, strict=True)], rotation=45)
    ax[2].set(ylabel="wind + solar curtailed (TWh)", title="Totals by approach (low / central / high)")
    ax[2].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(ra.figs_dir() / "task11e_overview.png", dpi=130)
    print("figure:", ra.figs_dir() / "task11e_overview.png")


def main() -> None:
    env, _ = part1()
    hourly = hourly_projection()
    part3(env, hourly)
    figure()


if __name__ == "__main__":
    main()
