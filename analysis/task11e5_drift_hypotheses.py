"""Task 11E5-b throwaway analysis (NOT part of the installed package; no src/ change; no new data): which candidate explanation of the residual wind drift can the data in hand support?

H1  regime break (operational / dispatch rule change) versus a smooth trend: monthly residual of the pooled hourly curve, constant / linear / step (best break by scan) / saturating, compared by BIC; the break date is set against the in-data
    markers of a change in curtailment practice (month in which the constraint description 'Controle de frequencia do SIN' first appears; month in which the energy-balance class share passes 30 and 50 percent).
    No machine-readable log of ONS / ANEEL rule changes is in the acquired data: documented rule changes cannot be matched to the break and are listed as untestable here.
H2  class composition: the residual by ONS reason class (ENE = DEB, CNF = REB, REL = EUB): is the drift carried by one class?
H3  fleet composition / vintage: plant-level hourly wind (COFF, 135 plants) with capacity vintage proxied by installed capacity added since 2021-12 (val_capacidadeinstalada of the plant-level capacity-factor files, key id_ons),
    and by state. Direct standardisation at fixed r (classes of r between 20 and 40, where the drift sits): total change of the standardised rate between 2023 and 2025 / 2026 split into a WITHIN-group change and a
    COMPOSITION change (shift-share).
H4  shape of the drift: linear vs saturating vs step.
Run (after task11e5_drift_characterization.py):  python analysis/task11e5_drift_hypotheses.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

sys.path.insert(0, str(Path(__file__).resolve().parent))
import task11e2_common as c2
import task11e5_drift_characterization as ch
import task11e_common as cm
from curtailmit.paths import get_interim_dir, get_raw_dir

pd.set_option("display.width", 230)
pd.set_option("display.max_columns", 50)
REAL, CURT = c2.TECH["wind"]
PLANT_CACHE = "task11e5_plant_hourly_wind.parquet"
CAP_CACHE = "task11e5_wind_capacity_by_plant.parquet"
R_LO, R_HI = 20.0, 40.0


# ----------------------------------------------------------------------------------------------- H1 / H4: break versus trend versus saturation
def ic(y: np.ndarray, X: np.ndarray) -> dict:
    n = len(y)
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    rss = float(((y - X @ beta) ** 2).sum())
    k = X.shape[1]
    return {"rss": rss, "k": k, "aic": n * np.log(rss / n) + 2 * k, "bic": n * np.log(rss / n) + k * np.log(n), "beta": beta}


def break_vs_trend(mr: pd.DataFrame) -> pd.DataFrame:
    y, t = mr["res_pp"].to_numpy(), mr["t_years"].to_numpy()
    n = len(y)
    one = np.ones(n)
    rows = [{"model": "constant", **ic(y, np.c_[one])}, {"model": "linear trend", **ic(y, np.c_[one, t])}]
    best = None
    for b in range(9, n - 9):  # break between month b-1 and b, at least 9 months per side
        step = (np.arange(n) >= b).astype(float)
        r = ic(y, np.c_[one, step])
        if best is None or r["rss"] < best[1]["rss"]:
            best = (b, r)
    rows.append({"model": f"step at {mr.index[best[0]]}", **best[1], "break_month": str(mr.index[best[0]]), "step_pp": float(best[1]["beta"][1])})
    b2 = None
    for b in range(9, n - 9):
        step = (np.arange(n) >= b).astype(float)
        r = ic(y, np.c_[one, t, step])
        if b2 is None or r["rss"] < b2[1]["rss"]:
            b2 = (b, r)
    rows.append({"model": f"linear + step at {mr.index[b2[0]]}", **b2[1], "break_month": str(mr.index[b2[0]]), "step_pp": float(b2[1]["beta"][2])})
    best_s = None
    for tau in (0.5, 1.0, 1.5, 2.0, 3.0, 5.0):
        sat = 1 - np.exp(-t / tau)
        r = ic(y, np.c_[one, sat])
        if best_s is None or r["rss"] < best_s[1]["rss"]:
            best_s = (tau, r)
    rows.append({"model": f"saturating (tau {best_s[0]} years)", **best_s[1]})
    out = pd.DataFrame(rows).drop(columns=["beta"])
    out["dBIC_vs_linear"] = out["bic"] - out.loc[out.model == "linear trend", "bic"].iloc[0]
    # permutation p-value for the step (sup-F type): shuffle the residual in blocks of 6 months, keep the best-step RSS reduction
    rng = np.random.default_rng(3)
    obs_gain = 1 - best[1]["rss"] / rows[0]["rss"]
    cnt, nperm = 0, 500
    for _ in range(nperm):
        blocks = [y[i : i + 6] for i in range(0, n, 6)]
        rng.shuffle(blocks)
        yp = np.concatenate(blocks)
        rss0 = ((yp - yp.mean()) ** 2).sum()
        g = max(1 - ic(yp, np.c_[one, (np.arange(n) >= b).astype(float)])["rss"] / rss0 for b in range(9, n - 9))
        cnt += g >= obs_gain
    out["perm_p_step_vs_constant"] = np.nan
    out.loc[out.model.str.startswith("step"), "perm_p_step_vs_constant"] = (cnt + 1) / (nperm + 1)
    return out


def regime_markers() -> dict:
    """In-data markers of a change in curtailment practice: first month with the frequency-control description; months in which the ENE (energy balance) share passes 30 / 50 percent."""
    hp = cm.hourly_panel()
    hp = hp[(hp.ts >= "2022-01-01") & (hp.ts < cm.END_EXCLUSIVE)]
    g = hp.groupby(hp.ts.dt.to_period("M"))[["cw_ENE", "cw_CNF", "cw_REL", "cw_OTH"]].sum()
    share = g["cw_ENE"] / g.sum(axis=1).replace(0, np.nan)
    first_desc = None
    for f in sorted(get_raw_dir("ons/curtailment_wind").glob("*.parquet")):
        x = pd.read_parquet(f, columns=["din_instante", "dsc_restricao"])
        m = x["dsc_restricao"].astype("string").str.contains("requ", case=False, na=False) & x["dsc_restricao"].astype("string").str.contains("SIN", na=False)
        if m.any():
            first_desc = str(pd.to_datetime(x.loc[m, "din_instante"]).min().to_period("M"))
            break
    smooth = share.rolling(3, min_periods=1).mean()
    return {"first_month_with_frequency_control_description": first_desc, "ENE_share_pass_30pct": str(smooth[smooth > 0.30].index.min()), "ENE_share_pass_50pct": str(smooth[smooth > 0.50].index.min()),
            "ENE_share_by_year_pct": {int(y): round(100 * float(g.loc[g.index.year == y, "cw_ENE"].sum() / g.loc[g.index.year == y].sum().sum()), 1) for y in range(2022, 2027)}}


# ----------------------------------------------------------------------------------------------- H2: class decomposition
def class_residual_trends(h: pd.DataFrame) -> pd.DataFrame:
    hp = cm.hourly_panel()
    hp = hp[(hp.ts >= "2022-01-01") & (hp.ts < cm.END_EXCLUSIVE)]
    g = hp.groupby("ts")[["cw_ENE", "cw_CNF", "cw_REL", "cw_OTH"]].sum()
    d = h.join(g, how="inner")
    d["curt_other"] = d["cw_CNF"] + d["cw_REL"] + d["cw_OTH"]
    rows = []
    for lab, col in (("ENE (energy balance, DEB)", "cw_ENE"), ("CNF+REL+other (REB, EUB)", "curt_other")):
        p = c2.fit_logistic(c2.MonthBins(d, REAL, col).bins())
        gp = d.groupby(d.index.to_period("M"))
        pot = gp[[REAL, "curt_wind"]].sum().sum(axis=1)
        obs = gp[col].sum() / pot
        pred = cm.predict_monthly(d.assign(_curt_cls=d[col]), p, "r", REAL, col)
        mr = pd.DataFrame({"res_pp": 100 * (obs - pred)}, index=obs.index)
        mr["t_years"] = (mr.index.year - 2022) + (mr.index.month - 0.5) / 12
        for win, sub in (("2022-26", mr), ("2023-26", mr[mr.index.year >= 2023])):
            tr = ch.trend_with_ci(sub, n_boot=500)
            rows.append({"class": lab, "window": win, "mean_rate_pct": float(100 * obs.mean()), "slope_pp_per_year": tr["slope_pp_per_year"], "NW_CI_lo": tr["NW_CI_lo"], "NW_CI_hi": tr["NW_CI_hi"], "NW_p": tr["NW_p"]})
    return pd.DataFrame(rows)


def class_rates_by_year(h: pd.DataFrame) -> pd.DataFrame:
    hp = cm.hourly_panel()
    hp = hp[(hp.ts >= "2022-01-01") & (hp.ts < cm.END_EXCLUSIVE)]
    g = hp.groupby("ts")[["cw_ENE", "cw_CNF", "cw_REL", "cw_OTH"]].sum()
    d = h.join(g, how="inner")
    d["pot"] = d[REAL] + d["curt_wind"]
    d["bin"] = pd.cut(d["r"], [R_LO, 25, 30, 35, R_HI])
    d["year"] = d.index.year
    rows = []
    for (y, b), s in d[d["r"].between(R_LO, R_HI, inclusive="right")].groupby(["year", "bin"], observed=True):
        rows.append({"year": y, "bin": str(b), "hours": len(s), "ENE_pct": 100 * s["cw_ENE"].sum() / s["pot"].sum(), "CNF_pct": 100 * s["cw_CNF"].sum() / s["pot"].sum(),
                     "REL_pct": 100 * s["cw_REL"].sum() / s["pot"].sum(), "total_pct": 100 * s["curt_wind"].sum() / s["pot"].sum()})
    t = pd.DataFrame(rows)
    return t


# ----------------------------------------------------------------------------------------------- H3: fleet composition
def build_plants(refresh: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    p1, p2 = get_interim_dir() / PLANT_CACHE, get_interim_dir() / CAP_CACHE
    if p1.exists() and p2.exists() and not refresh:
        return pd.read_parquet(p1), pd.read_parquet(p2)
    frames = []
    for f in sorted(get_raw_dir("ons/curtailment_wind").glob("*.parquet")):
        x = pd.read_parquet(f, columns=["id_ons", "id_estado", "id_subsistema", "din_instante", "val_geracao", "val_geracaonaorealizadaapurada"])
        ts = pd.to_datetime(x["din_instante"])
        step = ts.drop_duplicates().sort_values().diff().dropna().median().total_seconds() / 3600
        x["ts"] = ts.dt.floor("h")
        x["real"] = pd.to_numeric(x["val_geracao"], errors="coerce").fillna(0.0) * step
        x["curt"] = pd.to_numeric(x["val_geracaonaorealizadaapurada"], errors="coerce").fillna(0.0) * step
        frames.append(x.groupby(["id_ons", "id_estado", "id_subsistema", "ts"], as_index=False)[["real", "curt"]].sum())
    plants = pd.concat(frames, ignore_index=True).groupby(["id_ons", "id_estado", "id_subsistema", "ts"], as_index=False)[["real", "curt"]].sum()
    plants = plants[(plants.ts >= "2022-01-01") & (plants.ts < cm.END_EXCLUSIVE)]
    caps = []
    for f in sorted(get_raw_dir("ons/capacity_factor").glob("*.parquet")):
        x = pd.read_parquet(f, columns=["id_ons", "nom_tipousina", "din_instante", "val_capacidadeinstalada"])
        x = x[x.nom_tipousina.astype(str).str.lower().str.startswith("e")]
        x["cap"] = pd.to_numeric(x.val_capacidadeinstalada, errors="coerce")
        x["m"] = pd.to_datetime(x.din_instante).dt.to_period("M").astype(str)
        caps.append(x.groupby(["id_ons", "m"], as_index=False).cap.max())
    cap = pd.concat(caps).groupby(["id_ons", "m"], as_index=False).cap.max()
    plants.to_parquet(p1)
    cap.to_parquet(p2)
    return plants, cap


def vintage_frame(plants: pd.DataFrame, cap: pd.DataFrame, h: pd.DataFrame) -> pd.DataFrame:
    base = cap[cap.m == "2021-12"].set_index("id_ons").cap
    cap = cap.assign(base=cap.id_ons.map(base).fillna(0.0))
    cap["new_share"] = ((cap.cap - cap.base).clip(lower=0) / cap.cap).clip(0, 1)
    d = plants.copy()
    d["m"] = d.ts.dt.to_period("M").astype(str)
    d = d.merge(cap[["id_ons", "m", "new_share", "cap"]], on=["id_ons", "m"], how="left")
    d["new_share"] = d["new_share"].fillna(0.0)
    d["cohort"] = pd.cut(d["new_share"], [-0.001, 0.1, 0.5, 1.0], labels=["old (<10% added)", "mixed (10-50%)", "new (>50% added)"])
    d["r"] = d.ts.map(h["r"])
    d["pot"] = d.real + d.curt
    d["year"] = d.ts.dt.year
    d["state"] = np.where(d.id_estado.isin(["BA", "RN", "PI", "CE"]), d.id_estado, "other")
    return d[d["r"].notna()]


def shift_share(d: pd.DataFrame, group: str, y0: int, y1: int) -> dict:
    """Direct standardisation at fixed r (classes between R_LO and R_HI): total = within + composition."""
    z = d[(d["r"] > R_LO) & (d["r"] <= R_HI)].copy()
    z["bin"] = pd.cut(z["r"], [R_LO, 25, 30, 35, R_HI])
    w_bin = z.groupby("bin", observed=True)["pot"].sum()
    w_bin = w_bin / w_bin.sum()

    def stats(y: int) -> tuple[pd.Series, pd.Series]:
        s = z[z.year == y]
        gb = s.groupby([group, "bin"], observed=True).agg(curt=("curt", "sum"), pot=("pot", "sum"))
        gb["rate"] = gb.curt / gb.pot
        rate = gb["rate"].unstack("bin")
        pot_g = s.groupby(group, observed=True)["pot"].sum()
        std_rate = (rate * w_bin).sum(axis=1, skipna=True) / (rate.notna() * w_bin).sum(axis=1)  # standardised rate of the group, bins renormalised where empty
        return std_rate, pot_g / pot_g.sum()

    r0, s0 = stats(y0)
    r1, s1 = stats(y1)
    idx = r0.index.intersection(r1.index)
    total = float((s1[idx] / s1[idx].sum() * r1[idx]).sum() - (s0[idx] / s0[idx].sum() * r0[idx]).sum())
    within = float((s0[idx] / s0[idx].sum() * (r1[idx] - r0[idx])).sum())
    comp = float(((s1[idx] / s1[idx].sum() - s0[idx] / s0[idx].sum()) * r1[idx]).sum())
    return {"group": group, "from": y0, "to": y1, "total_pp": 100 * total, "within_pp": 100 * within, "composition_pp": 100 * comp, "shares_from": {str(k): round(float(v), 3) for k, v in s0.items()}, "shares_to": {str(k): round(float(v), 3) for k, v in s1.items()},
            "std_rate_from_pct": {str(k): round(100 * float(v), 1) for k, v in r0.items()}, "std_rate_to_pct": {str(k): round(100 * float(v), 1) for k, v in r1.items()}}


def main() -> None:
    h = cm.sin_hourly("2022-01-01")
    T = cm.tables_dir()
    params = c2.fit_logistic(c2.MonthBins(h, REAL, CURT).bins())
    mr = ch.monthly_residual(h, params)

    print("==== H1 / H4: break vs trend vs saturation (monthly residual, 57 months) ====")
    bt = break_vs_trend(mr)
    bt.to_csv(T / "task11e5_break_vs_trend.csv", index=False)
    print(bt[["model", "k", "rss", "aic", "bic", "dBIC_vs_linear", "step_pp", "perm_p_step_vs_constant"]].round(3).to_string(index=False))
    mk = regime_markers()
    print("In-data regime markers:", mk)
    print("Residual by year (pp):", ch.annual_table(h, params)[["year", "resid_pp"]].round(2).to_dict("records"))

    print("\n==== H2: residual by ONS class ====")
    cl = class_residual_trends(h)
    cl.to_csv(T / "task11e5_class_residual_trends.csv", index=False)
    print(cl.round(3).to_string(index=False))
    cr = class_rates_by_year(h)
    cr.to_csv(T / "task11e5_class_rates_by_year.csv", index=False)
    print("Observed curtailment rate (% of potential) by class, r 20-40, by year and r class:\n", cr.pivot_table(index="bin", columns="year", values=["ENE_pct", "CNF_pct", "total_pct"]).round(1).to_string())
    tot = cr.groupby("year").apply(lambda s: pd.Series({c: np.average(s[c], weights=s["hours"]) for c in ("ENE_pct", "CNF_pct", "REL_pct", "total_pct")}), include_groups=False)
    print("hours-weighted over the four r classes (20-40):\n", tot.round(2).to_string())

    print("\n==== H3: fleet vintage and state composition (plant level) ====")
    plants, cap = build_plants()
    print(f"plant-hour frame: {len(plants):,} rows, {plants.id_ons.nunique()} plants; capacity table {cap.id_ons.nunique()} plants; match of COFF plants in the capacity table: {100 * plants.id_ons.drop_duplicates().isin(cap.id_ons).mean():.1f} %")
    vf = vintage_frame(plants, cap, h)
    fleet = vf.groupby("year").apply(lambda s: pd.Series({"potential_share_new_cohort_pct": 100 * s.loc[s.cohort == "new (>50% added)", "pot"].sum() / s.pot.sum(), "potential_share_mixed_pct": 100 * s.loc[s.cohort == "mixed (10-50%)", "pot"].sum() / s.pot.sum(),
                                                         "mean_new_share_pct": 100 * np.average(s.new_share, weights=s.pot)}), include_groups=False)
    print("Fleet vintage by year (potential-weighted):\n", fleet.round(1).to_string())
    rows = []
    for grp in ("cohort", "state"):
        for y0, y1 in ((2023, 2025), (2023, 2026), (2024, 2026)):
            rows.append(shift_share(vf, grp, y0, y1))
    ss = pd.DataFrame(rows)
    ss.drop(columns=["shares_from", "shares_to", "std_rate_from_pct", "std_rate_to_pct"]).to_csv(T / "task11e5_shift_share.csv", index=False)
    print("Shift-share of the change of the standardised wind curtailment rate at r 20-40 (pp):\n", ss[["group", "from", "to", "total_pp", "within_pp", "composition_pp"]].round(2).to_string(index=False))
    for r_ in rows:
        if (r_["from"], r_["to"]) == (2023, 2026):
            print(f"  {r_['group']} 2023 -> 2026: shares {r_['shares_from']} -> {r_['shares_to']}; standardised rates % {r_['std_rate_from_pct']} -> {r_['std_rate_to_pct']}")


if __name__ == "__main__":
    main()
