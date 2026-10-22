"""Pydantic v2 schemas for CurtailMit configuration and intermediate data."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

ScenarioName = Literal["TB", "TA", "TG"]


class ScenarioYearData(BaseModel):
    solar_pct: float = Field(ge=0, le=100)
    wind_pct: float = Field(ge=0, le=100)
    total_generation_twh: float = Field(gt=0)

    @model_validator(mode="after")
    def check_penetration_bound(self) -> ScenarioYearData:
        total = self.solar_pct + self.wind_pct
        if total > 100:
            raise ValueError(
                f"solar_pct + wind_pct = {total} > 100 - invalid penetration value."
            )
        return self

    @property
    def penetration_pct(self) -> float:
        return self.solar_pct + self.wind_pct

    @property
    def solar_wind_generation_twh(self) -> float:
        return (self.penetration_pct / 100) * self.total_generation_twh


class BaselineConfig(BaseModel):
    source: Literal["historical_ons", "pte_projection"]
    note: str | None = None


class ElectrolyzerSEC(BaseModel):
    min: float
    max: float
    central_estimate: float

    @model_validator(mode="after")
    def check_bounds(self) -> ElectrolyzerSEC:
        if not (self.min <= self.central_estimate <= self.max):
            raise ValueError("central_estimate must lie within [min, max].")
        return self


class PTEScenarioTable(BaseModel):
    TB: dict[int, ScenarioYearData]
    TA: dict[int, ScenarioYearData]
    TG: dict[int, ScenarioYearData]

    def all_valid(self) -> bool:
        for scenario_years in (self.TB, self.TA, self.TG):
            for year_data in scenario_years.values():
                if year_data.penetration_pct > 100:
                    return False
        return True


class PipelineConfig(BaseModel):
    year_grid: list[int]
    interpolation_method: Literal["linear"]
    baseline_2020: BaselineConfig
    pte_scenarios: PTEScenarioTable


# --- Acquisition / provenance ----------------------------------------------

class RetrievalManifest(BaseModel):
    source_url: str
    http_status: int
    retrieved_at_utc: str
    sha256: str
    byte_size: int
    params: dict[str, Any] = Field(default_factory=dict)
    # Optional generic-manifest fields (added for manifest.py / multi-source
    # acquisition support: ONS, MCTI, ANEEL). All optional and default to
    # None so existing callers (e.g. acquisition.py::fetch_and_cache) that
    # do not supply them remain fully backward compatible.
    source: str | None = None
    package_id: str | None = None
    resource_id: str | None = None
    row_count: int | None = None


# --- Stage 1 outputs ---------------------------------------------------------

class CoverageInfo(BaseModel):
    earliest_date: str | None = None
    latest_date: str | None = None
    n_records: int = 0


class Baseline2020Generation(BaseModel):
    source: Literal["historical_ons"] = "historical_ons"
    year: Literal[2020] = 2020
    solar_twh: float
    wind_twh: float
    total_twh: float

    @property
    def penetration_pct(self) -> float:
        return 100 * (self.solar_twh + self.wind_twh) / self.total_twh


CheckStatus = Literal["PASS", "WARNING", "NOT APPLICABLE", "FAIL"]


class CheckResult(BaseModel):
    """One checked item of the Stage 1 report. WARNING = a documented, non-blocking limitation (never collapsed into PASS)."""

    id: str
    name: str
    status: CheckStatus
    detail: str
    decisions: list[str] = Field(default_factory=list)


class DataQualityReport(BaseModel):
    timestamp_utc: str
    ons_wind_coverage: CoverageInfo
    ons_solar_coverage: CoverageInfo
    classification_available: bool
    classification_reason: str
    mcti_average_factor_coverage: CoverageInfo
    mcti_marginal_factor_years: list[int] = Field(default_factory=list)
    fallback_sources_used: list[str] = Field(default_factory=list)
    validation_data_loaded: bool
    overall_status: Literal["ok", "degraded", "failed"]
    # --- Task 8 extension (all optional: older callers keep working) ---
    stage: str = "stage1"
    solar_curtailment_2020_baseline: str = "documented_zero_not_measured"  # D14
    ons_generation_coverage: CoverageInfo = Field(default_factory=CoverageInfo)
    dispatched_solar_coverage: CoverageInfo = Field(default_factory=CoverageInfo)  # D20 (earliest/latest = months, n_records = months)
    solar_basis_dispatched_from: str | None = None
    baseline_2020: dict[str, float | str] = Field(default_factory=dict)
    pre_2023_solar_gap: dict[str, float | str | None] = Field(default_factory=dict)
    anomalous_days: list[str] = Field(default_factory=list)
    capacity_factor_schema_differences: list[str] = Field(default_factory=list)
    classification_energy_gwh_by_category: dict[str, float] = Field(default_factory=dict)
    classification_unclassified_share_pct: float | None = None
    mcti_average_years: list[int] = Field(default_factory=list)
    mcti_skipped_years: dict[str, str] = Field(default_factory=dict)
    mcti_om_is_derived: bool | None = None
    mcti_cm_is_derived: bool | None = None
    mcti_manual_ingestion_used: list[str] = Field(default_factory=list)
    pld_enabled: bool = False  # D10
    aneel_fallback_invoked: bool = False  # D19
    manifest_summary: dict[str, dict[str, Any]] = Field(default_factory=dict)
    checks: list[CheckResult] = Field(default_factory=list)
    calibration_readiness_note: str = ""  # forward-looking (D21/D22); NOT a Stage 1 data-quality finding


# --- Stage 2 outputs ---------------------------------------------------------

class CalibrationParams(BaseModel):
    functional_form: Literal["logistic"] = "logistic"
    params: dict[str, float]
    fit_date_utc: str
    validation_rmse: float | None = None
    n_calibration_points: int


# --- Stage 3 outputs ---------------------------------------------------------

class ProjectionRow(BaseModel):
    scenario: ScenarioName
    year: int
    P: float
    C_hat: float
    E_curt_twh: float
    source: Literal["historical_ons", "pte_published", "interpolated"]


# --- Stage 4 outputs ---------------------------------------------------------

class MitigationRow(BaseModel):
    scenario: ScenarioName
    year: int
    E_curt_twh: float
    mitigation_deficit_avg_tco2: float
    mitigation_deficit_marginal_tco2: float
    marginal_proxy_used: str
    classification_available: bool
    # Task 11B (additive, optional): low/high from the bootstrap CI of the two curves (sampling uncertainty only, D21/D22) and the wind/solar split.
    E_curt_twh_low: float | None = None
    E_curt_twh_high: float | None = None
    E_curt_wind_twh: float | None = None
    E_curt_wind_twh_low: float | None = None
    E_curt_wind_twh_high: float | None = None
    E_curt_solar_twh: float | None = None
    E_curt_solar_twh_low: float | None = None
    E_curt_solar_twh_high: float | None = None
    mitigation_deficit_avg_tco2_low: float | None = None
    mitigation_deficit_avg_tco2_high: float | None = None
    mitigation_deficit_marginal_tco2_low: float | None = None
    mitigation_deficit_marginal_tco2_high: float | None = None
    mitigation_deficit_avg_wind_tco2: float | None = None
    mitigation_deficit_avg_solar_tco2: float | None = None
    mitigation_deficit_marginal_wind_tco2: float | None = None
    mitigation_deficit_marginal_solar_tco2: float | None = None
    extrapolated_wind: bool | None = None
    extrapolated_solar: bool | None = None


# --- Stage 5 outputs ---------------------------------------------------------

class HydrogenRow(BaseModel):
    scenario: ScenarioName
    year: int
    h2_potential_min_kg: float
    h2_potential_central_kg: float
    h2_potential_max_kg: float

    @model_validator(mode="after")
    def check_ordering(self) -> HydrogenRow:
        if not (self.h2_potential_min_kg <= self.h2_potential_central_kg <= self.h2_potential_max_kg):
            raise ValueError("H2 potential range must satisfy min <= central <= max.")
        return self


class CurtailmentPackageDiscovery(BaseModel):
    """Outcome of discovering/re-confirming one ONS curtailment CKAN package (Task 2)."""

    source: Literal["wind", "solar"]
    configured_package_id: str
    resolved_package_id: str
    used_fallback_search: bool = False
    n_resources: int = Field(ge=0)
    formats_seen: list[str] = Field(default_factory=list)
    n_months_downloaded: int = Field(default=0, ge=0)
    n_rows: int = Field(default=0, ge=0)
    earliest_date: str | None = None
    latest_date: str | None = None


class DictionaryCheck(BaseModel):
    """Outcome of reading an ONS data dictionary for scope statements (Task 6B). Verbatim texts, never paraphrased."""

    package_id: str
    dictionary_url: str | None = None
    package_notes: str = ""
    field_definitions: dict[str, str] = Field(default_factory=dict)
    keyword_hits: list[dict[str, str]] = Field(default_factory=list)
    resource_last_modified: dict[str, str] = Field(default_factory=dict)
    states_mmgd_included: bool = False
    states_centralized_only: bool = False


class AneelFallbackChoice(BaseModel):
    """Outcome of the ANEEL fallback package discovery (Task 6): what was chosen and why the alternatives lost."""

    queries: list[str]
    package_id: str
    title: str = ""
    score: int
    resource_name: str
    resource_format: str
    n_candidates: int = Field(ge=1)
    rejected: dict[str, str] = Field(default_factory=dict)


class GenerationPackageDiscovery(BaseModel):
    """Outcome of discovering/re-confirming the ONS generation-by-source CKAN package (Task 3)."""

    configured_package_id: str
    resolved_package_id: str
    used_fallback_search: bool = False
    n_resources: int = Field(ge=0)
    formats_seen: list[str] = Field(default_factory=list)
    n_years_downloaded: int = Field(default=0, ge=0)
    n_rows: int = Field(default=0, ge=0)
    earliest_date: str | None = None
    latest_date: str | None = None
