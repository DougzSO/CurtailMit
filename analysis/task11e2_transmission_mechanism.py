"""Task 11E2-d throwaway analysis (NOT part of the installed package; no src/ change): what do the ONS curtailment reason classes say about the mechanism (export-bound or not)?

Sources, all already in DATABASE_ROOT/raw (no acquisition): COFF wind and solar curtailment files (half-hourly per plant, 2022-2026-09) with
  cod_razaorestricao  ENE / CNF / REL  -> mapped in the project (D5, Task 4) to DEB / REB / EUB (energy-surplus / reliability / external unavailability)
  cod_origemrestricao SIS / LOC        (system / local origin of the constraint)
  dsc_restricao       free-text description of the constraint (present in about half of the curtailed energy)
plus the NE net export of the ONS balance (hourly) for the 11E saturation test (export >= 95 % of its trailing 12-month maximum).
Outputs: reason class x origin x year x subsystem; a keyword classification of the free-text description into the constrained element (system frequency; interchange flow control;
SE-side network element; NE-internal network; outage; other); the cross with export saturation; and an upper bound on the share of NE wind curtailment that can depend on interchange.
The description classifier is keyword based and approximate (labelled as such); the code classes are ONS's own.
Run:  python analysis/task11e2_transmission_mechanism.py
"""

from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import task11e_common as cm

pd.set_option("display.width", 230)
pd.set_option("display.max_columns", 50)
D5 = {"ENE": "DEB", "CNF": "REB", "REL": "EUB"}
SAT_FRAC = 0.95
NE_KEYS = ("IO-ON.NE", "ACU III", "JAGUARUANA", "QUIXADA", "MILAGRES", "PACATUBA", "IRECE", "MORRO DO CHAPEU", "BAHIA SUDOESTE", "SENHOR DO BONFIM", "CURRAL NOVO", "CAMPINA GRANDE",
           "CEARA MIRIM", "BARREIRAS", "BURITIRAMA", "SOBRADINHO", "SAO JOAO DO PIAUI", "COLINAS", "RIBEIRO GONCALVES", "ALAGOINHAS", "XINGU")
SE_KEYS = ("IO-ON.SE", "RIO NOVO DO SUL", "ITABIRA", "CAMPOS", "VESPASIANO", "NEVES")
CATS = ["system_frequency", "interchange_flow_control", "SE_side_network", "NE_internal_network", "outage_other", "other_named", "no_description"]


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().upper()


def classify_description(desc) -> str:
    """Keyword classification of the ONS free-text constraint description (approximate)."""
    if desc is None or (isinstance(desc, float) and np.isnan(desc)) or str(desc).strip() in ("", "<NA>", "nan"):
        return "no_description"
    s = _norm(str(desc))
    if "FREQUENCIA" in s:
        return "system_frequency"
    if s.startswith("CONTROLE DO FLUXO") or re.search(r"\bFNESE\b|\bFNS\b|\bFNE\b", s):
        return "interchange_flow_control"
    if any(k in s for k in SE_KEYS):
        return "SE_side_network"
    if any(k in s for k in NE_KEYS):
        return "NE_internal_network"
    if s.startswith("DESLIGAMENTO") or "PERDA DA" in s or "INDISPONIBILIDADE" in s:
        return "outage_other"
    return "other_named"


