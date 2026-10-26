"""Task 11E4-d throwaway analysis (NOT part of the installed package; no src/ change): conformal prediction intervals for option E (hourly dose-response), 2030 / 2040 primary, 2050 attempted.

Variant: SPLIT conformal on the signed log error e = ln(predicted / observed) of genuinely out-of-sample forecasts, with the calibration scores taken from the Task 11E3 splits that mimic real use
(families expanding and rolling_12 / 18 / 24: the model is fitted on earlier months and evaluated on a later calendar quarter). Truncated-training splits (trunc_past, trunc_any) are NOT in the 2030 / 2040 calibration set: they are
deliberate stress tests and not forecasts; they are used only in the 2050 covariate-shift attempt.
  * Conformity score  s = |e|  (symmetric)  -> truth in [pred x exp(-q), pred x exp(+q)];      "bias-adjusted" variant s = |e - m| (m = weighted median of e) -> truth in pred x exp(-(m +- q)).
  * Splits that share a test quarter are dependent, so each quarter carries total weight 1 (weight 1 / number of splits of that quarter) and the test point has weight 1: weighted split conformal
    (Tibshirani et al. 2019 with a unit test weight). The effective calibration size is the number of test quarters (wind 13, solar 7-10).
    Finite-sample rule: with n calibration blocks the (1 - alpha) interval is finite only if ceil((n + 1)(1 - alpha)) <= n; otherwise it is reported as unbounded (no guarantee can be given).
  * Guarantee: P(truth inside) >= 1 - alpha IF calibration blocks and test block are exchangeable. We check this: leave-one-quarter-out coverage, a forward test (calibrate up to 2025Q2, test 2025Q3..2026Q3),
    and the lead-time evidence of Task 11E3 (error correlates with lead time).
  * Unit of the guarantee: a QUARTER of curtailment. Annual projections average four quarters, so the quarter-block interval is conservative for the idiosyncratic noise but NOT for the persistent level bias;
    an annual-block version (calendar years, expanding windows; n = 4 wind, 2 solar) is computed as a direct check.
2050 attempt: localised (covariate-shift) weighted conformal on ALL splits, kernel on the extrapolation distance of Task 11E3 (E_out; bandwidth 0.1, and a 2-D kernel adding D_pp, bandwidth 5 pp), reporting the effective sample
size, the overlap of D_pp, and the interval whatever it looks like. The covariate-shift assumption (only the distribution of the covariate differs, not the error given the covariate) is evaluated and stated in the memo.
Run (after task11e3_error_growth.py and task11e3_2050_calibration.py):  python analysis/task11e4_conformal_prediction.py
"""

from __future__ import annotations

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
ALPHAS = (0.2, 0.1)
TEMPORAL = ("expanding", "rolling_12", "rolling_18", "rolling_24")
H_E, H_D = 0.10, 5.0


def weighted_quantile_conformal(scores: np.ndarray, weights: np.ndarray, w_test: float, alpha: float) -> float:
    """Smallest q with  sum_{s_i <= q} w_i / (sum w + w_test) >= 1 - alpha ; inf if the mass never reaches 1 - alpha (the test point carries the mass at +inf)."""
    order = np.argsort(scores)
    s, w = scores[order], weights[order]
    tot = w.sum() + w_test
    cum = np.cumsum(w) / tot
    idx = np.searchsorted(cum, 1 - alpha - 1e-12)
    return float(s[idx]) if idx < len(s) else float("inf")


def plain_weighted_quantile(scores: np.ndarray, weights: np.ndarray, level: float) -> float:
    """Ordinary weighted empirical quantile (NO test-point mass, hence NO finite-sample guarantee): shown only to display what an unguaranteed interval would look like."""
    o = np.argsort(scores)
    c = np.cumsum(weights[o]) / weights.sum()
    return float(scores[o][min(np.searchsorted(c, level - 1e-12), len(scores) - 1)])


