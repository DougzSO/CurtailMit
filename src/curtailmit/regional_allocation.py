"""Regional allocation of the national curtailment (Task 17-3, decision D37).

Rule under validation (Option B): the regional share of the national curtailment is the share
observed in a reference year (or years). This module holds the state -> macro-region map, the
observed regional shares, and the hold-out validation of the rule. It does not project anything:
the projection step (applying the shares to the Option E national values) is a separate function
that exists only if the validation is accepted.

Macro-regions follow the IBGE division. A region with no plant in the ONS data has a share of 0.
"""

from __future__ import annotations

import argparse
import itertools
from pathlib import Path

import numpy as np
import pandas as pd

REGIONS = ("N", "NE", "CO", "SE", "S")
REGION_NAMES = {"N": "North", "NE": "Northeast", "CO": "Centro-Oeste", "SE": "Southeast", "S": "South"}
STATE_REGION = {
    **dict.fromkeys(("AC", "AP", "AM", "PA", "RO", "RR", "TO"), "N"),
    **dict.fromkeys(("AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE"), "NE"),
    **dict.fromkeys(("DF", "GO", "MT", "MS"), "CO"),
    **dict.fromkeys(("ES", "MG", "RJ", "SP"), "SE"),
    **dict.fromkeys(("PR", "RS", "SC"), "S"),
}
TECHNOLOGIES = ("wind", "solar")

# Acceptance criterion, fixed before the numbers were looked at (docs/task17_design.md, Task 17-3).
# A region "matters" when its observed share is at least MATERIAL_SHARE_PP in the held-out year.
MATERIAL_SHARE_PP = 10.0
MAX_MEAN_ABS_ERROR_PP = 5.0   # mean over held-out years, per material region
MAX_ABS_ERROR_PP = 10.0       # worst single held-out year, any material region
MAX_ADJACENT_SWING_PP = 10.0  # year-to-year change of a material region's share (double digits = volatile)
MIN_ENERGY_TWH = 1.0          # years with less national curtailment are reported but not judged (noise floor)


def regional_energy(state_year: pd.DataFrame) -> pd.DataFrame:
    """Curtailed energy (TWh) by technology, year and macro-region, with the number of months covered."""
    d = state_year.copy()
    unknown = sorted(set(d["id_estado"]) - set(STATE_REGION))
    if unknown:
        raise ValueError(f"states without a macro-region: {unknown}")
    d["region"] = d["id_estado"].map(STATE_REGION)
    g = d.groupby(["technology", "year", "region"], as_index=False)["curtailed_energy_twh"].sum()
    full = pd.MultiIndex.from_product([TECHNOLOGIES, sorted(d["year"].unique()), REGIONS], names=["technology", "year", "region"])
    g = g.set_index(["technology", "year", "region"]).reindex(full, fill_value=0.0).reset_index()
    months = d.groupby(["technology", "year"])["months_covered"].max().rename("months_covered")
    g = g.join(months, on=["technology", "year"]).dropna(subset=["months_covered"])
    g["months_covered"] = g["months_covered"].astype(int)
    return g


def regional_shares(state_year: pd.DataFrame) -> pd.DataFrame:
    """Regional share (percent of the national total of the year) by technology, year and region."""
    g = regional_energy(state_year)
    tot = g.groupby(["technology", "year"])["curtailed_energy_twh"].transform("sum")
    g["national_twh"] = tot
    g["share_pct"] = 100.0 * g["curtailed_energy_twh"] / tot
    g["complete_year"] = g["months_covered"] == 12
    return g


def _wide(shares: pd.DataFrame, tech: str, complete_only: bool) -> pd.DataFrame:
    s = shares[shares["technology"] == tech]
    if complete_only:
        s = s[s["complete_year"]]
    return s.pivot(index="year", columns="region", values="share_pct")[list(REGIONS)]


def leave_one_year_out(shares: pd.DataFrame, tech: str) -> pd.DataFrame:
    """Predict each complete year from the mean of the other complete years (shares in energy-weighted terms).

    The prediction pools the energy of the training years (weights = energy), so a year with little
    curtailment does not weigh as much as a year with a lot.
    """
    s = shares[(shares["technology"] == tech) & shares["complete_year"]]
    years = sorted(s["year"].unique())
    rows = []
    for held in years:
        train = s[s["year"] != held]
        if train.empty:
            continue
        e = train.groupby("region")["curtailed_energy_twh"].sum().reindex(REGIONS, fill_value=0.0)
        pred = 100.0 * e / e.sum()
        obs = s[s["year"] == held].set_index("region")["share_pct"].reindex(REGIONS)
        for r in REGIONS:
            rows.append((tech, held, r, float(pred[r]), float(obs[r]), float(pred[r] - obs[r]),
                         float(s[s["year"] == held]["national_twh"].iloc[0])))
    return pd.DataFrame(rows, columns=["technology", "held_out_year", "region", "predicted_pct", "observed_pct", "error_pp", "national_twh"])


