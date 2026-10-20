"""Tests for curtailmit.projection."""

import pytest

from curtailmit.projection import (
    ANCHOR_YEARS,
    AnchorPoint,
    HISTORICAL_SOURCE_LABEL,
    INTERPOLATED_SOURCE_LABEL,
    ProjectionError,
    build_anchor_points,
    headline_table,
    interpolate_series,
    validate_anchor_set,
)


def identity_calibration(penetration: float) -> float:
    """Trivial calibration function for tests: curtailment = 10% of penetration."""
    return 0.10 * penetration


def make_valid_rows():
    return [
        {"year": 2020, "solar_pct": 2.0, "wind_pct": 9.0, "source": "historical_ons"},
        {"year": 2025, "solar_pct": 12.0, "wind_pct": 14.0, "source": "pte_projection"},
        {"year": 2030, "solar_pct": 16.0, "wind_pct": 13.0, "source": "pte_projection"},
        {"year": 2040, "solar_pct": 20.0, "wind_pct": 16.0, "source": "pte_projection"},
        {"year": 2050, "solar_pct": 17.0, "wind_pct": 33.0, "source": "pte_projection"},
    ]


class TestAnchorPointValidation:
    def test_2020_must_be_historical(self):
        with pytest.raises(ProjectionError, match="historical_ons"):
            AnchorPoint(year=2020, solar_pct=2.0, wind_pct=9.0, source="pte_projection")

    def test_non_2020_cannot_be_historical(self):
        with pytest.raises(ProjectionError, match="Only year 2020"):
            AnchorPoint(year=2025, solar_pct=12.0, wind_pct=14.0, source="historical_ons")

    def test_negative_percentage_rejected(self):
        with pytest.raises(ProjectionError, match="Negative percentage"):
            AnchorPoint(year=2025, solar_pct=-1.0, wind_pct=14.0, source="pte_projection")

    def test_penetration_over_100_rejected(self):
        with pytest.raises(ProjectionError, match="exceeds 100"):
            AnchorPoint(year=2025, solar_pct=60.0, wind_pct=50.0, source="pte_projection")

    def test_valid_anchor_penetration_property(self):
        a = AnchorPoint(year=2025, solar_pct=12.0, wind_pct=14.0, source="pte_projection")
        assert a.penetration == pytest.approx(26.0)


class TestValidateAnchorSet:
    def test_valid_set_passes(self):
        anchors = build_anchor_points(make_valid_rows())
        validate_anchor_set(anchors)  # should not raise

    def test_missing_year_rejected(self):
        rows = [r for r in make_valid_rows() if r["year"] != 2040]
        with pytest.raises(ProjectionError, match="must contain exactly years"):
            build_anchor_points(rows)

    def test_wrong_year_rejected(self):
        rows = make_valid_rows()
        rows[-1]["year"] = 2045
        with pytest.raises(ProjectionError):
            build_anchor_points(rows)


class TestBuildAnchorPoints:
    def test_builds_sorted_anchor_points(self):
        rows = make_valid_rows()
        rows.reverse()
        anchors = build_anchor_points(rows)
        assert [a.year for a in anchors] == list(ANCHOR_YEARS)

    def test_2020_tagged_historical(self):
        anchors = build_anchor_points(make_valid_rows())
        anchor_2020 = next(a for a in anchors if a.year == 2020)
        assert anchor_2020.source == HISTORICAL_SOURCE_LABEL


class TestHeadlineTable:
    def test_returns_exactly_five_points(self):
        anchors = build_anchor_points(make_valid_rows())
        table = headline_table(anchors, identity_calibration)
        assert len(table) == 5
        assert [p.year for p in table] == list(ANCHOR_YEARS)

    def test_all_points_are_anchors_not_interpolated(self):
        anchors = build_anchor_points(make_valid_rows())
        table = headline_table(anchors, identity_calibration)
        assert all(p.is_anchor for p in table)
        assert all(not p.is_interpolated for p in table)

    def test_curtailment_applied_correctly(self):
        anchors = build_anchor_points(make_valid_rows())
        table = headline_table(anchors, identity_calibration)
        point_2025 = next(p for p in table if p.year == 2025)
        assert point_2025.penetration == pytest.approx(26.0)
        assert point_2025.curtailment == pytest.approx(2.6)

    def test_2020_source_preserved(self):
        anchors = build_anchor_points(make_valid_rows())
        table = headline_table(anchors, identity_calibration)
        point_2020 = next(p for p in table if p.year == 2020)
        assert point_2020.source == HISTORICAL_SOURCE_LABEL


class TestInterpolateSeries:
    def test_contains_all_years_in_range(self):
        anchors = build_anchor_points(make_valid_rows())
        series = interpolate_series(anchors, identity_calibration)
        years = [p.year for p in series]
        assert years == list(range(2020, 2051))

    def test_anchor_years_labeled_as_anchor(self):
        anchors = build_anchor_points(make_valid_rows())
        series = interpolate_series(anchors, identity_calibration)
        by_year = {p.year: p for p in series}
        for anchor_year in ANCHOR_YEARS:
            assert by_year[anchor_year].is_anchor is True
            assert by_year[anchor_year].is_interpolated is False

    def test_non_anchor_years_labeled_as_interpolated(self):
        anchors = build_anchor_points(make_valid_rows())
        series = interpolate_series(anchors, identity_calibration)
        by_year = {p.year: p for p in series}
        for year in (2021, 2026, 2035, 2045):
            assert by_year[year].is_anchor is False
            assert by_year[year].is_interpolated is True
            assert by_year[year].source == INTERPOLATED_SOURCE_LABEL

    def test_linear_interpolation_midpoint(self):
        # 2025 -> 2030: solar 12->16, wind 14->13, over 5 years
        anchors = build_anchor_points(make_valid_rows())
        series = interpolate_series(anchors, identity_calibration)
        by_year = {p.year: p for p in series}
        midpoint = by_year[2027]  # 2 years into a 5-year span -> frac = 0.4
        expected_solar = 12.0 + 0.4 * (16.0 - 12.0)
        expected_wind = 14.0 + 0.4 * (13.0 - 14.0)
        assert midpoint.solar_pct == pytest.approx(expected_solar)
        assert midpoint.wind_pct == pytest.approx(expected_wind)

    def test_2020_never_labeled_interpolated(self):
        anchors = build_anchor_points(make_valid_rows())
        series = interpolate_series(anchors, identity_calibration)
        point_2020 = next(p for p in series if p.year == 2020)
        assert point_2020.source == HISTORICAL_SOURCE_LABEL
        assert point_2020.is_interpolated is False

    def test_incomplete_anchor_set_rejected(self):
        rows = [r for r in make_valid_rows() if r["year"] != 2030]
        with pytest.raises(ProjectionError, match="must contain exactly years"):
            build_anchor_points(rows)