def load_rows() -> pd.DataFrame:
    frames = []
    for tech, d in (("wind", "curtailment_wind"), ("solar", "curtailment_solar")):
        for f in sorted(cm.get_raw_dir(f"ons/{d}").glob("*.parquet")):
            x = pd.read_parquet(f, columns=["id_subsistema", "din_instante", "val_geracaonaorealizadaapurada", "cod_razaorestricao", "cod_origemrestricao", "dsc_restricao"])
            ts = pd.to_datetime(x["din_instante"])
            step_h = ts.drop_duplicates().sort_values().diff().dropna().median().total_seconds() / 3600
            x["mwh"] = pd.to_numeric(x["val_geracaonaorealizadaapurada"], errors="coerce").fillna(0.0) * step_h
            x = x[(x.mwh > 0) & (ts < cm.END_EXCLUSIVE)].copy()
            x["ts"] = ts[x.index].dt.floor("h") if x.index.is_unique else pd.to_datetime(x["din_instante"]).dt.floor("h")
            x["sub"] = x["id_subsistema"].astype(str).str.strip()
            x["reason"] = x["cod_razaorestricao"].astype("string").str.strip().str.upper().fillna("NONE")
            x["origin"] = x["cod_origemrestricao"].astype("string").str.strip().str.upper().fillna("NONE")
            x["klass"] = x["reason"].map(D5).fillna("UNCLASSIFIED")
            x["year"] = x["ts"].dt.year
            uniq = x["dsc_restricao"].dropna().unique()
            m = {u: classify_description(u) for u in uniq}
            x["cat"] = x["dsc_restricao"].map(m).fillna("no_description")
            x["tech"] = tech
            frames.append(x[["ts", "year", "sub", "tech", "reason", "klass", "origin", "cat", "mwh", "dsc_restricao"]])
    return pd.concat(frames, ignore_index=True)


def ne_saturation_flags() -> pd.DataFrame:
    hp = cm.hourly_panel()
    ne = hp[hp["sub"] == "NE"].set_index("ts").sort_index()
    out = pd.DataFrame({"net_export": ne["net_export"]})
    out["cap_rev"] = out["net_export"].rolling(24 * 365, min_periods=24 * 90).max()
    out["saturated"] = out["net_export"] >= SAT_FRAC * out["cap_rev"]
    out["export_ratio"] = out["net_export"] / out["cap_rev"]
    return out


def shares(df: pd.DataFrame, by: list[str], col: str) -> pd.DataFrame:
    t = df.groupby(by + [col])["mwh"].sum().unstack(col).fillna(0.0) / 1e6
    t["total_twh"] = t.sum(axis=1)
    for c in [c for c in t.columns if c != "total_twh"]:
        t[f"{c}_%"] = 100 * t[c] / t["total_twh"]
    return t


