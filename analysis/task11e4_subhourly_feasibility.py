"""Task 11E4-c throwaway analysis (NOT part of the installed package; no src/ change): is the hourly aggregation hiding extreme instantaneous VRE-share-of-load conditions?

What exists (probed 2026-10-26, see docs/task11e4_findings.md):
  - COFF wind / solar plant files (already in raw/ons/curtailment_*): 30-minute per plant, generation (val_geracao), reference generation and curtailment since 2022 (wind) / 2024-04 (solar);
    the hourly frame of Task 11E sums them to the hour (task11e_common._curtailment_hourly).
  - Verified load, semi-hourly per load area (API https://apicarga.ons.org.br/prd/cargaverificada, areas N / NE / S / SE; area 'SIN' returns zeros): ACQUIRED here for 2025 only (feasibility sample).
  - DESSEM balance (balanco_dessem_geral / _detalhe): semi-hourly but PROGRAMMED (day-ahead) values since 2025-05-23, not realized: not used.
  - COFF intra-half-hour packages (coff_*_intrasemihora): restriction periods inside the half-hour (finer than 30 min); listed, not used.
Test: build the 30-minute potential VRE share of load r30 = (wind + solar generation + curtailment of the COFF plants) / verified load, compare its distribution with the same quantity aggregated to the hour (r1h), and
compare how well the dose-response curve explains 30-minute curtailment when driven by r30 versus r1h.
D27 trigger rule (fixed before the results): D27 is registered only if (i) the 30-minute p99.9 or maximum of r exceeds the hourly one by >= 10 percent (relative) AND (ii) driving the curve with r30 lowers the 30-minute
unexplained curtailment variance by >= 15 percent (relative) with respect to r1h. Otherwise the result is negative / inconclusive and D27 is not registered.
Run:  python analysis/task11e4_subhourly_feasibility.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import task11e2_common as c2
import task11e_common as cm
from curtailmit.ons_mmgd_probe import ProbeError, acquire_mmgd_load
from curtailmit.paths import get_interim_dir, get_raw_dir

pd.set_option("display.width", 230)
pd.set_option("display.max_columns", 50)
AREAS = ["N", "NE", "S", "SE"]
YEAR = 2025
CACHE = "task11e4_subhourly_2025.parquet"
UTC_OFFSET_H = 3  # Brazil, no DST since 2019: local = UTC - 3 h
EMPTY: list[str] = []  # (area, month) requests that returned no records


def acquire_load(year: int = YEAR) -> list[Path]:
    """One request per month and area (the same API function used in the Task 10 MMGD probe); cached on disk with a manifest per file."""
    files = []
    for m in range(1, 13):
        start = pd.Timestamp(year=year, month=m, day=1)
        end = start + pd.offsets.MonthEnd(0)
        for area in AREAS + ["SECO"]:  # the Southeast / Center-West area is published as 'SE' until 2025-04 and as 'SECO' from 2025-05 (found in this probe); the API answers an empty list for the retired code
            try:
                out = acquire_mmgd_load([area], start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), use_cache=True)
                files += list(out.values())
            except ProbeError:
                EMPTY.append(f"{area} {start:%Y-%m}")
    return files


def load_30min(files: list[Path]) -> pd.DataFrame:
    rows = []
    for f in files:
        rows.append(pd.DataFrame(json.loads(Path(f).read_text(encoding="utf-8-sig"))))
    d = pd.concat(rows, ignore_index=True)
    d["cod_areacarga"] = d["cod_areacarga"].replace({"SECO": "SE"})
    # the API stamp is the END of the half-hour in UTC (first record of a day is 00:30 local); convert to local period START to match the COFF stamps
    d["ts"] = pd.to_datetime(d["din_referenciautc"], utc=True).dt.tz_localize(None) - pd.Timedelta(hours=UTC_OFFSET_H) - pd.Timedelta(minutes=30)
    d = d.drop_duplicates(["cod_areacarga", "ts"], keep="last")
    return d.pivot(index="ts", columns="cod_areacarga", values="val_cargaglobal").sort_index()


def coff_30min(tech: str, year: int = YEAR) -> pd.DataFrame:
    """Per-area 30-minute realized generation and curtailment (MW) of the COFF plants."""
    name = "curtailment_wind" if tech == "wind" else "curtailment_solar"
    frames = []
    for f in sorted(get_raw_dir(f"ons/{name}").glob("*.parquet")):
        if not (f.stem[-7:-3] == str(year) or str(year) in f.stem):
            continue
        x = pd.read_parquet(f, columns=["id_subsistema", "din_instante", "val_geracao", "val_geracaonaorealizadaapurada"])
        x["ts"] = pd.to_datetime(x["din_instante"])
        x["area"] = x["id_subsistema"].astype(str).str.strip()
        x["real"] = pd.to_numeric(x["val_geracao"], errors="coerce").fillna(0.0)
        x["curt"] = pd.to_numeric(x["val_geracaonaorealizadaapurada"], errors="coerce").fillna(0.0)
        frames.append(x.groupby(["ts", "area"], as_index=False)[["real", "curt"]].sum())
    d = pd.concat(frames, ignore_index=True).groupby(["ts", "area"], as_index=False)[["real", "curt"]].sum()
    return d[(d.ts.dt.year == year)]


def build_panel(refresh: bool = False) -> pd.DataFrame:
    path = get_interim_dir() / CACHE
    if path.exists() and not refresh:
        return pd.read_parquet(path)
    load = load_30min(acquire_load())
    out = []
    for tech in ("wind", "solar"):
        d = coff_30min(tech).pivot(index="ts", columns="area", values=["real", "curt"])
        d.columns = [f"{tech}_{a}_{b}" for a, b in ((x[0], x[1]) for x in d.columns)]
        out.append(d)
    cf = pd.concat(out, axis=1).fillna(0.0)
    panel = cf.join(load.add_prefix("load_"), how="inner")
    panel.to_parquet(path)
    return panel


def series(panel: pd.DataFrame, areas: list[str]) -> pd.DataFrame:
    """30-minute frame for a set of areas: wind / solar realized and curtailed MW, load MW, r30 (%)."""
    g = lambda pre: sum(panel.get(f"{pre}_{a}", 0.0) for a in areas)  # noqa: E731
    d = pd.DataFrame({"wind_real": g("wind_real"), "wind_curt": g("wind_curt"), "solar_real": g("solar_real"), "solar_curt": g("solar_curt")}, index=panel.index)
    d["load"] = sum(panel[f"load_{a}"] for a in areas)
    d["pot"] = d.wind_real + d.wind_curt + d.solar_real + d.solar_curt
    d["r30"] = 100 * d["pot"] / d["load"]
    h = d.groupby(d.index.floor("h"))[["pot", "load"]].mean()
    d["r1h"] = (100 * h["pot"] / h["load"]).reindex(d.index.floor("h")).to_numpy()
    return d


def distribution(d: pd.DataFrame, label: str) -> dict:
    row = {"scope": label, "n30": len(d)}
    for c in ("r30", "r1h"):
        q = d[c].quantile([0.5, 0.95, 0.99, 0.999])
        row.update({f"{c}_p50": q[0.5], f"{c}_p95": q[0.95], f"{c}_p99": q[0.99], f"{c}_p999": q[0.999], f"{c}_max": d[c].max()})
    row["max_ratio"] = row["r30_max"] / row["r1h_max"]
    row["p999_ratio"] = row["r30_p999"] / row["r1h_p999"]
    row["share_gt60_30"], row["share_gt60_1h"] = float((d.r30 > 60).mean()), float((d.r1h > 60).mean())
    return row


def dose_response_gain(d: pd.DataFrame, tech: str) -> dict:
    """30-minute curtailment explained by the logistic of r30 vs of r1h (same fitting recipe; unexplained variance = weighted SSE of the rate, share of the total weighted variance)."""
    real, curt = f"{tech}_real", f"{tech}_curt"
    z = d.copy()
    z["pot_t"] = z[real] + z[curt]
    z = z[z.pot_t > 0]
    res = {}
    for xcol in ("r30", "r1h"):
        mb = c2.MonthBins(z, real, curt, xcol=xcol)
        p = c2.fit_logistic(mb.bins())
        rate = z[curt] / z.pot_t
        pred = cm.logistic_w(z[xcol].to_numpy(), *p)
        w = z.pot_t.to_numpy()
        sse = float((w * (rate - pred) ** 2).sum())
        sst = float((w * (rate - np.average(rate, weights=w)) ** 2).sum())
        res[xcol] = {"params": p, "unexplained": sse / sst}
    return {"tech": tech, "unexplained_r30": res["r30"]["unexplained"], "unexplained_r1h": res["r1h"]["unexplained"], "relative_reduction": 1 - res["r30"]["unexplained"] / res["r1h"]["unexplained"],
            "params_r30": res["r30"]["params"], "params_r1h": res["r1h"]["params"]}


def main() -> None:
    panel = build_panel()
    print(f"30-minute panel 2025: {len(panel)} rows {panel.index.min()}..{panel.index.max()}; columns {len(panel.columns)}")
    sin, ne = series(panel, AREAS), series(panel, ["NE"])
    # coverage check of the COFF-plant generation against the ONS balance (hourly, 2025) and of the verified load against the balance load
    hp = cm.hourly_panel()
    hp = hp[hp.ts.dt.year == YEAR].groupby("ts")[["wind", "solar_disp", "load"]].sum()
    h1 = sin[["wind_real", "solar_real", "load"]].groupby(sin.index.floor("h")).mean()
    cmp_ = pd.DataFrame({"wind_coff_over_balance": h1.wind_real.sum() / hp.wind.sum(), "solar_coff_over_dispatched": h1.solar_real.sum() / hp.solar_disp.sum(), "verified_load_over_balance_load": h1.load.sum() / hp["load"].sum()}, index=[0])
    print("\nCoverage (annual ratios, 2025, SIN):\n", cmp_.round(3).to_string(index=False))
    rr = (100 * (h1.wind_real + h1.solar_real) / h1.load)
    print("corr of the 30-min-panel hourly realized-VRE share with the main hourly panel (realized basis):", round(float(rr.corr(100 * (hp.wind + hp.solar_disp) / hp["load"])), 4))
    dist = pd.DataFrame([distribution(sin, "SIN (N+NE+S+SE)"), distribution(ne, "NE")])
    dist.to_csv(cm.tables_dir() / "task11e4_subhourly_distribution.csv", index=False)
    print("\nDistribution of r (%), 30-minute vs hourly aggregation of the same data, 2025:\n", dist.round(3).T.to_string())
    gains = pd.DataFrame([dose_response_gain(sin, "wind"), dose_response_gain(sin, "solar")])
    gains.to_csv(cm.tables_dir() / "task11e4_subhourly_dose_response.csv", index=False)
    print("\nDose-response, SIN, 30-minute targets: unexplained share of weighted variance with r30 vs r1h:\n", gains.round(3).to_string(index=False))
    # within-hour spread: how different are the two halves of an hour?
    pair = sin.groupby(sin.index.floor("h"))["r30"].agg(["min", "max"])
    spread = (pair["max"] - pair["min"])
    print(f"\nWithin-hour spread of r30 (max - min of the two half-hours, SIN): median {spread.median():.2f} pp, p99 {spread.quantile(0.99):.2f} pp, max {spread.max():.2f} pp")
    rule_i = bool(max(dist.max_ratio.iloc[0], dist.p999_ratio.iloc[0]) >= 1.10)
    rule_ii = bool(gains.relative_reduction.max() >= 0.15)
    print(f"\nD27 rule: (i) 30-min p99.9 or max >= 1.10 x hourly: {rule_i} (SIN max ratio {dist.max_ratio.iloc[0]:.3f}, p99.9 ratio {dist.p999_ratio.iloc[0]:.3f}); (ii) unexplained variance reduced >= 15 %: {rule_ii} "
          f"(wind {gains.relative_reduction.iloc[0]:.3f}, solar {gains.relative_reduction.iloc[1]:.3f}). D27 triggered: {rule_i and rule_ii}")
    sizes = {p.name: p.stat().st_size for p in (get_raw_dir("ons/mmgd")).glob("cargaverificada_*_2025-*.json")}
    print(f"\nAcquired sample: {len(sizes)} JSON files, {sum(sizes.values()) / 1e6:.1f} MB (2025, 4 areas, 12 months)")


if __name__ == "__main__":
    main()
