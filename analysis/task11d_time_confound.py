"""Task 11D-b throwaway analysis (NOT part of the installed package; no src/ file is modified): how much of the P -> curtailment relation is a time trend?

Unit: NE subsystem, monthly, 57 months (2022-01..2026-09). Dependent variable: NE wind curtailment rate C = curtailed / (realized + curtailed).
Regressors: P_NE (generation-share definition of 11D-a), t (month index 0..56), NE load (TWh/month, demand proxy), SIN hydro share of load (hydrology proxy:
total SIN hydro generation / total SIN load of the month), and optionally month-of-year dummies (wind seasonality).
OLS with Newey-West (HAC, 6 lags) standard errors because monthly residuals are autocorrelated. Also first-difference and last-30-month checks.
No causal claim: this is a descriptive decomposition of a short, single-regime sample.
Run:  python analysis/task11d_time_confound.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats
from statsmodels.stats.outliers_influence import variance_inflation_factor

sys.path.insert(0, str(Path(__file__).resolve().parent))
import task11d_regional_recalibration as ra

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 40)
HAC_LAGS = 6


def build_frame() -> pd.DataFrame:
    z = ra.load_subsystem_panel()
    ne = ra.ne_panel()
    tot = z.groupby("month")[["hydro", "load"]].sum()
    ne = ne.set_index("month")
    ne["load_twh"] = ne["load"] / 1e6
    ne["hydro_share_sin"] = (tot["hydro"] / tot["load"]).reindex(ne.index)
    ne["moy"] = ne.index.month
    ne["C"] = ne["C_wind"]
    return ne.reset_index()


def spearman(a, b) -> float:
    return float(stats.spearmanr(a, b)[0])


def partial_corr(df: pd.DataFrame, x: str, y: str, controls: list[str]) -> tuple[float, float]:
    """Pearson partial correlation of x and y given controls (residualise both on controls with OLS) and its t-test p-value."""
    Z = sm.add_constant(df[controls])
    rx, ry = sm.OLS(df[x], Z).fit().resid, sm.OLS(df[y], Z).fit().resid
    r = float(np.corrcoef(rx, ry)[0, 1])
    n, k = len(df), len(controls)
    tstat = r * np.sqrt((n - 2 - k) / (1 - r**2))
    return r, float(2 * stats.t.sf(abs(tstat), n - 2 - k))


def ols(df: pd.DataFrame, cols: list[str], dummies: bool = False):
    X = df[cols].copy()
    if dummies:
        X = pd.concat([X, pd.get_dummies(df["moy"], prefix="m", drop_first=True).astype(float)], axis=1)
    X = sm.add_constant(X)
    return sm.OLS(df["C"], X).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS})


def summarise(name: str, m, cols: list[str]) -> dict:
    row = {"model": name, "n": int(m.nobs), "R2": m.rsquared, "adjR2": m.rsquared_adj}
    for c in cols:
        row[f"b_{c}"], row[f"p_{c}"] = float(m.params[c]), float(m.pvalues[c])
    return row


def run_block(df: pd.DataFrame, label: str) -> list[dict]:
    print(f"\n---- {label}: n={len(df)}, P {df.P.min():.1f}-{df.P.max():.1f}, C {df.C.min():.3f}-{df.C.max():.3f}")
    print(f"(i) corr(C,P)  Pearson {df.C.corr(df.P):.3f}  Spearman {spearman(df.C, df.P):.3f}")
    print(f"(ii) corr(C,t) Pearson {df.C.corr(df.t):.3f}  Spearman {spearman(df.C, df.t):.3f};   corr(P,t) Pearson {df.P.corr(df.t):.3f}")
    r, p = partial_corr(df, "P", "C", ["t"])
    print(f"(iii) partial corr(C,P | t) Pearson {r:.3f} (p={p:.3g})")
    rr = df[["P", "C", "t"]].rank()
    rs, ps = partial_corr(rr, "P", "C", ["t"])
    print(f"      partial Spearman(C,P | t) {rs:.3f} (p={ps:.3g})")
    r2, p2 = partial_corr(df, "t", "C", ["P"])
    print(f"      partial corr(C,t | P) {r2:.3f} (p={p2:.3g})")
    vif = {c: float(variance_inflation_factor(sm.add_constant(df[["P", "t"]]).values, i + 1)) for i, c in enumerate(["P", "t"])}
    print("VIF of (P, t):", {k: round(v, 2) for k, v in vif.items()})
    rows = []
    specs = [("M0 C~P", ["P"], False), ("M1 C~t", ["t"], False), ("M2 C~P+t", ["P", "t"], False), ("M3 C~P+t+load+hydro", ["P", "t", "load_twh", "hydro_share_sin"], False),
             ("M4 M3+month-of-year dummies", ["P", "t", "load_twh", "hydro_share_sin"], True)]
    for name, cols, dm in specs:
        m = ols(df, cols, dm)
        rows.append(summarise(name, m, cols))
    out = pd.DataFrame(rows)
    out.insert(0, "block", label)
    print(out.round(4).to_string())
    m0, m1, m2 = ols(df, ["P"]), ols(df, ["t"]), ols(df, ["P", "t"])
    print(f"R2: P only {m0.rsquared:.3f}, t only {m1.rsquared:.3f}, P+t {m2.rsquared:.3f};  incremental R2 of P given t = {m2.rsquared - m1.rsquared:.3f}, of t given P = {m2.rsquared - m0.rsquared:.3f}")
    print(f"slope of P: alone {m0.params['P']:.4f} -> with t {m2.params['P']:.4f}  (change {100 * (m2.params['P'] / m0.params['P'] - 1):+.0f}%); in standardised terms "
          f"beta_P(M2)={m2.params['P'] * df.P.std() / df.C.std():.2f}, beta_t(M2)={m2.params['t'] * df.t.std() / df.C.std():.2f}")
    # first differences remove any common linear trend
    d = df[["C", "P", "t"]].diff().dropna()
    mfd = sm.OLS(d["C"], sm.add_constant(d[["P"]])).fit(cov_type="HAC", cov_kwds={"maxlags": 3})
    print(f"first-difference dC~dP: b={mfd.params['P']:.4f} (p={mfd.pvalues['P']:.3g}), R2={mfd.rsquared:.3f}")
    out.attrs["fd"] = (float(mfd.params["P"]), float(mfd.pvalues["P"]), float(mfd.rsquared))
    return rows + [{"model": "first-difference dC~dP", "n": int(mfd.nobs), "R2": mfd.rsquared, "b_P": float(mfd.params["P"]), "p_P": float(mfd.pvalues["P"]), "block": label}]


def main() -> None:
    df = build_frame()
    print("NE monthly frame:", len(df), "months", df.month.min(), "..", df.month.max())
    allrows = []
    allrows += run_block(df, "all 57 months")
    allrows += run_block(df.iloc[-30:].reset_index(drop=True).assign(t=lambda d: np.arange(len(d))), "last 30 months")
    # within-year check: does P explain month-to-month variation inside a year, where the trend is small?
    print("\n---- within-year (year fixed effects) ----")
    d = df.copy()
    d["yr"] = d.month.dt.year
    X = pd.concat([d[["P"]], pd.get_dummies(d["yr"], prefix="y", drop_first=True).astype(float)], axis=1)
    m = sm.OLS(d["C"], sm.add_constant(X)).fit(cov_type="HAC", cov_kwds={"maxlags": 3})
    print(f"C ~ P + year dummies: b_P={m.params['P']:.4f} (p={m.pvalues['P']:.3g}), R2={m.rsquared:.3f}")
    allrows.append({"block": "all 57 months", "model": "C~P+year fixed effects", "n": int(m.nobs), "R2": m.rsquared, "b_P": float(m.params["P"]), "p_P": float(m.pvalues["P"])})
    # national comparison (same 57 months): wind C vs national P and time
    nat = ra.national_frame_wind()
    nat["t"] = np.arange(len(nat))
    print("\n---- national wind frame (same months) for comparison ----")
    print(f"corr(C,P_nat) {nat.C.corr(nat.P):.3f}; corr(C,t) {nat.C.corr(nat.t):.3f}; corr(P_nat,t) {nat.P.corr(nat.t):.3f}; partial corr(C,P_nat | t) {partial_corr(nat, 'P', 'C', ['t'])[0]:.3f} (p={partial_corr(nat, 'P', 'C', ['t'])[1]:.3g})")
    pd.DataFrame(allrows).to_csv(ra.tables_dir() / "task11d_time_confound_regressions.csv", index=False)
    df.to_csv(ra.tables_dir() / "task11d_ne_panel_with_covariates.csv", index=False)


if __name__ == "__main__":
    main()
