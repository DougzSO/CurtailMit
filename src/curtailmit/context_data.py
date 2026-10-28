"""State attribution and aggregation of OBSERVED curtailment for the context maps (Task 17; decisions D36 and the Q5 / Q6 answers of docs/task17_design.md).

No spatial inference and no allocation: the raw ONS curtailment files carry the state (`id_estado`, `nom_estado`) of every plant-hour; the production table
`processed/ons_curtailment_classified.parquet` carries the plant (`usina`) and the energy but not the state. This module builds the plant -> state map from the raw files, attaches it to the classified
table and sums `curtailed_energy_mwh` by state, technology and calendar year, so the energy definition is the pipeline's own.

Hard gates (they raise, they never pick or split silently):
- a plant name that maps to more than one state across the raw data stops the build and names the plant and the states (Q6; a multi-state complex is NOT split by energy share);
- a classified plant without a state, or a raw row without a state, stops the build;
- RECONCILIATION: the sum over all states equals the national total of the classified table for every technology and year, rtol 1e-9.

The result is cached in `interim/curtailment_by_state_year.parquet` (Q5) with the exact numbers that get plotted also written to `outputs/tables/curtailment_by_state_year.csv`. It is rebuilt only when
missing or with `--force`; it is not a `curtailmit-run` stage and takes no part in the pipeline-stamp mechanism (nothing downstream of the production numbers depends on it).

    python scripts/build_context_data.py [--force]        (or: python -m curtailmit.context_data [--force])
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

CACHE_NAME = "curtailment_by_state_year.parquet"
CSV_NAME = "curtailment_by_state_year.csv"
CLASSIFIED_NAME = "ons_curtailment_classified.parquet"
RAW_DIRS = {"wind": "curtailment_wind", "solar": "curtailment_solar"}
RTOL = 1e-9
COLUMNS = ("id_estado", "nom_estado", "technology", "year", "curtailed_energy_mwh", "curtailed_energy_twh", "national_total_mwh", "share_of_national_pct", "months_covered", "is_partial_year")


class ContextDataError(ValueError):
    """Base class of the stop conditions of this module."""


class PlantStateConflictError(ContextDataError):
    """A plant name maps to more than one state in the raw ONS data (Q6: stop and report, do not split by energy share)."""


class MissingStateError(ContextDataError):
    """A raw row has no state, or a classified plant has no entry in the plant -> state map."""


class ReconciliationError(ContextDataError):
    """The sum over states differs from the national total of the classified table."""


# ================================================================================================================================================================================ plant -> state
def usina_state_map(raw_root: Path) -> pd.DataFrame:
    """One row per plant name with its state, from every raw wind and solar curtailment file. Raises PlantStateConflictError / MissingStateError instead of choosing."""
    raw_root = Path(raw_root)
    parts = []
    for tech, d in RAW_DIRS.items():
        files = sorted((raw_root / "ons" / d).glob("*.parquet"))
        if not files:
            raise MissingStateError(f"no raw ONS files under {raw_root / 'ons' / d}")
        for f in files:
            x = pd.read_parquet(f, columns=["nom_usina", "id_estado", "nom_estado"]).drop_duplicates()
            x["technology"] = tech
            parts.append(x)
    m = pd.concat(parts, ignore_index=True).drop_duplicates()
    blank = m["id_estado"].isna() | (m["id_estado"].astype(str).str.strip() == "")
    if blank.any():
        raise MissingStateError(f"raw rows without a state for plants {sorted(m.loc[blank, 'nom_usina'].astype(str).unique())[:10]}")
    states = m.groupby("nom_usina")["id_estado"].agg(lambda s: sorted(set(s)))
    multi = states[states.map(len) > 1]
    if len(multi):
        detail = "; ".join(f"{name!r}: {', '.join(v)}" for name, v in multi.head(10).items())
        raise PlantStateConflictError(f"{len(multi)} plant name(s) map to more than one state in the raw ONS data ({detail}); not split by energy share (Task 17 Q6)")
    names = m.drop_duplicates("nom_usina").set_index("nom_usina")["nom_estado"]
    out = pd.DataFrame({"usina": states.index.astype(str), "id_estado": states.map(lambda v: v[0]).to_numpy(), "nom_estado": names.reindex(states.index).to_numpy()})
    return out.reset_index(drop=True)


# ===================================================================================================================================================================== aggregation
def aggregate_by_state(classified: pd.DataFrame, mapping: pd.DataFrame) -> pd.DataFrame:
    """State x technology x calendar year energy, share of the national total of that technology-year, and the months of data behind each technology-year. Reconciles to the classified table (hard gate)."""
    need = {"usina", "source", "timestamp", "curtailed_energy_mwh"}
    if need - set(classified.columns):
        raise ContextDataError(f"classified table lacks {sorted(need - set(classified.columns))}")
    c = classified[["usina", "source", "timestamp", "curtailed_energy_mwh"]].copy()
    c["usina"] = c["usina"].astype(str)
    c["technology"] = c["source"].astype(str)
    c["year"] = pd.DatetimeIndex(c["timestamp"]).year
    unmapped = sorted(set(c["usina"]) - set(mapping["usina"]))
    if unmapped:
        raise MissingStateError(f"{len(unmapped)} classified plant(s) have no state in the raw ONS data, e.g. {unmapped[:5]}")
    national = c.groupby(["technology", "year"])["curtailed_energy_mwh"].sum()
    months = c.assign(month=pd.DatetimeIndex(c["timestamp"]).month).groupby(["technology", "year"])["month"].nunique()
    c = c.merge(mapping[["usina", "id_estado", "nom_estado"]], on="usina", how="left", validate="many_to_one")
    agg = c.groupby(["id_estado", "nom_estado", "technology", "year"], as_index=False)["curtailed_energy_mwh"].sum()
    check = agg.groupby(["technology", "year"])["curtailed_energy_mwh"].sum()
    if not (check.index.equals(national.index) and np.allclose(check.to_numpy(), national.to_numpy(), rtol=RTOL, atol=0.0)):
        worst = (check.reindex(national.index) - national).abs().idxmax()
        raise ReconciliationError(f"sum over states differs from the national total of the classified table (worst: {worst}, states {float(check.reindex(national.index)[worst])!r} vs national {float(national[worst])!r})")
    key = list(zip(agg["technology"], agg["year"], strict=True))
    agg["national_total_mwh"] = national.reindex(pd.MultiIndex.from_tuples(key)).to_numpy()
    agg["months_covered"] = months.reindex(pd.MultiIndex.from_tuples(key)).to_numpy().astype(int)
    agg["is_partial_year"] = agg["months_covered"] < 12
    agg["curtailed_energy_twh"] = agg["curtailed_energy_mwh"] / 1e6
    agg["share_of_national_pct"] = 100.0 * agg["curtailed_energy_mwh"] / agg["national_total_mwh"]
    out = agg[list(COLUMNS)].sort_values(["technology", "year", "curtailed_energy_mwh"], ascending=[True, True, False]).reset_index(drop=True)
    return out


def reconcile(table: pd.DataFrame, classified: pd.DataFrame) -> None:
    """Re-check an existing state-year table against the classified table (used by the integration test): rtol 1e-9 for every technology and year."""
    c = classified[["source", "timestamp", "curtailed_energy_mwh"]]
    national = c.assign(technology=c["source"].astype(str), year=pd.DatetimeIndex(c["timestamp"]).year).groupby(["technology", "year"])["curtailed_energy_mwh"].sum()
    states = table.groupby(["technology", "year"])["curtailed_energy_mwh"].sum()
    if not (states.index.equals(national.index) and np.allclose(states.to_numpy(), national.to_numpy(), rtol=RTOL, atol=0.0)):
        raise ReconciliationError("state-year table does not reconcile with the classified table")


# ========================================================================================================================================================================== build / cache
def _layout(raw_root=None, processed=None, interim=None, tables=None) -> dict[str, Path]:
    from curtailmit import paths

    lay = paths.planned_layout()
    return {"raw": Path(raw_root) if raw_root is not None else lay["root"] / "raw", "processed": Path(processed) if processed is not None else lay["processed"],
            "interim": Path(interim) if interim is not None else lay["interim"], "tables": Path(tables) if tables is not None else lay["tables"]}


def build(force: bool = False, raw_root=None, processed=None, interim=None, tables=None) -> pd.DataFrame:
    """The state-year table. Read from interim/curtailment_by_state_year.parquet unless it is missing or `force`; when built it is written to the cache and to outputs/tables/*.csv."""
    lay = _layout(raw_root, processed, interim, tables)
    cache, csv = lay["interim"] / CACHE_NAME, lay["tables"] / CSV_NAME
    if cache.is_file() and not force:
        table = pd.read_parquet(cache)
        if not csv.is_file():
            lay["tables"].mkdir(parents=True, exist_ok=True)
            table.to_csv(csv, index=False, lineterminator="\n")
        return table
    classified_path = lay["processed"] / CLASSIFIED_NAME
    if not classified_path.is_file():
        raise ContextDataError(f"{classified_path} not found: run the pipeline (curtailmit-run) first")
    classified = pd.read_parquet(classified_path, columns=["usina", "source", "timestamp", "curtailed_energy_mwh"])
    table = aggregate_by_state(classified, usina_state_map(lay["raw"]))
    lay["interim"].mkdir(parents=True, exist_ok=True)
    lay["tables"].mkdir(parents=True, exist_ok=True)
    table.to_parquet(cache, index=False)
    table.to_csv(csv, index=False, lineterminator="\n")
    return table


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build the observed curtailment by state and year (context maps, Task 17). Not a curtailmit-run stage.")
    ap.add_argument("--force", action="store_true", help="rebuild even if interim/curtailment_by_state_year.parquet exists")
    args = ap.parse_args(argv)
    try:
        t = build(force=args.force)
    except ContextDataError as exc:
        print(f"context data: STOP: {exc}", file=sys.stderr)
        return 2
    print(f"curtailment by state and year: {len(t)} rows, {t['id_estado'].nunique()} states, years {int(t['year'].min())}-{int(t['year'].max())}; reconciled with the classified table (rtol {RTOL})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
