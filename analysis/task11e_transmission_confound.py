"""Task 11E-c throwaway analysis (NOT part of the installed package; no src/ change): is the "time effect" on NE wind curtailment a transmission effect?

Data (all ONS operational data, cc-by; planning documents PDE/PET are NOT used):
  * Linha_Transmissao (registry of >= 230 kV lines: terminals, kV, long-duration operating current, entry/deactivation dates)  -> NE boundary capacity stock by month
  * Capacidade_Transformacao (basic-network transformers: MVA, entry/deactivation dates)                                       -> NE transformer stock by month
  * Balance by subsystem (hourly `val_intercambio` = net export), COFF curtailment, dispatched solar (already in raw/)           -> revealed export, saturation tests
  * Intercambio_Nacional (pairwise hourly flows)                                                                                -> reconciliation of net export
Capacity measures are STOCKS reconstructed from the CURRENT registry and its commissioning dates; they are not published transfer limits.

Run:  python analysis/task11e_transmission_confound.py
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

from curtailmit.calibration import fit_calibration, logistic
from curtailmit.paths import get_raw_dir

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 40)
HAC = 6
SAT_FRAC = 0.95  # export >= 95 % of the trailing 12-month maximum counts as "saturated"


# ----------------------------------------------------------------------------------------------- data
def pairwise_ne_net_export() -> pd.Series:
    """Hourly NE net export (MW) from the ONS pairwise interchange files (positive = leaves NE); used only to reconcile the balance column."""
    parts = []
    for f in sorted(get_raw_dir("ons/interchange").glob("Intercambio_Nacional-*")):
        if f.suffix == ".parquet":
            df = pd.read_parquet(f)
        elif f.suffix == ".csv":
            df = pd.read_csv(f, sep=";")
        else:
            continue
        df["ts"] = pd.to_datetime(df["din_instante"])
        df["v"] = pd.to_numeric(df["val_intercambiomwmed"], errors="coerce")
        o, d = df["id_subsistema_origem"].astype(str).str.strip(), df["id_subsistema_destino"].astype(str).str.strip()
        df["out"] = np.where(o == "NE", df["v"], np.where(d == "NE", -df["v"], 0.0))
        parts.append(df[(o == "NE") | (d == "NE")].groupby("ts")["out"].sum())
    return pd.concat(parts).groupby(level=0).sum()


def hourly_ne() -> pd.DataFrame:
    h = cm.hourly_panel()
    ne = h[h["sub"] == "NE"].set_index("ts").sort_index().copy()
    ne["vre_real"] = ne["wind"] + ne["solar_disp"]
    ne["curt"] = ne["curt_wind"] + ne["curt_solar"]
    ne["vre_pot"] = ne["vre_real"] + ne["curt"]
    ne["export_need"] = ne["net_export"] + ne["curt"]  # export that would be needed without curtailment
    ne["cap_rev"] = ne["net_export"].rolling(24 * 365, min_periods=24 * 90).max()  # trailing 12-month maximum observed export ("revealed capacity")
    ne["saturated"] = ne["net_export"] >= SAT_FRAC * ne["cap_rev"]
    return ne


def monthly_frame() -> pd.DataFrame:
    ne = ra.ne_panel()  # 57 months: P (P_NE), C_wind, t, ...
    h = hourly_ne()
    m = h.copy()
    m["month"] = m.index.to_period("M")
    g = m.groupby("month")
    agg = pd.DataFrame({"vre_pot_mw": g["vre_pot"].mean(), "vre_real_mw": g["vre_real"].mean(), "load_mw": g["load"].mean(), "export_mean": g["net_export"].mean(),
                        "export_p99": g["net_export"].quantile(0.99), "export_max": g["net_export"].max(), "cap_rev_mw": g["cap_rev"].last(),
                        "need_p99": g["export_need"].quantile(0.99), "curt_wind_mwh": g["curt_wind"].sum()})
    sat_w = m[m["saturated"]].groupby("month")["curt_wind"].sum()
    agg["curt_wind_in_saturated_h"] = sat_w.reindex(agg.index).fillna(0.0)
    agg["share_curt_in_saturated"] = agg["curt_wind_in_saturated_h"] / agg["curt_wind_mwh"].where(agg["curt_wind_mwh"] > 0)
    agg["share_hours_saturated"] = g["saturated"].mean()
    cap = cm.monthly_capacity_series(agg.index).set_index("month")
    out = ne.set_index("month").join(agg).join(cap)
    out["R_boundary"] = 100 * out["vre_pot_mw"] / out["boundary_mva"]  # % : potential VRE / boundary rating
    out["R_revealed"] = 100 * out["vre_pot_mw"] / out["cap_rev_mw"]
    out["need_ratio"] = 100 * out["need_p99"] / out["cap_rev_mw"]
    out["C"] = out["C_wind"]
    for c in ("boundary_mva", "ne_km", "ne_trafo_mva", "cap_rev_mw"):
        out[f"log_{c}"] = np.log(out[c])
    return out.reset_index()


# ----------------------------------------------------------------------------------------------- statistics
def ols(df: pd.DataFrame, cols: list[str]):
    return sm.OLS(df["C"], sm.add_constant(df[cols])).fit(cov_type="HAC", cov_kwds={"maxlags": HAC})


def aic_gauss(m) -> float:
    n, k = int(m.nobs), len(m.params)
    rss = float((m.resid**2).sum())
    return n * np.log(rss / n) + 2 * k


def partial_corr(df, x, y, controls):
    Z = sm.add_constant(df[controls])
    rx, ry = sm.OLS(df[x], Z).fit().resid, sm.OLS(df[y], Z).fit().resid
    return float(np.corrcoef(rx, ry)[0, 1])


def regressions(df: pd.DataFrame) -> pd.DataFrame:
    specs = [("t", ["t"]), ("P_NE", ["P"]), ("P_NE + t", ["P", "t"]),
             ("log boundary MVA", ["log_boundary_mva"]), ("log NE km", ["log_ne_km"]), ("log NE transformer MVA", ["log_ne_trafo_mva"]), ("log revealed export cap", ["log_cap_rev_mw"]),
             ("R_boundary (VRE potential / boundary MVA)", ["R_boundary"]), ("R_revealed (VRE potential / revealed cap)", ["R_revealed"]),
             ("R_boundary + t", ["R_boundary", "t"]), ("R_revealed + t", ["R_revealed", "t"]), ("R_boundary + P_NE", ["R_boundary", "P"]), ("R_revealed + P_NE", ["R_revealed", "P"]),
             ("share_hours_saturated", ["share_hours_saturated"]), ("share_hours_saturated + t", ["share_hours_saturated", "t"])]
    rows = []
    for name, cols in specs:
        d = df.dropna(subset=cols + ["C"])
        m = ols(d, cols)
        row = {"model": name, "n": int(m.nobs), "R2": m.rsquared, "adjR2": m.rsquared_adj, "AIC": aic_gauss(m), "RMSE": float(np.sqrt((m.resid**2).mean()))}
        for c in cols:
            row[f"b[{c}]"], row[f"p[{c}]"] = float(m.params[c]), float(m.pvalues[c])
        rows.append(row)
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------------------------- mechanism checks
def part_classes_and_sin() -> None:
    """Where does the NE wind curtailment occur? vs NE export saturation, by ONS reason class, and vs the SIN-wide hourly VRE share of load."""
    h = hourly_ne()
    hh = h[h.index >= "2022-01-01"].copy()
    rows = []
    for k, label in (("cw_ENE", "ENE (energy)"), ("cw_CNF", "CNF (reliability)"), ("cw_REL", "REL (external unavailability)")):
        d = hh[hh[k] > 0]
        w = d[k]
        ratio = (d["net_export"] / d["cap_rev"]).to_numpy()
        order = np.argsort(ratio)
        cw = np.cumsum(w.to_numpy()[order]) / w.sum()
        med = float(ratio[order][np.searchsorted(cw, 0.5)])
        rows.append({"class": label, "TWh": w.sum() / 1e6, "share_pct": 100 * w.sum() / hh["curt_wind"].sum(), "energy_weighted_median_export_over_revealed_cap": med,
                     "share_in_saturated_hours_pct": 100 * d.loc[d["saturated"], k].sum() / w.sum(), "share_in_hours_export_below_50pct_cap": 100 * d.loc[(d["net_export"] / d["cap_rev"]) < 0.5, k].sum() / w.sum()})
    cls = pd.DataFrame(rows)
    cls.to_csv(ra.tables_dir() / "task11e_ne_wind_curtailment_by_class_vs_export.csv", index=False)
    print("\nNE wind curtailment by reason class vs NE export / revealed capacity (2022-01..):\n", cls.round(2).to_string())

    allh = cm.hourly_panel()
    sin = allh.groupby("ts")[["wind", "solar_disp", "curt_wind", "curt_solar", "load"]].sum()
    sin["vre_pot"] = sin.wind + sin.solar_disp + sin.curt_wind + sin.curt_solar
    sin["r"] = 100 * sin.vre_pot / sin["load"]
    sin = sin[sin.index >= "2022-01-01"]
    ne_c = hh["curt_wind"].reindex(sin.index)
    sin["dec"] = pd.qcut(sin["r"], 10, labels=False)
    t = sin.assign(ne_curt=ne_c).groupby("dec").agg(r_mean=("r", "mean"), hours=("r", "size"), ne_curt_mwh=("ne_curt", "sum"), p_curt=("ne_curt", lambda x: float((x > 0).mean())))
    t["share_of_total_pct"] = 100 * t["ne_curt_mwh"] / t["ne_curt_mwh"].sum()
    t.to_csv(ra.tables_dir() / "task11e_ne_wind_curtailment_by_sin_vre_share.csv")
    print("\nNE wind curtailment by decile of the hourly SIN-wide potential VRE share of load (2022-01..):\n", t.round(2).to_string())
    byyr = sin.assign(ne_curt=ne_c, y=sin.index.year).groupby("y").apply(lambda d: pd.Series({"r_p95": d["r"].quantile(0.95), "r_mean": d["r"].mean(), "ne_curt_twh": d["ne_curt"].sum() / 1e6}), include_groups=False)
    print("SIN hourly potential-VRE share of load by year:\n", byyr.round(2).to_string())


def part_dose_response() -> None:
    """Hourly dose-response: NE wind curtailment rate vs the hourly SIN-wide potential VRE share of load, by year (is the relation stable over time?)."""
    allh = cm.hourly_panel()
    sin = allh.groupby("ts")[["wind", "solar_disp", "curt_wind", "curt_solar", "load"]].sum()
    sin["r"] = 100 * (sin.wind + sin.solar_disp + sin.curt_wind + sin.curt_solar) / sin["load"]
    ne = allh[allh["sub"] == "NE"].set_index("ts")[["wind", "curt_wind"]]
    d = sin[["r"]].join(ne, how="inner")
    d = d[d.index >= "2022-01-01"].copy()
    d["year"] = d.index.year
    edges = [0, 15, 20, 25, 30, 35, 40, 45, 50, 60, 100]
    d["bin"] = pd.cut(d["r"], edges)
    g = d.groupby(["bin", "year"], observed=True).agg(h=("r", "size"), w=("wind", "sum"), c=("curt_wind", "sum"))
    g["rate_pct"] = 100 * g["c"] / (g["w"] + g["c"])
    tab = g["rate_pct"].unstack("year")
    cnt = g["h"].unstack("year")
    print("\nNE wind curtailment rate (% of potential) by hourly SIN VRE share of load (rows) and year (columns); hours in brackets below:\n", tab.round(1).to_string())
    print(cnt.fillna(0).astype(int).to_string())
    tab.to_csv(ra.tables_dir() / "task11e_ne_wind_hourly_dose_response_by_year.csv")
    allr = d.groupby("bin", observed=True).agg(w=("wind", "sum"), c=("curt_wind", "sum"), h=("r", "size"))
    allr["rate_pct"] = 100 * allr["c"] / (allr["w"] + allr["c"])
    print("pooled 2022-2026:\n", allr.round(2).to_string())
    print(f"hourly r: max {d.r.max():.1f}, p99 {d.r.quantile(0.99):.1f}, p95 {d.r.quantile(0.95):.1f}")


def part_floor() -> pd.DataFrame:
    """Energy-balance FLOOR on NE VRE curtailment given NE load and export capacity (a necessary-curtailment bound, ignores the hourly profile -> a lower bound).

        floor = max(0, VRE_pot - (NE_load + K x 8.76 + O_mr)),  VRE_pot = NE wind + NE solar potential (PTE proxy of Task 11D), O_mr = must-run hydro + thermal kept in the NE.
    Back-test on the observed years first; then the PTE years with three export-capacity paths. Everything beyond 2026 is a labelled proxy, not a forecast.
    """
    h = hourly_ne()
    yr = h[h.index >= "2022-01-01"].groupby(h[h.index >= "2022-01-01"].index.year).agg(vre_pot=("vre_pot", "sum"), load=("load", "sum"), hydro=("hydro", "sum"), thermal=("thermal", "sum"), curt=("curt", "sum"))
    yr = yr.loc[2022:2025] / 1e6
    k_now = float(h["net_export"].iloc[-24 * 365:].max()) / 1000  # GW, trailing-12-month maximum
    back = yr.copy()
    for ok, kk in (("2022", 9.7), ("2023", 11.8), ("2024", 13.0), ("2025", 13.1)):
        pass
    rows = []
    for y, r in yr.iterrows():
        k = float(h.loc[:f"{y}-12-31", "net_export"].iloc[-24 * 365:].max()) / 1000
        rows.append({"year": y, "vre_pot_twh": r.vre_pot, "ne_load_twh": r["load"], "K_gw_revealed": k, "export_cap_twh": 8.76 * k, "O_hydro_thermal_twh": r.hydro + r.thermal, "observed_curt_twh": r.curt,
                     "floor_O0": max(0.0, r.vre_pot - r["load"] - 8.76 * k), "floor_O_as_observed": max(0.0, r.vre_pot - r["load"] - 8.76 * k - (r.hydro + r.thermal))})
    back = pd.DataFrame(rows)
    print("\nFloor back-test on observed years (NE, TWh):\n", back.round(2).to_string())
    back.to_csv(ra.tables_dir() / "task11e_capacity_floor_backtest.csv", index=False)

    cap = cm.monthly_capacity_series(pd.period_range("2022-01", "2026-09", freq="M")).set_index("month")
    n_years = (len(cap) - 1) / 12
    cagr = float((cap.boundary_mva.iloc[-1] / cap.boundary_mva.iloc[0]) ** (1 / n_years) - 1)
    print(f"boundary stock CAGR 2022-01..2026-09 = {100 * cagr:.2f} %/yr (from {cap.boundary_mva.iloc[0]:.0f} to {cap.boundary_mva.iloc[-1]:.0f} MVA); K_now (trailing max export) = {k_now:.2f} GW")
    proj = pd.read_parquet(ra.get_processed_dir() / "pte_curtailment_two_curves.parquet")
    shares = ra.annual_shares()
    last = shares[shares.months == 12].iloc[-1]
    ne25 = float(yr.loc[2025, "load"])
    t25 = proj[(proj.year == 2025)].groupby("scenario")["total_generation_twh"].first()
    o25 = float(yr.loc[2025, "hydro"] + yr.loc[2025, "thermal"])
    out = []
    slope = float(np.polyfit(np.arange(len(cap)) / 12, cap.boundary_mva.to_numpy(), 1)[0])  # MVA of boundary stock added per year (linear trend)
    g_gw = k_now * slope / float(cap.boundary_mva.iloc[-1])  # same relative growth applied to the revealed capacity, GW per year (linear)
    print(f"linear boundary-stock trend = {slope:.0f} MVA/yr -> K grows {g_gw:.2f} GW/yr (trend), {2 * g_gw:.2f} GW/yr (2x)")
    paths = {"K const (no expansion)": 0.0, "K linear trend": g_gw, "K 2x linear trend": 2 * g_gw}
    for r in proj[proj.year.isin([2025, 2030, 2040, 2050])].itertuples():
        w_ne, s_ne = float(last.ne_share_wind) * r.wind_gen_twh, float(last.ne_share_solar) * r.solar_gen_twh
        load = ne25 * r.total_generation_twh / float(t25[r.scenario])
        for pname, g in paths.items():
            k = k_now + g * max(0, r.year - 2026)
            for omr_name, omr in (("O=0", 0.0), ("O=50% of 2025", 0.5 * o25)):
                fl = max(0.0, w_ne + s_ne - load - 8.76 * k - omr)
                out.append({"scenario": r.scenario, "year": r.year, "K_path": pname, "K_gw": k, "must_run_case": omr_name, "NE_wind_pot_twh": w_ne, "NE_solar_pot_twh": s_ne, "NE_load_twh_proxy": load,
                            "floor_total_twh": fl, "floor_pct_of_NE_VRE": 100 * fl / (w_ne + s_ne), "floor_wind_twh_prorata": fl * w_ne / (w_ne + s_ne), "floor_wind_pct_of_NE_wind": 100 * fl / (w_ne + s_ne)})
    fl = pd.DataFrame(out)
    fl.to_csv(ra.tables_dir() / "task11e_capacity_floor_projection.csv", index=False)
    print("\nEnergy-balance floor, PTE years (proxy; TWh):\n", fl[fl.year >= 2030][fl.must_run_case == "O=0"].round(1).to_string())
    return fl


def part_hourly_vs_time() -> None:
    """Does a FIXED hourly dose-response curve reproduce the monthly 'time effect'? (national wind rate, 57 months; curve fitted on all hours, then on 2022-24 only)"""
    h = cm.sin_hourly("2022-01-01")
    obs = h.groupby(h.index.to_period("M"))["curt_wind"].sum() / (h.groupby(h.index.to_period("M"))[["wind", "curt_wind"]].sum().sum(axis=1))
    rows = []
    for label, train in (("fitted on all 57 months", h), ("fitted on 2022-2024 only (out-of-sample 2025-26)", h[h.index.year <= 2024])):
        p = cm.fit_binned(cm.binned(train, "r", "wind", "curt_wind"))
        pred = cm.predict_monthly(h, p, "r", "wind", "curt_wind")
        d = pd.DataFrame({"C": obs, "pred": pred})
        d["t"] = np.arange(len(d))
        d["year"] = d.index.year
        m0, m1, m2 = ols(d, ["pred"]), ols(d, ["t"]), ols(d, ["pred", "t"])
        test = d[d.year >= 2025] if "out-of-sample" in label else d
        rmse = float(np.sqrt(((test.C - test.pred) ** 2).mean()))
        rows.append({"hourly curve": label, "L": p[0], "k": p[1], "x0": p[2], "R2 pred only": m0.rsquared, "R2 t only": m1.rsquared, "R2 pred + t": m2.rsquared, "b_t (pred+t)": m2.params["t"], "p_t": m2.pvalues["t"],
                     "partial corr(C,pred|t)": partial_corr(d, "pred", "C", ["t"]), "partial corr(C,t|pred)": partial_corr(d, "t", "C", ["pred"]), "RMSE (eval months)": rmse, "mean error by year": (d.C - d.pred).groupby(d.year).mean().round(3).to_dict()})
    out = pd.DataFrame(rows)
    out.to_csv(ra.tables_dir() / "task11e_hourly_curve_vs_time.csv", index=False)
    print('\n' + "Fixed hourly curve vs time (national wind monthly rate):" + '\n', out.round(3).to_string())


def main() -> None:
    # ---- 0. reconciliation
    ne = hourly_ne()
    pw = pairwise_ne_net_export()
    j = pd.concat([ne["net_export"], pw.rename("pairwise")], axis=1).dropna()
    print(f"Reconciliation of NE net export (balance `val_intercambio` vs ONS pairwise interchange): hours={len(j)}, corr={j.net_export.corr(j.pairwise):.4f}, "
          f"annual mean MW balance/pairwise: {j.groupby(j.index.year).mean().round(0).to_dict()}")
    annual = ne.groupby(ne.index.year)[["hydro", "thermal", "wind", "solar_balance_raw", "load", "net_export"]].sum() / 1e6
    annual["gen_minus_load"] = annual.hydro + annual.thermal + annual.wind + annual.solar_balance_raw - annual["load"]
    print("Annual NE energy balance (TWh): gen - load vs reported net export\n", annual[["gen_minus_load", "net_export"]].round(2).to_string())

    df = monthly_frame()
    df.to_csv(ra.tables_dir() / "task11e_ne_monthly_transmission_frame.csv", index=False)
    cols = ["month", "P", "C", "boundary_mva", "boundary_n", "ne_km", "ne_trafo_mva", "cap_rev_mw", "export_max", "vre_pot_mw", "R_boundary", "R_revealed", "share_hours_saturated", "share_curt_in_saturated"]
    print(df[cols].iloc[[0, 6, 12, 18, 24, 30, 36, 42, 48, 54, 56]].round(2).to_string())
    print("\nstock steps: boundary MVA/lines (month of change)")
    chg = df[df.boundary_mva.diff().abs() > 0][["month", "boundary_mva", "boundary_n"]]
    print(chg.round(0).to_string())

    # ---- 1. correlations with t
    print("\ncorr with t:", {c: round(float(df[c].corr(df["t"])), 3) for c in ["C", "P", "boundary_mva", "ne_km", "ne_trafo_mva", "cap_rev_mw", "R_boundary", "R_revealed", "share_hours_saturated"]})
    print("corr with C:", {c: round(float(df[c].corr(df["C"])), 3) for c in ["t", "P", "boundary_mva", "ne_km", "ne_trafo_mva", "cap_rev_mw", "R_boundary", "R_revealed", "share_hours_saturated", "vre_pot_mw", "load_mw"]})
    for c in ("R_boundary", "R_revealed", "share_hours_saturated", "P", "boundary_mva"):
        print(f"partial corr(C,{c} | t) = {partial_corr(df.dropna(subset=[c]), c, 'C', ['t']):.3f}")
    print(f"partial corr(C,t | R_revealed) = {partial_corr(df, 't', 'C', ['R_revealed']):.3f}; partial corr(C,t | R_boundary) = {partial_corr(df, 't', 'C', ['R_boundary']):.3f}")

    # ---- 2. regressions
    reg = regressions(df)
    reg.to_csv(ra.tables_dir() / "task11e_transmission_regressions.csv", index=False)
    print("\nRegressions of C_wind(NE) (OLS, Newey-West 6 lags):\n", reg.round(4).to_string())

    # ---- 3. hourly saturation test
    h = ne.copy()
    h["year"] = h.index.year
    hh = h[h.index >= "2022-01-01"]
    tbl = []
    for y, d in hh.groupby("year"):
        sat = d["saturated"]
        tbl.append({"year": y, "curt_wind_TWh": d.curt_wind.sum() / 1e6, "share_curt_in_saturated_hours_pct": 100 * d.loc[sat, "curt_wind"].sum() / max(d.curt_wind.sum(), 1e-9),
                    "share_hours_saturated_pct": 100 * sat.mean(), "share_saturated_hours_with_curt_pct": 100 * (d.loc[sat, "curt_wind"] > 0).mean() if sat.any() else np.nan,
                    "share_other_hours_with_curt_pct": 100 * (d.loc[~sat, "curt_wind"] > 0).mean(), "mean_export_when_curt_MW": d.loc[d.curt_wind > 0, "net_export"].mean(), "cap_rev_MW": d.cap_rev.iloc[-1]})
    sat_tbl = pd.DataFrame(tbl)
    sat_tbl.to_csv(ra.tables_dir() / "task11e_export_saturation_by_year.csv", index=False)
    print("\nHourly export-saturation test (saturated = export >= 95 % of trailing 12-month max):\n", sat_tbl.round(1).to_string())
    # export near max whenever curtailment occurs?
    cu = hh[hh.curt_wind > 0.0]
    print(f"hours with NE wind curtailment: {len(cu)}; export/revealed capacity quantiles when curtailed: {(cu.net_export / cu.cap_rev).quantile([0.1, 0.25, 0.5, 0.75, 0.9]).round(2).to_dict()}; "
          f"all hours: {(hh.net_export / hh.cap_rev).quantile([0.1, 0.25, 0.5, 0.75, 0.9]).round(2).to_dict()}")

    # ---- 4. logistic with the ratio as running variable (production fitting function, D21 bounds)
    out = []
    base = df[["P", "C"]].copy()
    p = fit_calibration(base).params
    out.append(("P_NE", p, float(np.sqrt(((df.C - logistic(df.P.to_numpy(), **p)) ** 2).mean()))))
    for col in ("R_boundary", "R_revealed"):
        d = df[[col, "C"]].rename(columns={col: "P"}).dropna()
        p = fit_calibration(d).params
        out.append((col, p, float(np.sqrt(((d.C - logistic(d.P.to_numpy(), **p)) ** 2).mean()))))
    print("\nBounded logistic C = L/(1+exp(-k(x-x0))) with different running variables x (same 57 months):")
    for name, p, rmse in out:
        print(f"  x={name:12s} L={p['L']:.3f} k={p['k']:.3f} x0={p['P0']:.1f}  RMSE={rmse:.4f}")
    print(f"  reference: linear in t RMSE={float(np.sqrt((ols(df, ['t']).resid ** 2).mean())):.4f}")
    pd.DataFrame([{"x": n, **p, "rmse": r} for n, p, r in out]).to_csv(ra.tables_dir() / "task11e_ratio_logistic_fits.csv", index=False)
    part_classes_and_sin()
    part_dose_response()
    part_hourly_vs_time()
    part_floor()


if __name__ == "__main__":
    main()
