"""Tests for curtailmit.results_writer."""

from pathlib import Path

import pytest

from curtailmit.results_writer import (
    RESULTS_COLUMNS,
    ResultsRow,
    load_results_csv,
    load_results_json,
    write_results_csv,
    write_results_json,
)
from curtailmit.validation import ValidationError


def _valid_row(**overrides) -> ResultsRow:
    defaults = {
        "scenario": "TB",
        "year": 2025,
        "source": "pte_projection",
        "is_interpolated": False,
        "classification_available": True,
        "E_curt_twh": 10.0,
        "mitigation_deficit_avg_tco2": 1000.0,
        "mitigation_deficit_marginal_om_tco2": 1500.0,
        "mitigation_deficit_marginal_cm_tco2": 1200.0,
        "marginal_proxy_note": "OM=DEB proxy, CM=REB proxy",
        "h2_potential_min_kg": 100.0,
        "h2_potential_central_kg": 110.0,
        "h2_potential_max_kg": 120.0,
    }
    defaults.update(overrides)
    return ResultsRow(**defaults)


def test_valid_row_constructs():
    row = _valid_row()
    assert row.scenario == "TB"
    assert row.year == 2025


def test_invalid_source_raises():
    with pytest.raises(ValidationError, match="source must be one of"):
        _valid_row(source="bogus_source")


def test_historical_ons_cannot_be_interpolated():
    with pytest.raises(ValidationError, match="cannot be is_interpolated=True"):
        _valid_row(source="historical_ons", year=2020, is_interpolated=True)


def test_interpolated_source_must_set_flag():
    with pytest.raises(ValidationError, match="must have is_interpolated=True"):
        _valid_row(source="interpolated", is_interpolated=False)


def test_negative_curtailment_raises():
    with pytest.raises(ValidationError, match="E_curt_twh must be non-negative"):
        _valid_row(E_curt_twh=-1.0)


def test_negative_avg_deficit_raises():
    with pytest.raises(ValidationError, match="mitigation_deficit_avg_tco2 must be non-negative"):
        _valid_row(mitigation_deficit_avg_tco2=-1.0)


def test_negative_om_deficit_raises():
    with pytest.raises(ValidationError, match="mitigation_deficit_marginal_om_tco2 must be non-negative"):
        _valid_row(mitigation_deficit_marginal_om_tco2=-1.0)


def test_negative_cm_deficit_raises():
    with pytest.raises(ValidationError, match="mitigation_deficit_marginal_cm_tco2 must be non-negative"):
        _valid_row(mitigation_deficit_marginal_cm_tco2=-1.0)


def test_h2_ordering_violation_raises():
    with pytest.raises(ValidationError, match="H2 potential range must satisfy"):
        _valid_row(h2_potential_min_kg=200.0, h2_potential_central_kg=110.0, h2_potential_max_kg=120.0)


def test_results_columns_match_field_order():
    assert RESULTS_COLUMNS == (
        "scenario", "year", "source", "is_interpolated", "classification_available",
        "E_curt_twh", "mitigation_deficit_avg_tco2", "mitigation_deficit_marginal_om_tco2",
        "mitigation_deficit_marginal_cm_tco2", "marginal_proxy_note",
        "h2_potential_min_kg", "h2_potential_central_kg", "h2_potential_max_kg",
    )


def test_write_and_load_csv_roundtrip(tmp_path: Path):
    rows = [
        _valid_row(scenario="TB", year=2020, source="historical_ons", is_interpolated=False),
        _valid_row(scenario="TB", year=2025, source="pte_projection", is_interpolated=False),
        _valid_row(scenario="TB", year=2026, source="interpolated", is_interpolated=True),
    ]
    out_path = tmp_path / "results.csv"
    write_results_csv(rows, out_path)
    assert out_path.exists()

    loaded = load_results_csv(out_path)
    assert len(loaded) == 3
    assert loaded[0].scenario == "TB"
    assert loaded[0].year == 2020
    assert loaded[0].source == "historical_ons"
    assert loaded[2].is_interpolated is True
    assert loaded[0] == rows[0]


def test_write_and_load_json_roundtrip(tmp_path: Path):
    rows = [
        _valid_row(scenario="TA", year=2030, classification_available=False),
    ]
    out_path = tmp_path / "results.json"
    write_results_json(rows, out_path)
    assert out_path.exists()

    loaded = load_results_json(out_path)
    assert len(loaded) == 1
    assert loaded[0] == rows[0]
    assert loaded[0].classification_available is False


def test_csv_header_matches_results_columns(tmp_path: Path):
    rows = [_valid_row()]
    out_path = tmp_path / "results.csv"
    write_results_csv(rows, out_path)
    header_line = out_path.read_text(encoding="utf-8").splitlines()[0]
    assert header_line == ",".join(RESULTS_COLUMNS)


def test_write_results_csv_creates_parent_dirs(tmp_path: Path):
    nested_path = tmp_path / "nested" / "dir" / "results.csv"
    write_results_csv([_valid_row()], nested_path)
    assert nested_path.exists()