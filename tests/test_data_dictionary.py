"""Sanity tests for docs/data_dictionary.md.

These are guardrail tests, not deep content tests: they ensure the data
dictionary stays in sync with the ResultsRow schema defined in
results_writer.py and continues to mention the key methodology terms that
must never silently drop out of the documentation.
"""
from pathlib import Path

import pytest

from curtailmit.results_writer import RESULTS_COLUMNS

DOC_PATH = Path(__file__).resolve().parents[1] / "docs" / "data_dictionary.md"


@pytest.fixture(scope="module")
def doc_text():
    assert DOC_PATH.exists(), f"data_dictionary.md not found at {DOC_PATH}"
    return DOC_PATH.read_text(encoding="utf-8")


def test_data_dictionary_file_exists():
    assert DOC_PATH.exists()


def test_data_dictionary_documents_every_results_column(doc_text):
    for column in RESULTS_COLUMNS:
        assert column in doc_text, f"Column '{column}' from RESULTS_COLUMNS not documented"


def test_data_dictionary_mentions_units(doc_text):
    for unit_term in ["TWh", "tCO2", "kg"]:
        assert unit_term in doc_text


def test_data_dictionary_mentions_emission_factor_methodology(doc_text):
    for term in ["Operating Margin", "Build Margin", "Combined Margin", "D12"]:
        assert term in doc_text


def test_data_dictionary_mentions_classification_terms(doc_text):
    for term in [
        "Razao Energetica",
        "Confiabilidade",
        "Indisponibilidade Externa",
        "DEB",
        "REB",
        "EUB",
    ]:
        assert term in doc_text


def test_data_dictionary_mentions_electrolyzer_sec_range(doc_text):
    for term in ["50", "52.5", "55"]:
        assert term in doc_text


def test_data_dictionary_mentions_source_provenance_values(doc_text):
    for term in ["historical_ons", "pte_projection", "interpolated"]:
        assert term in doc_text


def test_data_dictionary_mentions_scenario_grid_years(doc_text):
    for year in ["2020", "2025", "2030", "2040", "2050"]:
        assert year in doc_text