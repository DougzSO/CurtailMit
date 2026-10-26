"""Task 11E2-e throwaway analysis (NOT part of the installed package; no src/ change): consolidated numeric table of the D24 options A-E (2040/2050, wind + solar curtailed TWh).

C  reject: national P curves of Task 11B                              (values from task11e_option_totals.csv)
A  regional wind envelope (L 0.25/0.5/1.0, capacity-grounded low) + hourly solar  (values from task11e_option_totals.csv)
B  alternative scenario: reports A and C as two labelled lines; has no number of its own
D  defer: no number by nature; the bracket across computed approaches is given for reference only
E  hourly dose-response for wind and solar (SIN-wide potential VRE share of load r), re-estimated here with:
     central = free L; low = r capped at the populated support (no extrapolation of the curve); high = L pinned at 1 (as in 11E);
     statistical band = month-resampling bootstrap (paired draws for wind and solar), 5-95 %;
     decomposition of the central value into curtailment from hours INSIDE and BEYOND the populated support (>= 15 observed hours per 2-pp bin of r);
     flexibility sensitivity r_eff = r / phi (phi = 1.25, 1.5);
     D23 sensitivity: the same hourly curves with the PTE generation read as DELIVERED (net) instead of potential (gross).
Run (after task11e_wind_envelope.py):  python analysis/task11e2_options_table.py
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
pd.set_option("display.max_columns", 60)
BOOT = 300
PHI = (1.0, 1.25, 1.5)


def net_basis_twh(real_w: np.ndarray, real_s: np.ndarray, load: np.ndarray, pw: tuple, ps: tuple, gen_w: float, gen_s: float, iters: int = 400) -> tuple[float, float, float]:
    """D23 sensitivity: PTE generation read as DELIVERED. Potential P = real / (1 - f(r)) with r from the potentials (monotone fixed point from r(real), bounded since f <= L).
    Returns (wind curtailed TWh, solar curtailed TWh, max change of r at the last iteration)."""
    r = 100 * (real_w + real_s) / load
    for _ in range(iters):
        pot_w = real_w / (1 - cm.logistic_w(r, *pw))
        pot_s = real_s / (1 - cm.logistic_w(r, *ps))
        r_new = 100 * (pot_w + pot_s) / load
        delta = float(np.abs(r_new - r).max())
        r = r_new
        if delta < 1e-9:
            break
    pot_w = real_w / (1 - cm.logistic_w(r, *pw))
    pot_s = real_s / (1 - cm.logistic_w(r, *ps))
    return float((pot_w - real_w).sum() / real_w.sum() * gen_w), float((pot_s - real_s).sum() / real_s.sum() * gen_s), delta


def main() -> None:
    h = cm.sin_hourly("2022-01-01")
    T = cm.tables_dir()
    pte = c2.load_pte()
    prof = c2.base_profile(h)
    b25 = h[h.index.year == 2025]
    Rw, Rs = b25.wind.to_numpy(), b25.solar_disp.to_numpy()
    hs = c2.window(h, c2.TECH_START["solar"])
    mbw, mbs = c2.MonthBins(h, *c2.TECH["wind"]), c2.MonthBins(hs, *c2.TECH["solar"])
    pw, ps = c2.fit_logistic(mbw.bins()), c2.fit_logistic(mbs.bins())
    pw_hi, ps_hi = c2.fit_logistic(mbw.bins(), L_fixed=1.0), c2.fit_logistic(mbs.bins(), L_fixed=1.0)
    cap_w, cap_s = c2.r_cap_of(mbw.bins(), 15), c2.r_cap_of(mbs.bins(), 15)
    print(f"wind curve L={pw[0]:.3f} k={pw[1]:.3f} x0={pw[2]:.1f} (support to r={cap_w:.1f}); solar curve L={ps[0]:.3f} k={ps[1]:.3f} x0={ps[2]:.1f} (support to r={cap_s:.1f})")

    # paired bootstrap over the 57 months (solar uses the months of its window with the same draw)
    rng = np.random.default_rng(23)
    idx_s = mbw.months.get_indexer(mbs.months)
    boots = []
    for _ in range(BOOT):
        w = np.bincount(rng.integers(0, len(mbw.months), len(mbw.months)), minlength=len(mbw.months)).astype(float)
        try:
            boots.append((c2.fit_logistic(mbw.bins(w)), c2.fit_logistic(mbs.bins(w[idx_s]))))
        except Exception:  # noqa: BLE001
            continue
    print(f"bootstrap draws used: {len(boots)}")

    # sanity check of the net-basis inversion on 2025 itself: realized in -> curtailment out should reproduce the ONS 2025 curtailment (37.2 TWh wind + solar, SIN)
    f25 = c2.scale_factors(pte, "TA", 2025)
    gw, gs, dl = net_basis_twh(Rw, Rs, prof["LD"], pw, ps, float(b25.wind.sum() / 1e6), float(b25.solar_disp.sum() / 1e6))
    print(f"net-basis inversion applied to the OBSERVED 2025 realized profile: wind {gw:.1f} + solar {gs:.1f} = {gw + gs:.1f} TWh curtailed vs ONS observed {float((b25.curt_wind + b25.curt_solar).sum() / 1e6):.1f}; last change of r {dl:.2g}")
    old = pd.read_csv(T / "task11e_option_totals.csv").set_index(["scenario", "year"])
    rows = []
    for sc in c2.SCENARIOS:
        for year in (2030, 2040, 2050):
            f = c2.scale_factors(pte, sc, year)
            potW, potS = prof["W"] * f["a_wind"], prof["S"] * f["a_solar"]
            row = {"scenario": sc, "year": year, "PTE_wind_twh": f["wind_gen_twh"], "PTE_solar_twh": f["solar_gen_twh"]}
            for phi in PHI:
                r = c2.projected_r(prof, f, phi)
                w_c, s_c = c2.projected_rate(r, potW, pw) * f["wind_gen_twh"], c2.projected_rate(r, potS, ps) * f["solar_gen_twh"]
                tag = "" if phi == 1.0 else f"_phi{phi}"
                row[f"E_central{tag}"] = w_c + s_c
                if phi == 1.0:
                    w_l, s_l = c2.projected_rate(r, potW, pw, cap_w) * f["wind_gen_twh"], c2.projected_rate(r, potS, ps, cap_s) * f["solar_gen_twh"]
                    w_h, s_h = c2.projected_rate(r, potW, pw_hi) * f["wind_gen_twh"], c2.projected_rate(r, potS, ps_hi) * f["solar_gen_twh"]
                    tot = np.array([c2.projected_rate(r, potW, a) * f["wind_gen_twh"] + c2.projected_rate(r, potS, b) * f["solar_gen_twh"] for a, b in boots])
                    inside_w = r <= cap_w
                    inside_s = r <= cap_s
                    row.update({"E_wind_central": w_c, "E_solar_central": s_c, "E_low_nocurveextrap": w_l + s_l, "E_high_L1": w_h + s_h, "E_boot_p05": np.percentile(tot, 5), "E_boot_p95": np.percentile(tot, 95),
                                "E_in_support_twh": float((cm.logistic_w(r, *pw) * potW)[inside_w].sum() / potW.sum() * f["wind_gen_twh"] + (cm.logistic_w(r, *ps) * potS)[inside_s].sum() / potS.sum() * f["solar_gen_twh"]),
                                "share_hours_beyond_support": float((r > cap_w).mean())})
                    row["E_extrapolated_twh"] = row["E_central"] - row["E_in_support_twh"]
                    gw, gs, dl = net_basis_twh(Rw * f["a_wind"], Rs * f["a_solar"], prof["LD"] * f["a_load"], pw, ps, f["wind_gen_twh"], f["solar_gen_twh"])
                    row.update({"E_net_basis_central": gw + gs, "E_net_basis_converged": dl < 1e-6})
            o = old.loc[(sc, year)] if (sc, year) in old.index else None
            if o is not None:
                row.update({"C_low": o.C_national_low, "C_central": o.C_national_central, "C_high": o.C_national_high, "A_low": o.A_total_low, "A_central": o.A_total_central, "A_high": o.A_total_high,
                            "E_11E_central": o.E_total_central})
                row["D_bracket_low"] = min(o.C_national_low, o.A_total_low, row["E_low_nocurveextrap"])
                row["D_bracket_high"] = max(o.C_national_high, o.A_total_high, row["E_high_L1"])
            rows.append(row)
    t = pd.DataFrame(rows)
    t.to_csv(T / "task11e2_options_table.csv", index=False)
    show = t[t.year.isin([2040, 2050])][["scenario", "year", "C_low", "C_central", "C_high", "A_low", "A_central", "A_high", "E_low_nocurveextrap", "E_central", "E_high_L1", "E_boot_p05", "E_boot_p95", "E_11E_central", "D_bracket_low", "D_bracket_high"]]
    print("\nOptions table (TWh, wind + solar):\n", show.round(0).to_string(index=False))
    print("\nE decomposition and sensitivities (TWh):\n", t[["scenario", "year", "PTE_wind_twh", "PTE_solar_twh", "E_wind_central", "E_solar_central", "E_central", "E_in_support_twh", "E_extrapolated_twh", "share_hours_beyond_support",
                       "E_central_phi1.25", "E_central_phi1.5", "E_net_basis_central", "E_net_basis_converged"]].round(1).to_string(index=False))
    print("2030 (in-sample regime):", t[t.year == 2030][["scenario", "E_central", "E_low_nocurveextrap", "E_high_L1"]].round(1).to_dict("records"))


if __name__ == "__main__":
    main()
