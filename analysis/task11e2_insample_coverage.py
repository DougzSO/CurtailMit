"""Task 11E2-a throwaway analysis (NOT part of the installed package; no src/ change): in-sample coverage of the hourly VRE-share-of-load driver.

Question: how much of the hourly operating conditions implied by the PTE 2040/2050 scenarios lies inside the range of r (hourly SIN potential VRE share of load, %) actually observed
in 2022-2026-09, and how much of the PROJECTED CURTAILED ENERGY is produced by hours outside that range (where the logistic is an extrapolation)?
Projected r uses the Task 11D-0/11E proxy (labelled): the 2025 SIN hourly shape scaled by the PTE annual totals (wind x W_t/W_2025, solar x S_t/S_2025, load x T_t/T_2025).
"Within the observed range" is reported under three definitions: (i) r <= the largest r ever observed; (ii) r <= the last 2-pp bin with >= 15 observed hours (the support used to fit);
(iii) r <= the last bin with >= 100 hours. It also reports the NE-only version (r_NE = NE VRE potential / NE load, same scaling) and the sensitivity to flexibility (r/phi).
Run:  python analysis/task11e2_insample_coverage.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import task11e2_common as c2
import task11e_common as cm

pd.set_option("display.width", 230)
pd.set_option("display.max_columns", 50)
PHI = (1.0, 1.25, 1.5)
EDGES = np.arange(0, 125, 5.0)


def support(h: pd.DataFrame, tech: str) -> dict:
    real, curt = c2.TECH[tech]
    d = c2.window(h, c2.TECH_START[tech])
    b = c2.MonthBins(d, real, curt).bins()
    params = c2.fit_logistic(b)
    return {"tech": tech, "params": params, "r_max": float(d["r"].max()), "cap15": c2.r_cap_of(b, 15), "cap100": c2.r_cap_of(b, 100), "n_hours": len(d)}


def observed_table(h: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label, d in [("2022-2026 (all)", h)] + [(str(y), g) for y, g in h.groupby(h.index.year)] + [("solar window 2024-04..", h[h.index >= "2024-04-01"])]:
        q = d["r"].quantile([0.5, 0.95, 0.99, 0.999])
        rows.append({"sample": label, "hours": len(d), "mean": d["r"].mean(), "p50": q[0.5], "p95": q[0.95], "p99": q[0.99], "p999": q[0.999], "max": d["r"].max(),
                     "share_hours_r_gt_40": (d["r"] > 40).mean(), "share_hours_r_gt_50": (d["r"] > 50).mean(), "share_hours_r_gt_60": (d["r"] > 60).mean()})
    return pd.DataFrame(rows)


def coverage_table(h: pd.DataFrame, sup: dict) -> pd.DataFrame:
    prof = c2.base_profile(h)
    pte = c2.load_pte()
    rows = []
    for sc in c2.SCENARIOS:
        for year in (2025, *c2.YEARS):
            f = c2.scale_factors(pte, sc, year)
            for phi in PHI:
                r = c2.projected_r(prof, f, phi)
                row = {"scenario": sc, "year": year, "phi": phi, "r_mean": r.mean(), "r_p95": np.percentile(r, 95), "r_max": r.max()}
                for tech, pot in (("wind", prof["W"] * f["a_wind"]), ("solar", prof["S"] * f["a_solar"])):
                    s = sup[tech]
                    curve = cm.logistic_w(r, *s["params"])
                    curt = curve * pot
                    for nm in ("r_max", "cap15", "cap100"):
                        thr = s[nm]
                        inside = r <= thr
                        row[f"{tech}_hours_inside_{nm}"] = inside.mean()
                        row[f"{tech}_pot_inside_{nm}"] = pot[inside].sum() / pot.sum()
                        row[f"{tech}_curt_share_beyond_{nm}"] = curt[~inside].sum() / curt.sum()
                rows.append(row)
    return pd.DataFrame(rows)


def ne_coverage(sup_r: dict) -> pd.DataFrame:
    """Same exercise for the NE alone (r_NE = NE wind+solar potential / NE load), with the same PTE scaling (constant-share proxy)."""
    hp = cm.hourly_panel()
    ne = hp[(hp["sub"] == "NE") & (hp.ts >= "2022-01-01") & (hp.ts < cm.END_EXCLUSIVE)].set_index("ts").sort_index()
    ne["rne"] = 100 * (ne.wind + ne.curt_wind + ne.solar_disp + ne.curt_solar) / ne["load"]
    obs_max, obs_p99 = float(ne["rne"].max()), float(ne["rne"].quantile(0.99))
    b25 = ne[ne.index.year == 2025]
    W, S, LD = (b25.wind + b25.curt_wind).to_numpy(), (b25.solar_disp + b25.curt_solar).to_numpy(), b25["load"].to_numpy()
    pte = c2.load_pte()
    rows = [{"scenario": "observed", "year": "2022-2026", "rNE_mean": ne["rne"].mean(), "rNE_p95": ne["rne"].quantile(0.95), "rNE_max": obs_max, "share_hours_beyond_obs_max": 0.0}]
    for sc in c2.SCENARIOS:
        for year in c2.YEARS:
            f = c2.scale_factors(pte, sc, year)
            r = 100 * (f["a_wind"] * W + f["a_solar"] * S) / (f["a_load"] * LD)
            rows.append({"scenario": sc, "year": year, "rNE_mean": r.mean(), "rNE_p95": np.percentile(r, 95), "rNE_max": r.max(), "share_hours_beyond_obs_max": (r > obs_max).mean()})
    out = pd.DataFrame(rows)
    out["obs_p99"] = obs_p99
    return out


def figure(h: pd.DataFrame, sup: dict, prof: dict, pte: pd.DataFrame) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(1, 3, figsize=(18, 5))
    xs = np.arange(0, 160, 2.0)
    mid = 0.5 * (xs[:-1] + xs[1:])
    obs = np.histogram(h["r"], xs)[0] / len(h)
    ax[0].fill_between(mid, 0, obs, step=None, color="0.7", label="observed 2022-2026-09 (41,616 h)")
    ax[0].axvspan(0, sup["wind"]["cap15"], color="tab:green", alpha=0.10, label=f"populated support (>=15 h/bin): r <= {sup['wind']['cap15']:.0f}")
    ax[0].axvline(sup["wind"]["r_max"], color="k", ls="--", lw=1, label=f"observed maximum {sup['wind']['r_max']:.1f}")
    colors = {"TB": "tab:blue", "TA": "tab:red", "TG": "tab:orange"}
    for sc in c2.SCENARIOS:
        for year, ls in ((2040, "-"), (2050, ":")):
            r = c2.projected_r(prof, c2.scale_factors(pte, sc, year))
            ax[0].plot(mid, np.histogram(r, xs)[0] / len(r), color=colors[sc], ls=ls, lw=1.4, label=f"{sc} {year}")
    ax[0].set(xlabel="hourly potential VRE share of load r (%)", ylabel="share of hours", title="Observed vs projected hourly r (2-pp bins)", xlim=(0, 140))
    ax[0].legend(fontsize=7)
    ax[1].plot(xs[1:], 1 - np.cumsum(obs), color="0.4", label="observed")
    for sc in c2.SCENARIOS:
        for year, ls in ((2040, "-"), (2050, ":")):
            r = c2.projected_r(prof, c2.scale_factors(pte, sc, year))
            ax[1].plot(xs[1:], 1 - np.cumsum(np.histogram(r, xs)[0] / len(r)), color=colors[sc], ls=ls, lw=1.4, label=f"{sc} {year}")
    ax[1].axvline(sup["wind"]["r_max"], color="k", ls="--", lw=1)
    ax[1].axvline(sup["wind"]["cap15"], color="tab:green", ls="--", lw=1)
    ax[1].set(xlabel="r (%)", ylabel="share of hours with r above x", yscale="log", ylim=(1e-4, 1), title="Exceedance (log): where the projection leaves the sample", xlim=(0, 140))
    ax[1].legend(fontsize=7)
    tab = pd.read_csv(Path(cm.tables_dir()) / "task11e2_coverage_table.csv")
    t = tab[(tab.phi == 1.0) & tab.year.isin(c2.YEARS)]
    x = np.arange(len(t))
    ax[2].bar(x - 0.2, 100 * t["wind_curt_share_beyond_cap15"], 0.4, label="wind", color="tab:cyan")
    ax[2].bar(x + 0.2, 100 * t["solar_curt_share_beyond_cap15"], 0.4, label="solar", color="gold")
    ax[2].set_xticks(x, [f"{a} {b}" for a, b in zip(t.scenario, t.year, strict=True)], rotation=45)
    ax[2].set(ylabel="% of projected curtailment beyond support", title="Extrapolated share of the projected curtailment (phi = 1)")
    ax[2].legend(fontsize=8)
    fig.tight_layout()
    path = Path(cm.figs_dir()) / "task11e2_insample_coverage.png"
    fig.savefig(path, dpi=130)
    return path


def main() -> None:
    h = cm.sin_hourly("2022-01-01")
    print(f"SIN hourly sample: {len(h)} h, {h.index.min()}..{h.index.max()}")
    ot = observed_table(h)
    print("\nObserved distribution of r (%):\n", ot.round(3).to_string())
    ot.to_csv(cm.tables_dir() / "task11e2_observed_distribution.csv", index=False)

    sup = {t: support(h, t) for t in ("wind", "solar")}
    for t, s in sup.items():
        print(f"{t}: curve L={s['params'][0]:.3f} k={s['params'][1]:.3f} x0={s['params'][2]:.1f}; max r {s['r_max']:.1f}; last bin >=15 h at {s['cap15']:.1f}; last bin >=100 h at {s['cap100']:.1f}")

    cov = coverage_table(h, sup)
    cov.to_csv(cm.tables_dir() / "task11e2_coverage_table.csv", index=False)
    show = cov[(cov.phi == 1.0)][["scenario", "year", "r_mean", "r_p95", "r_max", "wind_hours_inside_r_max", "wind_hours_inside_cap15", "wind_pot_inside_cap15", "wind_curt_share_beyond_cap15",
                                  "solar_hours_inside_cap15", "solar_pot_inside_cap15", "solar_curt_share_beyond_cap15", "wind_curt_share_beyond_r_max"]]
    print("\nCoverage of the projected hours (phi = 1):\n", show.round(3).to_string())
    flex = cov[(cov.year == 2050) & (cov.scenario == "TA")][["phi", "r_mean", "r_p95", "wind_hours_inside_cap15", "wind_curt_share_beyond_cap15", "solar_curt_share_beyond_cap15"]]
    print("\nTA 2050 flexibility sensitivity (r_eff = r / phi):\n", flex.round(3).to_string())

    ne = ne_coverage(sup)
    ne.to_csv(cm.tables_dir() / "task11e2_coverage_ne.csv", index=False)
    print("\nNortheast-only r_NE (same proxy scaling):\n", ne.round(3).to_string())

    print("figure:", figure(h, sup, c2.base_profile(h), c2.load_pte()))


if __name__ == "__main__":
    main()
