"""Task 11E3-a throwaway analysis (NOT part of the installed package; no src/ change): how does the hourly dose-response model's prediction error grow with extrapolation distance?

Panel: the SIN hourly frame 2022-01..2026-09 of Task 11E (the COFF curtailment series starts in 2022-01, so there is no 2021 curtailment to train or test on; 2021 exists only as balance data).
Test unit: a calendar QUARTER of hourly data (annual totals would give too few blocks; quarters add seasonal heterogeneity noise, so the resulting error band is conservative for an annual projection).
Error: e = ln(predicted / observed curtailed energy of the block) (signed; 0 = perfect). Blocks with observed curtailment < MIN_OBS_TWH are dropped (relative error is meaningless on a near-zero base).

EXTRAPOLATION-DISTANCE METRICS (per split; all computed with the same curve that is being tested):
  E_out  share of the block's PREDICTED curtailed energy produced by hours whose r exceeds the training support (r_cap = largest 2-pp bin of r with >= 15 hours in the training months).
         PRIMARY metric: unit-free (0-1), directly comparable with the 2050 values of Task 11E2-a (51-77 percent), and it weights hours by what the model predicts they contribute.
  H_out  share of the block's hours with r above r_cap.
  D_pp   energy-weighted mean excess (r - r_cap) over the beyond-support hours, in pp of r (SECOND metric: how FAR beyond the support, not only how much).

SPLIT FAMILIES (training months always exclude the test quarter):
  expanding   train = every month before the test quarter (>= MIN_TRAIN months)                      [temporal]
  rolling_W   train = the W months before the test quarter, W = 12, 18, 24                             [temporal]
  trunc_past  train = months before the test quarter whose r_p95 <= theta (theta on a quantile grid)    [temporal + deliberately low-penetration training]
  trunc_any   train = ALL other months whose r_p95 <= theta                                            [covariate shift: "train on low penetration, predict higher"]

CREDIBILITY RULE FOR A 2050 BAND (fixed BEFORE looking at the results; checked in task11e3_2050_calibration.py):
  (1) the error-growth relation must be statistically distinguishable from flat (cluster-bootstrap CI of the slope excludes 0) OR the error spread must be shown to be compatible with a constant;
  (2) the 2050 distance must lie inside, or at most 25 percent beyond, the range of distances spanned by the historical splits, on BOTH E_out and D_pp;
  (3) at least 25 test blocks spanning at least 3 calendar years.
If the rule fails, 2050 stays a qualitative / conditional range (Task 11E2 recommendation) and the calibrated band is reported only as an indicative bound.
Run:  python analysis/task11e3_error_growth.py
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

pd.set_option("display.width", 230)
pd.set_option("display.max_columns", 50)
MIN_OBS_TWH = {"wind": 0.3, "solar": 0.3, "unified": 0.5}
MIN_TRAIN = {"wind": 12, "solar": 9, "unified": 9}
THETA_Q = (0.25, 0.4, 0.55, 0.7, 0.85)
ROLL = (12, 18, 24)
N_BOOT = 400
TECHS = ("wind", "solar", "unified")


def prepare(h: pd.DataFrame, tech: str) -> tuple[pd.DataFrame, str, str]:
    """Hourly frame restricted to the technology's window, with the (realized, curtailed) column pair; 'unified' = wind + solar totals."""
    if tech == "unified":
        d = c2.window(h, "2024-04-01").copy()
        d["vre_real"] = d.wind + d.solar_disp
        d["curt_vre"] = d.curt_wind + d.curt_solar
        return d, "vre_real", "curt_vre"
    real, curt = c2.TECH[tech]
    return c2.window(h, c2.TECH_START[tech]).copy(), real, curt


def monthly_r95(d: pd.DataFrame) -> pd.Series:
    return d.groupby(d.index.to_period("M"))["r"].quantile(0.95)


