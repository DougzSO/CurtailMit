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
    def check_penetration_bound(self) -> "ScenarioYearData":
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
    def check_bounds(self) -> "ElectrolyzerSEC":
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


# --- Stage 5 outputs ---------------------------------------------------------

class HydrogenRow(BaseModel):
    scenario: ScenarioName
    year: int
    h2_potential_min_kg: float
    h2_potential_central_kg: float
    h2_potential_max_kg: float

    @model_validator(mode="after")
    def check_ordering(self) -> "HydrogenRow":
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