def main() -> None:
    x = load_rows()
    T = cm.tables_dir()
    print(f"curtailment rows with energy: {len(x):,}; total {x.mwh.sum() / 1e6:.2f} TWh (wind {x[x.tech == 'wind'].mwh.sum() / 1e6:.2f}, solar {x[x.tech == 'solar'].mwh.sum() / 1e6:.2f})")
    print("unclassified (no reason code) energy share:", round(100 * x[x.klass == "UNCLASSIFIED"].mwh.sum() / x.mwh.sum(), 4), "%")

    # ---- 1. DEB/REB/EUB by year and subsystem (wind, solar) and origin
    for tech in ("wind", "solar"):
        d = x[x.tech == tech]
        by_year = shares(d, ["year"], "klass")
        by_year.to_csv(T / f"task11e2_reason_by_year_{tech}.csv")
        print(f"\n==== {tech}: curtailed energy by ONS class (DEB = ENE energy surplus, REB = CNF reliability, EUB = REL external unavailability), TWh and % ====\n", by_year.round(2).to_string())
        by_sub = shares(d, ["sub"], "klass")
        by_sub.to_csv(T / f"task11e2_reason_by_subsystem_{tech}.csv")
        print(f"\n{tech}: by subsystem (all years)\n", by_sub.round(2).to_string())
        by_sy = shares(d[d["sub"] == "NE"], ["year"], "klass")
        print(f"\n{tech}: NE only, by year\n", by_sy[[c for c in by_sy.columns if c.endswith('%') or c == 'total_twh']].round(1).to_string())
        org = shares(d[d["sub"] == "NE"], ["year"], "origin")
        org.to_csv(T / f"task11e2_origin_by_year_{tech}_NE.csv")
        print(f"\n{tech} NE: origin (SIS system / LOC local) by year, %\n", org[[c for c in org.columns if c.endswith('%') or c == 'total_twh']].round(1).to_string())
    cross = shares(x[(x.tech == "wind") & (x["sub"] == "NE")], ["klass"], "origin")
    print("\nWind NE: class x origin (TWh, % within class)\n", cross.round(2).to_string())
    cross.to_csv(T / "task11e2_class_by_origin_wind_NE.csv")

    # ---- 2. what element is constrained (keyword classes of the description)
    w = x[(x.tech == "wind") & (x["sub"] == "NE")]
    cat_year = shares(w, ["year"], "cat")
    cat_year.to_csv(T / "task11e2_constraint_element_by_year_wind_NE.csv")
    print("\nWind NE: constrained element (keyword classes), % of curtailed energy by year\n", cat_year[[c for c in cat_year.columns if c.endswith('%') or c == 'total_twh']].round(1).to_string())
    cat_class = shares(w, ["klass"], "cat")
    cat_class.to_csv(T / "task11e2_constraint_element_by_class_wind_NE.csv")
    print("\nWind NE: constrained element within each ONS class, TWh and %\n", cat_class.round(2).to_string())
    resid = w[w.cat == "other_named"].assign(d=lambda z: z.dsc_restricao.astype(str).str[:100]).groupby("d").mwh.sum().sort_values(ascending=False).head(8) / 1e6
    print("\nLargest descriptions left in 'other_named' (TWh):\n", resid.round(3).to_string())
    for tech in ("solar",):
        s = x[(x.tech == tech) & (x["sub"].isin(["NE", "SE"]))]
        print(f"\n{tech}: constrained element, % of curtailed energy by subsystem\n", shares(s, ["sub"], "cat")[[c for c in shares(s, ['sub'], 'cat').columns if c.endswith('%') or c == 'total_twh']].round(1).to_string())

    # ---- 3. cross with export saturation (NE wind, hourly)
    sat = ne_saturation_flags()
    ww = w.merge(sat[["saturated", "export_ratio"]], left_on="ts", right_index=True, how="left")
    ww = ww[ww["saturated"].notna()]
    rows = []
    for key, g in ww.groupby("cat"):
        e = g.mwh
        rows.append({"element": key, "twh": e.sum() / 1e6, "share_of_NE_wind_%": 100 * e.sum() / ww.mwh.sum(), "share_in_saturated_hours_%": 100 * e[g.saturated].sum() / e.sum(),
                     "median_export_ratio": float(np.median(np.repeat(g.export_ratio.to_numpy(), np.maximum((e / e.max() * 50).round().astype(int).to_numpy(), 1))))})
    for key, g in ww.groupby("klass"):
        e = g.mwh
        rows.append({"element": f"class {key}", "twh": e.sum() / 1e6, "share_of_NE_wind_%": 100 * e.sum() / ww.mwh.sum(), "share_in_saturated_hours_%": 100 * e[g.saturated].sum() / e.sum(),
                     "median_export_ratio": float(np.median(np.repeat(g.export_ratio.to_numpy(), np.maximum((e / e.max() * 50).round().astype(int).to_numpy(), 1))))})
    sat_tbl = pd.DataFrame(rows)
    sat_tbl.to_csv(T / "task11e2_element_vs_saturation_wind_NE.csv", index=False)
    print("\nNE wind curtailment: by constrained element / class, share in export-saturated hours (>=95 % of trailing 12-month max) and (weighted) median export / revealed capacity\n", sat_tbl.round(2).to_string(index=False))

    # ---- 4. bounds on the interchange-dependent share
    tot = w.mwh.sum()
    e = w.groupby("cat").mwh.sum()
    described = tot - e.get("no_description", 0.0)
    bound_lo = (e.get("interchange_flow_control", 0.0)) / tot
    bound_hi = (e.get("interchange_flow_control", 0.0) + e.get("SE_side_network", 0.0) + e.get("no_description", 0.0) * 0.0) / tot
    bound_hi_alldescr_unknown = (e.get("interchange_flow_control", 0.0) + e.get("SE_side_network", 0.0) + e.get("no_description", 0.0) * (1 - e.get("system_frequency", 0.0) / max(described, 1e-9))) / tot
    ene_share = w[w.klass == "DEB"].mwh.sum() / tot
    print(f"\nNE wind curtailment {tot / 1e6:.2f} TWh. Described {100 * described / tot:.1f} %. Directly interchange-linked (flow controls) {100 * bound_lo:.1f} %; flow controls + SE-side network elements {100 * bound_hi:.1f} % of all NE wind curtailment "
          f"({100 * (e.get('interchange_flow_control', 0.0) + e.get('SE_side_network', 0.0)) / described:.1f} % of the described part). DEB (energy-surplus class) {100 * ene_share:.1f} %. "
          f"Upper bound if the undescribed energy were split like the described non-frequency part: {100 * bound_hi_alldescr_unknown:.1f} %.")
    rows = [{"period": "2022-2026 (all years; descriptions exist only from 2025)", "ne_wind_twh": tot / 1e6, "described_share_%": 100 * described / tot, "interchange_flow_%": 100 * bound_lo, "interchange_flow_plus_SE_side_%": 100 * bound_hi,
             "DEB_share_%": 100 * ene_share, "upper_bound_%": 100 * bound_hi_alldescr_unknown}]
    for yrs, lab in (([2025], "2025"), ([2026], "2026 (Jan-Sep; 100 % described)")):
        wy = w[w.year.isin(yrs)]
        ey = wy.groupby("cat").mwh.sum()
        ty = wy.mwh.sum()
        dy = ty - ey.get("no_description", 0.0)
        rows.append({"period": lab, "ne_wind_twh": ty / 1e6, "described_share_%": 100 * dy / ty, "interchange_flow_%": 100 * ey.get("interchange_flow_control", 0.0) / ty,
                     "interchange_flow_plus_SE_side_%": 100 * (ey.get("interchange_flow_control", 0.0) + ey.get("SE_side_network", 0.0)) / ty, "NE_internal_network_%": 100 * ey.get("NE_internal_network", 0.0) / ty,
                     "system_frequency_%": 100 * ey.get("system_frequency", 0.0) / ty, "DEB_share_%": 100 * wy[wy.klass == "DEB"].mwh.sum() / ty,
                     "transmission_network_total_%": 100 * (ey.get("interchange_flow_control", 0.0) + ey.get("SE_side_network", 0.0) + ey.get("NE_internal_network", 0.0)) / ty})
    bounds = pd.DataFrame(rows)
    bounds.to_csv(T / "task11e2_interchange_dependent_bounds.csv", index=False)
    print("\nShare of NE wind curtailment by constrained element (descriptions only exist from 2025):\n", bounds.round(1).T.to_string())

    try:
        figure(x)
    except Exception as exc:  # noqa: BLE001
        print("figure failed:", exc)