def distance_metrics(r: np.ndarray, pot: np.ndarray, params: tuple, r_cap: float) -> dict:
    """E_out, H_out, D_pp of a set of hours (r %, potential MWh) with respect to a training support edge r_cap and a fitted curve."""
    curt = cm.logistic_w(r, *params) * pot
    out = r > r_cap
    tot = curt.sum()
    e_out = float(curt[out].sum() / tot) if tot > 0 else 0.0
    d_pp = float(np.average(r[out] - r_cap, weights=np.maximum(curt[out], 1e-12))) if out.any() else 0.0
    return {"E_out": e_out, "H_out": float(out.mean()), "D_pp": d_pp}


def make_splits(months: pd.PeriodIndex, r95: pd.Series, tech: str):
    """Yield (family, train_mask over months, test quarter Period) for every split."""
    quarters = pd.PeriodIndex(sorted({m.asfreq("Q") for m in months}))
    for q in quarters:
        q_months = [m for m in months if m.asfreq("Q") == q]
        if len(q_months) < 3:
            continue
        first = min(q_months)
        before = np.array([m < first for m in months])
        other = np.array([m.asfreq("Q") != q for m in months])
        if before.sum() >= MIN_TRAIN[tech]:
            yield "expanding", before, q
        for w in ROLL:
            idx = np.where(before)[0]
            if len(idx) >= max(w, MIN_TRAIN[tech]):
                m = np.zeros(len(months), bool)
                m[idx[-w:]] = True
                yield f"rolling_{w}", m, q
        for qu in THETA_Q:
            theta = float(r95.quantile(qu))
            low = (r95.reindex(months).to_numpy() <= theta)
            m1 = before & low
            m2 = other & low
            if m1.sum() >= MIN_TRAIN[tech]:
                yield "trunc_past", m1, q
            if m2.sum() >= MIN_TRAIN[tech]:
                yield "trunc_any", m2, q


def run_splits(h: pd.DataFrame, tech: str) -> pd.DataFrame:
    d, real, curt = prepare(h, tech)
    mb = c2.MonthBins(d, real, curt)
    r95 = monthly_r95(d)
    pot_all = (d[real] + d[curt]).to_numpy()
    quarter = d.index.to_period("Q")
    rows = []
    for family, mask, q in make_splits(mb.months, r95, tech):
        bins = mb.bins(mask.astype(float))
        try:
            params = c2.fit_logistic(bins)
        except Exception:  # noqa: BLE001 - a degenerate training window is skipped
            continue
        r_cap = c2.r_cap_of(bins, c2.MIN_HOURS)
        sel = (quarter == q)
        r, pot, c_obs = d["r"].to_numpy()[sel], pot_all[sel], d[curt].to_numpy()[sel]
        obs = c_obs.sum() / 1e6
        if obs < MIN_OBS_TWH[tech]:
            continue
        pred = float((cm.logistic_w(r, *params) * pot).sum() / 1e6)
        dm = distance_metrics(r, pot, params, r_cap)
        last_train = mb.months[mask].max()
        lead = float((min(m for m in mb.months if m.asfreq("Q") == q) - last_train).n)  # months between the last training month and the test quarter (negative when training months lie after it)
        rows.append({"tech": tech, "family": family, "lead_months": lead, "test_quarter": str(q), "test_year": q.year, "train_months": int(mask.sum()),"train_r_cap": r_cap, "train_L": params[0], "train_k": params[1], "train_x0": params[2],
                     "obs_twh": obs, "pred_twh": pred, "err_log": float(np.log(pred / obs)), "err_pct": 100 * (pred - obs) / obs, **dm})
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------------------------- error-growth relation
def fit_relation(df: pd.DataFrame, x: str = "E_out") -> dict:
    """e = a + b x + eps, with sd(eps) = c + d x (fitted on |resid| * sqrt(pi/2)); returns the coefficients."""
    X = np.column_stack([np.ones(len(df)), df[x].to_numpy()])
    y = df["err_log"].to_numpy()
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    res = y - X @ beta
    gam = np.linalg.lstsq(X, np.abs(res) * np.sqrt(np.pi / 2), rcond=None)[0]
    return {"a": float(beta[0]), "b": float(beta[1]), "c": float(gam[0]), "d": float(gam[1]), "n": len(df), "R2": float(1 - (res**2).sum() / ((y - y.mean()) ** 2).sum()) if len(df) > 2 else np.nan}


