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
            }
        },
    }
}

# Constant power (MW) per source -> closed-form energy: MW x hours / 1e6 = TWh.
POWER = {"val_gerhidraulica": 40000.0, "val_gertermica": 10000.0, "val_gereolica": 6000.0, "val_gersolar": 4000.0}


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
        result = og.acquire_ons_generation(targets=TARGETS)

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
    assert "package_show('balanco-energia-subsistema') OK" in caplog.text


@responses.activate
def test_series_not_reaching_floor_raises_coverage_error_before_download():
    _mock_package(years=(2021,))
    with pytest.raises(CoverageError):
        og.acquire_ons_generation(targets=TARGETS)
    assert not any(c.request.url == URLS[2021] for c in responses.calls)


@responses.activate
def test_incomplete_2020_baseline_fails_explicitly():
    _mock_package(bodies={2020: _year_csv(2020, drop_hours=48)})
    with pytest.raises(og.GenerationDiscoveryError, match="baseline incomplete"):
        og.acquire_ons_generation(targets=TARGETS)


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
        result = og.acquire_ons_generation(targets=TARGETS)
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
