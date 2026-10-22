"""Stage 2 - calibration of the curtailment projection function C(P).

Functional form (docs/methodology.md Section 2.3):
    C(P) = L / (1 + exp(-k * (P - P0)))

where P is solar+wind penetration (%) and C(P) is the curtailment fraction (0-1)
applied to solar+wind generation.

The generic fitting machinery is at the top; the Task 9 wiring to the real ONS series (D20) is at the bottom
(`build_calibration_frame`, `annual_rates`, `run_calibration`).

D20: "solar generation" is the ONS-dispatched (centralized) series everywhere in this module - in P(s,t) (through the `solar_basis ==
"dispatched"` penetration table of ons_generation) and in the potential-generation denominator of the solar curtailment rate (dispatched
solar + curtailed solar). The raw balance `val_gersolar` is a diagnostic column of the penetration table and is never read here.
Wind uses the balance `val_gereolica` as before. Projection years (PTE/BLUES, D16) are not touched.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.optimize import curve_fit

from curtailmit.paths import get_interim_dir, get_processed_dir
from curtailmit.schemas import CalibrationParams

logger = logging.getLogger(__name__)


def logistic(P: np.ndarray, L: float, k: float, P0: float) -> np.ndarray:
    return L / (1 + np.exp(-k * (P - P0)))


def fit_calibration(
    df: pd.DataFrame,
    p_col: str = "P",
    c_col: str = "C",
    initial_guess: tuple[float, float, float] = (1.0, 0.3, 50.0),
) -> CalibrationParams:
    """Fit the logistic C(P) function to a calibration dataframe.

    df must contain columns p_col (penetration %, 0-100) and c_col
    (observed curtailment fraction, 0-1).
    """
    if df.empty:
        raise ValueError("Calibration dataframe is empty - cannot fit C(P).")

    P = df[p_col].to_numpy(dtype=float)
    C = df[c_col].to_numpy(dtype=float)

    popt, _ = curve_fit(logistic, P, C, p0=initial_guess, maxfev=10_000)
    L, k, P0 = popt

    residuals = C - logistic(P, L, k, P0)
    rmse = float(np.sqrt(np.mean(residuals ** 2)))

    logger.info("Calibration fit: L=%.4f k=%.4f P0=%.4f (in-sample RMSE=%.5f)", L, k, P0, rmse)

    return CalibrationParams(
        functional_form="logistic",
        params={"L": float(L), "k": float(k), "P0": float(P0)},
        fit_date_utc=datetime.now(timezone.utc).isoformat(),
        validation_rmse=None,
        n_calibration_points=len(df),
    )


def apply_calibration(P: float, params: dict[str, float]) -> float:
    """Evaluate the fitted C(P) at a given penetration level."""
    return float(logistic(np.array([P]), params["L"], params["k"], params["P0"])[0])


def validate_against_holdout(
    calib: CalibrationParams, holdout_df: pd.DataFrame, p_col: str = "P", c_col: str = "C"
) -> float:
    """RMSE of the fitted function against a held-out validation set (e.g. the
    2026-2029 ONS/EPE prospection), kept strictly separate from the data used
    in fit_calibration().
    """
    P = holdout_df[p_col].to_numpy(dtype=float)
    C_actual = holdout_df[c_col].to_numpy(dtype=float)
    C_pred = np.array([apply_calibration(p, calib.params) for p in P])
    rmse = float(np.sqrt(np.mean((C_actual - C_pred) ** 2)))
    logger.info("Validation RMSE against holdout set: %.5f", rmse)
    return rmse


def save_calibration(calib: CalibrationParams, dest_path: Path) -> None:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_text(calib.model_dump_json(indent=2), encoding="utf-8")
    logger.info("Calibration parameters saved to %s", dest_path)


def load_calibration(dest_path: Path) -> CalibrationParams:
    data = json.loads(dest_path.read_text(encoding="utf-8"))
    return CalibrationParams(**data)


# ------------------------------------------------------------------ Task 9: wiring to the real ONS series (D20)

CURTAILMENT_RAW_FILENAME = "ons_curtailment_raw.parquet"
PENETRATION_MONTHLY_FILENAME = "ons_penetration_monthly.parquet"
CALIBRATION_FRAME_FILENAME = "calibration_frame.parquet"
CALIBRATION_PARAMS_FILENAME = "calibration_params.json"
_FRAME_COLUMNS = ("year", "month", "P", "wind_pct", "solar_pct", "wind_gen_mwh", "solar_gen_mwh", "curt_wind_mwh", "curt_solar_mwh", "scope", "C")


class CalibrationDataError(RuntimeError):
    """Raised when the calibration inputs are not on the D20 basis or do not line up."""


def monthly_curtailment(path: Path) -> pd.DataFrame:
    """Curtailed energy (MWh) per [year, month, source] from interim/ons_curtailment_raw.parquet (D13 numerator), memory-safe.

    `complete` is True when the last timestamp of the month is on the month's last day (a month still running is not a rate sample).
    """
    table = pq.read_table(path, columns=["timestamp", "curtailed_energy_mwh", "source"], read_dictionary=["source"])
    df = table.to_pandas()
    ts = pd.to_datetime(df["timestamp"])
    grouped = df.assign(year=ts.dt.year, month=ts.dt.month, ts=ts).groupby(["year", "month", "source"], observed=True)
    out = grouped.agg(curtailed_mwh=("curtailed_energy_mwh", "sum"), last_ts=("ts", "max")).reset_index()
    out["source"] = out["source"].astype(str)
    out["complete"] = out["last_ts"].dt.normalize() >= (out["last_ts"].dt.to_period("M").dt.end_time.dt.normalize())
    return out.drop(columns="last_ts")


def build_calibration_frame(penetration_monthly: pd.DataFrame, curtailed_monthly: pd.DataFrame) -> pd.DataFrame:
    """One row per complete month with curtailment data: P(s,t) on the D20 basis and the curtailment fraction C.

    scope 'wind_only'  (months before solar curtailment is published - the first month with solar COFF rows is read from the data):
        C = curt_wind / (wind_gen + curt_wind).
    scope 'wind_solar': C = (curt_wind + curt_solar) / (wind_gen + curt_wind + solar_dispatched_gen + curt_solar).
    P is always the full wind+solar penetration of the SIN (corrected solar, D20). Raises if a month in the window is not on the dispatched
    basis (val_gersolar must never be the calibration basis) or has no generation row.
    """
    pen = penetration_monthly.set_index(["year", "month"])
    wind_c = curtailed_monthly[curtailed_monthly["source"] == "wind"].set_index(["year", "month"])
    solar_c = curtailed_monthly[curtailed_monthly["source"] == "solar"].set_index(["year", "month"])
    if wind_c.empty:
        raise CalibrationDataError("No wind curtailment rows - cannot build the calibration frame.")
    first_solar = solar_c.index.min() if not solar_c.empty else None
    rows = []
    for key in wind_c.index:
        if not wind_c.loc[key, "complete"]:
            logger.info("Calibration: month %s is still running - excluded", key)
            continue
        if key not in pen.index:
            raise CalibrationDataError(f"Month {key} has curtailment data but no generation row.")
        g = pen.loc[key]
        if g["solar_basis"] != "dispatched":
            raise CalibrationDataError(f"Month {key} solar is on the '{g['solar_basis']}' basis; D20 requires the dispatched series in the calibration window.")
        cw = float(wind_c.loc[key, "curtailed_mwh"])
        solar_observed = first_solar is not None and key >= first_solar
        if solar_observed and key not in solar_c.index:
            raise CalibrationDataError(f"Month {key}: solar curtailment published before and after but not in this month.")
        cs = float(solar_c.loc[key, "curtailed_mwh"]) if solar_observed else 0.0
        if solar_observed and not solar_c.loc[key, "complete"]:
            logger.info("Calibration: month %s solar curtailment incomplete - excluded", key)
            continue
        wg, sg = float(g["eolica_mwh"]), float(g["solar_mwh"])
        denominator = wg + cw + ((sg + cs) if solar_observed else 0.0)
        rows.append({
            "year": key[0], "month": key[1], "P": float(g["penetration_pct"]), "wind_pct": float(g["wind_pct"]), "solar_pct": float(g["solar_pct"]),
            "wind_gen_mwh": wg, "solar_gen_mwh": sg, "curt_wind_mwh": cw, "curt_solar_mwh": cs,
            "scope": "wind_solar" if solar_observed else "wind_only", "C": (cw + cs) / denominator,
        })
    frame = pd.DataFrame(rows, columns=list(_FRAME_COLUMNS))
    if frame.empty:
        raise CalibrationDataError("Calibration frame is empty after excluding incomplete months.")
    logger.info("Calibration frame: %d months %d-%02d..%d-%02d, P %.1f-%.1f %%, scope counts %s", len(frame), frame.year.iloc[0], frame.month.iloc[0],
                frame.year.iloc[-1], frame.month.iloc[-1], frame.P.min(), frame.P.max(), frame.scope.value_counts().to_dict())
    return frame


def annual_rates(frame: pd.DataFrame) -> pd.DataFrame:
    """Annual curtailment rates (%) from the monthly calibration frame (complete months only), for the Task 9 report.

    - rate_wind: curt_wind / (wind_gen + curt_wind)
    - rate_solar: curt_solar / (dispatched solar + curt_solar), over the months where solar curtailment is published
    - rate_combined_all_months: (curt_wind + curt_solar) / (wind_gen + solar_dispatched + curt_wind + curt_solar) over ALL months of the year - the
      convention of the earlier 0.43/2.40/6.61/15.23 % series, with the D20 solar; solar enters the denominator even before its curtailment is published
    - rate_scope_consistent: the frame's own C aggregated (wind-only months wind-only, wind+solar months both)
    """
    out = []
    for year, g in frame.groupby("year"):
        solar_months = g[g["scope"] == "wind_solar"]
        consistent_den = g["wind_gen_mwh"].sum() + g["curt_wind_mwh"].sum() + (solar_months["solar_gen_mwh"].sum() + solar_months["curt_solar_mwh"].sum())
        out.append({
            "year": int(year), "months": len(g),
            "rate_wind": 100 * g["curt_wind_mwh"].sum() / (g["wind_gen_mwh"].sum() + g["curt_wind_mwh"].sum()),
            "rate_solar": (100 * solar_months["curt_solar_mwh"].sum() / (solar_months["solar_gen_mwh"].sum() + solar_months["curt_solar_mwh"].sum())) if len(solar_months) else float("nan"),
            "rate_combined_all_months": 100 * (g["curt_wind_mwh"].sum() + g["curt_solar_mwh"].sum()) / (g["wind_gen_mwh"].sum() + g["solar_gen_mwh"].sum() + g["curt_wind_mwh"].sum() + g["curt_solar_mwh"].sum()),
            "rate_scope_consistent": 100 * (g["curt_wind_mwh"].sum() + g["curt_solar_mwh"].sum()) / consistent_den,
        })
    return pd.DataFrame(out)


def run_calibration(interim_dir: Path | None = None, processed_dir: Path | None = None, initial_guess: tuple[float, float, float] = (1.0, 0.3, 50.0)) -> dict:
    """Task 9: penetration table (D20 basis) + COFF curtailment -> monthly calibration frame -> logistic fit.

    Reads processed/ons_penetration_monthly.parquet and interim/ons_curtailment_raw.parquet; writes processed/calibration_frame.parquet and
    processed/calibration_params.json. The primary fit uses every complete month (scope-consistent C); a sensitivity fit on the months with
    published solar curtailment only is returned alongside (not saved as the calibration).
    """
    interim_dir = interim_dir or get_interim_dir()
    processed_dir = processed_dir or get_processed_dir()
    pen_path, curt_path = processed_dir / PENETRATION_MONTHLY_FILENAME, interim_dir / CURTAILMENT_RAW_FILENAME
    for path in (pen_path, curt_path):
        if not path.exists():
            raise CalibrationDataError(f"{path} not found - run Stage 1 (acquire_ons_generation / acquire_ons_curtailment) first.")
    frame = build_calibration_frame(pd.read_parquet(pen_path), monthly_curtailment(curt_path))
    frame.to_parquet(processed_dir / CALIBRATION_FRAME_FILENAME, index=False)
    calib = fit_calibration(frame, initial_guess=initial_guess)
    save_calibration(calib, processed_dir / CALIBRATION_PARAMS_FILENAME)
    sensitivity = None
    solar_frame = frame[frame["scope"] == "wind_solar"]
    if len(solar_frame) >= 4:
        sensitivity = fit_calibration(solar_frame, initial_guess=initial_guess)
    return {"frame": frame, "calibration": calib, "sensitivity_wind_solar_only": sensitivity, "annual_rates": annual_rates(frame)}