def forward_persistence(shares: pd.DataFrame, tech: str, partial_too: bool = True) -> pd.DataFrame:
    """Predict each year from the previous year's shares (the form in which the rule is used: 2025 -> later years)."""
    s = shares[shares["technology"] == tech]
    wide = _wide(shares, tech, complete_only=False)
    rows = []
    years = sorted(wide.index)
    for prev, cur in itertools.pairwise(years):
        cur_row = s[s["year"] == cur].iloc[0]
        if not partial_too and not cur_row["complete_year"]:
            continue
        for r in REGIONS:
            rows.append((tech, prev, cur, r, float(wide.loc[prev, r]), float(wide.loc[cur, r]), float(wide.loc[prev, r] - wide.loc[cur, r]),
                         float(cur_row["national_twh"]), bool(cur_row["complete_year"])))
    return pd.DataFrame(rows, columns=["technology", "from_year", "to_year", "region", "predicted_pct", "observed_pct", "error_pp", "national_twh", "to_year_complete"])


def judge(loyo: pd.DataFrame, forward: pd.DataFrame, shares: pd.DataFrame, tech: str) -> dict:
    """Apply the acceptance criterion; returns the per-technology verdict with the numbers behind it."""
    out: dict = {"technology": tech, "checks": {}}
    lo = loyo[(loyo["technology"] == tech) & (loyo["national_twh"] >= MIN_ENERGY_TWH)]
    mat = lo[lo["observed_pct"] >= MATERIAL_SHARE_PP]
    mae = mat.groupby("region")["error_pp"].apply(lambda x: float(np.mean(np.abs(x))))
    out["loyo_mean_abs_error_pp_by_region"] = mae.round(2).to_dict()
    out["loyo_worst_abs_error_pp"] = float(mat["error_pp"].abs().max()) if len(mat) else float("nan")
    fw = forward[(forward["technology"] == tech) & (forward["national_twh"] >= MIN_ENERGY_TWH)]
    fwm = fw[fw["observed_pct"] >= MATERIAL_SHARE_PP]
    out["forward_worst_abs_error_pp"] = float(fwm["error_pp"].abs().max()) if len(fwm) else float("nan")
    out["forward_mean_abs_error_pp"] = float(fwm["error_pp"].abs().mean()) if len(fwm) else float("nan")
    wide = _wide(shares, tech, complete_only=False)
    energy = shares[shares["technology"] == tech].groupby("year")["national_twh"].first()
    judged = [y for y in wide.index if energy[y] >= MIN_ENERGY_TWH]
    sw = wide.loc[judged].diff().abs().iloc[1:]
    material_regions = [r for r in REGIONS if (wide.loc[judged, r] >= MATERIAL_SHARE_PP).any()]
    out["max_adjacent_swing_pp"] = {r: round(float(sw[r].max()), 2) for r in material_regions}
    c = out["checks"]
    c["loyo_mean_abs_error"] = bool((mae <= MAX_MEAN_ABS_ERROR_PP).all()) if len(mae) else False
    c["loyo_worst_abs_error"] = out["loyo_worst_abs_error_pp"] <= MAX_ABS_ERROR_PP
    c["forward_worst_abs_error"] = out["forward_worst_abs_error_pp"] <= MAX_ABS_ERROR_PP
    c["adjacent_swing"] = all(v <= MAX_ADJACENT_SWING_PP for v in out["max_adjacent_swing_pp"].values())
    out["verdict"] = "reasonable" if all(c.values()) else "poor"
    return out


def validate(state_year: pd.DataFrame) -> dict:
    shares = regional_shares(state_year)
    techs = [t for t in TECHNOLOGIES if t in set(shares["technology"])]
    loyo = pd.concat([leave_one_year_out(shares, t) for t in techs], ignore_index=True)
    fwd = pd.concat([forward_persistence(shares, t) for t in techs], ignore_index=True)
    verdicts = {t: judge(loyo, fwd, shares, t) for t in techs}
    return {"shares": shares, "loyo": loyo, "forward": fwd, "verdicts": verdicts}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Hold-out validation of the D37 regional allocation rule (Task 17-3).")
    ap.add_argument("--state-year", type=Path, default=None, help="curtailment_by_state_year.parquet (default: interim/ of the database)")
    a = ap.parse_args(argv)
    from curtailmit import paths  # local import: only the CLI needs the layout

    path = a.state_year or (paths.get_interim_dir() / "curtailment_by_state_year.parquet")
    res = validate(pd.read_parquet(path))
    pd.set_option("display.width", 200)
    print(res["shares"].pivot_table(index=["technology", "year", "months_covered", "national_twh"], columns="region", values="share_pct").round(1))
    print(res["loyo"].round(2).to_string(index=False))
    print(res["forward"].round(2).to_string(index=False))
    for t, v in res["verdicts"].items():
        print(t, v)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
