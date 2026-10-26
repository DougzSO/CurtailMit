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
- Task 11F (D23-D26 adopted): the PRODUCTION curtailment model is option E, the hourly dose-response model (project_curtailment_hourly, with the by-horizon treatment of D24 and the D25
  known-limitation fields). project_curtailment_two_curves (national monthly P, Tasks 7-11B) is kept as a labelled REFERENCE (model="reference_national_curve", role="reference") for the
  paper's methodological narrative; it must not be presented as the production result.
- This module must NEVER be used for the primary-energy 6-point grid (that grid is a
  robustness cross-check handled elsewhere and must not substitute this series).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from curtailmit.hourly_model import (
    HourlyCalibration,
    extrapolation_metrics,
    projected_r,
    projected_rate,
    scale_factors,
)
from curtailmit.hourly_uncertainty import conformal_interval
from curtailmit.limitations import D25, DRIFT_DIRECTION, REFERENCE_NOT_PRODUCTION, SOLAR_SHORT_RECORD

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
    out["model"], out["role"], out["known_limitations"] = REFERENCE_NATIONAL_LABEL, "reference", REFERENCE_NOT_PRODUCTION
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


# ----------------------------------------------------------------------------------------------- Task 11F: option E (production)
OPTION_E_MODEL_LABEL = "option_E_hourly"
REFERENCE_NATIONAL_LABEL = "reference_national_curve"
OPTION_E_FILENAME = "pte_curtailment_option_E.parquet"
HORIZON_BAND = "band_plus_conformal"  # 2025 / 2030 / 2040: central + empirical annual band (headline) + conformal 80 % (supplement)
HORIZON_CONDITIONAL = "decomposition_conditional"  # 2050: central + in/out-of-support decomposition + flexibility-conditional range; no conformal, no "calibrated"
CONDITIONAL_FROM_YEAR = 2050
# support status of a (scenario, year) from the share of the predicted curtailment (E_out) and of the hours (H_out) beyond the populated support (rule fixed in Task 11F-1)
PARTIAL_E_OUT, PARTIAL_H_OUT, MOSTLY_E_OUT = 0.30, 0.10, 0.50


def pte_generation_frame(pte_table) -> pd.DataFrame:
    """Rows (scenario, year) of a schemas.PTEScenarioTable with the PTE generation of each technology (TWh): the input of the hourly projection."""
    rows = []
    for scenario in ("TB", "TA", "TG"):
        for year, d in getattr(pte_table, scenario).items():
            total = d.total_generation_twh
            rows.append({"scenario": scenario, "year": int(year), "solar_pct": d.solar_pct, "wind_pct": d.wind_pct, "P": d.penetration_pct, "total_generation_twh": total,
                         "wind_gen_twh": d.wind_pct / 100 * total, "solar_gen_twh": d.solar_pct / 100 * total})
    return pd.DataFrame(rows)


def support_status(e_out: float, h_out: float) -> str:
    """'within_support' / 'partially_out_of_support' / 'mostly_out_of_support' from the beyond-support shares of predicted curtailment (E_out) and of hours (H_out)."""
    if e_out >= MOSTLY_E_OUT:
        return "mostly_out_of_support"
    if e_out >= PARTIAL_E_OUT or h_out >= PARTIAL_H_OUT:
        return "partially_out_of_support"
    return "within_support"