def figure(x: pd.DataFrame) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    w = x[(x.tech == "wind") & (x["sub"] == "NE")]
    fig, ax = plt.subplots(1, 2, figsize=(14, 4.8))
    a = (w.groupby(["year", "klass"]).mwh.sum().unstack().fillna(0) / 1e6)
    a.plot.bar(stacked=True, ax=ax[0], color={"DEB": "tab:blue", "REB": "tab:orange", "EUB": "tab:green", "UNCLASSIFIED": "0.6"})
    ax[0].set(ylabel="NE wind curtailment (TWh)", title="ONS class by year (DEB energy / REB reliability / EUB external unavailability)", xlabel="")
    b = (w.groupby(["year", "cat"]).mwh.sum().unstack().reindex(columns=CATS).fillna(0) / 1e6)
    b.plot.bar(stacked=True, ax=ax[1], colormap="tab20")
    ax[1].set(ylabel="NE wind curtailment (TWh)", title="Constrained element (keyword classes of dsc_restricao)", xlabel="")
    ax[1].legend(fontsize=7)
    fig.tight_layout()
    p = Path(cm.figs_dir()) / "task11e2_transmission_mechanism.png"
    fig.savefig(p, dpi=130)
    print("figure:", p)


if __name__ == "__main__":
    main()
