"""Stage 4 - mitigation deficit computation (average vs. marginal sensitivity).

Per docs/methodology.md Section 2.5:
    Mitigation_deficit_avg(s,t)      = E_curt(s,t) x average_factor(t)
    Mitigation_deficit_marginal(s,t) = E_curt(s,t) x marginal_factor_proxy(t)

Both values are always computed and reported together - never collapsed into a
single number without labeling which factor was used.

Task 11B: when projection_df also carries the two-curve outputs of projection.project_curtailment_two_curves
(E_curt_twh_low / E_curt_twh_high, E_curt_{wind,solar}_twh[_low|_high], extrapolated_{wind,solar}), the same factors are applied to them and
the low/high deficits plus the wind/solar split are carried through. The low/high values are bootstrap bounds of the two calibrated curves:
SAMPLING uncertainty only, not logistic functional-form uncertainty (D21/D22), which dominates for the extrapolated 2040/2050 points.
The single marginal-factor input is passed through unchanged (the OM/CM dual-column split is Task 13).
"""

from __future__ import annotations

import logging

import pandas as pd

from curtailmit.schemas import MitigationRow

logger = logging.getLogger(__name__)

DEFAULT_MARGINAL_PROXY_NO_CLASSIFICATION = "OM_default_no_classification"


def compute_mitigation(
    projection_df: pd.DataFrame,
    average_factor_df: pd.DataFrame,
    marginal_factor_df: pd.DataFrame,
    classification_available: bool,
    deb_proxy_col: str = "om_factor",
    reb_proxy_col: str = "cm_factor",
) -> pd.DataFrame:
    """
    projection_df: columns [scenario, year, E_curt_twh]
    average_factor_df: columns [year, factor_tco2_per_mwh]
    marginal_factor_df: columns [year, om_factor, cm_factor] (tCO2/MWh)
    """
    for required_col in ("scenario", "year", "E_curt_twh"):
        if required_col not in projection_df.columns:
            raise ValueError(f"projection_df missing required column '{required_col}'")

    merged = projection_df.merge(average_factor_df, on="year", how="left", validate="many_to_one")
    merged = merged.merge(marginal_factor_df, on="year", how="left", validate="many_to_one")

    missing_avg = merged["factor_tco2_per_mwh"].isna().sum()
    if missing_avg:
        raise ValueError(
            f"{missing_avg} rows have no matching average emission factor for their year - "
            "Stage 1 average factor coverage is insufficient for the projection year grid."
        )

    twh_to_mwh = 1e6
    merged["mitigation_deficit_avg_tco2"] = (
        merged["E_curt_twh"] * twh_to_mwh * merged["factor_tco2_per_mwh"]
    )

    if classification_available:
        merged["marginal_factor_used"] = merged[deb_proxy_col]
        merged["marginal_proxy_used"] = f"DEB={deb_proxy_col}/REB={reb_proxy_col} (classified)"
    else:
        logger.warning(
            "classification_available=False - using default marginal proxy '%s' for all rows.",
            DEFAULT_MARGINAL_PROXY_NO_CLASSIFICATION,
        )
        merged["marginal_factor_used"] = merged[deb_proxy_col]
        merged["marginal_proxy_used"] = DEFAULT_MARGINAL_PROXY_NO_CLASSIFICATION

    merged["mitigation_deficit_marginal_tco2"] = (
        merged["E_curt_twh"] * twh_to_mwh * merged["marginal_factor_used"]
    )
    merged["classification_available"] = classification_available

    out_cols = [
        "scenario", "year", "E_curt_twh",
        "mitigation_deficit_avg_tco2", "mitigation_deficit_marginal_tco2",
        "marginal_proxy_used", "classification_available",
    ]
    # Task 11B: low/high bounds and the wind/solar split, same factors, only for the columns that are present.
    for suffix in ("_low", "_high"):
        if f"E_curt_twh{suffix}" in merged.columns:
            merged[f"mitigation_deficit_avg_tco2{suffix}"] = merged[f"E_curt_twh{suffix}"] * twh_to_mwh * merged["factor_tco2_per_mwh"]
            merged[f"mitigation_deficit_marginal_tco2{suffix}"] = merged[f"E_curt_twh{suffix}"] * twh_to_mwh * merged["marginal_factor_used"]
            out_cols += [f"E_curt_twh{suffix}", f"mitigation_deficit_avg_tco2{suffix}", f"mitigation_deficit_marginal_tco2{suffix}"]
    for tech in ("wind", "solar"):
        for suffix in ("", "_low", "_high"):
            col = f"E_curt_{tech}_twh{suffix}"
            if col in merged.columns:
                out_cols.append(col)
        if f"E_curt_{tech}_twh" in merged.columns:
            merged[f"mitigation_deficit_avg_{tech}_tco2"] = merged[f"E_curt_{tech}_twh"] * twh_to_mwh * merged["factor_tco2_per_mwh"]
            merged[f"mitigation_deficit_marginal_{tech}_tco2"] = merged[f"E_curt_{tech}_twh"] * twh_to_mwh * merged["marginal_factor_used"]
            out_cols += [f"mitigation_deficit_avg_{tech}_tco2", f"mitigation_deficit_marginal_{tech}_tco2"]
        if f"extrapolated_{tech}" in merged.columns:
            out_cols.append(f"extrapolated_{tech}")
    result = merged[out_cols].copy()

    for row in result.itertuples(index=False):
        MitigationRow(**row._asdict())

    return result
