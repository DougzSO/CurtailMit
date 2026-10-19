"""Stage 2 - calibration of the curtailment projection function C(P).

Functional form (docs/methodology.md Section 2.3):
    C(P) = L / (1 + exp(-k * (P - P0)))

where P is solar+wind penetration (%) and C(P) is the curtailment fraction (0-1)
applied to solar+wind generation.

This module provides the generic fitting machinery. Wiring it to the real ONS
historical series (merging generation-by-source + curtailment data) happens once
Stage 1 discovery produces the actual historical dataframes.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

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