def quarter_weights(df: pd.DataFrame) -> np.ndarray:
    """Each test quarter carries total weight 1."""
    return (1.0 / df.groupby("test_quarter")["err_log"].transform("size")).to_numpy()


def ess(w: np.ndarray) -> float:
    return float(w.sum() ** 2 / (w**2).sum()) if w.sum() > 0 else 0.0


def intervals(cal: pd.DataFrame, central: float, alpha: float, adjust: bool) -> tuple[float, float, float]:
    e, w = cal["err_log"].to_numpy(), quarter_weights(cal)
    m = float(np.average(e, weights=w)) if False else float(_wmedian(e, w)) if adjust else 0.0
    q = weighted_quantile_conformal(np.abs(e - m), w, 1.0, alpha)
    if not np.isfinite(q):
        return np.nan, np.nan, np.nan
    return central * float(np.exp(-(m + q))), central * float(np.exp(-(m - q))), q


def _wmedian(x: np.ndarray, w: np.ndarray) -> float:
    o = np.argsort(x)
    c = np.cumsum(w[o]) / w.sum()
    return float(x[o][np.searchsorted(c, 0.5)])


def calibration_sets(tech: str) -> pd.DataFrame:
    df = pd.read_csv(cm.tables_dir() / f"task11e3_splits_{tech}.csv")
    return df[df.family.isin(TEMPORAL)].reset_index(drop=True)


def coverage_checks(cal: pd.DataFrame, alpha: float, adjust: bool) -> dict:
    """Leave-one-quarter-out and forward coverage of the (symmetric or bias-adjusted) interval for the expanding-window forecast of each quarter."""
    quarters = sorted(cal.test_quarter.unique())
    hits, n = 0, 0
    for q in quarters:
        train = cal[cal.test_quarter != q]
        test = cal[(cal.test_quarter == q) & (cal.family == "expanding")]
        if test.empty:
            continue
        e = train["err_log"].to_numpy()
        w = quarter_weights(train)
        m = _wmedian(e, w) if adjust else 0.0
        qq = weighted_quantile_conformal(np.abs(e - m), w, 1.0, alpha)
        hits += int(abs(float(test["err_log"].iloc[0]) - m) <= qq)
        n += 1
    fwd = {"hits": 0, "n": 0}
    cut = pd.Period("2025Q2", freq="Q")
    train = cal[cal.test_quarter.map(lambda s: pd.Period(s, freq="Q") <= cut)]
    if train.test_quarter.nunique() >= 4:
        e, w = train["err_log"].to_numpy(), quarter_weights(train)
        m = _wmedian(e, w) if adjust else 0.0
        qq = weighted_quantile_conformal(np.abs(e - m), w, 1.0, alpha)
        for q in [x for x in quarters if pd.Period(x, freq="Q") > cut]:
            t = cal[(cal.test_quarter == q) & (cal.family == "expanding")]
            if not t.empty:
                fwd["hits"] += int(abs(float(t["err_log"].iloc[0]) - m) <= qq)
                fwd["n"] += 1
    return {"loqo_cov": hits / n if n else np.nan, "loqo_n": n, "fwd_cov": fwd["hits"] / fwd["n"] if fwd["n"] else np.nan, "fwd_n": fwd["n"]}


def annual_block_scores(h: pd.DataFrame, tech: str) -> pd.DataFrame:
    """Calendar-year blocks (2026 = Jan-Sep), model fitted on all earlier months (expanding): the direct annual-scale calibration set."""
    d, real, curt = eg.prepare(h, tech)
    mb = c2.MonthBins(d, real, curt)
    pot = (d[real] + d[curt]).to_numpy()
    rows = []
    for y in sorted(set(d.index.year)):
        mask = np.array([m.year < y for m in mb.months])
        if mask.sum() < eg.MIN_TRAIN[tech]:
            continue
        p = c2.fit_logistic(mb.bins(mask.astype(float)))
        sel = d.index.year == y
        obs = float(d[curt].to_numpy()[sel].sum() / 1e6)
        if obs < eg.MIN_OBS_TWH[tech]:
            continue
        pred = float((cm.logistic_w(d["r"].to_numpy()[sel], *p) * pot[sel]).sum() / 1e6)
        rows.append({"tech": tech, "year": y, "obs": obs, "pred": pred, "err_log": float(np.log(pred / obs))})
    return pd.DataFrame(rows)