def project_curtailment_hourly(pte, cal: HourlyCalibration, years: Sequence[int] = PROJECTION_YEARS) -> pd.DataFrame:
    """Option E (D24) applied to the PTE scenarios with the by-horizon treatment adopted in Task 11F0. One row per (scenario, year).

    For each technology: the 2025 hourly profile is scaled by the PTE annual totals (wind x W_t/W_2025, solar x S_t/S_2025, load x T_t/T_2025), r_h is the hourly potential VRE share
    of load, curtailed = PTE generation x energy-weighted curve rate (D23: PTE generation is gross). `pte` is a schemas.PTEScenarioTable or the frame of pte_generation_frame.

    Years 2025 / 2030 / 2040 (horizon_treatment = "band_plus_conformal"): E_curt_*_low / _high = the empirical annual-backtest band of Task 11E3 (descriptive, headline);
    conformal80_* = the split-conformal 80 % interval of Task 11E4 (supplement; NaN where unbounded). Year 2050 (horizon_treatment = "decomposition_conditional"): E_curt_*_low / _high are the
    flexibility-conditional range (flexibility phi = 1.5 as the lower scenario, asymptote L = 1 as the upper) - NOT a confidence interval; conformal80_* are always NaN, conformal_available
    and calibrated_label are False (calibration and projection conditions are not exchangeable: the correctly applied procedure is unbounded).
    Every row also carries: the in-support / beyond-support decomposition of the central curtailment, E_out / H_out / D_pp per technology (Task 11E3 distance metrics),
    support_status, partially_out_of_support, the flexibility and L = 1 scenarios for all years, and the known-limitation ids (D25 for wind-containing results, drift_direction).
    The total's conformal interval applies the log-quantile of the unified (wind + solar) calibration to the sum of the technology centrals.
    """
    frame = pte if isinstance(pte, pd.DataFrame) else pte_generation_frame(pte)
    base_year = cal.profile.year
    prof = cal.profile
    rows = []
    for scenario in ("TB", "TA", "TG"):
        for year in years:
            g = frame[(frame["scenario"] == scenario) & (frame["year"] == year)]
            if g.empty:
                raise ProjectionError(f"PTE table has no {year} entry for scenario {scenario}.")
            src = g.iloc[0]
            f = scale_factors(frame, scenario, year, base_year)
            r = projected_r(prof, f)
            r_flex = projected_r(prof, f, cal.bands.phi_low)
            conditional = year >= CONDITIONAL_FROM_YEAR
            row = {"scenario": scenario, "year": int(year), "source": PROJECTION_SOURCE_LABEL, "model": OPTION_E_MODEL_LABEL, "role": "production",
                   "horizon_treatment": HORIZON_CONDITIONAL if conditional else HORIZON_BAND, "solar_pct": src["solar_pct"], "wind_pct": src["wind_pct"], "P": src["P"],
                   "total_generation_twh": src["total_generation_twh"], "wind_gen_twh": f.wind_gen_twh, "solar_gen_twh": f.solar_gen_twh}
            tot = {k: 0.0 for k in ("central", "low", "high", "in", "flex", "L1")}
            h_out = {}
            for tech, curve, curve_l1, pot, gen in (("wind", cal.wind, cal.wind_L1, prof.wind * f.a_wind, f.wind_gen_twh), ("solar", cal.solar, cal.solar_L1, prof.solar * f.a_solar, f.solar_gen_twh)):
                rate = projected_rate(r, pot, curve)
                central = rate * gen
                flex = projected_rate(r_flex, pot, curve) * gen
                l1 = projected_rate(r, pot, curve_l1) * gen
                inside = r <= curve.r_cap
                in_support = float((curve.rate(r) * pot)[inside].sum() / pot.sum() * gen)
                dm = extrapolation_metrics(r, pot, curve.params, curve.r_cap)
                if conditional:
                    low, high = flex, l1
                    clo = chi = float("nan")
                else:
                    flo, fhi = cal.bands.band_factors[tech]
                    low, high = central * flo, central * fhi
                    clo, chi = conformal_interval(central, cal.bands.logq(tech))
                row.update({f"C_{tech}_central": rate, f"E_curt_{tech}_twh": central, f"E_curt_{tech}_twh_low": low, f"E_curt_{tech}_twh_high": high,
                            f"E_curt_{tech}_flex_phi_twh": flex, f"E_curt_{tech}_L1_twh": l1, f"conformal80_{tech}_lo_twh": clo, f"conformal80_{tech}_hi_twh": chi,
                            f"curt_in_support_{tech}_twh": in_support, f"curt_out_support_{tech}_twh": central - in_support, f"r_cap_{tech}": curve.r_cap,
                            f"E_out_{tech}": dm["E_out"], f"H_out_{tech}": dm["H_out"], f"D_pp_{tech}": dm["D_pp"], f"extrapolated_{tech}": bool(dm["H_out"] > 0)})
                for key, v in (("central", central), ("low", low), ("high", high), ("in", in_support), ("flex", flex), ("L1", l1)):
                    tot[key] += v
                h_out[tech] = dm["H_out"]
            total = tot["central"]
            e_out = (total - tot["in"]) / total if total > 0 else 0.0
            tlo, thi = (float("nan"), float("nan")) if conditional else conformal_interval(total, cal.bands.logq("unified"))
            status = support_status(e_out, max(h_out.values()))
            row.update({"E_curt_twh": total, "E_curt_twh_low": tot["low"], "E_curt_twh_high": tot["high"], "E_curt_flex_phi_twh": tot["flex"], "E_curt_L1_twh": tot["L1"],
                        "conformal80_total_lo_twh": tlo, "conformal80_total_hi_twh": thi, "curt_in_support_total_twh": tot["in"], "curt_out_support_total_twh": total - tot["in"],
                        "E_out": e_out, "in_support_fraction": 1 - e_out, "support_status": status, "partially_out_of_support": status != "within_support",
                        "conformal_available": not conditional, "calibrated_label": not conditional, "flex_phi": cal.bands.phi_low,
                        "known_limitations": f"{D25};{SOLAR_SHORT_RECORD}", "drift_direction": DRIFT_DIRECTION})
            rows.append(row)
    return pd.DataFrame(rows)


def build_option_e_table(processed_dir=None, panel: pd.DataFrame | None = None, recalibrate: bool = False) -> pd.DataFrame:
    """Task 11F entry point: calibrate (or load the frozen calibration), project the PTE scenarios and write processed/pte_curtailment_option_E.parquet with its limitations sidecar.

    Fails loudly if the D25 decision is not `adopted` (limitations.load_adopted_decision); needs Stage 1 data in raw/ons when it has to recalibrate.
    """
    from curtailmit.data_ingestion import load_config
    from curtailmit.hourly_model import BASE_PROFILE_FILENAME, load_hourly_calibration, run_hourly_calibration
    from curtailmit.limitations import limitations_payload, write_table_with_limitations
    from curtailmit.paths import get_processed_dir

    processed_dir = processed_dir or get_processed_dir()
    payload = limitations_payload()
    if recalibrate or panel is not None or not (processed_dir / BASE_PROFILE_FILENAME).exists():
        cal = run_hourly_calibration(panel, processed_dir)
    else:
        cal = load_hourly_calibration(processed_dir)
    table = project_curtailment_hourly(load_config().pte_scenarios, cal)
    write_table_with_limitations(table, processed_dir / OPTION_E_FILENAME, payload)
    logger.info("Wrote %s (%d rows)", processed_dir / OPTION_E_FILENAME, len(table))
    return table
