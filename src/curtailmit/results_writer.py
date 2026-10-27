"""
results_writer.py

Final output schema and mechanical writer for the CurtailMit pipeline
final per-scenario/year results table.

This module defines the schema for the final combined output (one row
per scenario x year) and provides CSV/JSON writers and loaders. It does
not compute any values itself - it is a mechanical schema + writer
layer, consuming already-computed rows produced by projection.py,
mitigation.py, hydrogen.py, and emission_factors.py. Real wiring of the
full pipeline into this writer is deferred to Claude Code Task 13.

DEPRECATION (Task 13, decision D27 option A): ResultsRow / RESULTS_COLUMNS / write_results_* / load_results_* are SUPERSEDED by the long-format writer at the end of this module
(build_final_results, build_final_results_with_sensitivity, write_final_results, read_final_results), which is the production path for the option E results. The legacy schema has no
horizon-dependent range, no per-row known_limitations / calibrated_label / support status and a single E_curt_twh; it stays importable and tested for backward compatibility only.
Nothing in the legacy part has been changed.

Schema notes
------------
- Marginal mitigation deficit is reported as a breakdown of BOTH the
  Operating Margin (OM) proxy value (DEB proxy) and the Combined Margin
  (CM) proxy value (REB proxy), never collapsed into one undifferentiated
  "marginal" number. This allows downstream analysis and the DeCarbon
  manuscript to present DEB- and REB-specific deficit sensitivity
  independently, consistent with docs/methodology.md Section 2.5 and
  decision D12.
- classification_available is always recorded explicitly. It reflects
  whether ONS curtailment classification (DEB/REB/EUB) was available at
  the data stage; it does not gate whether OM/CM columns are present
  (those are always computed, as general marginal proxies), but it does
  affect how the OM/CM figures should be interpreted in the manuscript
  (classification-specific proxies vs. generic marginal proxies).
- H2 potential is always a min/central/max range, never a single point.
- is_interpolated / source follow projection.py labeling convention
  exactly (source in {"historical_ons", "pte_projection",
  "interpolated"}).
"""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from curtailmit.hydrogen import compute_hydrogen_potential
from curtailmit.limitations import D25_DRIFT_PERIOD, D25_DRIFT_RANGE, DRIFT_DIRECTION, FLEX_2050_RANGE, LIMITATIONS_SIDECAR_SUFFIX, SOLAR_MONTHS, limitations_payload, write_table_with_limitations
from curtailmit.mitigation import REQUIRED_MODEL, ModelProvenanceError, check_provenance, compute_mitigation
from curtailmit.validation import ValidationError, validate_mcti_factor_coverage

VALID_SOURCES = ("historical_ons", "pte_projection", "interpolated")


@dataclass(frozen=True)
class ResultsRow:
    """DEPRECATED (D27, Task 13): legacy wide row, one scenario x year. Superseded by the long-format writer (build_final_results); kept importable for backward compatibility."""

    scenario: str
    year: int
    source: str
    is_interpolated: bool
    classification_available: bool

    E_curt_twh: float

    mitigation_deficit_avg_tco2: float
    mitigation_deficit_marginal_om_tco2: float
    mitigation_deficit_marginal_cm_tco2: float
    marginal_proxy_note: str

    h2_potential_min_kg: float
    h2_potential_central_kg: float
    h2_potential_max_kg: float

    def __post_init__(self) -> None:
        if self.source not in VALID_SOURCES:
            raise ValidationError(
                f"source must be one of {VALID_SOURCES}, got {self.source!r}."
            )
        if self.source == "historical_ons" and self.is_interpolated:
            raise ValidationError(
                "A row sourced from historical_ons cannot be is_interpolated=True."
            )
        if self.source == "interpolated" and not self.is_interpolated:
            raise ValidationError(
                "A row with source='interpolated' must have is_interpolated=True."
            )
        if self.E_curt_twh < 0:
            raise ValidationError(f"E_curt_twh must be non-negative, got {self.E_curt_twh}.")
        if self.mitigation_deficit_avg_tco2 < 0:
            raise ValidationError("mitigation_deficit_avg_tco2 must be non-negative.")
        if self.mitigation_deficit_marginal_om_tco2 < 0:
            raise ValidationError("mitigation_deficit_marginal_om_tco2 must be non-negative.")
        if self.mitigation_deficit_marginal_cm_tco2 < 0:
            raise ValidationError("mitigation_deficit_marginal_cm_tco2 must be non-negative.")
        if not (self.h2_potential_min_kg <= self.h2_potential_central_kg <= self.h2_potential_max_kg):
            raise ValidationError(
                "H2 potential range must satisfy min <= central <= max "
                f"(got min={self.h2_potential_min_kg}, "
                f"central={self.h2_potential_central_kg}, "
                f"max={self.h2_potential_max_kg})."
            )