def annual_interval(blocks: pd.DataFrame, central: float, alpha: float) -> tuple[float, float, float]:
    e = blocks["err_log"].to_numpy()
    q = weighted_quantile_conformal(np.abs(e), np.ones(len(e)), 1.0, alpha)
    if not np.isfinite(q):
        return np.nan, np.nan, np.nan
    return central * float(np.exp(-q)), central * float(np.exp(q)), q


def main() -> None:
    h = cm.sin_hourly("2022-01-01")
    T = cm.tables_dir()
    td = pd.read_csv(T / "task11e3_target_distance.csv")
    band3 = pd.read_csv(T / "task11e3_annual_backtest_band.csv").set_index(["scenario", "year"])
    cals = {t: calibration_sets(t) for t in eg.TECHS}
    ann = {t: annual_block_scores(h, t) for t in eg.TECHS}
    print("Calibration sets (temporal splits only):", {t: {"splits": len(c), "quarters": int(c.test_quarter.nunique()), "lead_months_max": float(c.lead_months.max()), "E_out_max": round(float(c.E_out.max()), 2), "D_pp_max": round(float(c.D_pp.max()), 1)} for t, c in cals.items()})
    print("Annual-block scores:", {t: [(int(r.year), round(float(r.err_log), 3)) for r in a.itertuples()] for t, a in ann.items()})
    print("Horizon facts: every calibration block is the quarter immediately after its training window (0-3 months ahead, training 9-57 months); a 2030 projection is about 4 years beyond the 2026-09 data end, 2040 about 14, 2050 about 24.")

    # ---- exchangeability checks
    chk = []
    for t, c in cals.items():
        for a in ALPHAS:
            for adj in (False, True):
                r = coverage_checks(c, a, adj)
                chk.append({"tech": t, "alpha": a, "variant": "bias-adjusted" if adj else "symmetric", **r, "n_quarters": int(c.test_quarter.nunique()), "finite": bool(np.isfinite(weighted_quantile_conformal(np.abs(c['err_log'].to_numpy()), quarter_weights(c), 1.0, a)))})
    chk = pd.DataFrame(chk)
    chk.to_csv(T / "task11e4_conformal_coverage_checks.csv", index=False)
    print("\nEmpirical coverage of the quarter-block conformal interval (nominal 1 - alpha): leave-one-quarter-out and forward (calibrate to 2025Q2, test 2025Q3..2026Q3)\n", chk.round(3).to_string(index=False))

    # ---- 2030 / 2040 intervals
    rows = []
    for _, r in td[td.year.isin([2030, 2040])].iterrows():
        c = cals[r.tech]
        row = {"scenario": r.scenario, "year": int(r.year), "tech": r.tech, "central": r.central_twh, "E_out": r.E_out}
        for a in ALPHAS:
            for adj, tag in ((False, "sym"), (True, "adj")):
                lo, hi, q = intervals(c, r.central_twh, a, adj)
                row[f"q{int((1 - a) * 100)}_{tag}_lo"], row[f"q{int((1 - a) * 100)}_{tag}_hi"], row[f"q{int((1 - a) * 100)}_{tag}_logq"] = lo, hi, q
            lo, hi, q = annual_interval(ann[r.tech], r.central_twh, a)
            row[f"q{int((1 - a) * 100)}_annual_lo"], row[f"q{int((1 - a) * 100)}_annual_hi"] = lo, hi
        mature = c[c.test_quarter.map(lambda x: pd.Period(x, freq="Q") >= pd.Period("2025Q1", freq="Q"))]
        row["n_quarters_mature"] = int(mature.test_quarter.nunique())
        for a in ALPHAS:
            lo, hi, q = intervals(mature, r.central_twh, a, False) if mature.test_quarter.nunique() >= 2 else (np.nan, np.nan, np.nan)
            row[f"q{int((1 - a) * 100)}_mature_lo"], row[f"q{int((1 - a) * 100)}_mature_hi"] = lo, hi
        if r.tech in ("wind", "solar"):
            b = band3.loc[(r.scenario, r.year)]
            row["e3_band_lo"], row["e3_band_hi"] = b[f"{r.tech}_low"], b[f"{r.tech}_high"]
        rows.append(row)
    iv = pd.DataFrame(rows)
    iv.to_csv(T / "task11e4_conformal_intervals_2030_2040.csv", index=False)
    show = iv[["scenario", "year", "tech", "central", "q80_sym_lo", "q80_sym_hi", "q80_adj_lo", "q80_adj_hi", "q80_annual_lo", "q80_annual_hi", "q90_sym_lo", "q90_sym_hi", "q90_annual_lo", "q80_mature_lo", "q80_mature_hi", "n_quarters_mature", "e3_band_lo", "e3_band_hi"]]
    print("\n==== Conformal intervals, 2030 / 2040 (TWh; NaN = unbounded: not enough calibration blocks for that level) ====\n", show.round(1).to_string(index=False))
    # total wind + solar, unified calibration
    tot = iv[iv.tech == "unified"][["scenario", "year", "central", "q80_sym_lo", "q80_sym_hi", "q80_adj_lo", "q80_adj_hi", "q90_sym_lo", "q90_sym_hi", "q90_adj_lo", "q90_adj_hi"]]
    tot.to_csv(T / "task11e4_conformal_total_2030_2040.csv", index=False)
    print("\nTotal wind + solar with the unified-driver calibration (TWh):\n", tot.round(1).to_string(index=False))

    # ---- 2050: exchangeability assessment and the localised covariate-shift attempt
    allsp = {t: pd.read_csv(T / f"task11e3_splits_{t}.csv") for t in eg.TECHS}
    rows = []
    for _, r in td[td.year == 2050].iterrows():
        sp = allsp[r.tech]
        temporal = sp[sp.family.isin(TEMPORAL)]
        e_out_over = float((temporal.E_out >= 0.8 * r.E_out).mean())
        d_over = float((sp.D_pp >= 0.8 * r.D_pp).mean())
        w1 = np.exp(-0.5 * ((sp.E_out - r.E_out) / H_E) ** 2).to_numpy()
        w2 = w1 * np.exp(-0.5 * ((sp.D_pp - r.D_pp) / H_D) ** 2).to_numpy()
        row = {"scenario": r.scenario, "tech": r.tech, "central": r.central_twh, "E_out_target": r.E_out, "D_pp_target": r.D_pp, "D_pp_cal_max_all_splits": float(sp.D_pp.max()), "D_pp_cal_max_temporal": float(temporal.D_pp.max()),
               "share_temporal_with_E_out>=0.8x": e_out_over, "share_all_with_D_pp>=0.8x": d_over, "lead_max_temporal_months": float(temporal.lead_months.max()), "ESS_1D": ess(w1), "ESS_2D": ess(w2),
               "n_quarters_with_weight_1D": int(sp.loc[w1 > 0.05 * w1.max(), "test_quarter"].nunique())}
        cap = float(r.central_twh) / max(float(r.rate), 1e-9) if "rate" in r and r.rate > 0 else np.nan  # PTE generation of the technology (rate = central / generation)
        for lab, w in (("1D", w1), ("2D", w2)):
            ws = np.asarray(w, float)
            # block weights: each test quarter's splits share the quarter's mass
            ws_q = ws / sp.groupby("test_quarter")["err_log"].transform("size").to_numpy()
            for a in ALPHAS:
                tot_w = ws_q.sum()
                q = weighted_quantile_conformal(np.abs(sp["err_log"].to_numpy()), ws_q, 1.0, a)  # kernel weight of the test point itself = 1
                m = 0.0
                lo = r.central_twh * float(np.exp(-q)) if np.isfinite(q) else np.nan
                hi = r.central_twh * float(np.exp(q)) if np.isfinite(q) else np.nan
                row[f"q{int((1 - a) * 100)}_{lab}_logq"], row[f"q{int((1 - a) * 100)}_{lab}_lo"], row[f"q{int((1 - a) * 100)}_{lab}_hi"] = q, lo, hi
        row["generation_cap_twh"] = cap
        for lab, w in (("1D", w1), ("2D", w2)):
            ws_q = np.asarray(w, float) / sp.groupby("test_quarter")["err_log"].transform("size").to_numpy()
            for lvl in (80, 90):
                qh = plain_weighted_quantile(np.abs(sp["err_log"].to_numpy()), ws_q, lvl / 100)
                row[f"heur{lvl}_{lab}_lo"], row[f"heur{lvl}_{lab}_hi"] = r.central_twh * float(np.exp(-qh)), min(r.central_twh * float(np.exp(qh)), cap) if np.isfinite(cap) else r.central_twh * float(np.exp(qh))
                row[f"heur{lvl}_{lab}_hi_uncapped"] = r.central_twh * float(np.exp(qh))
        wq = pd.Series(w1).groupby(sp["test_quarter"].to_numpy()).sum()
        wq2 = pd.Series(w2).groupby(sp["test_quarter"].to_numpy()).sum()
        row["n_eff_quarters_1D"], row["n_eff_quarters_2D"] = ess(wq.to_numpy()), ess(wq2.to_numpy())
        for lab in ("1D", "2D"):
            for lvl in (80, 90):
                hi = row[f"q{lvl}_{lab}_hi"]
                row[f"q{lvl}_{lab}_hi_capped"] = min(hi, cap) if np.isfinite(hi) and np.isfinite(cap) else np.nan
        rows.append(row)
    f50 = pd.DataFrame(rows)
    f50.to_csv(T / "task11e4_conformal_2050.csv", index=False)
    print("\n==== 2050: exchangeability diagnostics and localised weighted conformal (all splits; kernel on E_out [1D] and on E_out and D_pp [2D]) ====")
    print(f50[["scenario", "tech", "central", "E_out_target", "D_pp_target", "D_pp_cal_max_all_splits", "D_pp_cal_max_temporal", "share_temporal_with_E_out>=0.8x", "share_all_with_D_pp>=0.8x", "lead_max_temporal_months", "ESS_1D", "ESS_2D", "n_eff_quarters_1D", "n_eff_quarters_2D"]].round(2).to_string(index=False))
    print(f50[["scenario", "tech", "central", "q80_1D_lo", "q80_1D_hi", "q90_1D_lo", "q90_1D_hi", "q80_2D_lo", "q80_2D_hi", "q90_2D_lo", "q90_2D_hi", "generation_cap_twh"]].round(1).to_string(index=False))
    print("\nHEURISTIC (no guarantee; plain weighted quantile of |ln(pred/obs)| over the E_out-localised splits; upper end shown uncapped / capped at the PTE generation):")
    print(f50[["scenario", "tech", "central", "heur80_1D_lo", "heur80_1D_hi_uncapped", "heur80_1D_hi", "heur90_1D_lo", "heur90_1D_hi_uncapped", "heur90_1D_hi", "heur80_2D_lo", "heur80_2D_hi_uncapped"]].round(1).to_string(index=False))


if __name__ == "__main__":
    main()
