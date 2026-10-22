"""
Emission factor derivation and combination logic.

This module implements pure, fully-specified math from
docs/methodology.md (decision D12). It does NOT fetch or parse any MCTI
files - that is source-specific acquisition logic (Claude Code Task 5)
and belongs in a dedicated mcti_client.py / mcti ingestion module.

This module only knows how to:
1. Derive an annual OM value from 12 published monthly OM values
   (MCTI publishes OM at monthly granularity only; no official annual
   figure exists).
2. Combine OM and BM into a Combined Margin (CM) using the UNFCCC CDM
   default 50/50 weighting (decision D12).

Every output here must be flagged by the caller as "derived" /
"computed", never presented as a directly MCTI-published value.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

DEFAULT_OM_WEIGHT = 0.5
DEFAULT_BM_WEIGHT = 0.5

CM_METHODOLOGY_REFERENCE = (
    "UNFCCC CDM default 50/50 Operating Margin / Build Margin weighting "
    "for low-carbon intermittent sources (consistent with ACM0002), "
    "adopted per decision D12 in the absence of an MCTI-published "
    "Combined Margin figure."
)

EXPECTED_MONTHS_PER_YEAR = 12


class EmissionFactorError(Exception):
    """Raised when emission factor inputs are invalid or incomplete."""


@dataclass(frozen=True)
class CombinedMarginResult:
    cm: float
    om_used: float
    bm_used: float
    om_weight: float
    bm_weight: float
    methodology_reference: str = CM_METHODOLOGY_REFERENCE


def derive_annual_om_from_monthly(monthly_values: Sequence[float]) -> float:
    """
    Derive an annual Operating Margin value from 12 published monthly
    values, as a simple arithmetic mean.

    MCTI's dispatch-analysis OM is published at monthly granularity
    only; no monthly generation weights are available in the published
    files to justify a weighted average, so a simple mean is used. This
    result MUST be flagged by the caller as a derived/computed value,
    not an MCTI-published figure.

    Raises
    ------
    EmissionFactorError
        If the number of monthly values is not exactly 12, or if any
        value is missing (None) or non-finite.
    """
    if len(monthly_values) != EXPECTED_MONTHS_PER_YEAR:
        raise EmissionFactorError(
            f"Expected exactly {EXPECTED_MONTHS_PER_YEAR} monthly OM values, "
            f"got {len(monthly_values)}. Explicit failure per project policy: "
            "never silently proceed with incomplete monthly coverage."
        )

    for i, v in enumerate(monthly_values, start=1):
        if v is None:
            raise EmissionFactorError(
                f"Monthly OM value for month {i} is missing (None). "
                "Explicit failure per project policy."
            )

    return sum(monthly_values) / EXPECTED_MONTHS_PER_YEAR


def compute_combined_margin(
    om: float,
    bm: float,
    om_weight: float = DEFAULT_OM_WEIGHT,
    bm_weight: float = DEFAULT_BM_WEIGHT,
) -> CombinedMarginResult:
    """
    Compute the Combined Margin (CM) from OM and BM using decision D12's
    default 50/50 weighting (overridable for sensitivity analysis).

    Raises
    ------
    EmissionFactorError
        If om_weight + bm_weight does not sum to 1.0 (within floating
        point tolerance), or if om/bm are negative.
    """
    if om < 0 or bm < 0:
        raise EmissionFactorError(
            f"OM and BM must be non-negative emission factors (tCO2/MWh). "
            f"Got om={om}, bm={bm}."
        )

    weight_sum = om_weight + bm_weight
    if abs(weight_sum - 1.0) > 1e-9:
        raise EmissionFactorError(
            f"om_weight + bm_weight must sum to 1.0, got {weight_sum}. "
            "Explicit failure rather than silently normalizing weights."
        )

    cm = om_weight * om + bm_weight * bm
    return CombinedMarginResult(
        cm=cm,
        om_used=om,
        bm_used=bm,
        om_weight=om_weight,
        bm_weight=bm_weight,
    )