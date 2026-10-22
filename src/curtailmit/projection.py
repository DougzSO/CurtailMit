"""Projection module for CurtailMit.

Builds continuous-year curtailment projections from anchor-point scenario data
(2020 historical ONS + 2025/2030/2040/2050 PTE projections) by applying the
calibrated curtailment function from calibration.py.

Rules enforced here (per methodology, non-negotiable):
- Year grid is exactly {2020, 2025, 2030, 2040, 2050}.
- Year 2020 MUST be tagged source="historical_ons"; no other year may use that tag.
- Headline tables (for the paper) use ONLY the 5 anchor points, never interpolated years.
- Linear interpolation is allowed ONLY for continuous-curve figures, and every
  interpolated year must be explicitly labeled is_interpolated=True, source="interpolated".
- Generation basis (D16): no basis reconciliation is performed here, by design. The 2020 anchor
  (baseline_2020_generation.json, source="historical_ons") is on ONS SIN scope; 2025-2050 anchors
  (config/scenarios.yaml pte_scenarios, source="pte_projection") are on the PTE/BLUES model's own
  published scope, used as published and never rescaled to ONS. The PTE scenarios are the evaluated
  object, not ground truth. See docs/pte_ons_basis_investigation.md.
- This module must NEVER be used for the primary-energy 6-point grid (that grid is a
  robustness cross-check handled elsewhere and must not substitute this series).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

ANCHOR_YEARS = (2020, 2025, 2030, 2040, 2050)
PROJECTION_YEARS = (2025, 2030, 2040, 2050)  # PTE grid years; 2020 is the historical anchor, not a projection
HISTORICAL_ANCHOR_YEAR = 2020
HISTORICAL_SOURCE_LABEL = "historical_ons"
PROJECTION_SOURCE_LABEL = "pte_projection"
INTERPOLATED_SOURCE_LABEL = "interpolated"


class ProjectionError(Exception):
    """Raised when projection inputs are invalid or incomplete."""


@dataclass(frozen=True)
class AnchorPoint:
    year: int
    solar_pct: float
    wind_pct: float
    source: str  # "historical_ons" (2020 only) or "pte_projection" (2025/2030/2040/2050)

    def __post_init__(self) -> None:
        if self.year == HISTORICAL_ANCHOR_YEAR and self.source != HISTORICAL_SOURCE_LABEL:
            raise ProjectionError(
                f"Anchor year {HISTORICAL_ANCHOR_YEAR} must be tagged "
                f"source='{HISTORICAL_SOURCE_LABEL}', got '{self.source}'"
            )
        if self.year != HISTORICAL_ANCHOR_YEAR and self.source == HISTORICAL_SOURCE_LABEL:
            raise ProjectionError(
                f"Only year {HISTORICAL_ANCHOR_YEAR} may use source="
                f"'{HISTORICAL_SOURCE_LABEL}'; year {self.year} was tagged with it."
            )
        if self.solar_pct < 0 or self.wind_pct < 0:
            raise ProjectionError(f"Negative percentage not allowed for year {self.year}")
        if self.solar_pct + self.wind_pct > 100:
            raise ProjectionError(
                f"solar_pct + wind_pct exceeds 100 for year {self.year}: "
                f"{self.solar_pct} + {self.wind_pct} = {self.solar_pct + self.wind_pct}"
            )

    @property
    def penetration(self) -> float:
        return self.solar_pct + self.wind_pct


@dataclass(frozen=True)
class ProjectedPoint:
    year: int
    solar_pct: float
    wind_pct: float
    penetration: float
    curtailment: float
    is_anchor: bool
    is_interpolated: bool
    source: str


def validate_anchor_set(anchors: Sequence[AnchorPoint]) -> None:
    years = sorted(a.year for a in anchors)
    expected = sorted(ANCHOR_YEARS)
    if years != expected:
        raise ProjectionError(
            f"Anchor set must contain exactly years {expected}, got {years}"
        )


def build_anchor_points(scenario_rows: Sequence[dict]) -> list[AnchorPoint]:
    """Build AnchorPoint objects from plain dict rows (e.g. loaded from scenarios.yaml
    merged with historical ONS data for 2020).

    D16: rows keep the generation basis of their `source`; no ONS/PTE rescaling happens here."""
    anchors = [
        AnchorPoint(
            year=int(row["year"]),
            solar_pct=float(row["solar_pct"]),
            wind_pct=float(row["wind_pct"]),
            source=row["source"],
        )
        for row in scenario_rows
    ]
    validate_anchor_set(anchors)
    return sorted(anchors, key=lambda a: a.year)


def _project_single(anchor: AnchorPoint, calibration_fn: Callable[[float], float]) -> ProjectedPoint:
    return ProjectedPoint(
        year=anchor.year,
        solar_pct=anchor.solar_pct,
        wind_pct=anchor.wind_pct,
        penetration=anchor.penetration,
        curtailment=calibration_fn(anchor.penetration),
        is_anchor=True,
        is_interpolated=False,
        source=anchor.source,
    )


def headline_table(
    anchors: Sequence[AnchorPoint],
    calibration_fn: Callable[[float], float],
) -> list[ProjectedPoint]:
    """Returns ONLY the 5 anchor points, with curtailment applied. Use this for
    any table that appears in the paper. Never mix in interpolated years here."""
    validate_anchor_set(anchors)
    ordered = sorted(anchors, key=lambda a: a.year)
    return [_project_single(a, calibration_fn) for a in ordered]


def interpolate_series(
    anchors: Sequence[AnchorPoint],
    calibration_fn: Callable[[float], float],
    year_step: int = 1,
) -> list[ProjectedPoint]:
    """Build a continuous-year series via linear interpolation between anchors.
    FOR FIGURES ONLY -- never use this output as a headline table. Every
    non-anchor year is explicitly labeled is_interpolated=True, source='interpolated'.
    """
    validate_anchor_set(anchors)
    ordered = sorted(anchors, key=lambda a: a.year)
    anchor_points = {a.year: _project_single(a, calibration_fn) for a in ordered}

    series: list[ProjectedPoint] = []
    for i in range(len(ordered) - 1):
        start, end = ordered[i], ordered[i + 1]
        if end.year <= start.year:
            raise ProjectionError("Anchors must be strictly increasing in year")
        for year in range(start.year, end.year, year_step):
            if year == start.year:
                series.append(anchor_points[start.year])
                continue
            frac = (year - start.year) / (end.year - start.year)
            solar_pct = start.solar_pct + frac * (end.solar_pct - start.solar_pct)
            wind_pct = start.wind_pct + frac * (end.wind_pct - start.wind_pct)
            penetration = solar_pct + wind_pct
            series.append(
                ProjectedPoint(
                    year=year,
                    solar_pct=solar_pct,
                    wind_pct=wind_pct,
                    penetration=penetration,
                    curtailment=calibration_fn(penetration),
                    is_anchor=False,
                    is_interpolated=True,
                    source=INTERPOLATED_SOURCE_LABEL,
                )
            )
    series.append(anchor_points[ordered[-1].year])
    return series


def project_curtailment_two_curves(pte_table, result, years: Sequence[int] = PROJECTION_YEARS, n_boot: int = 1000, seed: int = 0) -> pd.DataFrame:
    """D22 combination rule applied to the PTE scenarios (Task 11B). One row per (scenario, year).

        wind_curtailed(s,t)  = wind_gen(s,t)  x C_wind(P(s,t))
        solar_curtailed(s,t) = solar_gen(s,t) x C_solar(P(s,t))
        total_curtailed      = wind_curtailed + solar_curtailed

    with P(s,t) = solar_pct + wind_pct of the PTE table (D16: PTE basis as published, no rescaling) and wind_gen/solar_gen = share x the PTE
    total generation. The PTE generation is treated as potential generation (the base of the calibrated rate), as in methodology 2.4
    (E_curt = generation x C_hat). The retained single "combined_diagnostic" curve is NOT used.

    low/central/high: central uses the fitted curve; low/high use the 2.5 / 97.5 percentile of each curve's own bootstrap (`bootstrap_calibration_ci`,
    resampling the calibration months, evaluated at the scenario's P). total low/high are the SUM of the wind and solar bounds - a conservative
    envelope, wider than a joint 95 % interval because the two bounds are not reached together.
    THESE INTERVALS CAPTURE SAMPLING UNCERTAINTY ONLY - not the uncertainty of the logistic functional form, which dominates far outside the
    calibrated range (D21/D22). `extrapolated_wind` / `extrapolated_solar` are True when P lies outside that curve's observed P range.

    `pte_table` is a schemas.PTEScenarioTable; `result` a calibration.CalibrationResult.
    """
    from curtailmit.calibration import apply_calibration, bootstrap_calibration_ci

    rows = []
    for scenario in ("TB", "TA", "TG"):
        data = getattr(pte_table, scenario)
        for year in years:
            if year not in data:
                raise ProjectionError(f"PTE table has no {year} entry for scenario {scenario}.")
            d = data[year]
            rows.append({"scenario": scenario, "year": int(year), "source": PROJECTION_SOURCE_LABEL, "solar_pct": d.solar_pct, "wind_pct": d.wind_pct,
                         "P": d.penetration_pct, "total_generation_twh": d.total_generation_twh,
                         "wind_gen_twh": d.wind_pct / 100 * d.total_generation_twh, "solar_gen_twh": d.solar_pct / 100 * d.total_generation_twh})
    out = pd.DataFrame(rows)
    p_values = sorted(out["P"].unique().tolist())
    for tech, curve, frame in (("wind", result.wind, result.wind_frame), ("solar", result.solar, result.solar_frame)):
        ci = bootstrap_calibration_ci(frame, p_values, n_boot=n_boot, seed=seed).set_index("P")
        if ci["n_failed"].max() > 0:
            logger.warning("%s bootstrap: %d of %d refits failed and were skipped", tech, int(ci["n_failed"].max()), n_boot)
        params = curve.calibration.params
        central = np.array([apply_calibration(p, params) for p in out["P"]])
        out[f"C_{tech}_central"] = central
        out[f"C_{tech}_low"] = ci.loc[out["P"], "lo"].to_numpy()
        out[f"C_{tech}_high"] = ci.loc[out["P"], "hi"].to_numpy()
        if not ((out[f"C_{tech}_low"] <= central + 1e-9) & (central <= out[f"C_{tech}_high"] + 1e-9)).all():
            logger.warning("%s: the fitted central estimate lies outside its bootstrap interval for some scenario/year (reported as is)", tech)
        for level in ("low", "central", "high"):
            out[f"{tech}_curtailed_twh_{level}"] = out[f"{tech}_gen_twh"] * out[f"C_{tech}_{level}"]
        out[f"extrapolated_{tech}"] = ~out["P"].between(curve.p_min, curve.p_max)
    for level in ("low", "central", "high"):
        out[f"total_curtailed_twh_{level}"] = out[f"wind_curtailed_twh_{level}"] + out[f"solar_curtailed_twh_{level}"]
    # columns consumed by mitigation.compute_mitigation (central + bounds)
    out["E_curt_twh"] = out["total_curtailed_twh_central"]
    out["E_curt_twh_low"] = out["total_curtailed_twh_low"]
    out["E_curt_twh_high"] = out["total_curtailed_twh_high"]
    for tech in ("wind", "solar"):
        for level, suffix in (("central", ""), ("low", "_low"), ("high", "_high")):
            out[f"E_curt_{tech}_twh{suffix}"] = out[f"{tech}_curtailed_twh_{level}"]
    return out


PTE_CURTAILMENT_FILENAME = "pte_curtailment_two_curves.parquet"


def build_pte_curtailment_table(n_boot: int = 1000, seed: int = 0, processed_dir=None) -> pd.DataFrame:
    """Task 11B entry point: refit the two D22 curves from the Stage 1 artifacts, apply them to the PTE table and write
    processed/pte_curtailment_two_curves.parquet. Needs Stage 1 (run_stage1) to have populated interim/ and processed/."""
    from curtailmit.calibration import run_calibration
    from curtailmit.data_ingestion import load_config
    from curtailmit.paths import get_processed_dir

    processed_dir = processed_dir or get_processed_dir()
    result = run_calibration(processed_dir=processed_dir)
    table = project_curtailment_two_curves(load_config().pte_scenarios, result, n_boot=n_boot, seed=seed)
    table.to_parquet(processed_dir / PTE_CURTAILMENT_FILENAME, index=False)
    logger.info("Wrote %s (%d rows)", processed_dir / PTE_CURTAILMENT_FILENAME, len(table))
    return table
