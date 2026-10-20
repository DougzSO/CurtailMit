"""
validation.py

Centralized acceptance-criteria validation for the CurtailMit pipeline.

This module exists to avoid duplicating validation logic across
data_ingestion.py, results_writer.py, and other pipeline stages. Any
module that needs to check acceptance criteria should import and call
these functions rather than reimplementing checks inline.

Acceptance criteria enforced here (per finalized methodology):

1. Penetration ceiling: solar_pct + wind_pct <= 100 for every
   (scenario, year) data point. This is also enforced inline in
   projection.py::AnchorPoint, but this module provides a standalone
   check for raw/intermediate data (e.g. full interpolated series, raw
   ONS records) before it ever reaches AnchorPoint construction.

2. ONS temporal coverage: ONS curtailment data must cover at least
   through January 2022. If coverage does not reach this date, this is
   an explicit failure, never a silent fallback to a shorter series.

3. MCTI emission factor coverage: MCTI "Fator Medio de Emissao de CO2
   do SIN" (average) and Operating Margin / Build Margin (marginal)
   series must have sufficient coverage for the requested years.
   Insufficient coverage is an explicit failure, never a silent
   fallback or extrapolation.

4. classification_available propagation: ONS curtailment classification
   (DEB/REB/EUB) may not always be exportable. When it is not, the
   pipeline falls back to an unclassified aggregate and must carry a
   classification_available: False flag through every downstream
   stage, all the way to results_writer.py. This module provides small
   helpers to attach/propagate/check that flag consistently so it can
   never be silently dropped or defaulted to True, and so a record
   flagged unavailable can never carry DEB/REB/EUB fields.

None of the functions in this module perform network calls; they
operate on already-loaded data structures (lists of dicts, or simple
records).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Mapping, Sequence


class ValidationError(Exception):
    """Raised when a CurtailMit acceptance criterion is violated."""


# ONS coverage must reach at least January 2022.
ONS_MIN_COVERAGE_DATE = date(2022, 1, 1)

# Fields that may only appear on records explicitly flagged as
# classification_available: True.
_CLASSIFIED_FIELDS = ("deb", "reb", "eub", "classification")


def validate_penetration_ceiling(records: Iterable[Mapping[str, Any]]) -> None:
    """
    Validate that solar_pct + wind_pct <= 100 for every record.

    Each record must be a mapping containing at least 'solar_pct' and
    'wind_pct' keys (floats). Optionally may contain 'scenario' and
    'year' keys, used to produce a more informative error message.

    Raises
    ------
    ValidationError
        If any record is missing solar_pct/wind_pct, has a negative
        value, or has solar_pct + wind_pct > 100.
    """
    for record in records:
        solar_pct = record.get("solar_pct")
        wind_pct = record.get("wind_pct")

        if solar_pct is None or wind_pct is None:
            raise ValidationError(
                "Record missing required 'solar_pct' and/or 'wind_pct' keys: "
                f"{record!r}"
            )

        if solar_pct < 0 or wind_pct < 0:
            raise ValidationError(
                "solar_pct and wind_pct must not be negative. "
                f"Got solar_pct={solar_pct}, wind_pct={wind_pct} "
                f"(scenario={record.get('scenario')!r}, year={record.get('year')!r})"
            )

        penetration = solar_pct + wind_pct
        if penetration > 100:
            raise ValidationError(
                "solar_pct + wind_pct exceeds 100 "
                f"(solar_pct={solar_pct}, wind_pct={wind_pct}, "
                f"penetration={penetration}, "
                f"scenario={record.get('scenario')!r}, year={record.get('year')!r})"
            )


def validate_ons_coverage(max_available_date: date) -> None:
    """
    Validate that ONS curtailment data coverage reaches at least
    January 2022.

    Parameters
    ----------
    max_available_date : date
        The latest date for which ONS curtailment data is actually
        available/retrieved.

    Raises
    ------
    ValidationError
        If max_available_date is earlier than ONS_MIN_COVERAGE_DATE.
    """
    if max_available_date < ONS_MIN_COVERAGE_DATE:
        raise ValidationError(
            "ONS curtailment data coverage is insufficient: latest available "
            f"date is {max_available_date.isoformat()}, but coverage must "
            f"reach at least {ONS_MIN_COVERAGE_DATE.isoformat()}."
        )


def validate_mcti_factor_coverage(
    available_years: Sequence[int],
    required_years: Sequence[int],
) -> None:
    """
    Validate that MCTI emission factor data covers every required year.

    Parameters
    ----------
    available_years : Sequence[int]
        Years for which MCTI factor data (average or marginal) was
        actually retrieved.
    required_years : Sequence[int]
        Years required by the pipeline (e.g. the anchor year grid, or
        the full interpolation range).

    Raises
    ------
    ValidationError
        If any required year is missing from available_years.
    """
    available_set = set(available_years)
    missing = sorted(set(required_years) - available_set)
    if missing:
        raise ValidationError(
            "MCTI emission factor coverage is insufficient. "
            f"Missing years: {missing}."
        )


@dataclass
class ClassificationFlag:
    """
    Carries the classification_available flag through pipeline stages.

    Attributes
    ----------
    classification_available : bool
        True if ONS curtailment data was exportable in classified form
        (DEB/REB/EUB). False if only an unclassified aggregate was
        available, in which case downstream consumers must never label
        the data as DEB/REB.
    reason : str | None
        Human-readable explanation for why classification is
        unavailable. Required (non-None) when classification_available
        is False.
    """

    classification_available: bool
    reason: str | None = None

    def __post_init__(self) -> None:
        if not self.classification_available and not self.reason:
            raise ValidationError(
                "reason must be provided when classification_available is False."
            )


def attach_classification_flag(
    record: Mapping[str, Any],
    flag: ClassificationFlag,
) -> dict[str, Any]:
    """
    Return a new dict combining `record` with the classification flag
    fields, so the flag is explicitly carried in every record emitted
    by a pipeline stage. Never mutates the input record.

    Raises
    ------
    ValidationError
        If flag.classification_available is False but `record` still
        carries a classified (DEB/REB/EUB/classification) field.
    """
    new_record = dict(record)
    new_record["classification_available"] = flag.classification_available
    if not flag.classification_available:
        new_record["classification_reason"] = flag.reason
        for key in _CLASSIFIED_FIELDS:
            if key in new_record:
                raise ValidationError(
                    f"Record has classification_available=False but still "
                    f"carries a '{key}' field. Classified fields must be "
                    "removed/never set when classification is unavailable."
                )
    return new_record


def validate_classification_propagation(
    records: Iterable[Mapping[str, Any]],
) -> None:
    """
    Validate that every record explicitly carries a
    'classification_available' key, and that records flagged as
    unavailable do not carry classified (DEB/REB/EUB) fields.

    Raises
    ------
    ValidationError
        If any record is missing the 'classification_available' key,
        or if a record flagged unavailable still carries a non-null
        classified field.
    """
    for record in records:
        if "classification_available" not in record:
            raise ValidationError(
                "Record is missing required 'classification_available' key: "
                f"{record!r}"
            )
        if record["classification_available"] is False:
            for key in _CLASSIFIED_FIELDS:
                if key in record and record[key] is not None:
                    raise ValidationError(
                        "Record has classification_available=False but "
                        f"still carries a non-null '{key}' field: {record!r}"
                    )