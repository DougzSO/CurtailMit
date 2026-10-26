"""Task 11F-2 one-off script (NOT part of the installed package): extract the golden reference values for the regression tests of the production option-E code.

Writes tests/fixtures/option_e/ :
  hourly_sample_2025H1.csv   the first half of the real 2025 SIN hourly panel (4,344 rows: wind, solar_disp, curt_wind, curt_solar, load, r) - public ONS data aggregated to the SIN
  golden.json                (a) reference values read from the COMMITTED analysis artifacts in outputs/tables (task11e2/e3/e4 CSV) for the full-sample integration test;
                             (b) outputs of the PROTOTYPE functions (analysis/task11e_common, task11e2_common, task11e3_error_growth, task11e4_conformal_prediction) on the sample and on a
                                 seeded synthetic panel, which the default test suite compares with the production functions.
Run (needs the local DATABASE_ROOT and the analysis tables):  python analysis/task11f_extract_golden.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import task11e2_common as c2
import task11e3_error_growth as eg
import task11e4_conformal_prediction as cp
import task11e_common as cm

FIX = HERE.parent / "tests" / "fixtures" / "option_e"


def synthetic_panel(seed: int = 7) -> pd.DataFrame:
    """Seeded 48-month hourly SIN-like panel with a known logistic curtailment (MUST stay identical to tests/test_hourly_model.py::synthetic_panel)."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2022-01-01", "2025-12-31 23:00", freq="h")
    n = len(idx)
    t = np.linspace(0.0, 1.0, n)
    hour = idx.hour.to_numpy()
    load = 60000 + 12000 * np.sin(2 * np.pi * (hour - 14) / 24) + rng.normal(0, 1500, n)
    wind = 20000 * (0.4 + 1.3 * t) * (0.6 + 0.5 * np.sin(2 * np.pi * idx.dayofyear.to_numpy() / 365)) * rng.lognormal(0, 0.25, n)
    solar = 9000 * (0.3 + 1.4 * t) * np.clip(np.sin(np.pi * (hour - 6) / 12), 0, None) * rng.lognormal(0, 0.15, n)
    r = 100 * (wind + solar) / load
    rate_w = 0.7 / (1 + np.exp(-0.14 * (r - 41)))
    rate_s = 0.74 / (1 + np.exp(-0.10 * (r - 42)))
    df = pd.DataFrame({"wind": wind * (1 - rate_w), "curt_wind": wind * rate_w, "solar_disp": solar * (1 - rate_s), "curt_solar": solar * rate_s, "load": load, "r": r}, index=idx)
    return df


