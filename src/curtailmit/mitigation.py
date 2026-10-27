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

Task 13 (D28): with split_margins=True (needs the CM column in the marginal factor table) compute_mitigation additionally returns the OM and CM deficits as two distinct column families
(mitigation_deficit_marginal_om_tco2 / ..._cm_tco2, with _low/_high and the wind/solar split). OM (DEB proxy) and CM (REB proxy) are alternative proxies of the marginal factor and are
never summed. The legacy single `mitigation_deficit_marginal_*` columns are kept and equal the OM family. The energy range is passed through the same factor after the split.
"""

from __future__ import annotations

import logging

import pandas as pd

from curtailmit.schemas import MitigationRow

logger = logging.getLogger(__name__)

DEFAULT_MARGINAL_PROXY_NO_CLASSIFICATION = "OM_default_no_classification"


REQUIRED_MODEL = "option_E_hourly"  # == projection.OPTION_E_MODEL_LABEL (asserted in tests)
REQUIRED_ROLE = "production"


class ModelProvenanceError(ValueError):
    """The projection table is not entirely the production option E table (model != 'option_E_hourly'); raised by compute_mitigation(require_model=True)."""


PASSTHROUGH_COLUMNS = ("model", "role", "horizon_treatment", "support_status", "partially_out_of_support", "conformal_available", "calibrated_label", "known_limitations", "drift_direction")


def output_prefix(df: pd.DataFrame) -> str:
    """File-name prefix for mitigation outputs: 'reference_' for tables whose role is reference (never to be mistaken for the production result), '' otherwise."""
    return "reference_" if "role" in df.columns and (df["role"] == "reference").all() else ""


def check_provenance(df: pd.DataFrame) -> None:
    if "model" not in df.columns:
        raise ModelProvenanceError("projection_df has no 'model' column: refusing to compute mitigation for a table of unknown provenance (use projection.build_option_e_table)")
    models = df["model"]
    bad = sorted({str(m) for m in models[models.isna() | (models != REQUIRED_MODEL)]})
    if bad:
        raise ModelProvenanceError(
            f"require_model=True: every row must have model == '{REQUIRED_MODEL}', found {bad}. Labelled reference tables (reference_*) and tables of unknown provenance must not feed "
            "headline results; use require_model=False together with the 'reference_' output prefix."
        )
    if "role" in df.columns and (df["role"] != REQUIRED_ROLE).any():
        raise ModelProvenanceError(f"require_model=True: every row must have role == '{REQUIRED_ROLE}', found {sorted(set(df['role'].astype(str)) - {REQUIRED_ROLE})}.")


def compute_mitigation(
    projection_df: pd.DataFrame,
    average_factor_df: pd.DataFrame,
    marginal_factor_df: pd.DataFrame,
    classification_available: bool,
    deb_proxy_col: str = "om_factor",
    reb_proxy_col: str = "cm_factor",
    require_model: bool = False,
    split_margins: bool = False,
) -> pd.DataFrame:
    """
    projection_df: columns [scenario, year, E_curt_twh]
    average_factor_df: columns [year, factor_tco2_per_mwh]
    marginal_factor_df: columns [year, om_factor, cm_factor] (tCO2/MWh)
    split_margins: Task 13 - also return the OM and CM deficit families (default False keeps the pre-Task 13 columns exactly).
    require_model: Task 11F/13 guard - when True EVERY row of the projection table must have model == 'option_E_hourly' (and role == 'production' when the column exists); otherwise
        ModelProvenanceError (a ValueError) is raised before any arithmetic. Tables of unknown provenance and labelled reference tables are never turned into headline mitigation figures
        (use require_model=False and the output_prefix for references). The model / role / horizon / known-limitation columns, when present, are passed through to the result.
    """
    for required_col in ("scenario", "year", "E_curt_twh"):
        if required_col not in projection_df.columns:
            raise ValueError(f"projection_df missing required column '{required_col}'")

    if require_model:
        check_provenance(projection_df)
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

    # Task 13 (D28): OM (DEB proxy) and CM (REB proxy) as two distinct families, plus the per-technology low/high of the average factor; added after the row validation.
    if split_margins:
        if reb_proxy_col not in merged.columns:
            raise ValueError(f"split_margins=True needs the CM column '{reb_proxy_col}' in marginal_factor_df")
        _add_margin_families(merged, result, deb_proxy_col, reb_proxy_col, twh_to_mwh)

    for col in PASSTHROUGH_COLUMNS:
        if col in merged.columns:
            result[col] = merged[col].to_numpy()
    return result


def _add_margin_families(merged: pd.DataFrame, result: pd.DataFrame, om_col: str, cm_col: str, twh_to_mwh: float) -> None:
    """Fill result with mitigation_deficit_marginal_{om,cm}_tco2 (and _low/_high, wind/solar) and the per-technology low/high of the average deficit. Same E x 1e6 x factor formula."""
    factors = {"avg": "factor_tco2_per_mwh", "marginal_om": om_col, "marginal_cm": cm_col}
    energy_cols = {("", ""): "E_curt_twh", **{("", s): f"E_curt_twh{s}" for s in ("_low", "_high")}}
    for tech in ("wind", "solar"):
        for s in ("", "_low", "_high"):
            energy_cols[(tech, s)] = f"E_curt_{tech}_twh{s}"
    for (tech, suffix), ecol in energy_cols.items():
        if ecol not in merged.columns:
            continue
        for name, fcol in factors.items():
            if name == "avg" and (tech, suffix) in (("", ""), ("", "_low"), ("", "_high"), ("wind", ""), ("solar", "")):
                continue  # already produced by the legacy block
            mid = f"_{tech}" if tech else ""
            result[f"mitigation_deficit_{name}{mid}_tco2{suffix}"] = merged[ecol].to_numpy() * twh_to_mwh * merged[fcol].to_numpy()
