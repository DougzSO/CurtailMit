"""Uncertainty inputs of option E by horizon (D24 as adopted in Task 11F0; Tasks 11E3 / 11E4), production version (Task 11F-2).

Two descriptive/formal instruments, both calibrated on the history of the hourly model and then FROZEN in a `HorizonBands` object (JSON in processed/), refreshed only when
the calibration is re-run:

* empirical annual-backtest band (Task 11E3): relative error range of the annual hourly forecasts for test years >= 2025 (the regime closest to the projections), applied as a
  multiplicative factor (1/(1+e_max), 1/(1+e_min)) to the central estimate. DESCRIPTIVE, not a prediction interval.
* split-conformal 80 % interval (Task 11E4): symmetric conformity score |ln(pred/obs)| over genuinely out-of-sample QUARTER forecasts (model fitted on earlier months: expanding and
  rolling 12 / 18 / 24-month windows), each test quarter carrying total weight 1 and the test point weight 1 (weighted split conformal). Finite-sample rule: the (1 - alpha) interval
  is finite only if ceil((n + 1)(1 - alpha)) <= n; otherwise it is unbounded (inf) and no guarantee is given. Valid only under exchangeability, which holds for 2025-2040 and NOT for
  2050 (no conformal interval is ever produced there; see projection.project_curtailment_hourly).

Faithful migration of analysis/task11e3_error_growth.py (splits), task11e2_backtest.py (annual backtest) and task11e4_conformal_prediction.py (conformal quantile).
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from curtailmit.hourly_model import MonthBins, fit_logistic, logistic_rate, technology_frame

logger = logging.getLogger(__name__)

MIN_OBS_TWH = {"wind": 0.3, "solar": 0.3, "unified": 0.5}  # blocks with less observed curtailment are dropped (relative error meaningless on a near-zero base)
MIN_TRAIN = {"wind": 12, "solar": 9, "unified": 9}
ROLL = (12, 18, 24)
ALPHA = 0.2
BACKTEST_FIRST_YEAR = 2025
PHI_LOW = 1.5  # flexibility sensitivity used as the lower scenario of the 2050 conditional range (upper: asymptote L = 1)


# ----------------------------------------------------------------------------------------------- conformal quantile
def weighted_quantile_conformal(scores: np.ndarray, weights: np.ndarray, w_test: float, alpha: float) -> float:
    """Smallest q with  sum_{s_i <= q} w_i / (sum w + w_test) >= 1 - alpha ; inf if the mass never reaches 1 - alpha (the test point carries the mass at +inf)."""
    order = np.argsort(scores)
    s, w = np.asarray(scores, float)[order], np.asarray(weights, float)[order]
    tot = w.sum() + w_test
    cum = np.cumsum(w) / tot
    idx = np.searchsorted(cum, 1 - alpha - 1e-12)
    return float(s[idx]) if idx < len(s) else float("inf")


def quarter_weights(test_quarters: pd.Series) -> np.ndarray:
    """Splits that share a test quarter are dependent: each quarter carries total weight 1."""
    return (1.0 / test_quarters.groupby(test_quarters).transform("size")).to_numpy()


def conformal_logq(splits: pd.DataFrame, alpha: float = ALPHA) -> float:
    """Symmetric weighted split-conformal log-quantile of |ln(pred/obs)|; inf when the finite-sample rule fails."""
    if splits.empty:
        return float("inf")
    return weighted_quantile_conformal(np.abs(splits["err_log"].to_numpy()), quarter_weights(splits["test_quarter"]), 1.0, alpha)


def conformal_interval(central: float, logq: float) -> tuple[float, float]:
    """(lo, hi) = central x exp(-+logq); (nan, nan) when the interval is unbounded."""
    if not np.isfinite(logq):
        return (float("nan"), float("nan"))
    return (central * math.exp(-logq), central * math.exp(logq))


# ----------------------------------------------------------------------------------------------- quarter-ahead out-of-sample splits
def quarter_splits(h: pd.DataFrame, tech: str) -> pd.DataFrame:
    """Out-of-sample forecasts of each calendar quarter by a curve fitted on earlier months only (families expanding and rolling_W).

    One row per (family, test quarter): obs / pred curtailed TWh and err_log = ln(pred/obs). Quarters need >= 3 months in the sample.
    """
    d, real, curt = technology_frame(h, tech)
    mb = MonthBins(d, real, curt)
    months = mb.months
    pot_all = (d[real] + d[curt]).to_numpy()
    r_all, c_all = d["r"].to_numpy(), d[curt].to_numpy()
    quarter = d.index.to_period("Q")
    rows = []
    for q in pd.PeriodIndex(sorted({m.asfreq("Q") for m in months})):
        q_months = [m for m in months if m.asfreq("Q") == q]
        if len(q_months) < 3:
            continue
        before = np.array([m < min(q_months) for m in months])
        masks = []
        if before.sum() >= MIN_TRAIN[tech]:
            masks.append(("expanding", before))
        idx = np.where(before)[0]
        for w in ROLL:
            if len(idx) >= max(w, MIN_TRAIN[tech]):
                m = np.zeros(len(months), bool)
                m[idx[-w:]] = True
                masks.append((f"rolling_{w}", m))
        sel = np.asarray(quarter == q)
        obs = c_all[sel].sum() / 1e6
        if obs < MIN_OBS_TWH[tech]:
            continue
        for family, mask in masks:
            try:
                params = fit_logistic(mb.bins(mask.astype(float)))
            except Exception as exc:  # noqa: BLE001 - a degenerate training window is skipped
                logger.debug("split refit skipped (%s, %s): %s", family, q, exc)
                continue
            pred = float((logistic_rate(r_all[sel], *params) * pot_all[sel]).sum() / 1e6)
            rows.append({"tech": tech, "family": family, "test_quarter": str(q), "train_months": int(mask.sum()), "obs_twh": float(obs), "pred_twh": pred, "err_log": float(np.log(pred / obs))})
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------------------------- annual backtest band
def annual_backtest_errors(h: pd.DataFrame, tech: str, first_year: int = BACKTEST_FIRST_YEAR) -> pd.DataFrame:
    """Relative error (pred - obs)/obs of the annual curtailment of the hourly model in test years >= first_year, over the schemes of Task 11E2-b.

    wind: in-sample; train 2022-24; train 2023-24; leave-one-year-out 2025.  solar: in-sample; train to 2025-06 (test from 2025-07); leave-one-year-out 2025 and 2026.
    The 2022-23-trained wind split (3 training years of almost no curtailment) is excluded, as in Task 11E3.
    """
    d, real, curt = technology_frame(h, tech)
    months = pd.PeriodIndex(sorted(set(d.index.to_period("M"))))
    yr = pd.Series(months.year, index=months)
    all_ = pd.Series(True, index=months)
    if tech == "wind":
        schemes = [("in-sample", all_, [2025, 2026]), ("train 2022-24", yr <= 2024, [2025, 2026]), ("train 2023-24", yr.isin([2023, 2024]), [2025, 2026]), ("loyo 2025", yr != 2025, [2025])]
    else:
        schemes = [("in-sample", all_, [2025, 2026]), ("train to 2025-06", pd.Series(months <= pd.Period("2025-06", freq="M"), index=months), [2025, 2026]),
                   ("loyo 2025", yr != 2025, [2025]), ("loyo 2026", yr != 2026, [2026])]
    rows = []
    pm = d.index.to_period("M")
    for name, train, test_years in schemes:
        hd = d[pm.isin(months[train.to_numpy()])]
        params = fit_logistic(MonthBins(hd, real, curt).bins())
        pred_h = logistic_rate(d["r"].to_numpy(), *params) * (d[real] + d[curt]).to_numpy()
        for y in test_years:
            if y < first_year:
                continue
            sel = np.asarray(d.index.year == y)
            if "to 2025-06" in name and y == 2025:
                sel &= np.asarray(d.index >= "2025-07-01")
            obs = float(d[curt].to_numpy()[sel].sum())
            if not sel.any() or obs <= 0:  # the sample has no such test period (or no curtailment in it): no relative error to report
                continue
            rows.append({"tech": tech, "scheme": name, "year": y, "obs_twh": obs / 1e6, "pred_twh": float(pred_h[sel].sum()) / 1e6, "err_pct": 100 * (float(pred_h[sel].sum()) - obs) / obs})
    return pd.DataFrame(rows)


def band_factors(err_pct: pd.Series) -> tuple[float, float]:
    """Multiplicative (low, high) factors truth/pred implied by the relative errors e = (pred - obs)/obs: truth = pred / (1 + e)."""
    e = err_pct.to_numpy() / 100
    return (float(1 / (1 + e.max())), float(1 / (1 + e.min())))


# ----------------------------------------------------------------------------------------------- frozen inputs
@dataclass
class HorizonBands:
    """Calibration inputs of the by-horizon uncertainty treatment, frozen at calibration time."""

    band_factors: dict[str, tuple[float, float]] = field(default_factory=dict)  # wind, solar: (low, high) factor on the central estimate
    band_n: dict[str, int] = field(default_factory=dict)
    conformal_alpha: float = ALPHA
    conformal_logq: dict[str, float | None] = field(default_factory=dict)  # wind, solar, unified (the total uses 'unified'); None = unbounded
    conformal_n_quarters: dict[str, int] = field(default_factory=dict)
    phi_low: float = PHI_LOW

    def logq(self, tech: str) -> float:
        v = self.conformal_logq.get(tech)
        return float("inf") if v is None else float(v)

    def save(self, dest: Path) -> None:
        dest.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, src: Path) -> HorizonBands:
        d = json.loads(src.read_text(encoding="utf-8"))
        d["band_factors"] = {k: (float(v[0]), float(v[1])) for k, v in d["band_factors"].items()}
        return cls(**d)


def build_horizon_bands(h: pd.DataFrame) -> HorizonBands:
    """Re-run the backtest and quarter-split procedures on the hourly panel and freeze their outcome."""
    hb = HorizonBands()
    for tech in ("wind", "solar"):
        errs = annual_backtest_errors(h, tech)
        hb.band_factors[tech] = band_factors(errs["err_pct"])
        hb.band_n[tech] = len(errs)
    for tech in ("wind", "solar", "unified"):
        sp = quarter_splits(h, tech)
        q = conformal_logq(sp, hb.conformal_alpha)
        hb.conformal_logq[tech] = float(q) if np.isfinite(q) else None
        hb.conformal_n_quarters[tech] = int(sp["test_quarter"].nunique()) if len(sp) else 0
    return hb
