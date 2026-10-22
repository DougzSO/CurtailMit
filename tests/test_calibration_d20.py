"""Task 9 / D20 tests: calibration frame, curtailment rates and the end-to-end run on synthetic monthly data."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from curtailmit import calibration as cal


def pen_rows(months, solar_basis="dispatched", wind=6000.0, solar=1500.0, solar_raw=4000.0, other=50000.0) -> pd.DataFrame:
    rows = []
    for year, month in months:
        hours = pd.Period(year=year, month=month, freq="M").days_in_month * 24
        total = (wind + solar + other) * hours
        rows.append({
            "year": year, "month": month, "eolica_mwh": wind * hours, "solar_mwh": solar * hours, "solar_gen_ons_balance_raw_mwh": solar_raw * hours,
            "total_mwh": total, "wind_pct": 100 * wind * hours / total, "solar_pct": 100 * solar * hours / total,
            "penetration_pct": 100 * (wind + solar) * hours / total, "solar_basis": solar_basis,
        })
    return pd.DataFrame(rows)


def curt_rows(months, wind_mwh, solar_mwh=None, solar_from=None, complete=True) -> pd.DataFrame:
    rows = []
    for year, month in months:
        rows.append({"year": year, "month": month, "source": "wind", "curtailed_mwh": wind_mwh, "complete": complete})
        if solar_from is not None and (year, month) >= solar_from:
            rows.append({"year": year, "month": month, "source": "solar", "curtailed_mwh": solar_mwh, "complete": complete})
    return pd.DataFrame(rows)


MONTHS = [(2024, 2), (2024, 3), (2024, 4), (2024, 5)]


def test_frame_uses_dispatched_solar_in_P_and_in_the_solar_denominator():
    pen = pen_rows(MONTHS)
    frame = cal.build_calibration_frame(pen, curt_rows(MONTHS, 100_000.0, 50_000.0, solar_from=(2024, 4))).set_index(["year", "month"])
    apr = frame.loc[(2024, 4)]
    hours = 720
    assert apr.scope == "wind_solar" and frame.loc[(2024, 3)].scope == "wind_only"
    assert apr.P == pytest.approx(100 * 7500 / 57500)  # (wind + dispatched solar) / (all sources with dispatched solar), not 9500/60000
    assert apr.C == pytest.approx((100_000 + 50_000) / (6000 * hours + 100_000 + 1500 * hours + 50_000))
    assert frame.loc[(2024, 3)].C == pytest.approx(100_000 / (6000 * 744 + 100_000))  # wind-only month: no solar in numerator or denominator
    assert "solar_gen_ons_balance_raw_mwh" not in frame.columns  # the raw balance never reaches the calibration frame


def test_frame_refuses_a_month_on_the_balance_basis():
    with pytest.raises(cal.CalibrationDataError, match="D20 requires the dispatched"):
        cal.build_calibration_frame(pen_rows(MONTHS, solar_basis="balance"), curt_rows(MONTHS, 1.0))


def test_frame_fails_when_a_curtailment_month_has_no_generation_row():
    with pytest.raises(cal.CalibrationDataError, match="no generation row"):
        cal.build_calibration_frame(pen_rows(MONTHS[:2]), curt_rows(MONTHS, 1.0))


def test_incomplete_month_is_excluded_not_used():
    curt = pd.concat([curt_rows(MONTHS[:3], 1000.0), curt_rows(MONTHS[3:], 1000.0, complete=False)])
    frame = cal.build_calibration_frame(pen_rows(MONTHS), curt)
    assert len(frame) == 3 and (2024, 5) not in set(zip(frame.year, frame.month))


def test_corrected_solar_changes_the_rate_versus_the_raw_balance():
    """The point of D20: with the raw balance solar in the denominator the same curtailment gives a lower rate."""
    months = [(2025, 1), (2025, 2)]
    curt = curt_rows(months, 200_000.0, 100_000.0, solar_from=(2025, 1))
    corrected = cal.build_calibration_frame(pen_rows(months, solar=1500.0), curt)
    raw_like = cal.build_calibration_frame(pen_rows(months, solar=4000.0), curt)  # same pipeline fed with the balance-sized solar
    assert corrected.C.iloc[0] > raw_like.C.iloc[0]
    assert corrected.P.iloc[0] < raw_like.P.iloc[0]


def test_annual_rates_closed_form_and_scope_handling():
    months = [(2024, m) for m in range(1, 13)]
    frame = cal.build_calibration_frame(pen_rows(months), curt_rows(months, 120_000.0, 60_000.0, solar_from=(2024, 4)))
    r = cal.annual_rates(frame).iloc[0]
    wind_gen = sum(6000.0 * pd.Period(year=2024, month=m, freq="M").days_in_month * 24 for m in range(1, 13))
    solar_gen = sum(1500.0 * pd.Period(year=2024, month=m, freq="M").days_in_month * 24 for m in range(1, 13))
    assert r.rate_wind == pytest.approx(100 * 12 * 120_000 / (wind_gen + 12 * 120_000))
    curt_s = 9 * 60_000.0
    assert r.rate_combined_all_months == pytest.approx(100 * (12 * 120_000 + curt_s) / (wind_gen + solar_gen + 12 * 120_000 + curt_s))
    solar_apr_dec = sum(1500.0 * pd.Period(year=2024, month=m, freq="M").days_in_month * 24 for m in range(4, 13))
    assert r.rate_solar == pytest.approx(100 * curt_s / (solar_apr_dec + curt_s))
    assert r.rate_scope_consistent > r.rate_combined_all_months  # Jan-Mar solar kept out of the denominator


def write_inputs(tmp_path, months, solar_basis="dispatched"):
    interim, processed = tmp_path / "interim", tmp_path / "processed"
    interim.mkdir()
    processed.mkdir()
    pen = pen_rows(months, solar_basis=solar_basis)
    pen["wind_pct"] = np.linspace(12, 30, len(pen))  # spread P so the logistic is identifiable
    pen["penetration_pct"] = pen["wind_pct"] + pen["solar_pct"]
    pen.to_parquet(processed / cal.PENETRATION_MONTHLY_FILENAME, index=False)
    ts = []
    for (year, month), p in zip(months, pen.penetration_pct):
        last = pd.Period(year=year, month=month, freq="M").end_time.normalize() + pd.Timedelta(hours=23, minutes=30)
        true_c = 0.5 / (1 + np.exp(-0.3 * (p - 25)))
        wind_gen = float(pen.set_index(["year", "month"]).loc[(year, month), "eolica_mwh"])
        curtailed = wind_gen * true_c / (1 - true_c)
        ts += [{"timestamp": pd.Timestamp(year=year, month=month, day=1), "curtailed_energy_mwh": 0.0, "source": "wind"},
               {"timestamp": last, "curtailed_energy_mwh": curtailed, "source": "wind"}]
    pd.DataFrame(ts).to_parquet(interim / cal.CURTAILMENT_RAW_FILENAME, index=False)
    return interim, processed


def test_run_calibration_end_to_end_on_synthetic_data(tmp_path):
    months = [(2022, m) for m in range(1, 13)] + [(2023, m) for m in range(1, 13)]
    interim, processed = write_inputs(tmp_path, months)
    out = cal.run_calibration(interim, processed)
    assert (processed / cal.CALIBRATION_PARAMS_FILENAME).exists() and (processed / cal.CALIBRATION_FRAME_FILENAME).exists()
    assert out["calibration"].n_calibration_points == 24 and out["sensitivity_wind_solar_only"] is None  # no solar curtailment in this fixture
    assert cal.load_calibration(processed / cal.CALIBRATION_PARAMS_FILENAME).params.keys() == {"L", "k", "P0"}
    assert set(out["annual_rates"].year) == {2022, 2023}


def test_run_calibration_refuses_balance_basis_inputs(tmp_path):
    months = [(2022, m) for m in range(1, 7)]
    interim, processed = write_inputs(tmp_path, months, solar_basis="balance")
    with pytest.raises(cal.CalibrationDataError, match="dispatched"):
        cal.run_calibration(interim, processed)


def test_run_calibration_missing_inputs_fail_explicitly(tmp_path):
    with pytest.raises(cal.CalibrationDataError, match="not found"):
        cal.run_calibration(tmp_path / "i", tmp_path / "p")


def test_monthly_curtailment_aggregates_and_flags_complete_months(tmp_path):
    rows = [
        {"timestamp": pd.Timestamp("2024-01-01 00:00"), "curtailed_energy_mwh": 1.0, "source": "wind"},
        {"timestamp": pd.Timestamp("2024-01-31 23:30"), "curtailed_energy_mwh": 2.0, "source": "wind"},
        {"timestamp": pd.Timestamp("2024-02-01 00:00"), "curtailed_energy_mwh": 4.0, "source": "wind"},
        {"timestamp": pd.Timestamp("2024-02-10 12:00"), "curtailed_energy_mwh": 8.0, "source": "wind"},
        {"timestamp": pd.Timestamp("2024-02-10 12:30"), "curtailed_energy_mwh": 16.0, "source": "solar"},
    ]
    path = tmp_path / "c.parquet"
    pd.DataFrame(rows).to_parquet(path, index=False)
    out = cal.monthly_curtailment(path).set_index(["year", "month", "source"])
    assert out.loc[(2024, 1, "wind"), "curtailed_mwh"] == 3.0 and bool(out.loc[(2024, 1, "wind"), "complete"])
    assert out.loc[(2024, 2, "wind"), "curtailed_mwh"] == 12.0 and not bool(out.loc[(2024, 2, "wind"), "complete"])
    assert out.loc[(2024, 2, "solar"), "curtailed_mwh"] == 16.0


@pytest.mark.integration
def test_live_calibration_on_real_database_root():
    """Needs the real DATABASE_ROOT after Stage 1 (generation + curtailment). Run manually: pytest -m integration"""
    from curtailmit.paths import get_interim_dir, get_processed_dir

    if not (get_interim_dir() / cal.CURTAILMENT_RAW_FILENAME).exists() or not (get_processed_dir() / cal.PENETRATION_MONTHLY_FILENAME).exists():
        pytest.skip("Stage 1 outputs not present")
    out = cal.run_calibration()
    frame = out["frame"]
    assert len(frame) > 24 and (frame.C >= 0).all() and (frame.C < 1).all()
    assert out["calibration"].params["L"] > 0