RESULTS_COLUMNS: tuple[str, ...] = tuple(f.name for f in fields(ResultsRow))


def write_results_csv(rows: Iterable[ResultsRow], path: Path) -> Path:
    """Write rows to a CSV file at path, creating parent dirs as needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RESULTS_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))
    return path


def write_results_json(rows: Iterable[ResultsRow], path: Path) -> Path:
    """Write rows to a JSON file at path, creating parent dirs as needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    data = [asdict(row) for row in rows]
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def load_results_csv(path: Path) -> list[ResultsRow]:
    """Load and reconstruct ResultsRow objects from a CSV file."""
    path = Path(path)
    rows: list[ResultsRow] = []
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            rows.append(_row_from_raw_dict(raw))
    return rows


def load_results_json(path: Path) -> list[ResultsRow]:
    """Load and reconstruct ResultsRow objects from a JSON file."""
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    return [_row_from_raw_dict(raw) for raw in data]


def _row_from_raw_dict(raw: dict[str, Any]) -> ResultsRow:
    coerced: dict[str, Any] = dict(raw)
    coerced["year"] = int(raw["year"])
    coerced["is_interpolated"] = _coerce_bool(raw["is_interpolated"])
    coerced["classification_available"] = _coerce_bool(raw["classification_available"])
    for key in (
        "E_curt_twh",
        "mitigation_deficit_avg_tco2",
        "mitigation_deficit_marginal_om_tco2",
        "mitigation_deficit_marginal_cm_tco2",
        "h2_potential_min_kg",
        "h2_potential_central_kg",
        "h2_potential_max_kg",
    ):
        coerced[key] = float(raw[key])
    return ResultsRow(**coerced)


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)


# ================================================================================================================================================
# Task 13 (D27 option A): long-format final results writer for the option E production table. This is the production path.
# ================================================================================================================================================
#
# One row per scenario x year x quantity x component. Every row repeats the caveat columns (known_limitations, known_limitations_text, calibrated_label, support_status,
# partially_out_of_support, drift_direction), so a filtered subset or a copy into a spreadsheet still carries them. The horizon-dependent range is reported as `conditional_range_*`
# with a mandatory free-text `range_basis`; it is a range implied by stated assumptions (2025-2040: empirical annual-backtest band; 2050: flexibility assumption), never a
# probabilistic statement. The split-conformal supplement (2025-2040 only) lives in its own columns. No arithmetic of its own: energy -> tCO2 is mitigation.compute_mitigation,
# energy -> kg H2 is hydrogen.compute_hydrogen_potential (D28: the energy range is passed through the fixed emission factor after the OM/CM split; D29: factor year 2025,
# 2021-2025 mean as a labelled sensitivity).

