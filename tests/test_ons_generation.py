"""Task 3 tests: ONS generation-by-source acquisition. All network calls are mocked with `responses`."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd
import pytest
import responses

from curtailmit import ons_generation as og
from curtailmit.ons_client import CkanClient, CoverageError, ResourceInfo
from curtailmit.schemas import Baseline2020Generation

FIXTURES = Path(__file__).parent / "fixtures" / "ons"
BASE = "https://dados.ons.org.br/api/3/action"
PKG = "balanco-energia-subsistema"
URLS = {2019: "https://files.test/b2019.csv", 2020: "https://files.test/b2020.csv", 2021: "https://files.test/b2021.csv"}

TARGETS = {
    "ons": {
        "ckan_base_url": BASE,
        "packages": {
            "generation_by_source": {
                "package_id": PKG,
                "title": "Balanco de Energia nos Subsistemas",
                "resource_name_pattern": "Balanco_de_Energia_Subsistema-YYYY",
                "preferred_formats": ["PARQUET", "CSV", "XLSX"],
                "min_coverage_start": "2020-01-01",
                "history_start_year": 2019,
                "solar_basis": {"dispatched_from": "2021-01"},
            }
        },
    }
}

# Constant power (MW) per source -> closed-form energy: MW x hours / 1e6 = TWh.
POWER = {"val_gerhidraulica": 40000.0, "val_gertermica": 10000.0, "val_gereolica": 6000.0, "val_gersolar": 4000.0}


def _dispatched(year: int, dispatched_mw: float = 1500.0, balance_mw: float = 4000.0, drop_month: int | None = None, hours_off: int = 0) -> pd.DataFrame:
    """Synthetic interim/ons_solar_dispatched_monthly (constant power): dispatched < balance, as after the 2023-04-29 MMGD step."""
    periods = [p for p in pd.period_range(f"{year}-01", f"{year}-12", freq="M") if p.month != drop_month]
    hours = pd.Series([p.days_in_month * 24 for p in periods], index=pd.PeriodIndex(periods, freq="M"))
    return pd.DataFrame({"hours": hours - hours_off, "dispatched_matched_mwh": dispatched_mw * hours, "balanco_matched_mwh": balance_mw * hours})


def _year_csv(year: int, drop_hours: int = 0) -> bytes:
    stamps = pd.date_range(f"{year}-01-01", f"{year + 1}-01-01", freq="h", inclusive="left")
    if drop_hours:
        stamps = stamps[:-drop_hours]
    frames = []
    for sub in ("SIN", "SE"):
        scale = 1.0 if sub == "SIN" else 0.4  # SE rows must never leak into the national aggregate
        df = pd.DataFrame({"id_subsistema": sub, "nom_subsistema": sub, "din_instante": stamps})
        for col, mw in POWER.items():
            df[col] = f"{mw * scale:.8f}"
        df["val_carga"], df["val_intercambio"] = "1.0", "0.0"
        frames.append(df)
    return pd.concat(frames).to_csv(sep=";", index=False).encode()


def _res(year: int, fmt: str, url: str) -> dict:
    return {"id": f"r{year}{fmt}", "name": f"Balanco_de_Energia_Subsistema-{year}", "format": fmt, "url": url, "last_modified": "2024-01-01"}


def _pkg(resources: list[dict], name: str = PKG, title: str = "Balanço de Energia nos Subsistemas") -> dict:
    return {"success": True, "result": {"name": name, "title": title, "resources": resources}}


@pytest.fixture(autouse=True)
def tmp_database(tmp_path, monkeypatch):
    def raw_dir(sub: str) -> Path:
        path = tmp_path / "raw" / sub
        path.mkdir(parents=True, exist_ok=True)
        return path

    def interim_dir() -> Path:
        path = tmp_path / "interim"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def processed_dir() -> Path:
        path = tmp_path / "processed"
        path.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr(og, "get_raw_dir", raw_dir)
    monkeypatch.setattr(og, "get_interim_dir", interim_dir)
    monkeypatch.setattr(og, "get_processed_dir", processed_dir)
    return tmp_path


def _mock_package(years=(2019, 2020, 2021), bodies: dict[int, bytes] | None = None) -> None:
    bodies = bodies or {}
    resources = [{"id": "dict", "name": "Dicionario de Dados", "format": "PDF", "url": "https://files.test/dict.pdf"}]
    for y in years:
        resources += [_res(y, "CSV", URLS[y]), _res(y, "XLSX", f"https://files.test/should-not-be-fetched-{y}.xlsx")]
    responses.add(responses.GET, f"{BASE}/package_show", match=[responses.matchers.query_param_matcher({"id": PKG})], json=_pkg(resources))
    for y in years:
        responses.add(responses.GET, URLS[y], body=bodies.get(y, _year_csv(y)))


def _sample() -> pd.DataFrame:
    return pd.read_csv(FIXTURES / "balanco_sample_2016.csv", sep=";")


def test_parse_generation_frame_filters_sin_and_handles_blank_solar():
    out = og.parse_generation_frame(_sample(), "sample")
    assert list(out.columns) == ["timestamp", "date", "source_type", "generation_mwh"]
    by = out.groupby("source_type").generation_mwh.sum()
    assert by["hidraulica"] == pytest.approx(118000.0)  # SIN rows only, 1 h interval
    assert by["eolica"] == pytest.approx(5000.0)
    assert by["solar"] == 0.0  # blank solar pre-2017 -> 0, not an error


def test_parse_accepts_decimal_strings_like_the_real_parquet():
    raw = _sample()
    for col in POWER:
        raw[col] = raw[col].map(lambda v: None if pd.isna(v) else f"{v:.8f}")
    out = og.parse_generation_frame(raw, "sample")
    assert out[out.source_type == "hidraulica"].generation_mwh.sum() == pytest.approx(118000.0)


def test_parse_missing_columns_fails_explicitly():
    with pytest.raises(og.GenerationDiscoveryError, match="missing columns"):
        og.parse_generation_frame(pd.DataFrame({"a": [1]}), "bad")


def test_parse_no_sin_rows_fails_explicitly():
    raw = _sample()
    with pytest.raises(og.GenerationDiscoveryError, match="SIN"):
        og.parse_generation_frame(raw[raw.id_subsistema != "SIN"], "nosin")


def test_parse_nan_in_non_solar_source_fails_instead_of_assuming_zero():
    raw = _sample()
    raw.loc[raw.id_subsistema == "SIN", "val_gereolica"] = None
    with pytest.raises(og.GenerationDiscoveryError, match="val_gereolica"):
        og.parse_generation_frame(raw, "nan-wind")


def test_select_yearly_resources_prefers_format_and_skips_docs():
    res = [
        ResourceInfo("1", "Balanco_de_Energia_Subsistema-2020", "CSV", None, "u1"),
        ResourceInfo("2", "Balanco_de_Energia_Subsistema-2020", "PARQUET", None, "u2"),
        ResourceInfo("3", "Balanco_de_Energia_Subsistema-2019", "XLSX", None, "u3"),
        ResourceInfo("4", "Dicionario de Dados", "PDF", None, "u4"),
    ]
    chosen = og.select_yearly_resources(res, ["PARQUET", "CSV", "XLSX"])
    assert [r.resource_id for r in chosen] == ["3", "2"]  # oldest first, parquet beats csv


def test_select_yearly_resources_respects_min_year():
    res = [ResourceInfo(str(y), f"Balanco_de_Energia_Subsistema-{y}", "CSV", None, f"u{y}") for y in (2006, 2015, 2016, 2020)]
    assert [r.resource_id for r in og.select_yearly_resources(res, ["CSV"], min_year=2016)] == ["2016", "2020"]


def test_history_start_after_floor_year_is_rejected():
    from curtailmit.validation import ValidationError

    cfg = dict(TARGETS["ons"]["packages"]["generation_by_source"], history_start_year=2021)
    with pytest.raises(ValidationError, match="history_start_year"):
        og.acquire_ons_generation(targets={"ons": {"ckan_base_url": BASE, "packages": {"generation_by_source": cfg}}}, client=CkanClient(BASE))


def test_parse_partially_blank_solar_is_zero_filled():
    raw = _sample()
    raw.loc[(raw.id_subsistema == "SIN") & (raw.din_instante == "2016-01-01 01:00:00"), "val_gersolar"] = 50.0
    solar = og.parse_generation_frame(raw, "partial")
    assert solar[solar.source_type == "solar"].generation_mwh.tolist() == [0.0, 50.0]


def test_select_yearly_resources_none_usable_raises():
    with pytest.raises(og.GenerationDiscoveryError):
        og.select_yearly_resources([ResourceInfo("1", "Dicionario de Dados", "PDF", None, "u")], ["CSV"])


def test_compute_penetration_matches_closed_form():
    tidy = og.parse_generation_frame(_sample(), "s")
    monthly = og.compute_penetration(tidy, "monthly")
    assert len(monthly) == 1 and (monthly.year[0], monthly.month[0]) == (2016, 1)
    assert monthly.wind_pct[0] == pytest.approx(100 * 5000 / (118000 + 22000 + 5000))
    assert monthly.solar_pct[0] == 0.0
    assert monthly.penetration_pct[0] == pytest.approx(monthly.wind_pct[0] + monthly.solar_pct[0])
    assert "month" not in og.compute_penetration(tidy, "annual").columns


@responses.activate
def test_acquire_happy_path_writes_all_outputs(tmp_database, caplog):
    _mock_package()
    with caplog.at_level(logging.INFO, logger=og.logger.name):
        result = og.acquire_ons_generation(targets=TARGETS, dispatched_monthly=_dispatched(2021))

    tidy = pd.read_parquet(result["interim_path"])
    assert Path(result["interim_path"]) == tmp_database / "interim" / "ons_generation_by_source.parquet"
    assert set(tidy.source_type) == {"hidraulica", "termica", "eolica", "solar"}
    assert (tmp_database / "raw" / "ons" / "generation_by_source" / "Balanco_de_Energia_Subsistema-2020.csv").exists()
    assert not any("should-not-be-fetched" in c.request.url for c in responses.calls)
    assert not result["package"]["used_fallback_search"]

    hours_2020 = 8784  # leap year
    data = json.loads(Path(result["baseline_path"]).read_text(encoding="utf-8"))
    baseline = Baseline2020Generation(**data)  # validates against the schema
    assert baseline.source == "historical_ons" and data["units"] == "TWh"
    assert baseline.wind_twh == pytest.approx(6000 * hours_2020 / 1e6)
    assert baseline.solar_twh == pytest.approx(4000 * hours_2020 / 1e6)
    assert baseline.total_twh == pytest.approx(60000 * hours_2020 / 1e6)
    assert baseline.penetration_pct == pytest.approx(100 * 10000 / 60000)

    annual = pd.read_parquet(result["annual_path"])
    assert sorted(annual.year) == [2019, 2020, 2021]
    assert len(pd.read_parquet(result["monthly_path"])) == 36
    # D20: 2021 solar is the dispatched series (1500 MW), the raw balance (4000 MW) is kept as a diagnostic; 2019-2020 stay on the balance
    a = annual.set_index("year")
    assert a.loc[2021, "solar_basis"] == "dispatched" and a.loc[2020, "solar_basis"] == "balance"
    assert a.loc[2021, "solar_mwh"] == pytest.approx(1500 * 8760) and a.loc[2021, og.SOLAR_RAW_COL] == pytest.approx(4000 * 8760)
    assert a.loc[2020, "solar_mwh"] == pytest.approx(4000 * 8784)
    assert a.loc[2021, "total_mwh"] == pytest.approx((56000 + 1500) * 8760)  # corrected solar also in the denominator
    assert a.loc[2021, "solar_pct"] == pytest.approx(100 * 1500 / 57500)
    assert "package_show('balanco-energia-subsistema') OK" in caplog.text


@responses.activate
def test_series_not_reaching_floor_raises_coverage_error_before_download():
    _mock_package(years=(2021,))
    with pytest.raises(CoverageError):
        og.acquire_ons_generation(targets=TARGETS, dispatched_monthly=_dispatched(2021))
    assert not any(c.request.url == URLS[2021] for c in responses.calls)


@responses.activate
def test_incomplete_2020_baseline_fails_explicitly():
    _mock_package(bodies={2020: _year_csv(2020, drop_hours=48)})
    with pytest.raises(og.GenerationDiscoveryError, match="baseline incomplete"):
        og.acquire_ons_generation(targets=TARGETS, dispatched_monthly=_dispatched(2021))


@responses.activate
def test_stale_package_id_falls_back_to_search_with_warning(caplog):
    responses.add(responses.GET, f"{BASE}/package_show", match=[responses.matchers.query_param_matcher({"id": PKG})], status=404, json={"success": False})
    responses.add(responses.GET, f"{BASE}/package_search", json={"success": True, "result": {"results": [
        {"name": "unrelated", "title": "Carga"},
        {"name": "balanco-energia-subsistema-v2", "title": "Balanço de Energia nos Subsistemas"},
    ]}})
    responses.add(responses.GET, f"{BASE}/package_show", match=[responses.matchers.query_param_matcher({"id": "balanco-energia-subsistema-v2"})],
                  json=_pkg([_res(2020, "CSV", URLS[2020])], name="balanco-energia-subsistema-v2"))
    responses.add(responses.GET, URLS[2020], body=_year_csv(2020))

    with caplog.at_level(logging.WARNING, logger=og.logger.name):
        cfg = dict(TARGETS["ons"]["packages"]["generation_by_source"], solar_basis={"dispatched_from": "2020-01"})
        result = og.acquire_ons_generation(targets={"ons": {"ckan_base_url": BASE, "packages": {"generation_by_source": cfg}}}, dispatched_monthly=_dispatched(2020))
    assert result["package"]["used_fallback_search"] and result["package"]["resolved_package_id"] == "balanco-energia-subsistema-v2"
    assert "STALE" in caplog.text


@responses.activate
def test_fallback_search_without_candidates_raises():
    responses.add(responses.GET, f"{BASE}/package_show", status=500, json={"success": False})
    responses.add(responses.GET, f"{BASE}/package_search", json={"success": True, "result": {"results": []}})
    with pytest.raises(og.GenerationDiscoveryError):
        og.discover_generation_package(CkanClient(BASE), TARGETS["ons"]["packages"]["generation_by_source"])


@responses.activate
def test_structure_change_logs_warning(caplog):
    responses.add(responses.GET, f"{BASE}/package_show", json=_pkg([{"id": "x", "name": "renamed", "format": "PDF", "url": "u"}], title="Other title"))
    with caplog.at_level(logging.WARNING, logger=og.logger.name):
        og.discover_generation_package(CkanClient(BASE), TARGETS["ons"]["packages"]["generation_by_source"])
    assert "title changed" in caplog.text
    assert "yearly" in caplog.text


@pytest.mark.integration
def test_live_generation_discovery_and_2020_baseline(tmp_path):
    """Real network call against ONS CKAN. Run manually: pytest -m integration"""
    from curtailmit.acquisition import fetch_and_cache

    targets = og.load_acquisition_targets()
    cfg = targets["ons"]["packages"]["generation_by_source"]
    info, resources = og.discover_generation_package(CkanClient(targets["ons"]["ckan_base_url"]), cfg)
    assert not info.used_fallback_search, f"static config stale -> {info.resolved_package_id}"
    res_2020 = next(r for r in og.select_yearly_resources(resources, cfg["preferred_formats"]) if r.name.endswith("-2020"))
    dest = fetch_and_cache(res_2020.url, tmp_path / f"b2020.{res_2020.format.lower()}")
    baseline = og.extract_baseline_2020(og.parse_generation_frame(og._read_table(dest, res_2020.format), "live-2020"))
    assert 400 < baseline.total_twh < 700
    assert 0 < baseline.penetration_pct < 25


# ------------------------------------------------------------------ D20 (Task 9): dispatched-solar basis


def _tidy_year(year: int) -> pd.DataFrame:
    raw = pd.read_csv(__import__("io").BytesIO(_year_csv(year)), sep=";")
    return og.parse_generation_frame(raw, f"t{year}")


def test_compute_penetration_uses_dispatched_solar_in_numerator_and_denominator():
    tidy = pd.concat([_tidy_year(2020), _tidy_year(2021)], ignore_index=True)
    monthly = og.compute_penetration(tidy, "monthly", _dispatched(2021), "2021-01").set_index(["year", "month"])
    jan21, jan20 = monthly.loc[(2021, 1)], monthly.loc[(2020, 1)]
    assert jan21.solar_basis == "dispatched" and jan20.solar_basis == "balance"
    assert jan21.solar_mwh == pytest.approx(1500 * 744) and jan21[og.SOLAR_RAW_COL] == pytest.approx(4000 * 744)
    assert jan21.total_mwh == pytest.approx((40000 + 10000 + 6000 + 1500) * 744)
    assert jan21.penetration_pct == pytest.approx(100 * 7500 / 57500)
    assert jan20.penetration_pct == pytest.approx(100 * 10000 / 60000)  # before the window: untouched
    annual = og.compute_penetration(tidy, "annual", _dispatched(2021), "2021-01").set_index("year")
    assert annual.loc[2021, "solar_mwh"] == pytest.approx(monthly.loc[2021, "solar_mwh"].sum())  # annual == sum of months


def test_without_dispatched_arguments_the_balance_is_used_and_labelled():
    monthly = og.compute_penetration(_tidy_year(2021), "monthly")
    assert set(monthly.solar_basis) == {"balance"} and (monthly.solar_mwh == monthly[og.SOLAR_RAW_COL]).all()
    with pytest.raises(ValueError, match="together"):
        og.compute_penetration(_tidy_year(2021), "monthly", dispatched_monthly=_dispatched(2021))


def test_missing_dispatched_month_fails_and_names_the_month():
    with pytest.raises(og.GenerationDiscoveryError, match="2021-06"):
        og.compute_penetration(_tidy_year(2021), "monthly", _dispatched(2021, drop_month=6), "2021-01")


def test_dispatched_with_different_hours_fails_explicitly():
    with pytest.raises(og.GenerationDiscoveryError, match="hour-count mismatch"):
        og.compute_penetration(_tidy_year(2021), "monthly", _dispatched(2021, hours_off=3), "2021-01")


def test_dispatched_built_on_a_different_balance_series_fails():
    with pytest.raises(og.GenerationDiscoveryError, match="balance energy mismatch"):
        og.compute_penetration(_tidy_year(2021), "monthly", _dispatched(2021, balance_mw=3999.0), "2021-01")


def test_missing_solar_basis_config_fails_explicitly():
    cfg = {k: v for k, v in TARGETS["ons"]["packages"]["generation_by_source"].items() if k != "solar_basis"}
    from curtailmit.validation import ValidationError

    with pytest.raises(ValidationError, match="solar_basis"), responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, f"{BASE}/package_show", match=[responses.matchers.query_param_matcher({"id": PKG})], json=_pkg([_res(2020, "CSV", URLS[2020])]))
        rsps.add(responses.GET, URLS[2020], body=_year_csv(2020))
        og.acquire_ons_generation(targets={"ons": {"ckan_base_url": BASE, "packages": {"generation_by_source": cfg}}})


def test_2020_baseline_is_independent_of_the_solar_basis():
    """D20 leaves the D1 baseline alone: extract_baseline_2020 reads the raw balance tidy series and takes no dispatched argument."""
    import inspect

    assert "dispatched" not in inspect.signature(og.extract_baseline_2020).parameters
    baseline = og.extract_baseline_2020(_tidy_year(2020))
    assert baseline.solar_twh == pytest.approx(4000 * 8784 / 1e6) and baseline.wind_twh == pytest.approx(6000 * 8784 / 1e6)
    assert baseline.total_twh == pytest.approx(60000 * 8784 / 1e6) and baseline.penetration_pct == pytest.approx(100 * 10000 / 60000)


@pytest.mark.integration
def test_live_2020_baseline_values_unchanged_after_d20():
    """Real DATABASE_ROOT output of the pipeline run after D20: 554.35 / 54.30 / 5.23 TWh, 10.74 %. Run manually: pytest -m integration"""
    from curtailmit.paths import get_processed_dir

    path = get_processed_dir() / og.BASELINE_FILENAME
    if not path.exists():
        pytest.skip("processed/baseline_2020_generation.json not built yet")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["total_twh"] == pytest.approx(554.35, abs=0.005) and data["wind_twh"] == pytest.approx(54.30, abs=0.005)
    assert data["solar_twh"] == pytest.approx(5.23, abs=0.005) and data["penetration_pct"] == pytest.approx(10.74, abs=0.005)
