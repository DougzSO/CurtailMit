import pytest

from curtailmit.emission_factors import (
    EmissionFactorError,
    derive_annual_om_from_monthly,
    compute_combined_margin,
)


def test_derive_annual_om_from_monthly_mean():
    monthly = [0.2366, 0.2478, 0.2146, 0.2895, 0.3087, 0.4549,
               0.5293, 0.5529, 0.5215, 0.5386, 0.578, 0.4772]
    result = derive_annual_om_from_monthly(monthly)
    assert result == pytest.approx(sum(monthly) / 12, rel=1e-9)


def test_derive_annual_om_wrong_length_raises():
    with pytest.raises(EmissionFactorError):
        derive_annual_om_from_monthly([0.1, 0.2, 0.3])


def test_derive_annual_om_missing_value_raises():
    monthly = [0.1] * 11 + [None]
    with pytest.raises(EmissionFactorError):
        derive_annual_om_from_monthly(monthly)


def test_compute_combined_margin_default_weights():
    result = compute_combined_margin(om=0.4, bm=0.07106)
    assert result.cm == pytest.approx(0.5 * 0.4 + 0.5 * 0.07106)
    assert result.om_weight == 0.5
    assert result.bm_weight == 0.5


def test_compute_combined_margin_custom_weights():
    result = compute_combined_margin(om=0.4, bm=0.1, om_weight=0.75, bm_weight=0.25)
    assert result.cm == pytest.approx(0.75 * 0.4 + 0.25 * 0.1)


def test_compute_combined_margin_invalid_weights_raises():
    with pytest.raises(EmissionFactorError):
        compute_combined_margin(om=0.4, bm=0.1, om_weight=0.6, bm_weight=0.6)


def test_compute_combined_margin_negative_input_raises():
    with pytest.raises(EmissionFactorError):
        compute_combined_margin(om=-0.1, bm=0.1)