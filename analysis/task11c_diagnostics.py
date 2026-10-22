"""Task 11C throwaway diagnostics (NOT part of the installed package, no unit tests).

Descriptive only: no curve is fitted, no pipeline module is changed. Writes CSV tables and PNG figures under DATABASE_ROOT/outputs and prints
the numbers quoted in docs/task11c_investigation_report.md.

Parts:
  basis  - (a) PTE 2025 vs ONS observed realized/potential generation, ONS capacity factors, gross-vs-net formula sensitivity at the 11B central C.
  region - (c) curtailment by subsystem, DEB/REB/EUB vs national P, subsystem P vs national P as predictors.
Run:  python analysis/task11c_diagnostics.py [basis|region|all]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from curtailmit.paths import get_outputs_dir, get_processed_dir, get_raw_dir  # noqa: E402

SUBSYSTEMS = ["N", "NE", "S", "SE"]
CROSSWALK_FILE = "classification_available.json"
pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 40)


def tables_dir() -> Path:
    return get_outputs_dir("tables")


def figs_dir() -> Path:
    return get_outputs_dir("figures")


# ----------------------------------------------------------------------------------------------- loaders
def load_coff_monthly() -> pd.DataFrame:
    """Curtailed energy (MWh) per month x technology x subsystem x state x reason x origin from the raw COFF files."""
    rows = []
    for tech, sub in (("wind", "curtailment_wind"), ("solar", "curtailment_solar")):
        for f in sorted(get_raw_dir(f"ons/{sub}").glob("*.parquet")):
            df = pd.read_parquet(f, columns=["id_subsistema", "id_estado", "din_instante", "val_geracaonaorealizadaapurada", "cod_razaorestricao", "cod_origemrestricao"])
            ts = pd.to_datetime(df["din_instante"])
            interval = ts.drop_duplicates().sort_values().diff().dropna().median().total_seconds() / 3600
            df["id_subsistema"] = df["id_subsistema"].astype(str).str.strip()
            df["mwh"] = pd.to_numeric(df["val_geracaonaorealizadaapurada"], errors="coerce").fillna(0.0) * interval
            df["month"] = ts.dt.to_period("M")
            df["last_ts"] = ts
            g = df.groupby(["month", "id_subsistema", "id_estado", "cod_razaorestricao", "cod_origemrestricao"], dropna=False, observed=True)["mwh"].sum().reset_index()
            g["tech"] = tech
            g["file_last_ts"] = ts.max()
            rows.append(g)
    out = pd.concat(rows, ignore_index=True)
    out["cod_razaorestricao"] = out["cod_razaorestricao"].astype("string").str.strip().str.upper()
    return out


def load_balance_by_subsystem() -> pd.DataFrame:
    frames = []
    for f in sorted(get_raw_dir("ons/generation_by_source").glob("Balanco_de_Energia_Subsistema-*.parquet")):
        year = int(f.stem[-4:])
        if year < 2021:
            continue
        df = pd.read_parquet(f)
        df["id_subsistema"] = df["id_subsistema"].astype(str).str.strip()  # some years pad the code ("N  ")
        df = df[df["id_subsistema"].isin(SUBSYSTEMS)].copy()
        for c in ("val_gerhidraulica", "val_gertermica", "val_gereolica", "val_gersolar", "val_carga"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df["month"] = pd.to_datetime(df["din_instante"]).dt.to_period("M")
        frames.append(df.groupby(["month", "id_subsistema"], observed=True)[["val_gerhidraulica", "val_gertermica", "val_gereolica", "val_gersolar", "val_carga"]].sum().reset_index())
    out = pd.concat(frames, ignore_index=True)  # hourly MW summed over hours = MWh
    return out.rename(columns={"val_gerhidraulica": "hydro", "val_gertermica": "thermal", "val_gereolica": "wind", "val_gersolar": "solar_balance_raw", "val_carga": "load"})


def load_dispatched_solar_by_subsystem() -> pd.DataFrame:
    frames = []
    for f in sorted(get_raw_dir("ons/capacity_factor").glob("*.parquet")):
        df = pd.read_parquet(f, columns=["id_subsistema", "nom_tipousina", "din_instante", "val_geracaoverificada"])
        df["id_subsistema"] = df["id_subsistema"].astype(str).str.strip()
        tipo = df["nom_tipousina"].astype(str).str.lower()
        df = df[tipo.str.startswith("solar")].copy()
        df["mwh"] = pd.to_numeric(df["val_geracaoverificada"], errors="coerce").fillna(0.0)
        df["month"] = pd.to_datetime(df["din_instante"]).dt.to_period("M")
        frames.append(df.groupby(["month", "id_subsistema"], observed=True)["mwh"].sum().reset_index())
    out = pd.concat(frames, ignore_index=True)
    return out.groupby(["month", "id_subsistema"], as_index=False)["mwh"].sum().rename(columns={"mwh": "solar_dispatched"})


def national_frame() -> pd.DataFrame:
    f = pd.read_parquet(get_processed_dir() / "calibration_frame.parquet")
    f["month"] = pd.PeriodIndex([pd.Period(year=y, month=m, freq="M") for y, m in zip(f.year, f.month)], freq="M")
    return f.set_index("month")


# ----------------------------------------------------------------------------------------------- (a)
def part_basis() -> None:
    print("\n==== (a) gross vs net basis ====")
    nat = national_frame()
    for y in (2022, 2023, 2024, 2025):
        s = nat[nat.index.year == y]
        print(y, "wind realized TWh", round(s.wind_gen_mwh.sum() / 1e6, 2), "wind curtailed", round(s.curt_wind_mwh.sum() / 1e6, 2),
              "solar(disp) realized", round(s.solar_gen_mwh.sum() / 1e6, 2), "solar curtailed", round(s.curt_solar_mwh.sum() / 1e6, 2))
    s25 = nat[nat.index.year == 2025]
    print("2025 ONS wind realized/potential TWh", s25.wind_gen_mwh.sum() / 1e6, (s25.wind_gen_mwh + s25.curt_wind_mwh).sum() / 1e6)
    bal = load_balance_by_subsystem()
    b25 = bal[bal.month.dt.year == 2025]
    print("2025 balance solar incl MMGD (4 subsystems) TWh", b25.solar_balance_raw.sum() / 1e6, " + solar curtailed", s25.curt_solar_mwh.sum() / 1e6)
    print("2025 SIN total generation TWh", (b25[["hydro", "thermal", "wind", "solar_balance_raw"]].sum().sum()) / 1e6)

    # observed ONS capacity factors (centralized, dispatched plants)
    cfs = []
    for f in sorted(get_raw_dir("ons/capacity_factor").glob("*2025-*.parquet")):
        df = pd.read_parquet(f, columns=["nom_tipousina", "id_ons", "din_instante", "val_geracaoverificada", "val_capacidadeinstalada"])
        df["gen"] = pd.to_numeric(df["val_geracaoverificada"], errors="coerce")
        df["cap"] = pd.to_numeric(df["val_capacidadeinstalada"], errors="coerce")
        df["tipo"] = np.where(df["nom_tipousina"].astype(str).str.lower().str.startswith("solar"), "solar", "wind")
        hourly = df.groupby(["tipo", "din_instante"])[["gen", "cap"]].sum().reset_index()
        cfs.append(hourly.groupby("tipo")[["gen", "cap"]].sum().assign(file=f.name))
    cf = pd.concat(cfs).groupby(level=0)[["gen", "cap"]].sum()
    cf["cf_realized"] = cf.gen / cf.cap
    print("ONS 2025 realized capacity factor (dispatched wind/solar):", cf.cf_realized.round(3).to_dict())

    proj = pd.read_parquet(get_processed_dir() / "pte_curtailment_two_curves.parquet")
    rows = []
    for r in proj.itertuples():
        for tech, gen, c in (("wind", r.wind_gen_twh, r.C_wind_central), ("solar", r.solar_gen_twh, r.C_solar_central)):
            gross = gen * c
            net = gen * c / (1 - c)
            rows.append({"scenario": r.scenario, "year": r.year, "tech": tech, "P": r.P, "generation_twh": gen, "C_central": c,
                         "E_curt_if_gross": gross, "E_curt_if_net": net, "implied_potential_if_net": gen / (1 - c), "ratio_net_over_gross": net / gross})
    sens = pd.DataFrame(rows)
    sens.to_csv(tables_dir() / "task11c_gross_vs_net_sensitivity.csv", index=False)
    print(sens[sens.year >= 2040].round(2).to_string())
    for tech, ratio_cf in (("wind", cf.loc["wind", "cf_realized"]), ("solar", cf.loc["solar", "cf_realized"])):
        for r in proj[proj.year.isin([2025, 2050])].itertuples():
            gen = r.wind_gen_twh if tech == "wind" else r.solar_gen_twh
            print(tech, r.scenario, r.year, "implied installed GW at ONS-2025 realized CF", round(gen * 1e3 / 8.76 / ratio_cf / 1.0, 1) if False else round(gen * 1e6 / 8760 / ratio_cf / 1000, 1))


# ----------------------------------------------------------------------------------------------- (c)
def spearman(a: pd.Series, b: pd.Series) -> float:
    return float(pd.concat([a, b], axis=1).dropna().rank().corr().iloc[0, 1])


def part_region() -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    print("\n==== (c) regional / mechanism diagnostic ====")
    nat = national_frame()
    coff = load_coff_monthly()
    coff = coff[coff.month.isin(nat.index)]  # the same complete months as the calibration
    bal = load_balance_by_subsystem()
    disp = load_dispatched_solar_by_subsystem()
    cw = json.loads((get_processed_dir() / CROSSWALK_FILE).read_text(encoding="utf-8"))["crosswalk"]
    cls_map = {k: v for k, v in cw["wind"].items() if v}
    coff["klass"] = coff["cod_razaorestricao"].map({"ENE": "DEB", "CNF": "REB", "REL": "EUB"})  # crosswalk of Task 4 (D17); PAR/blank -> none

    # ---- 1. subsystem breakdown
    sub_year = coff.groupby([coff.month.dt.year.rename("year"), "tech", "id_subsistema"], observed=True)["mwh"].sum().unstack("id_subsistema").fillna(0)
    sub_year["total"] = sub_year.sum(axis=1)
    share = sub_year[SUBSYSTEMS].div(sub_year["total"], axis=0)
    print("Curtailed TWh by year x tech x subsystem:\n", (sub_year / 1e6).round(2).to_string())
    print("Share of curtailed energy by subsystem:\n", (100 * share).round(1).to_string())
    gen_w = bal.assign(year=bal.month.dt.year).groupby(["year", "id_subsistema"])["wind"].sum().unstack().reindex(columns=SUBSYSTEMS)
    gen_s = disp.assign(year=disp.month.dt.year).groupby(["year", "id_subsistema"])["solar_dispatched"].sum().unstack().reindex(columns=SUBSYSTEMS).fillna(0)
    rate_rows = []
    for (y, tech), r in sub_year.iterrows():
        gen = (gen_w if tech == "wind" else gen_s).loc[y]
        for s in SUBSYSTEMS:
            c = r[s]
            g = gen[s]
            rate_rows.append({"year": y, "tech": tech, "subsystem": s, "curtailed_twh": c / 1e6, "generation_twh": g / 1e6, "share_of_curtailment_pct": 100 * c / r["total"] if r["total"] else np.nan,
                              "share_of_generation_pct": 100 * g / gen.sum() if gen.sum() else np.nan, "rate_pct": 100 * c / (c + g) if (c + g) > 0 else np.nan})
    rates = pd.DataFrame(rate_rows)
    rates.to_csv(tables_dir() / "task11c_subsystem_year_tech.csv", index=False)
    print(rates.round(2).to_string())

    # origin (SIS = system-wide / LOC = local network) and states
    org = coff.groupby(["tech", "cod_origemrestricao"], dropna=False, observed=True)["mwh"].sum().unstack("cod_origemrestricao").fillna(0)
    print("Curtailed TWh by origin code:\n", (org / 1e6).round(2).to_string())
    org_year = coff.groupby([coff.month.dt.year.rename("year"), "cod_origemrestricao"], observed=True)["mwh"].sum().unstack().fillna(0)
    print("Origin share by year (%):", (100 * org_year.div(org_year.sum(axis=1), axis=0)).round(1).to_string())
    xt = coff.groupby(["klass", "cod_origemrestricao"], dropna=False, observed=True)["mwh"].sum().unstack().fillna(0) / 1e6
    print("Class x origin (TWh):", xt.round(2).to_string())
    print("Calibration months:", len(nat), "solar-observed months:", int((nat.scope == "wind_solar").sum()))
    st = coff.groupby(["id_subsistema", "id_estado"], observed=True)["mwh"].sum().sort_values(ascending=False) / 1e6
    print("Top states (TWh):\n", st.head(8).round(2).to_string())

    # ---- 2. DEB vs REB vs EUB vs national P
    cm = coff.groupby(["month", "klass"], dropna=False, observed=True)["mwh"].sum().unstack("klass").reindex(nat.index).fillna(0)
    cm["total"] = cm.sum(axis=1)
    potential = nat.wind_gen_mwh + nat.curt_wind_mwh + np.where(nat.scope == "wind_solar", nat.solar_gen_mwh + nat.curt_solar_mwh, 0.0)
    class_rate = pd.DataFrame({k: 100 * cm[k] / potential for k in ("DEB", "REB", "EUB")})
    class_rate["total"] = 100 * cm["total"] / potential
    class_rate["P"] = nat.P
    class_rate["scope"] = nat.scope
    yearly = cm.groupby(cm.index.year)[["DEB", "REB", "EUB"]].sum()
    yearly_share = 100 * yearly.div(yearly.sum(axis=1), axis=0)
    print("DEB/REB/EUB TWh per year:\n", (yearly / 1e6).round(2).to_string())
    print("DEB/REB/EUB share per year (%):\n", yearly_share.round(1).to_string())
    corr = {k: {"spearman_vs_P": round(spearman(class_rate[k], class_rate["P"]), 3), "pearson_vs_P": round(float(class_rate[k].corr(class_rate["P"])), 3),
                "slope_pp_per_1pp_P": round(float(np.polyfit(class_rate["P"], class_rate[k], 1)[0]), 3)} for k in ("DEB", "REB", "EUB", "total")}
    print("class rate (% of potential generation) vs national P:\n", pd.DataFrame(corr).T.to_string())
    early, late = class_rate[class_rate.P < class_rate.P.median()], class_rate[class_rate.P >= class_rate.P.median()]
    print("mean class rate (pp) below / above median P:", early[["DEB", "REB", "EUB"]].mean().round(2).to_dict(), late[["DEB", "REB", "EUB"]].mean().round(2).to_dict())
    class_rate.to_csv(tables_dir() / "task11c_class_rate_vs_P.csv")
    yearly_share.to_csv(tables_dir() / "task11c_class_share_by_year.csv")

    # ---- 3. subsystem P vs national P as predictors of subsystem curtailment rate
    b = bal.set_index(["month", "id_subsistema"])
    d = disp.set_index(["month", "id_subsistema"])["solar_dispatched"]
    b = b.join(d).fillna({"solar_dispatched": 0.0})
    b["total_gen"] = b.hydro + b.thermal + b.wind + b.solar_dispatched
    b["P_sub"] = 100 * (b.wind + b.solar_dispatched) / b.total_gen
    b["P_vs_load"] = 100 * (b.wind + b.solar_dispatched) / b["load"]
    cc = coff.groupby(["month", "id_subsistema", "tech"], observed=True)["mwh"].sum().unstack("tech").fillna(0).reindex(columns=["wind", "solar"]).fillna(0)
    cc.columns = ["curt_wind", "curt_solar"]
    z = b.join(cc, how="inner")
    z = z[z.index.get_level_values("month").isin(nat.index)].copy()
    solar_obs = z.index.get_level_values("month") >= nat.index[nat.scope == "wind_solar"].min()
    z["potential"] = z.wind + z.curt_wind + np.where(solar_obs, z.solar_dispatched + z.curt_solar, 0.0)
    z["rate_pct"] = 100 * (z.curt_wind + np.where(solar_obs, z.curt_solar, 0.0)) / z.potential
    z["P_nat"] = [nat.loc[m, "P"] for m in z.index.get_level_values("month")]
    z = z.reset_index()
    z.to_csv(tables_dir() / "task11c_subsystem_monthly.csv", index=False)
    out = []
    for s in SUBSYSTEMS + ["ALL"]:
        zz = z if s == "ALL" else z[z.id_subsistema == s]
        out.append({"subsystem": s, "n": len(zz), "mean_rate_pct": zz.rate_pct.mean(), "max_rate_pct": zz.rate_pct.max(), "P_sub_range": f"{zz.P_sub.min():.0f}-{zz.P_sub.max():.0f}",
                    "spearman_rate_vs_P_sub": spearman(zz.rate_pct, zz.P_sub), "spearman_rate_vs_P_nat": spearman(zz.rate_pct, zz.P_nat),
                    "spearman_rate_vs_P_load": spearman(zz.rate_pct, zz.P_vs_load), "pearson_rate_vs_P_sub": float(zz.rate_pct.corr(zz.P_sub)), "pearson_rate_vs_P_nat": float(zz.rate_pct.corr(zz.P_nat))})
    cmp_ = pd.DataFrame(out)
    cmp_.to_csv(tables_dir() / "task11c_subsystem_vs_national_P.csv", index=False)
    print(cmp_.round(3).to_string())
    # variance explained by a simple linear fit of the rate on each P (indicative, in-sample)
    for s in ["NE", "ALL"]:
        zz = z if s == "ALL" else z[z.id_subsistema == s]
        for col in ("P_sub", "P_nat"):
            r2 = float(np.corrcoef(zz[col], zz.rate_pct)[0, 1] ** 2)
            print(f"R2 linear rate~{col} [{s}] = {r2:.3f}")

    # ---- figures
    fig, ax = plt.subplots(1, 3, figsize=(16, 4.5))
    for s, c in zip(SUBSYSTEMS, ["tab:green", "tab:red", "tab:blue", "tab:orange"]):
        zz = z[z.id_subsistema == s]
        ax[0].scatter(zz.P_nat, zz.rate_pct, s=14, label=s, color=c)
        ax[1].scatter(zz.P_sub, zz.rate_pct, s=14, label=s, color=c)
    ax[0].set(xlabel="national P (%)", ylabel="subsystem curtailment rate (%)", title="rate vs national P")
    ax[1].set(xlabel="subsystem P (%)", ylabel="subsystem curtailment rate (%)", title="rate vs subsystem P")
    ax[0].legend()
    for k, c in zip(("DEB", "REB", "EUB"), ["tab:red", "tab:blue", "tab:gray"]):
        ax[2].scatter(class_rate.P, class_rate[k], s=14, label=k, color=c)
    ax[2].set(xlabel="national P (%)", ylabel="class rate (% of potential generation)", title="DEB / REB / EUB vs national P")
    ax[2].legend()
    fig.tight_layout()
    fig.savefig(figs_dir() / "task11c_regional_diagnostics.png", dpi=130)
    fig2, ax2 = plt.subplots(figsize=(9, 4))
    bottom = np.zeros(len(yearly_share))
    for k, c in zip(("DEB", "REB", "EUB"), ["tab:red", "tab:blue", "tab:gray"]):
        ax2.bar(yearly_share.index.astype(str), yearly_share[k], bottom=bottom, label=k, color=c)
        bottom += yearly_share[k].to_numpy()
    ax2.set(ylabel="share of curtailed energy (%)", title="Class share by year"); ax2.legend()
    fig2.tight_layout(); fig2.savefig(figs_dir() / "task11c_class_share.png", dpi=130)
    print("figures:", figs_dir() / "task11c_regional_diagnostics.png", figs_dir() / "task11c_class_share.png")


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("basis", "all"):
        part_basis()
    if which in ("region", "all"):
        part_region()