def cluster_bootstrap(df: pd.DataFrame, x: str = "E_out", n: int = N_BOOT, seed: int = 5) -> np.ndarray:
    """Bootstrap over TEST QUARTERS (splits sharing a test quarter are strongly dependent); returns rows (a, b, c, d)."""
    rng = np.random.default_rng(seed)
    groups = [g for _, g in df.groupby("test_quarter")]
    out = []
    for _ in range(n):
        pick = rng.integers(0, len(groups), len(groups))
        s = pd.concat([groups[i] for i in pick], ignore_index=True)
        if s[x].nunique() < 3:
            continue
        f = fit_relation(s, x)
        out.append([f["a"], f["b"], f["c"], f["d"]])
    return np.array(out)


def binned_errors(df: pd.DataFrame, x: str, edges: list[float]) -> pd.DataFrame:
    b = pd.cut(df[x], edges, include_lowest=True)
    g = df.groupby(b, observed=True)
    return pd.DataFrame({"n": g.size(), "mean_x": g[x].mean(), "mean_err_pct": g["err_pct"].mean(), "median_err_pct": g["err_pct"].median(), "p05_err_pct": g["err_pct"].quantile(0.05),
                         "p95_err_pct": g["err_pct"].quantile(0.95), "mean_abs_err_pct": g["err_pct"].apply(lambda s: s.abs().mean()), "sd_log": g["err_log"].std()})


