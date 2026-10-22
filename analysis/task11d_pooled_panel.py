"""Task 11D-c throwaway analysis (NOT part of the installed package; no src/ file is modified): pooled annual panel, Brazil subsystems + international systems.

Dependent variable: wind curtailment / dispatch-down rate C_wind (share of available wind energy). Driver: P = wind + solar share of generation (Brazil, SA) or of
demand/consumption (Ireland, Denmark) - definitions differ and are flagged in the output. Unit: system x year (annual), because the international sources only give
annual figures.

International points (every number from a primary document retrieved in Task 11C; none invented):
  Ireland+N.Ireland 2024   P = 35.0 % of demand (wind 33.0 + solar 2.0)           C_wind = 14.0 %   [EirGrid/SONI 2024, Annual Renewable Constraint & Curtailment Report]
                           (2023: C_wind = 10.7 % but wind+solar share not retrieved -> excluded)
  South Australia FY24-25  wind 44.5 % + larger solar 10.1 % = 54.6 % of generation (77.0 % with rooftop PV 22.4 %)   C_wind = 11 %   [AEMO SAER 2025]
  South Australia FY23-24  wind 45.2 % + larger solar 10.7 % = 55.9 % (74.2 % with rooftop PV 18.3 %)                 C_wind = 7 %    [AEMO SAER 2024, 2025]
                           (FY22-23: C_wind = 8 %, wind 46.9 %, rooftop 17.6 %, larger-solar share not retrieved -> excluded)
  Denmark 2023             P = 64 % of consumption (wind 54 %)                   C_wind: "up to 1,000 GWh" in earlier years ~ 5.2 % of ~19.4 TWh (upper bound),
                           0-10 GWh in H2 2023 (~0 %) -> carried as the interval [0, 5.2] %   [IEA Wind TCP, Denmark 2023]
Brazil: ONS subsystems NE/S/SE/N, full years 2022-2025 (2026 is Jan-Sep and excluded to avoid a seasonal bias), P_sub = subsystem generation share (task11d_regional_recalibration).
Run:  python analysis/task11d_pooled_panel.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import task11d_regional_recalibration as ra

from curtailmit.calibration import fit_calibration, logistic

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 40)

INTERNATIONAL = [
    # system, period, P (primary: wind + dispatchable-visible solar), P_alt, C_wind, C_lo, C_hi, basis, source
    ("Ireland+NI", "2024", 35.0, 35.0, 0.140, 0.140, 0.140, "share of demand", "EirGrid/SONI 2024"),
    ("South Australia", "FY2023-24", 55.9, 74.2, 0.070, 0.070, 0.070, "share of generation (curtailment + economic offloading)", "AEMO SAER 2024/2025"),
    ("South Australia", "FY2024-25", 54.6, 77.0, 0.110, 0.110, 0.110, "share of generation (curtailment + economic offloading)", "AEMO SAER 2025"),
    ("Denmark", "2023", 64.0, 64.0, 0.026, 0.0, 0.052, "share of consumption (rate = interval, midpoint shown)", "IEA Wind TCP Denmark 2023"),
]


def brazil_panel() -> pd.DataFrame:
    z = ra.load_subsystem_panel()
    z["year"] = z.month.dt.year
    z = z[z.year <= 2025]
    a = z.groupby(["year", "id_subsistema"])[["hydro", "thermal", "wind", "solar_dispatched", "curt_wind"]].sum().reset_index()
    a["P"] = 100 * (a.wind + a.solar_dispatched) / (a.hydro + a.thermal + a.wind + a.solar_dispatched)
    a["C"] = a.curt_wind / (a.wind + a.curt_wind)
    a["system"] = "Brazil-" + a.id_subsistema
    a["period"] = a.year.astype(str)
    a["wind_twh"] = a.wind / 1e6
    return a[["system", "period", "P", "C", "wind_twh"]].assign(P_alt=lambda d: d.P, C_lo=lambda d: d.C, C_hi=lambda d: d.C, source="ONS")


def build_panel() -> pd.DataFrame:
    intl = pd.DataFrame(INTERNATIONAL, columns=["system", "period", "P", "P_alt", "C", "C_lo", "C_hi", "basis", "source"])
    br = brazil_panel()
    panel = pd.concat([br, intl], ignore_index=True)
    panel["group"] = np.where(panel.system.str.startswith("Brazil"), "Brazil", "International")
    return panel


def frac_logit(df: pd.DataFrame, cols: list[str], groups: pd.Series | None = None, c_col: str = "C"):
    X = sm.add_constant(df[cols].astype(float))
    m = sm.GLM(df[c_col], X, family=sm.families.Binomial())
    return m.fit(cov_type="cluster", cov_kwds={"groups": pd.factorize(groups)[0]}) if groups is not None else m.fit(cov_type="HC1")


def main() -> None:
    panel = build_panel()
    panel.to_csv(ra.tables_dir() / "task11d_pooled_panel.csv", index=False)
    print(panel.round(3).to_string())
    print(f"\nN = {len(panel)} system-years, {panel.system.nunique()} systems; P range {panel.P.min():.1f}-{panel.P.max():.1f}; international N = {int((panel.group == 'International').sum())}")
    print("Observations per system:", panel.groupby("system").size().to_dict())

    # ---- A: pooled fractional logit, no fixed effects
    ok = panel.copy()
    mA = frac_logit(ok, ["P"], ok.system)
    print("\nModel A - pooled fractional logit  C = logistic(a + b P), clustered by system\n", mA.summary().tables[1])
    # ---- B: + Brazil-vs-international intercept
    ok["brazil"] = (ok.group == "Brazil").astype(float)
    mB = frac_logit(ok, ["P", "brazil"], ok.system)
    print("\nModel B - + Brazil intercept\n", mB.summary().tables[1])
    # ---- C: system fixed effects (only systems with >= 2 observations identify anything; singletons Ireland and Denmark drop out of the within estimator)
    multi = ok[ok.groupby("system")["C"].transform("size") >= 2].copy()
    X = pd.concat([multi[["P"]], pd.get_dummies(multi["system"], drop_first=False).astype(float)], axis=1)
    mC = sm.GLM(multi["C"].clip(1e-4, 1 - 1e-4), X, family=sm.families.Binomial()).fit(cov_type="cluster", cov_kwds={"groups": pd.factorize(multi.system)[0]})
    print(f"\nModel C - system fixed effects (n={len(multi)}, systems={multi.system.nunique()}; Ireland and Denmark are singletons -> not identified)\n", mC.summary().tables[1])
    # ---- D: international only (the 'external' trend), then predict Brazil-NE
    intl = ok[ok.group == "International"].copy()
    xs = np.array([intl.P.min(), intl.P.max()])
    print(f"\nInternational points only (n={len(intl)}): P {xs[0]:.0f}-{xs[1]:.0f}, C {intl.C.min():.3f}-{intl.C.max():.3f}; correlation(P, C) = {intl.P.corr(intl.C):.2f} (not identifiable as a curve with 3 systems)")

    # ---- Comparison table at comparable P: NE vs SA vs Ireland vs Denmark
    ne = ok[ok.system == "Brazil-NE"][["period", "P", "C", "wind_twh"]]
    print("\nNE annual:\n", ne.round(3).to_string())
    # ---- three-parameter bounded logistic (production form, D21) on pooled data: sensitivity
    for nm, d in (("Brazil subsystems only", ok[ok.group == "Brazil"]), ("pooled Brazil + international", ok), ("NE + international", ok[(ok.system == "Brazil-NE") | (ok.group == "International")])):
        try:
            p = fit_calibration(d[["P", "C"]].reset_index(drop=True)).params
            r = d.C - logistic(d.P.to_numpy(), **p)
            print(f"bounded logistic [{nm}] n={len(d)}: L={p['L']:.3f} k={p['k']:.3f} P0={p['P0']:.1f} RMSE={np.sqrt((r**2).mean()):.3f}; C at P=44/58/80: {[round(float(logistic(np.array([x]), **p)[0]), 3) for x in (44, 58, 80)]}")
        except Exception as exc:  # noqa: BLE001
            print(f"bounded logistic [{nm}] failed: {exc}")

    # ---- predictions of pooled fractional logit at PTE-national P levels and at NE levels
    grid = pd.DataFrame({"const": 1.0, "P": [20.0, 35.0, 44.0, 58.0, 78.0]})
    for nm, m in (("Model A", mA),):
        pr = m.get_prediction(grid[["const", "P"]]).summary_frame(alpha=0.05)
        print(f"\n{nm} predictions:\n", pd.concat([grid.P, pr[["mean", "mean_ci_lower", "mean_ci_upper"]]], axis=1).round(3).to_string())
    # Model B prediction for Brazil vs international at the PTE P levels
    for b in (0.0, 1.0):
        g = pd.DataFrame({"const": 1.0, "P": [44.0, 58.0, 78.0], "brazil": b})
        pr = mB.get_prediction(g).summary_frame(alpha=0.05)
        print(f"Model B, brazil={int(b)}:", pr["mean"].round(3).tolist(), "CI", list(zip(pr.mean_ci_lower.round(3), pr.mean_ci_upper.round(3))))
    # ---- Brazil national-curve prediction at the same P for contrast
    print("\nTask 7D national wind curve at P=44/58/78:", [round(float(logistic(np.array([x]), 1.0, 0.1669, 35.5666)[0]), 3) for x in (44, 58, 78)])

    # ---- figure
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 5))
    colors = {"Brazil-NE": "tab:red", "Brazil-S": "tab:blue", "Brazil-SE": "tab:orange", "Brazil-N": "tab:green", "Ireland+NI": "k", "South Australia": "tab:purple", "Denmark": "tab:brown"}
    for s, d in ok.groupby("system"):
        ax.scatter(d.P, d.C, label=s, color=colors[s], s=40, marker="o" if s.startswith("Brazil") else "s")
    den = ok[ok.system == "Denmark"].iloc[0]
    ax.vlines(den.P, den.C_lo, den.C_hi, color="tab:brown")
    pg = np.linspace(0, 100, 200)
    ax.plot(pg, logistic(pg, 1.0, 0.1669, 35.5666), "k--", lw=1, label="Task 7D national curve")
    gg = pd.DataFrame({"const": 1.0, "P": pg})
    ax.plot(pg, mA.predict(gg), "g-", lw=1.5, label="pooled fractional logit (Model A)")
    ax.set(xlabel="P (wind + solar share, %)", ylabel="wind curtailment / dispatch-down rate", ylim=(0, 0.7), title="Pooled annual panel (definitions differ, see doc)")
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(ra.figs_dir() / "task11d_pooled_panel.png", dpi=130)
    print("figure:", ra.figs_dir() / "task11d_pooled_panel.png")


if __name__ == "__main__":
    main()
