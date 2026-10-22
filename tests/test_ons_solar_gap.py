"""Task 6C tests: capacity-factor range selection, schema comparison, dispatched-solar aggregation, gap comparison/analysis. Synthetic fixtures."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from curtailmit import ons_solar_gap as sg
from curtailmit.ons_client import CkanClient, ResourceInfo
from curtailmit.ons_mmgd_probe import CF_REQUIRED_COLUMNS, ProbeError


def res(name: str, fmt: str = "PARQUET") -> ResourceInfo:
    return ResourceInfo(resource_id=name + fmt, name=name, format=fmt, last_modified=None, url=f"https://files.test/{name}.{fmt.lower()}")


def cf_file(path: Path, start: str, hours: int, solar_mw: float = 100.0, wind_mw: float = 500.0, fc_type: str = "string") -> Path:
    idx = pd.date_range(start, periods=hours, freq="h")
    rows = []
    for t in idx:
        rows += [
            {"din_instante": t, "nom_tipousina": "Solar", "nom_usina_conjunto": "S1", "id_ons": "A", "val_geracaoverificada": solar_mw / 2, "val_capacidadeinstalada": 1.0, "val_fatorcapacidade": "0.1"},
            {"din_instante": t, "nom_tipousina": "Solar", "nom_usina_conjunto": "S2", "id_ons": "B", "val_geracaoverificada": solar_mw / 2, "val_capacidadeinstalada": 1.0, "val_fatorcapacidade": "0.1"},
            {"din_instante": t, "nom_tipousina": "Eólica", "nom_usina_conjunto": "W1", "id_ons": "C", "val_geracaoverificada": wind_mw, "val_capacidadeinstalada": 1.0, "val_fatorcapacidade": "0.3"},
        ]
    df = pd.DataFrame(rows)
    if fc_type == "double":
        df["val_fatorcapacidade"] = df["val_fatorcapacidade"].astype(float)
    df.to_parquet(path, index=False)
    return path


def test_label_of():
    assert sg.label_of("Fator_Capacidade_2-2024-06") == "2024-06"
    assert sg.label_of("Fator_Capacidade-2021") == "2021"
    with pytest.raises(ProbeError):
        sg.label_of("Dicionario")


def test_list_resources_filters_year_and_format_and_rejects_duplicates():
    rs = [res("Fator_Capacidade-2020"), res("Fator_Capacidade-2021"), res("Fator_Capacidade_2-2022-01"), res("Fator_Capacidade_2-2022-01", "CSV"), res("Dicionario de Dados", "JSON")]
    out = sg.list_capacity_factor_resources(rs, first_year=2021)
    assert list(out) == ["2021", "2022-01"]
    with pytest.raises(ProbeError, match="Two PARQUET"):
        sg.list_capacity_factor_resources(rs + [res("Fator_Capacidade_2-2022-01")], first_year=2021)
    with pytest.raises(ProbeError, match="No PARQUET"):
        sg.list_capacity_factor_resources([res("Fator_Capacidade-2019")], first_year=2021)


def test_schema_findings_reports_type_change_and_missing_columns(tmp_path):
    ref = sg.read_schema(cf_file(tmp_path / "a.parquet", "2022-12-01", 2))
    same = sg.schema_findings("x", sg.read_schema(cf_file(tmp_path / "b.parquet", "2023-01-01", 2)), ref)
    assert same.identical and same.usable
    changed = sg.schema_findings("y", sg.read_schema(cf_file(tmp_path / "c.parquet", "2026-01-01", 2, fc_type="double")), ref)
    assert not changed.identical and changed.usable
    assert changed.type_changes == {"val_fatorcapacidade": "string -> double"}
    broken = {k: v for k, v in ref.items() if k != "val_geracaoverificada"}
    f = sg.schema_findings("z", broken, ref)
    assert f.missing_required == ["val_geracaoverificada"] and not f.usable
    assert set(CF_REQUIRED_COLUMNS) >= set(f.missing_required)


def test_aggregate_solar_only_and_duplicate_timestamps_fail(tmp_path):
    p1 = cf_file(tmp_path / "a.parquet", "2024-01-01", 3, solar_mw=100, wind_mw=999)
    s = sg.aggregate_dispatched_solar_file(p1)
    assert s.tolist() == [100.0, 100.0, 100.0]  # two plants summed, wind excluded
    p2 = cf_file(tmp_path / "b.parquet", "2024-01-01 02:00", 3)
    with pytest.raises(ProbeError, match="Duplicated"):
        sg.aggregate_dispatched_solar({"a": p1, "b": p2})
    p3 = cf_file(tmp_path / "c.parquet", "2024-01-02", 2, solar_mw=50)
    assert len(sg.aggregate_dispatched_solar({"a": p1, "c": p3})) == 5


def test_compare_with_balanco_gap_and_partial_month_coverage():
    idx = pd.date_range("2024-02-01", periods=24 * 29, freq="h")  # all of Feb 2024 (leap)
    disp = pd.Series(100.0, index=idx)
    bal = pd.Series(300.0, index=idx)
    m = sg.compare_with_balanco(disp, bal)
    row = m.loc[pd.Period("2024-02")]
    assert row["hours_in_month"] == 696 and row["coverage"] == 1.0
    assert row["gap_mwmed"] == pytest.approx(200.0)
    assert row["gap_gwh"] == pytest.approx(200 * 696 / 1000)
    assert row["gap_pct_of_balanco"] == pytest.approx(100 * 200 / 300)
    half = sg.compare_with_balanco(disp.iloc[:348], bal)
    assert half.iloc[0]["coverage"] == pytest.approx(0.5)
    assert half.iloc[0]["gap_gwh"] == pytest.approx(200 * 696 / 1000)  # scaled to the full month


def test_compare_drops_hours_missing_in_balance(caplog):
    idx = pd.date_range("2024-03-01", periods=10, freq="h")
    bal = pd.Series(10.0, index=idx[:8])
    with caplog.at_level("WARNING"):
        m = sg.compare_with_balanco(pd.Series(5.0, index=idx), bal)
    assert m.iloc[0]["hours"] == 8 and "no val_gersolar" in caplog.text


def synthetic_months(step_at: int = 26, n: int = 48, base: float = 100.0, post0: float = 3000.0, growth: float = 60.0) -> pd.DataFrame:
    periods = pd.period_range("2021-01", periods=n, freq="M")
    gap = np.array([base if i < step_at else post0 + growth * (i - step_at) for i in range(n)], dtype=float)
    disp = np.full(n, 1500.0)
    hours = np.array([p.days_in_month * 24 for p in periods])
    m = pd.DataFrame({"dispatched_mwmed": disp, "balanco_mwmed": disp + gap, "hours": hours, "hours_in_month": hours, "coverage": 1.0}, index=periods)
    m["gap_mwmed"] = gap
    m["gap_gwh"] = gap * hours / 1000
    m["balanco_gwh"] = m["balanco_mwmed"] * hours / 1000
    m["gap_pct_of_balanco"] = 100 * m["gap_gwh"] / m["balanco_gwh"]
    return m


def test_analyse_gap_detects_step_and_growth():
    m = synthetic_months()
    a = sg.analyse_gap(m)
    assert a.first_nontrivial_month == str(m.index[26])
    assert a.first_pct_above_threshold_month == str(m.index[0])  # 100/1600 = 6.3 % > 5 % from the start: the absolute rule is not the step
    assert a.pre_step_baseline_mwmed == pytest.approx(100.0)
    assert a.post_character == "growing"
    assert a.post_gap_trend_mwmed_per_year == pytest.approx(60 * 12, rel=0.01)


def test_analyse_gap_flat_and_rt_comparison():
    m = synthetic_months(growth=0.0, post0=5000.0)
    a = sg.analyse_gap(m)
    assert a.post_character == "roughly flat"
    # 2024 gap = 5000 MWmed x 8784 h = 43,920 GWh; adjusted by the 100 MWmed baseline = 43,041.6 GWh
    assert a.gap_2024_gwh == pytest.approx(43_920.0)
    assert a.gap_2024_baseline_adjusted_gwh == pytest.approx(43_041.6)
    assert a.rt_consistent  # -4.0 % and -5.9 % vs 45,752, inside the 10 % tolerance
    assert not sg.analyse_gap(m, rt_tolerance_pct=3.0).rt_consistent


def test_analyse_gap_without_a_step_reports_none_and_excludes_partial_month():
    periods = pd.period_range("2021-01", periods=40, freq="M")
    m = synthetic_months(step_at=999, n=40)
    m.loc[periods[-1], "coverage"] = 0.5
    a = sg.analyse_gap(m)
    assert a.first_nontrivial_month is None and a.post_character == "insufficient post-step months"


def test_find_step_day_is_windowed_and_glitch_days_listed():
    days = pd.date_range("2023-03-01", "2024-12-31", freq="D")
    d = pd.Series(100.0, index=days)
    d[d.index >= "2023-04-29"] = 3000.0
    d.loc["2024-11-09"] = 60.0  # ONS glitch day: the jump back up on 11-10 is the largest one in the series
    day, after, before = sg.find_step_day(d, "2023-04")
    assert day == pd.Timestamp("2023-04-29") and (before, after) == (100.0, 3000.0)
    g = sg.glitch_days(d, "2023-05-01", 500)
    assert g.index.tolist() == [pd.Timestamp("2024-11-09")]


def test_write_monthly_roundtrip(tmp_path):
    m = synthetic_months(n=14)
    path = sg.write_monthly(m, tmp_path / "x.parquet")
    back = pd.read_parquet(path)
    assert back["month"].iloc[0] == "2021-01" and len(back) == 14 and "gap_gwh" in back.columns


@pytest.mark.integration
def test_live_resource_listing_and_cached_schema():
    """Real network call against ONS: the 2021 yearly file and the monthly series exist exactly once as PARQUET (no download here)."""
    client = CkanClient("https://dados.ons.org.br/api/3/action")
    out = sg.list_capacity_factor_resources(CkanClient.resources_from_package(client.package_show("fator-capacidade-2")), 2021)
    assert "2021" in out and "2022-01" in out and "2024-06" in out
    assert all(k == "2021" or len(k) == 7 for k in out)