FINAL_RESULTS_FILENAME = "final_results"
SENSITIVITY_FILENAME = "final_results_mcti_sensitivity"
OPTION_E_FILENAME = "pte_curtailment_option_E.parquet"
MCTI_CENTRAL_YEAR = 2025
MCTI_SENSITIVITY_YEARS = (2021, 2025)
SENSITIVITY_COLUMN = "mcti_sensitivity_avg_2021_2025_central_value"
DEFAULT_SEC_KWH_PER_KG = (50.0, 52.5, 55.0)
HORIZON_BAND = "band_plus_conformal"
HORIZON_CONDITIONAL = "decomposition_conditional"
EMPIRICAL_BAND_BASIS = "empirical_annual_backtest_band_task11e3; not a coverage guarantee"
SUPPLEMENT_BASIS = "split_conformal_nominal_80_finite_sample_rule"
SUPPLEMENT_BASIS_TOTAL = SUPPLEMENT_BASIS + "; total is an approximation (unified log-quantile applied to the sum of the technology central values)"
SUPPLEMENT_UNAVAILABLE = "not_available_2050_exchangeability_not_certifiable"
MODEL_TABLE_COLUMNS = ("model", "role", "horizon_treatment", "support_status", "partially_out_of_support", "calibrated_label", "known_limitations", "drift_direction", "conformal_available")

FINAL_COLUMNS: tuple[str, ...] = (
    "scenario", "year", "quantity", "component", "unit",
    "central_value", "conditional_range_low", "conditional_range_high", "range_basis", "central_inside_range",
    "supplement_low", "supplement_high", "supplement_basis",
    "sec_sensitivity_low", "sec_sensitivity_high",
    "horizon_treatment", "in_support_fraction", "support_status", "partially_out_of_support", "calibrated_label",
    "known_limitations", "known_limitations_text", "drift_direction",
    "model", "role", "source", "is_interpolated",
    "mcti_factor_year", "emission_factor_basis", "marginal_proxy_note", "classification_available",
    SENSITIVITY_COLUMN,
)
QUANTITIES = ("curtailed_energy", "mitigation_deficit_avg", "mitigation_deficit_marginal_om", "mitigation_deficit_marginal_cm", "h2_potential")
COMPONENTS = ("total", "wind", "solar")
# Language that must never describe the horizon-dependent range (checked on column names, text columns and this module's own text).
FORBIDDEN_LANGUAGE = re.compile(r"(^|[^a-z])ci_|_ci($|[^a-z])|confiden|credible|margin of error", re.IGNORECASE)
_TEXT_COLUMNS = ("range_basis", "supplement_basis", "known_limitations_text", "emission_factor_basis", "marginal_proxy_note", "quantity", "component")


class FinalResultsError(RuntimeError):
    """The final results table violates a schema or caveat-propagation rule."""


class SupportStatusConflictError(FinalResultsError):
    """The support status of the option E table disagrees with projection.support_status recomputed from the table's own E_out / H_out columns."""


@dataclass(frozen=True)
class FactorYearRule:
    """Which MCTI factor year(s) are applied to every projection year (D29)."""

    label: str  # value of the mcti_factor_year column
    years: tuple[int, ...]  # years whose factor values are averaged (one year = held fixed)

    def describe(self) -> str:
        return f"fixed at {self.years[0]}" if len(self.years) == 1 else f"fixed at the mean of {self.years[0]}-{self.years[-1]}"

    def factors_for(self, years: Sequence[int], average_factors: pd.DataFrame, marginal_factors: pd.DataFrame, om_col: str = "om", cm_col: str = "cm") -> tuple[pd.DataFrame, pd.DataFrame]:
        """(average, marginal) factor frames with one row per requested projection year, all carrying the rule's value."""
        span = list(range(self.years[0], self.years[-1] + 1)) if len(self.years) > 1 else list(self.years)
        validate_mcti_factor_coverage(average_factors["year"].tolist(), span)
        validate_mcti_factor_coverage(marginal_factors["year"].tolist(), span)
        avg = float(average_factors.loc[average_factors.year.isin(span), "factor_tco2_per_mwh"].mean())
        marg = marginal_factors.loc[marginal_factors.year.isin(span)]
        yrs = sorted({int(y) for y in years})
        return (pd.DataFrame({"year": yrs, "factor_tco2_per_mwh": avg}),
                pd.DataFrame({"year": yrs, "om_factor": float(marg[om_col].mean()), "cm_factor": float(marg[cm_col].mean())}))