def main() -> None:
    FIX.mkdir(parents=True, exist_ok=True)
    T = cm.tables_dir()
    h = cm.sin_hourly("2022-01-01")
    cols = ["wind", "solar_disp", "curt_wind", "curt_solar", "load", "r"]
    sample = h[(h.index >= "2025-01-01") & (h.index < "2025-07-01")][cols]
    sample.to_csv(FIX / "hourly_sample_2025H1.csv", float_format="%.10g")
    sample = pd.read_csv(FIX / "hourly_sample_2025H1.csv", index_col=0, parse_dates=True)  # exactly what the tests will read back

    g: dict = {}
    # ---------------------------------------------------------------- (b1) prototype on the real sample
    pte = pd.DataFrame({"scenario": ["TA"] * 2, "year": [2025, 2040], "wind_gen_twh": [60.0, 150.0], "solar_gen_twh": [40.0, 120.0], "total_generation_twh": [800.0, 1100.0]})
    s = {}
    for tech in ("wind", "solar"):
        mb = c2.MonthBins(sample, *c2.TECH[tech])
        bins = mb.bins()
        params = c2.fit_logistic(bins)
        params1 = c2.fit_logistic(bins, L_fixed=1.0)
        s[tech] = {"params": list(params), "params_L1": list(params1), "r_cap": c2.r_cap_of(bins), "n_bins_populated": int((bins.hours >= 15).sum()), "bins_x": bins.x.tolist(), "bins_rate": bins.rate.tolist(), "bins_hours": bins.hours.tolist()}
    prof = c2.base_profile(sample, 2025)
    f = c2.scale_factors(pte, "TA", 2040)
    r = c2.projected_r(prof, f)
    r15 = c2.projected_r(prof, f, 1.5)
    s["projection_2040"] = {"a_wind": f["a_wind"], "a_solar": f["a_solar"], "a_load": f["a_load"], "r_sum": float(r.sum()), "r_flex_sum": float(r15.sum())}
    for tech, pot, gen in (("wind", prof["W"] * f["a_wind"], f["wind_gen_twh"]), ("solar", prof["S"] * f["a_solar"], f["solar_gen_twh"])):
        p = tuple(s[tech]["params"])
        s["projection_2040"][tech] = {"rate": c2.projected_rate(r, pot, p), "rate_capped": c2.projected_rate(r, pot, p, s[tech]["r_cap"]), "rate_flex": c2.projected_rate(r15, pot, p),
                                      "rate_L1": c2.projected_rate(r, pot, tuple(s[tech]["params_L1"])), "dist": eg.distance_metrics(r, pot, p, s[tech]["r_cap"])}
    g["sample"] = s

    # ---------------------------------------------------------------- (b2) prototype on the synthetic panel
    syn = synthetic_panel()
    q = {"checksum": float(syn.to_numpy().sum()), "splits": {}, "conformal_logq": {}, "curves": {}}
    for tech in ("wind", "solar", "unified"):
        sp = eg.run_splits(syn, tech)
        sp = sp[sp.family.isin(cp.TEMPORAL)].reset_index(drop=True)
        q["splits"][tech] = sp[["family", "test_quarter", "train_months", "obs_twh", "pred_twh", "err_log"]].to_dict("list")
        w = cp.quarter_weights(sp)
        q["conformal_logq"][tech] = cp.weighted_quantile_conformal(np.abs(sp["err_log"].to_numpy()), w, 1.0, 0.2) if len(sp) else None
        d, real, curt = eg.prepare(syn, tech)
        bins = c2.MonthBins(d, real, curt).bins()
        q["curves"][tech] = {"params": list(c2.fit_logistic(bins)), "r_cap": c2.r_cap_of(bins), "n_months": int(len(c2.MonthBins(d, real, curt).months))}
    rng = np.random.default_rng(3)
    sc, wt = rng.normal(0, 1, 40), rng.uniform(0.2, 1.0, 40)
    q["wqc"] = {"scores": np.abs(sc).tolist(), "weights": wt.tolist(), "alpha": 0.2, "q": cp.weighted_quantile_conformal(np.abs(sc), wt, 1.0, 0.2), "q_infeasible": cp.weighted_quantile_conformal(np.abs(sc[:3]), wt[:3], 1.0, 0.1)}
    g["synthetic"] = q

    # ---------------------------------------------------------------- (a) committed analysis artifacts, full sample
    cur = pd.read_csv(T / "task11e2_wind_solar_curves.csv")
    g["full_curves"] = {"wind": cur.iloc[0][["L", "k", "x0", "r_cap15"]].astype(float).to_dict(), "solar": cur.iloc[2][["L", "k", "x0", "r_cap15"]].astype(float).to_dict()}
    iv = pd.read_csv(T / "task11e4_conformal_intervals_2030_2040.csv")
    g["full_conformal_logq80"] = {t: float(iv[iv.tech == t]["q80_sym_logq"].iloc[0]) for t in ("wind", "solar", "unified")}
    ab = pd.read_csv(T / "task11e3_annual_backtest_band.csv")
    r0 = ab.iloc[0]
    g["full_band_factors"] = {"wind": [float(r0.wind_low / r0.wind_central), float(r0.wind_high / r0.wind_central)], "solar": [float(r0.solar_low / r0.solar_central), float(r0.solar_high / r0.solar_central)]}
    td = pd.read_csv(T / "task11e3_target_distance.csv")
    ct = pd.read_csv(T / "task11e4_conformal_total_2030_2040.csv")
    opt = pd.read_csv(T / "task11e2_options_table.csv")
    rows = []
    for _, a in ab.iterrows():
        sc_, yr = a.scenario, int(a.year)
        o = opt[(opt.scenario == sc_) & (opt.year == yr)].iloc[0]
        row = {"scenario": sc_, "year": yr, "E_wind": a.wind_central, "E_solar": a.solar_central, "E_total": a.total_central, "wind_low": a.wind_low, "wind_high": a.wind_high, "solar_low": a.solar_low, "solar_high": a.solar_high,
               "flex_phi15_total": float(o["E_central_phi1.5"]), "L1_total": float(o.E_high_L1), "in_support_total": float(o.E_in_support_twh)}
        for t in ("wind", "solar"):
            e = td[(td.scenario == sc_) & (td.year == yr) & (td.tech == t)].iloc[0]
            row.update({f"E_out_{t}": float(e.E_out), f"H_out_{t}": float(e.H_out), f"D_pp_{t}": float(e.D_pp)})
            if yr in (2030, 2040):
                c = iv[(iv.scenario == sc_) & (iv.year == yr) & (iv.tech == t)].iloc[0]
                row.update({f"conf_{t}_lo": float(c.q80_sym_lo), f"conf_{t}_hi": float(c.q80_sym_hi)})
        rows.append(row)
    g["full_projection"] = rows
    g["note"] = "Generated by analysis/task11f_extract_golden.py from the committed Task 11E2-11E4 tables and the prototype functions; do not edit by hand."
    (FIX / "golden.json").write_text(json.dumps(g, indent=1), encoding="utf-8")
    print("wrote", FIX, "sample rows", len(sample), "synthetic splits", {k: len(v["family"]) for k, v in q["splits"].items()}, "logq", q["conformal_logq"])


if __name__ == "__main__":
    main()
