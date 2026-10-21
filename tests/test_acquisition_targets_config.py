"""Sanity checks for config/acquisition_targets.yaml.

This config is pure data consolidation (not a Python module), so tests
here only verify it parses as valid YAML and contains the expected
top-level structure and confirmed identifiers - not full schema
validation.
"""

from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "acquisition_targets.yaml"


def _load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_config_file_exists():
    assert CONFIG_PATH.exists()


def test_config_parses_as_valid_yaml():
    config = _load_config()
    assert isinstance(config, dict)


def test_top_level_sources_present():
    config = _load_config()
    for key in ("ons", "classification", "aneel", "mcti", "ccee_pld"):
        assert key in config, f"Missing top-level key: {key}"


def test_ons_confirmed_package_ids():
    config = _load_config()
    packages = config["ons"]["packages"]
    assert packages["curtailment_wind"]["package_id"] == "restricao_coff_eolica_usi"
    assert packages["curtailment_solar"]["package_id"] == "restricao_coff_fotovoltaica"
    assert packages["generation_by_source"]["package_id"] == "balanco-energia-subsistema"


def test_ons_min_coverage_start_matches_methodology():
    config = _load_config()
    assert config["ons"]["min_coverage_start"] == "2022-01-01"


def test_per_package_ons_coverage_floors():
    packages = _load_config()["ons"]["packages"]
    assert packages["curtailment_wind"]["min_coverage_start"] == "2022-01-01"
    assert packages["curtailment_solar"]["min_coverage_start"] == "2024-04-01"


def test_classification_mapping_complete():
    config = _load_config()
    mapping = config["classification"]["mapping"]
    assert mapping["Razao Energetica"] == "DEB"
    assert mapping["Confiabilidade"] == "REB"
    assert mapping["Indisponibilidade Externa"] == "EUB"


def test_mcti_landing_page_present():
    config = _load_config()
    assert config["mcti"]["landing_page"].startswith("https://www.gov.br/mcti")


def test_mcti_combined_margin_formula_documented():
    config = _load_config()
    cm = config["mcti"]["combined_margin"]
    assert cm["formula"] == "CM = 0.5 * OM + 0.5 * BM"
    assert cm["decision_reference"] == "D12"


def test_ccee_pld_disabled_and_blocked():
    config = _load_config()
    assert config["ccee_pld"]["enabled"] is False
    assert config["ccee_pld"]["status"] == "blocked_permanent"


def test_aneel_marked_fallback_only():
    config = _load_config()
    assert config["aneel"]["role"] == "fallback_only"