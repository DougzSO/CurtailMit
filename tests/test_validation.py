"""Tests for curtailmit.validation."""

from datetime import date

import pytest

from curtailmit.validation import (
    ValidationError,
    validate_penetration_ceiling,
    validate_ons_coverage,
    validate_mcti_factor_coverage,
    ClassificationFlag,
    attach_classification_flag,
    validate_classification_propagation,
)


# --- validate_penetration_ceiling ---

def test_penetration_ceiling_accepts_valid_records():
    records = [
        {"scenario": "PTE", "year": 2025, "solar_pct": 30.0, "wind_pct": 40.0},
        {"scenario": "PTE", "year": 2030, "solar_pct": 0.0, "wind_pct": 0.0},
        {"scenario": "PTE", "year": 2040, "solar_pct": 50.0, "wind_pct": 50.0},
    ]
    validate_penetration_ceiling(records)  # should not raise


def test_penetration_ceiling_rejects_over_100():
    records = [
        {"scenario": "PTE", "year": 2050, "solar_pct": 60.0, "wind_pct": 50.0},
    ]
    with pytest.raises(ValidationError, match="exceeds 100"):
        validate_penetration_ceiling(records)


def test_penetration_ceiling_rejects_negative():
    records = [
        {"scenario": "PTE", "year": 2050, "solar_pct": -1.0, "wind_pct": 50.0},
    ]
    with pytest.raises(ValidationError, match="must not be negative"):
        validate_penetration_ceiling(records)


def test_penetration_ceiling_rejects_missing_keys():
    records = [{"scenario": "PTE", "year": 2050, "solar_pct": 10.0}]
    with pytest.raises(ValidationError, match="missing required"):
        validate_penetration_ceiling(records)


# --- validate_ons_coverage ---

def test_ons_coverage_accepts_sufficient_date():
    validate_ons_coverage(date(2022, 1, 1))  # should not raise
    validate_ons_coverage(date(2023, 6, 15))  # should not raise


def test_ons_coverage_rejects_insufficient_date():
    with pytest.raises(ValidationError, match="insufficient"):
        validate_ons_coverage(date(2021, 12, 31))


# --- validate_mcti_factor_coverage ---

def test_mcti_coverage_accepts_full_coverage():
    validate_mcti_factor_coverage(
        available_years=[2020, 2021, 2022, 2025, 2030],
        required_years=[2020, 2025, 2030],
    )  # should not raise


def test_mcti_coverage_rejects_missing_years():
    with pytest.raises(ValidationError, match=r"Missing years: \[2040, 2050\]"):
        validate_mcti_factor_coverage(
            available_years=[2020, 2025, 2030],
            required_years=[2020, 2025, 2030, 2040, 2050],
        )


# --- ClassificationFlag ---

def test_classification_flag_available_true_no_reason_required():
    flag = ClassificationFlag(classification_available=True)
    assert flag.classification_available is True
    assert flag.reason is None


def test_classification_flag_available_false_requires_reason():
    with pytest.raises(ValidationError, match="reason must be provided"):
        ClassificationFlag(classification_available=False)


def test_classification_flag_available_false_with_reason_ok():
    flag = ClassificationFlag(
        classification_available=False,
        reason="ONS API does not expose classified series for this period.",
    )
    assert flag.classification_available is False
    assert flag.reason is not None


# --- attach_classification_flag ---

def test_attach_classification_flag_available_true_passthrough():
    record = {"scenario": "PTE", "year": 2025, "deb": 1.2, "reb": 0.5}
    flag = ClassificationFlag(classification_available=True)
    result = attach_classification_flag(record, flag)
    assert result["classification_available"] is True
    assert result["deb"] == 1.2
    assert result["reb"] == 0.5
    assert "classification_reason" not in result
    # original record not mutated
    assert "classification_available" not in record


def test_attach_classification_flag_unavailable_attaches_reason():
    record = {"scenario": "PTE", "year": 2025, "curtailment_total": 10.0}
    flag = ClassificationFlag(
        classification_available=False,
        reason="Classified export unavailable for 2025.",
    )
    result = attach_classification_flag(record, flag)
    assert result["classification_available"] is False
    assert result["classification_reason"] == "Classified export unavailable for 2025."
    assert result["curtailment_total"] == 10.0


def test_attach_classification_flag_unavailable_rejects_leftover_classified_fields():
    record = {"scenario": "PTE", "year": 2025, "deb": 1.2}
    flag = ClassificationFlag(
        classification_available=False,
        reason="Classified export unavailable for 2025.",
    )
    with pytest.raises(ValidationError, match="classification_available=False"):
        attach_classification_flag(record, flag)


# --- validate_classification_propagation ---

def test_classification_propagation_accepts_valid_records():
    records = [
        {"scenario": "PTE", "year": 2025, "classification_available": True, "deb": 1.0},
        {"scenario": "PTE", "year": 2030, "classification_available": False,
         "classification_reason": "unavailable"},
    ]
    validate_classification_propagation(records)  # should not raise


def test_classification_propagation_rejects_missing_flag():
    records = [{"scenario": "PTE", "year": 2025, "deb": 1.0}]
    with pytest.raises(ValidationError, match="missing required"):
        validate_classification_propagation(records)


def test_classification_propagation_rejects_classified_field_when_unavailable():
    records = [
        {"scenario": "PTE", "year": 2025, "classification_available": False, "deb": 1.0},
    ]
    with pytest.raises(ValidationError, match="still carries"):
        validate_classification_propagation(records)