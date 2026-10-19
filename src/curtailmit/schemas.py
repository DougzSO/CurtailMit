"""Pydantic v2 schemas for CurtailMit configuration and intermediate data."""

from __future__ import annotations

from typing import Literal

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
        """P(s,t) = solar_pct + wind_pct."""
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
