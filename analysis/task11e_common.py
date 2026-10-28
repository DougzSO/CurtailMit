"""Shared loaders for the Task 11E analysis scripts (throwaway, outside the package, no src/ change).

Builds ONE hourly subsystem panel from data already in DATABASE_ROOT/raw (ONS balance by subsystem, per-plant capacity-factor files, COFF curtailment files) and
caches it as DATABASE_ROOT/interim/task11e_hourly_subsystem.parquet (an analysis cache, regenerable). Also builds the monthly capacity series from the ONS
transmission registries acquired in Task 11E (raw/ons/interchange).

Conventions: hourly index = hour start (local ONS time). MW over one hour = MWh. COFF rows are half-hourly MW per plant -> hourly MWh = sum of the rows / 2.
Subsystems: N, NE, S, SE (ONS ids stripped of padding). Net export of a subsystem = balance `val_intercambio` (positive = leaves the subsystem; checked against
generation - load in task11e_transmission_confound.py).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from curtailmit.paths import get_interim_dir, get_outputs_dir, get_raw_dir

SUBSYSTEMS = ["N", "NE", "S", "SE"]
CACHE = "task11e_hourly_subsystem.parquet"
SQRT3 = np.sqrt(3.0)
END_EXCLUSIVE = "2026-10-01"  # October 2026 is incomplete in the raw files


def tables_dir() -> Path:
    return get_outputs_dir("tables")


def figs_dir() -> Path:
    d = get_outputs_dir("figures").parent / "figures_exploratory"  # exploratory analysis figures stay out of outputs/figures (main figures only)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _balance_hourly() -> pd.DataFrame:
    frames = []
    for f in sorted(get_raw_dir("ons/generation_by_source").glob("Balanco_de_Energia_Subsistema-*.parquet")):
        if int(f.stem[-4:]) < 2021:
            continue
        df = pd.read_parquet(f)
        df["sub"] = df["id_subsistema"].astype(str).str.strip()
        df = df[df["sub"].isin(SUBSYSTEMS)].copy()
        df["ts"] = pd.to_datetime(df["din_instante"])
        for c in ("val_gerhidraulica", "val_gertermica", "val_gereolica", "val_gersolar", "val_carga", "val_intercambio"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        frames.append(df[["ts", "sub", "val_gerhidraulica", "val_gertermica", "val_gereolica", "val_gersolar", "val_carga", "val_intercambio"]])
    out = pd.concat(frames, ignore_index=True)
    out = out.rename(columns={"val_gerhidraulica": "hydro", "val_gertermica": "thermal", "val_gereolica": "wind", "val_gersolar": "solar_balance_raw", "val_carga": "load", "val_intercambio": "net_export"})
    return out.groupby(["ts", "sub"], as_index=False).sum(numeric_only=True)


def _dispatched_solar_hourly() -> pd.DataFrame:
    frames = []
    for f in sorted(get_raw_dir("ons/capacity_factor").glob("*.parquet")):
        df = pd.read_parquet(f, columns=["id_subsistema", "nom_tipousina", "din_instante", "val_geracaoverificada"])
        df = df[df["nom_tipousina"].astype(str).str.lower().str.startswith("solar")].copy()
        df["sub"] = df["id_subsistema"].astype(str).str.strip()
        df["ts"] = pd.to_datetime(df["din_instante"]).dt.floor("h")
        df["mwh"] = pd.to_numeric(df["val_geracaoverificada"], errors="coerce").fillna(0.0)
        frames.append(df.groupby(["ts", "sub"], as_index=False)["mwh"].sum())
    out = pd.concat(frames, ignore_index=True).groupby(["ts", "sub"], as_index=False)["mwh"].sum()
    return out.rename(columns={"mwh": "solar_disp"})


def _curtailment_hourly() -> pd.DataFrame:
    frames = []
    for tech, d in (("wind", "curtailment_wind"), ("solar", "curtailment_solar")):
        for f in sorted(get_raw_dir(f"ons/{d}").glob("*.parquet")):
            df = pd.read_parquet(f, columns=["id_subsistema", "din_instante", "val_geracaonaorealizadaapurada", "cod_razaorestricao"])
            ts = pd.to_datetime(df["din_instante"])
            step_h = ts.drop_duplicates().sort_values().diff().dropna().median().total_seconds() / 3600
            df["sub"] = df["id_subsistema"].astype(str).str.strip()
            df["ts"] = ts.dt.floor("h")
            df["mwh"] = pd.to_numeric(df["val_geracaonaorealizadaapurada"], errors="coerce").fillna(0.0) * step_h
            g = df.groupby(["ts", "sub"], as_index=False)["mwh"].sum()
            g["tech"] = tech
            frames.append(g)
    out = pd.concat(frames, ignore_index=True)
    out = out.groupby(["ts", "sub", "tech"], as_index=False)["mwh"].sum().pivot_table(index=["ts", "sub"], columns="tech", values="mwh", aggfunc="sum").reset_index()
    out = out.rename(columns={"wind": "curt_wind", "solar": "curt_solar"})
    return out.merge(_wind_reason_hourly(), on=["ts", "sub"], how="left")


def _wind_reason_hourly() -> pd.DataFrame:
    """Hourly wind curtailment (MWh) by ONS reason code (ENE energy, CNF reliability, REL external unavailability, PAR/other)."""
    frames = []
    for f in sorted(get_raw_dir("ons/curtailment_wind").glob("*.parquet")):
        df = pd.read_parquet(f, columns=["id_subsistema", "din_instante", "val_geracaonaorealizadaapurada", "cod_razaorestricao"])
        ts = pd.to_datetime(df["din_instante"])
        step_h = ts.drop_duplicates().sort_values().diff().dropna().median().total_seconds() / 3600
        df["sub"] = df["id_subsistema"].astype(str).str.strip()
        df["ts"] = ts.dt.floor("h")
        r = df["cod_razaorestricao"].astype("string").str.strip().str.upper()
        df["reason"] = np.where(r.isin(["ENE", "CNF", "REL"]), r, "OTH")
        df["mwh"] = pd.to_numeric(df["val_geracaonaorealizadaapurada"], errors="coerce").fillna(0.0) * step_h
        frames.append(df.groupby(["ts", "sub", "reason"], as_index=False)["mwh"].sum())
    out = pd.concat(frames, ignore_index=True).groupby(["ts", "sub", "reason"], as_index=False)["mwh"].sum()
    return out.pivot_table(index=["ts", "sub"], columns="reason", values="mwh", aggfunc="sum").add_prefix("cw_").reset_index()


def hourly_panel(refresh: bool = False) -> pd.DataFrame:
    path = get_interim_dir() / CACHE
    if path.exists() and not refresh:
        return pd.read_parquet(path)
    b, s, c = _balance_hourly(), _dispatched_solar_hourly(), _curtailment_hourly()
    h = b.merge(s, on=["ts", "sub"], how="left").merge(c, on=["ts", "sub"], how="left")
    h["solar_disp"] = h["solar_disp"].fillna(0.0)
    for col in ("curt_wind", "curt_solar", "cw_ENE", "cw_CNF", "cw_REL", "cw_OTH"):
        if col not in h:
            h[col] = 0.0
        h[col] = h[col].fillna(0.0)
    h.to_parquet(path)
    return h


# ----------------------------------------------------------------------------------------------- transmission registries (Task 11E acquisition)
def load_lines() -> pd.DataFrame:
    L = pd.read_parquet(get_raw_dir("ons/interchange") / "Linha_Transmissao.parquet")
    for c in ("dat_entradaoperacao", "dat_desativacao"):
        L[c] = pd.to_datetime(L[c], errors="coerce")
    for c in ("val_niveltensao_kv", "val_capacoperlongacomlimit", "val_capacoperlongasemlimit", "val_comprimento"):
        L[c] = pd.to_numeric(L[c], errors="coerce")
    # MVA from the long-duration operating current: sqrt(3) x kV x A / 1000. Prefer the value with the limiting factor, fall back to the one without.
    amps = L["val_capacoperlongacomlimit"].where(L["val_capacoperlongacomlimit"] > 0, L["val_capacoperlongasemlimit"])
    L["mva"] = SQRT3 * L["val_niveltensao_kv"] * amps / 1000.0
    return L


def load_transformers() -> pd.DataFrame:
    T = pd.read_parquet(get_raw_dir("ons/interchange") / "Capacidade_Transformacao.parquet")
    for c in ("dat_entradaoperacao", "dat_desativacao"):
        T[c] = pd.to_datetime(T[c], errors="coerce")
    T["val_potencianominal_mva"] = pd.to_numeric(T["val_potencianominal_mva"], errors="coerce")
    return T


def active_at(df: pd.DataFrame, when: pd.Timestamp) -> pd.Series:
    """Equipment in service at `when`: entered operation on/before, and not deactivated on/before (registry reconstruction, see caveats in the report)."""
    return (df["dat_entradaoperacao"] <= when) & (df["dat_desativacao"].isna() | (df["dat_desativacao"] > when))


def monthly_capacity_series(months: pd.PeriodIndex) -> pd.DataFrame:
    """End-of-month NE transmission stock reconstructed from the ONS registries.

    boundary_mva  - AC/DC lines with exactly one terminal in NE and the other in another Brazilian subsystem (N or SE): thermal-limit MVA
    boundary_n    - number of such lines
    ne_km         - km of lines >= 230 kV with the DE terminal in NE (NE internal + boundary + taps)
    ne_trafo_mva  - nominal MVA of NE basic-network transformers
    """
    L, T = load_lines(), load_transformers()
    de, pa = L["id_subsistema_terminalde"], L["id_subsistema_terminalpara"]
    boundary = ((de == "NE") & pa.isin(["N", "SE", "S"])) | ((pa == "NE") & de.isin(["N", "SE", "S"]))
    ne_line = de == "NE"
    ne_tr = T["id_subsistema"] == "NE"
    rows = []
    for m in months:
        when = m.to_timestamp(how="end").normalize()
        a_l, a_t = active_at(L, when), active_at(T, when)
        rows.append({"month": m, "boundary_mva": L.loc[boundary & a_l, "mva"].sum(), "boundary_n": int((boundary & a_l).sum()), "ne_km": L.loc[ne_line & a_l, "val_comprimento"].sum(),
                     "ne_lines_n": int((ne_line & a_l).sum()), "ne_trafo_mva": T.loc[ne_tr & a_t, "val_potencianominal_mva"].sum()})
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------------------------- hourly dose-response model (SIN-wide potential VRE share of load)
from scipy.optimize import curve_fit


def sin_hourly(start: str = "2022-01-01") -> pd.DataFrame:
    """SIN-wide hourly frame: potential VRE share of load r (%), wind/solar realized and curtailed MWh (national, 4 subsystems)."""
    h = hourly_panel()
    g = h.groupby("ts")[["wind", "solar_disp", "curt_wind", "curt_solar", "load"]].sum()
    g["r"] = 100 * (g.wind + g.solar_disp + g.curt_wind + g.curt_solar) / g["load"]
    g["r_solar"] = 100 * (g.solar_disp + g.curt_solar) / g["load"]
    g["hour"] = g.index.hour
    return g[(g.index >= start) & (g.index < END_EXCLUSIVE)].copy()  # same 57 complete months as the calibration frame (to 2026-09)


def logistic_w(x, L, k, x0):
    return L / (1 + np.exp(-k * (x - x0)))


def binned(df: pd.DataFrame, xcol: str, real: str, curt: str, width: float = 2.0) -> pd.DataFrame:
    """Energy-weighted curtailment rate by bin of x. rate = curtailed / (realized + curtailed)."""
    edges = np.arange(0, float(df[xcol].max()) + width, width)
    b = pd.cut(df[xcol], edges)
    g = df.groupby(b, observed=True).apply(lambda d: pd.Series({"x": float(np.average(d[xcol], weights=(d[real] + d[curt]).clip(lower=1e-9))), "pot": float((d[real] + d[curt]).sum()),
                                                               "rate": float(d[curt].sum() / max((d[real] + d[curt]).sum(), 1e-9)), "hours": len(d)}), include_groups=False)
    return g.reset_index(drop=True)


def fit_binned(bins: pd.DataFrame, min_hours: int = 15):
    """Weighted bounded logistic fit on the binned hourly rates (weights = potential energy of the bin); returns (L, k, x0)."""
    d = bins[bins["hours"] >= min_hours]
    w = d["pot"] / d["pot"].max()
    popt, _ = curve_fit(logistic_w, d["x"], d["rate"], p0=(0.9, 0.1, 40.0), sigma=1 / np.sqrt(w.clip(lower=1e-6)), bounds=([1e-9, 1e-3, -np.inf], [1.0, np.inf, np.inf]), maxfev=20000)
    return tuple(float(v) for v in popt)


def predict_monthly(df: pd.DataFrame, params: tuple, xcol: str, real: str, curt: str) -> pd.Series:
    """Monthly rate implied by a fixed hourly curve: sum_h f(x_h) pot_h / sum_h pot_h, with pot_h = realized + curtailed of the hour."""
    pot = df[real] + df[curt]
    f = logistic_w(df[xcol].to_numpy(), *params)
    num = pd.Series(f * pot.to_numpy(), index=df.index).groupby(df.index.to_period("M")).sum()
    den = pot.groupby(df.index.to_period("M")).sum()
    return num / den
