"""Stage 1 - data ingestion, discovery, and validation.

Order of operations:
1. Load + validate config/scenarios.yaml against schemas.py.
2. ONS discovery (curtailment wind/solar + generation by source) via CKAN.
3. Classification availability check + fallback decision (logged, never silent).
4. MCTI discovery (average + marginal emission factors).
5. Load 2026-2029 validation_data, kept separate from calibration_data.
6. Produce data-quality report.

This is a skeleton: discovery/parsing logic (steps 2-4) is intentionally left as TODO,
with control flow, logging, and fail-explicit behavior already structured.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import yaml

from curtailmit.ons_client import CkanClient
from curtailmit.schemas import PipelineConfig

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "scenarios.yaml"


def load_config(path: Path = CONFIG_PATH) -> PipelineConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    config = PipelineConfig(
        year_grid=raw["year_grid"],
        interpolation_method=raw["interpolation_method"],
        baseline_2020=raw["baseline_2020"],
        pte_scenarios=raw["pte_scenarios"],
    )
    if not config.pte_scenarios.all_valid():
        raise ValueError("PTE table failed sanity check: solar_pct + wind_pct > 100 somewhere.")
    logger.info(
        "Config loaded and validated: %d scenarios, year_grid=%s",
        len(raw["pte_scenarios"]), config.year_grid,
    )
    return config


def discover_ons_resources(raw_config: dict) -> dict:
    """Discover ONS curtailment + generation datasets via CKAN. TODO: implement parsing."""
    client = CkanClient(raw_config["ons"]["ckan_base_url"])
    min_coverage = date.fromisoformat(raw_config["ons"]["min_coverage_start"])

    discovered = {}

    wind_id = raw_config["ons"]["datasets"]["curtailment_wind"]
    discovered["curtailment_wind"] = client.list_resources(wind_id)

    solar_id = raw_config["ons"]["datasets"]["curtailment_solar"]
    if solar_id is None:
        logger.warning("curtailment_solar dataset id not set - searching CKAN catalog...")
        results = client.package_search("geracao fotovoltaica curtailment corte")
        discovered["curtailment_solar_search_results"] = results

    gen_id = raw_config["ons"]["datasets"]["generation_by_source"]
    if gen_id is None:
        logger.warning("generation_by_source dataset id not set - searching CKAN catalog...")
        results = client.package_search("geracao")
        discovered["generation_by_source_search_results"] = results

    return discovered


def check_classification_availability(raw_config: dict, discovered: dict) -> bool:
    """TODO: inspect resource schemas to confirm whether the classified series is exportable.
    Must return False (not raise) if unavailable - fallback is a valid, logged path.
    """
    logger.warning("Classification availability check not yet implemented - defaulting to False.")
    return False


def discover_mcti_factors(raw_config: dict) -> dict:
    """TODO: implement discovery of MCTI average + margin emission factor publications."""
    logger.warning("MCTI factor discovery not yet implemented.")
    return {}


def load_validation_data(raw_config: dict) -> dict:
    validation = raw_config.get("validation_data", {})
    if not validation.get("years"):
        logger.warning("validation_data is empty - fill from the v2 2026-2029 prospection table.")
    return validation


def run_stage1() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        raw_config = yaml.safe_load(f)

    config = load_config()
    discovered = discover_ons_resources(raw_config)
    classification_available = check_classification_availability(raw_config, discovered)
    mcti = discover_mcti_factors(raw_config)
    validation_data = load_validation_data(raw_config)

    report = {
        "config_valid": True,
        "classification_available": classification_available,
        "ons_discovered": discovered,
        "mcti_discovered": mcti,
        "validation_data_loaded": bool(validation_data.get("years")),
    }
    logger.info("Stage 1 data-quality report: %s", report)
    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_stage1()
