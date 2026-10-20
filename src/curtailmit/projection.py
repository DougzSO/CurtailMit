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
- This module must NEVER be used for the primary-energy 6-point grid (that grid is a
  robustness cross-check handled elsewhere and must not substitute this series).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

ANCHOR_YEARS = (2020, 2025, 2030, 2040, 2050)
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
    merged with historical ONS data for 2020)."""
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