def figure(res: dict[str, pd.DataFrame], rel: dict[str, dict], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(2, 3, figsize=(17, 8.5))
    colors = {"expanding": "tab:blue", "rolling_12": "tab:cyan", "rolling_18": "tab:cyan", "rolling_24": "tab:cyan", "trunc_past": "tab:orange", "trunc_any": "tab:red"}
    for j, tech in enumerate(TECHS):
        df = res[tech]
        for fam, g in df.groupby("family"):
            ax[0, j].scatter(g["E_out"], g["err_log"], s=14, alpha=0.6, color=colors[fam], label=fam if fam in ("expanding", "rolling_12", "trunc_past", "trunc_any") else None)
        xs = np.linspace(0, max(0.9, df["E_out"].max()), 50)
        f = rel[tech]
        ax[0, j].plot(xs, f["a"] + f["b"] * xs, "k-")
        ax[0, j].fill_between(xs, f["a"] + f["b"] * xs - 1.645 * np.maximum(f["c"] + f["d"] * xs, 0), f["a"] + f["b"] * xs + 1.645 * np.maximum(f["c"] + f["d"] * xs, 0), color="0.7", alpha=0.35)
        ax[0, j].axhline(0, color="k", lw=0.6)
        ax[0, j].axvspan(0.51, 0.77, color="tab:green", alpha=0.12, label="2050 (11E2-a: wind 51-77 %)")
        ax[0, j].set(xlabel="E_out: share of predicted curtailment from beyond-support hours", ylabel="ln(pred / obs), quarter block", title=f"{tech}: error vs extrapolation distance (n={len(df)})")
        ax[0, j].legend(fontsize=7)
        ax[1, j].scatter(df["D_pp"], df["err_log"], s=14, alpha=0.6, c=df["E_out"], cmap="viridis")
        ax[1, j].axhline(0, color="k", lw=0.6)
        ax[1, j].set(xlabel="D_pp: mean excess of r beyond the training support (pp)", ylabel="ln(pred / obs)", title=f"{tech}: error vs distance in pp (colour = E_out)")
    fig.tight_layout()
    fig.savefig(path, dpi=130)


def main() -> None:
    h = cm.sin_hourly("2022-01-01")
    T = cm.tables_dir()
    res, rel, boots = {}, {}, {}
    for tech in TECHS:
        df = run_splits(h, tech)
        res[tech] = df
        df.to_csv(T / f"task11e3_splits_{tech}.csv", index=False)
        print(f"\n==== {tech}: {len(df)} splits, {df.test_quarter.nunique()} test quarters {df.test_quarter.min()}..{df.test_quarter.max()}, test years {sorted(df.test_year.unique())} ====")
        print(df.groupby("family").agg(n=("err_log", "size"), E_out_mean=("E_out", "mean"), E_out_max=("E_out", "max"), D_pp_max=("D_pp", "max"), err_pct_mean=("err_pct", "mean"), abs_err_pct_mean=("err_pct", lambda s: s.abs().mean())).round(2).to_string())
        rel[tech] = fit_relation(df)
        bs = cluster_bootstrap(df)
        boots[tech] = bs
        ci = {k: (float(np.percentile(bs[:, i], 5)), float(np.percentile(bs[:, i], 95))) for i, k in enumerate("abcd")} if len(bs) else {}
        rel[tech]["ci90"] = ci
        rel[tech]["E_out_range"] = [float(df["E_out"].min()), float(df["E_out"].max())]
        rel[tech]["D_pp_range"] = [float(df["D_pp"].min()), float(df["D_pp"].max())]
        rel[tech]["n_quarters"] = int(df.test_quarter.nunique())
        rel[tech]["n_years"] = int(df.test_year.nunique())
        print("relation e = a + b E_out, sd = c + d E_out:", {k: (round(v, 3) if isinstance(v, float) else v) for k, v in rel[tech].items() if k in ("a", "b", "c", "d", "n", "R2")})
        print("90 % cluster-bootstrap intervals:", {k: tuple(round(x, 3) for x in v) for k, v in ci.items()})
        be = binned_errors(df, "E_out", [0, 0.02, 0.1, 0.25, 0.5, 1.0])
        be.to_csv(T / f"task11e3_error_by_Eout_{tech}.csv")
        print("error by E_out bin (err_pct = (pred-obs)/obs):\n", be.round(2).to_string())
        bd = binned_errors(df[df.E_out > 0], "D_pp", [0, 3, 6, 10, 15, 100])
        print("error by D_pp bin (E_out > 0 only):\n", bd.round(2).to_string())
        # secondary relation on D_pp for reference, and a diagnostic: does lead time (drift) matter more than distance? (temporal families only)
        rel[tech]["relation_Dpp"] = fit_relation(df, "D_pp")
        tp = df[df.family != "trunc_any"]
        X = np.column_stack([np.ones(len(tp)), tp["E_out"], tp["lead_months"]])
        beta, *_ = np.linalg.lstsq(X, tp["err_log"].to_numpy(), rcond=None)
        res_ = tp["err_log"].to_numpy() - X @ beta
        rel[tech]["lead_diagnostic"] = {"a": float(beta[0]), "b_Eout": float(beta[1]), "b_lead_per_month": float(beta[2]), "R2": float(1 - (res_**2).sum() / ((tp["err_log"] - tp["err_log"].mean()) ** 2).sum()), "n": len(tp),
                                        "corr_err_lead": float(tp["err_log"].corr(tp["lead_months"])), "corr_err_Eout": float(tp["err_log"].corr(tp["E_out"]))}
        print("diagnostic (temporal splits): err_log ~ E_out + lead_months:", {k: round(v, 3) for k, v in rel[tech]["lead_diagnostic"].items()})
    json.dump(rel, open(T / "task11e3_error_growth_relations.json", "w"), indent=1)
    figure(res, rel, Path(cm.figs_dir()) / "task11e3_error_growth.png")
    print("\nfigure:", Path(cm.figs_dir()) / "task11e3_error_growth.png")


if __name__ == "__main__":
    main()
