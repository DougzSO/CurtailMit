from datetime import date
import pytest
from curtailmit.ons_client import CkanClient, CoverageError


def test_enforce_min_coverage_passes():
    CkanClient.enforce_min_coverage(date(2021, 1, 1), date(2022, 1, 1))


def test_enforce_min_coverage_fails():
    with pytest.raises(CoverageError):
        CkanClient.enforce_min_coverage(date(2023, 1, 1), date(2022, 1, 1))