CENTRAL_FACTOR_RULE = FactorYearRule(label=str(MCTI_CENTRAL_YEAR), years=(MCTI_CENTRAL_YEAR,))
SENSITIVITY_FACTOR_RULE = FactorYearRule(label="mean_2021_2025", years=MCTI_SENSITIVITY_YEARS)


def load_option_e_table(processed_dir: Path | None = None) -> pd.DataFrame:
    """The sole input of the final layer: processed/pte_curtailment_option_E.parquet."""
    from curtailmit.paths import get_processed_dir

    path = (Path(processed_dir) if processed_dir is not None else get_processed_dir()) / OPTION_E_FILENAME
    if not path.exists():
        raise FinalResultsError(f"{path} not found: run projection.build_option_e_table first (Task 11F).")
    return pd.read_parquet(path)


def load_emission_factors(processed_dir: Path | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(average factors [year, factor_tco2_per_mwh], margin factors [year, om, bm, cm, ...]) from the Stage 1 products."""
    from curtailmit.paths import get_processed_dir

    base = Path(processed_dir) if processed_dir is not None else get_processed_dir()
    return pd.read_parquet(base / "mcti_average_factor_annual.parquet"), pd.read_parquet(base / "mcti_margin_factors.parquet")


def limitations_text(row: pd.Series) -> str:
    """Self-contained one-paragraph caveat for a row (so that a copied row explains itself). The full adopted D25 text travels in the sidecar."""
    parts = [f"Central values are more likely low than high: residual {DRIFT_DIRECTION} drift of the wind curtailment rate at fixed hourly VRE share (D25; {D25_DRIFT_RANGE} pp per year over {D25_DRIFT_PERIOD}, not corrected)."]
    if "SOLAR_SHORT_RECORD" in str(row["known_limitations"]):
        parts.append(f"Solar curve fitted on {SOLAR_MONTHS} months (shorter record than wind).")
    if row["support_status"] != "within_support":
        parts.append(f"Part of the projected curtailment ({100 * (1 - float(row['in_support_fraction'])):.0f} percent) comes from hours with no historical analogue ({row['support_status']}).")
    if row["horizon_treatment"] == HORIZON_CONDITIONAL:
        parts.append(f"2050 values are a range conditional on a flexibility assumption ({FLEX_2050_RANGE}), not a calibrated forecast; the emission factor is a fixed point value (D28).")
    return " ".join(parts)


def _check_upstream(option_e: pd.DataFrame) -> None:
    from curtailmit.projection import support_status

    need = {"scenario", "year", "E_curt_twh", *MODEL_TABLE_COLUMNS, "in_support_fraction", "E_out", "H_out_wind", "H_out_solar", "flex_phi"}
    miss = sorted(need - set(option_e.columns))
    if miss:
        raise FinalResultsError(f"option E table lacks required columns {miss}")
    if option_e[["known_limitations", "drift_direction", "calibrated_label", "support_status"]].isna().any().any():
        raise FinalResultsError("option E table has rows without known_limitations / drift_direction / calibrated_label / support_status")
    if not option_e["known_limitations"].astype(str).str.contains("D25").all():
        raise FinalResultsError("every production row must carry D25 in known_limitations")
    for r in option_e.itertuples():
        expect = support_status(float(r.E_out), max(float(r.H_out_wind), float(r.H_out_solar)))
        if expect != r.support_status or bool(r.partially_out_of_support) != (expect != "within_support"):
            raise SupportStatusConflictError(f"{r.scenario} {r.year}: table says {r.support_status!r} (partially_out_of_support={r.partially_out_of_support}), projection.support_status gives {expect!r}")


def _energy_columns(component: str) -> tuple[str, str, str]:
    mid = "" if component == "total" else f"_{component}"
    return f"E_curt{mid}_twh", f"E_curt{mid}_twh_low", f"E_curt{mid}_twh_high"


def _conformal_columns(component: str) -> tuple[str, str]:
    return f"conformal80_{component}_lo_twh", f"conformal80_{component}_hi_twh"


def _mitigation_column(name: str, component: str, suffix: str) -> str:
    mid = "" if component == "total" else f"_{component}"
    return f"mitigation_deficit_{name}{mid}_tco2{suffix}"


def _derived(option_e: pd.DataFrame, lo_hi: str) -> pd.DataFrame:
    """Frame for compute_mitigation / hydrogen in which the energy columns are the conformal supplement end point (so no second formula exists)."""
    out = option_e[["scenario", "year", *MODEL_TABLE_COLUMNS]].copy()
    k = 0 if lo_hi == "lo" else 1
    for comp in COMPONENTS:
        out[_energy_columns(comp)[0]] = option_e[_conformal_columns(comp)[k]].to_numpy()
    return out


def _basis_range(option_e: pd.DataFrame) -> pd.Series:
    cond = option_e["horizon_treatment"] == HORIZON_CONDITIONAL
    flex = option_e["flex_phi"].map(lambda v: f"flexibility_assumption_phi_{v:g}_to_L1; conditional on the flexibility assumption, not a probabilistic statement")
    return flex.where(cond, EMPIRICAL_BAND_BASIS)


def build_final_results(
    option_e: pd.DataFrame,
    average_factors: pd.DataFrame,
    marginal_factors: pd.DataFrame,
    classification_available: bool,
    factor_rule: FactorYearRule = CENTRAL_FACTOR_RULE,
    sec: tuple[float, float, float] = DEFAULT_SEC_KWH_PER_KG,
) -> pd.DataFrame:
    """Long-format final results for the option E table. `marginal_factors` has columns [year, om, cm] (mcti_margin_factors.parquet). Raises ModelProvenanceError unless every row is option_E_hourly."""
    check_provenance(option_e)
    _check_upstream(option_e)
    option_e = option_e.reset_index(drop=True)
    years = option_e["year"].unique()
    avg_f, marg_f = factor_rule.factors_for(years, average_factors, marginal_factors)
    mit = compute_mitigation(option_e, avg_f, marg_f, classification_available, require_model=True, split_margins=True)
    sup = {k: compute_mitigation(_derived(option_e, k), avg_f, marg_f, classification_available, require_model=True, split_margins=True) for k in ("lo", "hi")}
    h2 = {}
    for key, col in (("c", "E_curt_twh"), ("lo", "E_curt_twh_low"), ("hi", "E_curt_twh_high")):
        h2[key] = compute_hydrogen_potential(option_e.assign(E_curt_twh=option_e[col])[["scenario", "year", "E_curt_twh"]], *sec)
    h2_sup = {k: compute_hydrogen_potential(_derived(option_e, k)[["scenario", "year", "E_curt_twh"]].fillna({"E_curt_twh": 0.0}), *sec) for k in ("lo", "hi")}  # NaN (2050) masked in block()

    n = len(option_e)
    nan = np.full(n, np.nan)
    band = _basis_range(option_e)
    marginal_note = (
        "OM = DEB proxy, CM = REB proxy (alternative proxies of the marginal factor, D12; never summed); classified curtailment data available" if classification_available
        else "OM and CM are generic marginal proxies; curtailment is aggregate (unclassified)"
    )
    blocks = []

    def block(quantity: str, component: str, unit: str, central, low, high, s_lo, s_hi, basis_suffix: str, factor_basis: str, sec_lo=None, sec_hi=None) -> None:
        b = option_e[["scenario", "year", "horizon_treatment", "in_support_fraction", "support_status", "partially_out_of_support", "calibrated_label", "known_limitations", "drift_direction", "model", "role", "source"]].copy()
        b["quantity"], b["component"], b["unit"] = quantity, component, unit
        b["central_value"], b["conditional_range_low"], b["conditional_range_high"] = np.asarray(central, float), np.asarray(low, float), np.asarray(high, float)
        b["range_basis"] = band + basis_suffix
        b["central_inside_range"] = (b["conditional_range_low"] <= b["central_value"]) & (b["central_value"] <= b["conditional_range_high"])
        has_sup = option_e["conformal_available"].to_numpy(bool)
        b["supplement_low"] = np.where(has_sup, np.asarray(s_lo, float), np.nan) if s_lo is not None else nan
        b["supplement_high"] = np.where(has_sup, np.asarray(s_hi, float), np.nan) if s_hi is not None else nan
        sb = SUPPLEMENT_BASIS_TOTAL if component == "total" else SUPPLEMENT_BASIS
        b["supplement_basis"] = np.where(has_sup, sb, SUPPLEMENT_UNAVAILABLE)
        b["sec_sensitivity_low"] = np.asarray(sec_lo, float) if sec_lo is not None else nan
        b["sec_sensitivity_high"] = np.asarray(sec_hi, float) if sec_hi is not None else nan
        b["is_interpolated"] = False
        b["mcti_factor_year"] = factor_rule.label if quantity.startswith("mitigation") else "not_applicable"
        b["emission_factor_basis"] = factor_basis
        b["marginal_proxy_note"] = marginal_note if quantity.startswith("mitigation_deficit_marginal") else "not_applicable"
        b["classification_available"] = classification_available
        blocks.append(b)

    for comp in COMPONENTS:
        c, lo, hi = _energy_columns(comp)
        slo, shi = _conformal_columns(comp)
        block("curtailed_energy", comp, "TWh", option_e[c], option_e[lo], option_e[hi], option_e[slo], option_e[shi], "", "not_applicable")
    fixed = factor_rule.describe()
    basis = {
        "avg": f"MCTI annual average SIN factor, {fixed}",
        "marginal_om": f"MCTI Operating Margin (simple mean of 12 monthly values; DEB proxy), {fixed}",
        "marginal_cm": f"MCTI Combined Margin = 0.5 OM + 0.5 BM (derived, D12; REB proxy), {fixed}",
    }
    suffix = f"; energy range only; emission factor {fixed}, not included in range"
    for name in ("avg", "marginal_om", "marginal_cm"):
        for comp in COMPONENTS:
            block(f"mitigation_deficit_{name}", comp, "tCO2", mit[_mitigation_column(name, comp, "")], mit[_mitigation_column(name, comp, "_low")], mit[_mitigation_column(name, comp, "_high")],
                  sup["lo"][_mitigation_column(name, comp, "")], sup["hi"][_mitigation_column(name, comp, "")], suffix, basis[name])
    block("h2_potential", "total", "kg_H2", h2["c"]["h2_potential_central_kg"], h2["lo"]["h2_potential_central_kg"], h2["hi"]["h2_potential_central_kg"],
          h2_sup["lo"]["h2_potential_central_kg"], h2_sup["hi"]["h2_potential_central_kg"], f"; energy range only; electrolyzer SEC fixed at {sec[1]} kWh/kg (SEC {sec[0]}-{sec[2]} in sec_sensitivity_*)", "not_applicable",
          sec_lo=h2["c"]["h2_potential_min_kg"], sec_hi=h2["c"]["h2_potential_max_kg"])
    out = pd.concat(blocks, ignore_index=True)
    out["known_limitations_text"] = [limitations_text(r) for _, r in out.iterrows()]
    out[SENSITIVITY_COLUMN] = np.nan
    out = out[list(FINAL_COLUMNS)]
    validate_final_results(out)
    return out


def build_final_results_with_sensitivity(option_e: pd.DataFrame, average_factors: pd.DataFrame, marginal_factors: pd.DataFrame, classification_available: bool,
                                         sec: tuple[float, float, float] = DEFAULT_SEC_KWH_PER_KG) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(central table with the 2025 factor, companion sensitivity table with the 2021-2025 mean factor). The central table carries the sensitivity central value in its own column."""
    central = build_final_results(option_e, average_factors, marginal_factors, classification_available, CENTRAL_FACTOR_RULE, sec)
    sens = build_final_results(option_e, average_factors, marginal_factors, classification_available, SENSITIVITY_FACTOR_RULE, sec)
    key = ["scenario", "year", "quantity", "component"]
    lookup = sens.set_index(key)["central_value"]
    mit = central["quantity"].str.startswith("mitigation")
    vals = lookup.reindex(pd.MultiIndex.from_frame(central[key])).to_numpy()
    central[SENSITIVITY_COLUMN] = np.where(mit, vals, np.nan)
    validate_final_results(central)
    return central, sens


def validate_final_results(df: pd.DataFrame) -> None:
    """Schema, provenance, caveat-propagation and language rules. Raises FinalResultsError."""
    miss = [c for c in FINAL_COLUMNS if c not in df.columns]
    if miss:
        raise FinalResultsError(f"missing columns {miss}")
    bad_names = [c for c in df.columns if FORBIDDEN_LANGUAGE.search(c)]
    if bad_names:
        raise FinalResultsError(f"forbidden wording (probabilistic-interval vocabulary) in column names {bad_names}")
    for col in _TEXT_COLUMNS:
        hits = df.loc[df[col].astype(str).map(lambda s: bool(FORBIDDEN_LANGUAGE.search(s))), col]
        if len(hits):
            raise FinalResultsError(f"forbidden wording (probabilistic-interval vocabulary) in column {col}: {hits.iloc[0]!r}")
    if (df["model"] != REQUIRED_MODEL).any() or (df["role"] != "production").any():
        raise ModelProvenanceError("final results may only contain model == 'option_E_hourly', role == 'production'")
    if df[["range_basis", "known_limitations", "known_limitations_text", "calibrated_label", "support_status", "drift_direction", "horizon_treatment"]].isna().any().any():
        raise FinalResultsError("range_basis / caveat columns must be populated on every row")
    if (df["range_basis"].astype(str).str.strip() == "").any() or (df["known_limitations_text"].astype(str).str.strip() == "").any():
        raise FinalResultsError("range_basis and known_limitations_text must be non-empty on every row")
    if not df["known_limitations"].str.contains("D25").all():
        raise FinalResultsError("known_limitations must contain D25 on every production row")
    if (df["conditional_range_low"] > df["conditional_range_high"]).any():
        raise FinalResultsError("conditional_range_low > conditional_range_high")
    cond = df["horizon_treatment"] == HORIZON_CONDITIONAL
    if (df["calibrated_label"].astype(bool) != (df["horizon_treatment"] == HORIZON_BAND)).any():
        raise FinalResultsError("calibrated_label must be True exactly for band_plus_conformal rows and False for decomposition_conditional rows")
    if (cond & (df["year"] != 2050)).any() or ((df["year"] == 2050) & ~cond).any():
        raise FinalResultsError("2050 rows must carry decomposition_conditional (and only 2050 rows)")
    if (cond & (df["supplement_low"].notna() | df["supplement_high"].notna())).any():
        raise FinalResultsError("the conformal supplement must be empty for 2050 rows")
    if (cond & ~df["range_basis"].str.contains("flexibility_assumption")).any():
        raise FinalResultsError("2050 range_basis must state the flexibility assumption")
    mit = df["quantity"].str.startswith("mitigation")
    if (mit & ~df["range_basis"].str.contains("not included in range")).any():
        raise FinalResultsError("mitigation range_basis must state that the emission factor is outside the range (D28)")
    if (df["partially_out_of_support"].astype(bool) != (df["support_status"] != "within_support")).any():
        raise FinalResultsError("partially_out_of_support disagrees with support_status")
    om_cm = df[df["quantity"].isin(["mitigation_deficit_marginal_om", "mitigation_deficit_marginal_cm"])]
    key = ["scenario", "year", "component"]
    if len(om_cm) and not (om_cm.groupby(key)["quantity"].nunique() == 2).all():
        raise FinalResultsError("OM and CM must be present together for every scenario/year/component")
    if not set(df["quantity"]) <= set(QUANTITIES):
        raise FinalResultsError(f"unknown quantities {sorted(set(df['quantity']) - set(QUANTITIES))}: OM and CM must never be combined into one quantity")


def limitations_sidecar_payload(path: Path | None = None) -> dict:
    """Sidecar content: the verbatim adopted D25 text (limitations.py), the D26 note, the D28 composition note and the D29 factor-year rule."""
    payload = limitations_payload(path)
    payload["uncertainty_composition"] = (
        "Final 2050 figures carry a partial uncertainty composition: an energy-side range conditional on a flexibility assumption (phi 1.5 to L=1) and a point-value emission factor fixed at "
        f"{MCTI_CENTRAL_YEAR} (D28). The range is not a probabilistic statement and the emission factor is not conditioned on the same assumption."
    )
    payload["emission_factor_rule"] = f"Central: MCTI factor of {MCTI_CENTRAL_YEAR} for all projection years (D29). Sensitivity: mean {MCTI_SENSITIVITY_YEARS[0]}-{MCTI_SENSITIVITY_YEARS[1]}, file {SENSITIVITY_FILENAME}."
    return payload


def write_final_results(central: pd.DataFrame, sensitivity: pd.DataFrame | None = None, out_dir: Path | None = None) -> dict[str, Path]:
    """Write final_results.{csv,parquet,limitations.json} and, when given, the sensitivity companion table. Returns the paths."""
    from curtailmit.paths import get_outputs_dir

    validate_final_results(central)
    out_dir = Path(out_dir) if out_dir is not None else get_outputs_dir("tables")
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = limitations_sidecar_payload()
    paths = {"csv": out_dir / f"{FINAL_RESULTS_FILENAME}.csv", "parquet": out_dir / f"{FINAL_RESULTS_FILENAME}.parquet"}
    central.to_csv(paths["csv"], index=False, encoding="utf-8")
    write_table_with_limitations(central, paths["parquet"], payload)
    paths["limitations"] = paths["parquet"].with_name(paths["parquet"].name + LIMITATIONS_SIDECAR_SUFFIX)
    if sensitivity is not None:
        validate_final_results(sensitivity)
        paths["sensitivity_csv"] = out_dir / f"{SENSITIVITY_FILENAME}.csv"
        paths["sensitivity_parquet"] = out_dir / f"{SENSITIVITY_FILENAME}.parquet"
        sensitivity.to_csv(paths["sensitivity_csv"], index=False, encoding="utf-8")
        write_table_with_limitations(sensitivity, paths["sensitivity_parquet"], payload)
    return paths


def read_final_results(path: Path) -> pd.DataFrame:
    """Read a final results CSV or parquet and re-validate it."""
    path = Path(path)
    df = pd.read_csv(path, dtype={"mcti_factor_year": str}) if path.suffix == ".csv" else pd.read_parquet(path)
    for col in ("calibrated_label", "partially_out_of_support", "central_inside_range", "classification_available", "is_interpolated"):
        df[col] = df[col].astype(bool)
    validate_final_results(df)
    return df


def run_final_results(processed_dir: Path | None = None, out_dir: Path | None = None) -> dict[str, Path]:
    """End to end: option E table + Stage 1 factors + classification flag -> final_results (central, 2025 factor) and the 2021-2025 sensitivity companion, written to outputs/tables."""
    from curtailmit.paths import get_processed_dir

    base = Path(processed_dir) if processed_dir is not None else get_processed_dir()
    flag_path = base / "classification_available.json"
    if not flag_path.exists():
        raise FinalResultsError(f"{flag_path} not found: the classification flag must be propagated from Stage 1 (D6).")
    classification_available = bool(json.loads(flag_path.read_text(encoding="utf-8"))["classification_available"])
    avg, margins = load_emission_factors(base)
    central, sens = build_final_results_with_sensitivity(load_option_e_table(base), avg, margins, classification_available)
    return write_final_results(central, sens, out_dir)
