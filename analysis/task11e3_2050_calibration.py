"""Task 11E3-b throwaway analysis (NOT part of the installed package; no src/ change): extrapolation-distance calibration of the 2030/2040/2050 uncertainty of option E.

Steps: (1) distance of the PTE-scaled hourly conditions (same proxy as Task 11E2-a) to the FULL training sample (2022-01..2026-09), with the same metrics as task11e3_error_growth
(E_out, H_out, D_pp); (2) the credibility rule fixed in task11e3_error_growth.py BEFORE the results were seen; (3) an indicative empirical band: the distribution of log(pred/obs) of the historical
splits whose E_out lies within +-0.15 of the target (obs = pred x exp(-err), so band = central x exp(-q95) .. central x exp(-q05)), only where at least MIN_NEIGHBOURS splits from at least
MIN_QUARTERS different test quarters exist; (4) comparison with the 11B / 11D / 11E / 11E2 wind figures; (5) the 2030 / 2040 sanity check (the band should be narrow where the horizon is in-sample).
A band is labelled "calibrated" only if the rule passes; otherwise it is reported as "indicative" and 2050 stays a qualitative / conditional range.
Run (after task11e3_error_growth.py, task11e_wind_envelope.py and task11e2_options_table.py):  python analysis/task11e3_2050_calibration.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import task11e2_common as c2
import task11e3_error_growth as eg
import task11e_common as cm

pd.set_option("display.width", 230)
pd.set_option("display.max_columns", 60)
NEIGHBOUR_WIDTH = 0.15
MIN_NEIGHBOURS = 15
MIN_QUARTERS = 4
RULE_MIN_BLOCKS, RULE_MIN_YEARS, RULE_BEYOND = 25, 3, 1.25


def full_sample_curves(h: pd.DataFrame) -> dict[str, dict]:
    out = {}
    for tech in eg.TECHS:
        d, real, curt = eg.prepare(h, tech)
        bins = c2.MonthBins(d, real, curt).bins()
        out[tech] = {"params": c2.fit_logistic(bins), "r_cap": c2.r_cap_of(bins, c2.MIN_HOURS)}
    return out


def target_metrics(h: pd.DataFrame, curves: dict[str, dict]) -> pd.DataFrame:
    prof = c2.base_profile(h)
    pte = c2.load_pte()
    rows = []
    for sc in c2.SCENARIOS:
        for year in c2.YEARS:
            f = c2.scale_factors(pte, sc, year)
            r = c2.projected_r(prof, f)
            pots = {"wind": prof["W"] * f["a_wind"], "solar": prof["S"] * f["a_solar"]}
            pots["unified"] = pots["wind"] + pots["solar"]
            for tech in eg.TECHS:
                c = curves[tech]
                dm = eg.distance_metrics(r, pots[tech], c["params"], c["r_cap"])
                gen = {"wind": f["wind_gen_twh"], "solar": f["solar_gen_twh"], "unified": f["wind_gen_twh"] + f["solar_gen_twh"]}[tech]
                rate = c2.projected_rate(r, pots[tech], c["params"])
                rows.append({"scenario": sc, "year": year, "tech": tech, **dm, "rate": rate, "central_twh": rate * gen})
    return pd.DataFrame(rows)


def rule_check(rel: dict, tm: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for tech in eg.TECHS:
        r = rel[tech]
        slope_ci = r["ci90"]["b"]
        c1 = bool(slope_ci[0] > 0 or slope_ci[1] < 0)
        n_ok = bool(r["n_quarters"] >= RULE_MIN_BLOCKS and r["n_years"] >= RULE_MIN_YEARS)
        for year in (2040, 2050):
            t = tm[(tm.tech == tech) & (tm.year == year)]
            c2e = bool((t["E_out"] <= RULE_BEYOND * r["E_out_range"][1]).all())
            c2d = bool((t["D_pp"] <= RULE_BEYOND * r["D_pp_range"][1]).all())
            rows.append({"tech": tech, "year": year, "(1) slope CI excludes 0": c1, "slope_b": r["b"], "slope_CI90": f"{slope_ci[0]:.2f}..{slope_ci[1]:.2f}", "R2": r["R2"],
                         "(2a) E_out within range x1.25": c2e, "target_E_out_max": float(t["E_out"].max()), "hist_E_out_max": r["E_out_range"][1],
                         "(2b) D_pp within range x1.25": c2d, "target_D_pp_max": float(t["D_pp"].max()), "hist_D_pp_max": r["D_pp_range"][1],
                         "(3) >=25 blocks and >=3 years": n_ok, "n_quarters": r["n_quarters"], "PASS": bool(c1 and c2e and c2d and n_ok)})
    return pd.DataFrame(rows)


def neighbour_band(splits: pd.DataFrame, e_target: float, central: float) -> dict:
    nb = splits[(splits.E_out >= e_target - NEIGHBOUR_WIDTH) & (splits.E_out <= e_target + NEIGHBOUR_WIDTH)]
    if len(nb) < MIN_NEIGHBOURS or nb.test_quarter.nunique() < MIN_QUARTERS:
        return {"n_nb": len(nb), "n_q": nb.test_quarter.nunique(), "band_low": np.nan, "band_high": np.nan, "err_q05": np.nan, "err_q50": np.nan, "err_q95": np.nan, "note": "insufficient neighbours"}
    q05, q50, q95 = np.percentile(nb["err_log"], [5, 50, 95])
    return {"n_nb": len(nb), "n_q": nb.test_quarter.nunique(), "err_q05": float(q05), "err_q50": float(q50), "err_q95": float(q95), "band_low": central * float(np.exp(-q95)), "band_median": central * float(np.exp(-q50)),
            "band_high": central * float(np.exp(-q05)), "note": ""}


def main() -> None:
    h = cm.sin_hourly("2022-01-01")
    T = cm.tables_dir()
    rel = json.load(open(T / "task11e3_error_growth_relations.json"))
    splits = {t: pd.read_csv(T / f"task11e3_splits_{t}.csv") for t in eg.TECHS}
    curves = full_sample_curves(h)
    tm = target_metrics(h, curves)
    tm.to_csv(T / "task11e3_target_distance.csv", index=False)
    print("Full-sample curves:", {t: (tuple(round(x, 3) for x in c["params"]), round(c["r_cap"], 1)) for t, c in curves.items()})
    piv = tm.pivot_table(index=["scenario", "year"], columns="tech", values=["E_out", "H_out", "D_pp"])
    print("\nDistance of the PTE-scaled hourly conditions to the full 2022-2026 training sample:\n", piv.round(3).to_string())
    print("\nHistorical split ranges:", {t: {"E_out": [round(x, 2) for x in rel[t]["E_out_range"]], "D_pp": [round(x, 1) for x in rel[t]["D_pp_range"]], "quarters": rel[t]["n_quarters"], "years": rel[t]["n_years"]} for t in eg.TECHS})

    rc = rule_check(rel, tm)
    rc.to_csv(T / "task11e3_credibility_rule.csv", index=False)
    print("\n==== Credibility rule (fixed before the results) ====\n", rc.round(3).to_string(index=False))

    rows = []
    for _, r in tm.iterrows():
        b = neighbour_band(splits[r.tech], r.E_out, r.central_twh)
        rows.append({**r.to_dict(), **b})
    bands = pd.DataFrame(rows)
    rule_pass = rc.set_index(["tech", "year"])["PASS"]
    bands["label"] = [("calibrated" if bool(rule_pass.get((t, y), False)) else "indicative (rule failed)") if not np.isnan(lo) else "insufficient evidence" for t, y, lo in zip(bands.tech, bands.year, bands.band_low, strict=True)]
    pte = c2.load_pte().set_index(["scenario", "year"])
    cap = {"wind": "wind_gen_twh", "solar": "solar_gen_twh"}
    bands["cap_twh"] = [float(pte.loc[(s, y), cap[t]]) if t in cap else float(pte.loc[(s, y), "wind_gen_twh"] + pte.loc[(s, y), "solar_gen_twh"]) for s, y, t in zip(bands.scenario, bands.year, bands.tech, strict=True)]
    bands["band_high_capped"] = np.minimum(bands["band_high"], bands["cap_twh"])
    bands["above_physical_cap"] = bands["band_high"] > bands["cap_twh"]
    bands.to_csv(T / "task11e3_calibrated_bands.csv", index=False)
    show = bands[["scenario", "year", "tech", "E_out", "D_pp", "central_twh", "n_nb", "n_q", "err_q05", "err_q50", "err_q95", "band_low", "band_high", "label"]]
    print("\n==== Empirical neighbour band (TWh; err = ln(pred/obs); band = central x exp(-q95) .. exp(-q05)) ====\n", show.round(2).to_string(index=False))

    # comparison with earlier wind figures (TWh)
    wp = pd.read_csv(T / "task11e2_wind_projection.csv")
    wp = wp[wp.phi == 1.0].set_index(["scenario", "year"])
    comp = []
    for sc in c2.SCENARIOS:
        for year in c2.YEARS:
            w = bands[(bands.scenario == sc) & (bands.year == year) & (bands.tech == "wind")].iloc[0]
            row = {"scenario": sc, "year": year, "11B_low": wp.loc[(sc, year), "11B_national_low"], "11B_central": wp.loc[(sc, year), "11B_national_central"], "11B_high": wp.loc[(sc, year), "11B_national_high"],
                   "11D_point": wp.loc[(sc, year), "11D_regional_central"], "11E_low": wp.loc[(sc, year), "11E_envelope_low"], "11E_high": wp.loc[(sc, year), "11E_envelope_high"],
                   "E_central": w.central_twh, "calib_low": w.band_low, "calib_high": w.band_high}
            row["11E_width_ratio"] = row["11E_high"] / row["11E_low"]
            row["calib_width_ratio"] = row["calib_high"] / row["calib_low"] if not np.isnan(row["calib_low"]) else np.nan
            row["calib_covers_11B_central"] = bool(row["calib_low"] <= row["11B_central"] <= row["calib_high"]) if not np.isnan(row["calib_low"]) else None
            row["calib_covers_11E_high"] = bool(row["calib_low"] <= row["11E_high"] <= row["calib_high"]) if not np.isnan(row["calib_low"]) else None
            comp.append(row)
    comp = pd.DataFrame(comp)
    comp.to_csv(T / "task11e3_wind_band_comparison.csv", index=False)
    print("\n==== Wind: calibrated / indicative band vs earlier figures (TWh) ====\n", comp.round(2).to_string(index=False))

    print("\nNeighbour bands above the physical cap (curtailed <= PTE generation, gross reading):", int(bands["above_physical_cap"].sum()), "of", int(bands["band_high"].notna().sum()), "; 2050 wind:",
          bands[(bands.tech == "wind") & (bands.year == 2050)][["scenario", "band_high", "cap_twh"]].round(0).to_dict("records"))

    # descriptive error band from the ANNUAL backtests of Task 11E2-b in the regime closest to the projections (test years 2025-2026): truth = pred / (1 + err)
    bt = pd.read_csv(T / "task11e2_backtest_annual.csv")
    bt["yr"] = bt["period"].astype(str).str[:4].astype(int)
    fac = {}
    for tech in ("wind", "solar"):
        e = bt[(bt.tech == tech) & (bt.yr >= 2025) & (bt.scheme != "train 2022-23 -> test 2024, 2025, 2026")]["hourly_err_pct"] / 100
        fac[tech] = (float(1 / (1 + e.max())), float(1 / (1 + e.min())), len(e), float(e.min()), float(e.max()))
    print("\nAnnual-backtest error band (test years 2025-26, excluding the 2022-23-trained split): truth / pred factor", {k: tuple(round(x, 3) for x in v[:2]) for k, v in fac.items()}, " n =", {k: v[2] for k, v in fac.items()},
          " err range", {k: (round(v[3], 3), round(v[4], 3)) for k, v in fac.items()})
    ab = []
    for sc in c2.SCENARIOS:
        for year in c2.YEARS:
            w = bands[(bands.scenario == sc) & (bands.year == year) & (bands.tech == "wind")].iloc[0].central_twh
            s = bands[(bands.scenario == sc) & (bands.year == year) & (bands.tech == "solar")].iloc[0].central_twh
            ab.append({"scenario": sc, "year": year, "wind_central": w, "solar_central": s, "total_central": w + s, "wind_low": w * fac["wind"][0], "wind_high": w * fac["wind"][1], "solar_low": s * fac["solar"][0], "solar_high": s * fac["solar"][1],
                       "total_low": w * fac["wind"][0] + s * fac["solar"][0], "total_high": w * fac["wind"][1] + s * fac["solar"][1]})
    ab = pd.DataFrame(ab)
    ab.to_csv(T / "task11e3_annual_backtest_band.csv", index=False)
    print("\nAnnual-backtest error band applied to the E central (TWh; descriptive, NOT a prediction interval; meaningful for in-sample horizons only):\n", ab.round(1).to_string(index=False))

    # total (wind + solar): wind indicative band + solar at central (labelled), for the options table
    opt = pd.read_csv(T / "task11e2_options_table.csv")
    tot = []
    for sc in c2.SCENARIOS:
        for year in (2030, 2040, 2050):
            w = bands[(bands.scenario == sc) & (bands.year == year) & (bands.tech == "wind")].iloc[0]
            s = bands[(bands.scenario == sc) & (bands.year == year) & (bands.tech == "solar")].iloc[0]
            o = opt[(opt.scenario == sc) & (opt.year == year)].iloc[0]
            tot.append({"scenario": sc, "year": year, "E_central_total": o.E_central, "wind_E_out": w.E_out, "solar_E_out": s.E_out, "wind_band_low": w.band_low, "wind_band_high": w.band_high,
                        "solar_band_low": s.band_low, "solar_band_high": s.band_high, "total_low_if_both": (w.band_low + s.band_low) if not np.isnan(s.band_low) else np.nan,
                        "total_high_if_both": (w.band_high + s.band_high) if not np.isnan(s.band_high) else np.nan, "total_low_wind_band_solar_central": w.band_low + s.central_twh, "total_high_wind_band_solar_central": w.band_high + s.central_twh})
    tot = pd.DataFrame(tot)
    tot.to_csv(T / "task11e3_total_band.csv", index=False)
    print("\n==== Total (wind + solar), TWh ====\n", tot.round(1).to_string(index=False))


if __name__ == "__main__":
    main()
