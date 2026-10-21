"""Task 2 tests: ONS curtailment discovery/acquisition. All network calls are mocked with `responses`."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
import responses

from curtailmit import data_ingestion as di
from curtailmit.ons_client import CkanClient, CoverageError, ResourceInfo

FIXTURES = Path(__file__).parent / "fixtures" / "ons"
BASE = "https://dados.ons.org.br/api/3/action"
WIND_URL = "https://files.test/wind-2022-01.csv"
SOLAR_URL = "https://files.test/solar-2022-01.csv"

TARGETS = {
    "ons": {
        "ckan_base_url": BASE,
        "min_coverage_start": "2022-01-01",
        "packages": {
            "curtailment_wind": {"package_id": "restricao_coff_eolica_usi", "resource_name_pattern": "Restricoes_coff_eolicas-YYYY-MM", "preferred_formats": ["PARQUET", "CSV", "XLSX"]},
            "curtailment_solar": {"package_id": "restricao_coff_fotovoltaica", "resource_name_pattern": "Restricoes_coff_fotovoltaica-YYYY-MM", "preferred_formats": ["PARQUET", "CSV", "XLSX"]},
        },
    }
}


def _pkg(name: str, resources: list[dict], title: str = "Restricao COFF") -> dict:
    return {"success": True, "result": {"name": name, "title": title, "resources": resources}}


def _res(rid: str, name: str, fmt: str, url: str) -> dict:
    return {"id": rid, "name": name, "format": fmt, "url": url, "last_modified": "2024-01-01"}


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

    monkeypatch.setattr(di, "get_raw_dir", raw_dir)
    monkeypatch.setattr(di, "get_interim_dir", interim_dir)
    return tmp_path


def _mock_happy_path(rsps: responses.RequestsMock, wind_file: str = "coff_wind_2022-01.csv") -> None:
    rsps.add(responses.GET, f"{BASE}/package_show", match=[responses.matchers.query_param_matcher({"id": "restricao_coff_eolica_usi"})], json=_pkg("restricao_coff_eolica_usi", [
        _res("w1", "Restricoes_coff_eolicas-2022-01", "CSV", WIND_URL),
        _res("w0", "Restricoes_coff_eolicas-2021-12", "CSV", "https://files.test/should-not-be-fetched.csv"),
        _res("wd", "Dicionario de Dados", "PDF", "https://files.test/dict.pdf"),
    ]))
    rsps.add(responses.GET, f"{BASE}/package_show", match=[responses.matchers.query_param_matcher({"id": "restricao_coff_fotovoltaica"})], json=_pkg("restricao_coff_fotovoltaica", [
        _res("s1", "Restricoes_coff_fotovoltaica-2022-01", "CSV", SOLAR_URL),
    ]))
    rsps.add(responses.GET, WIND_URL, body=(FIXTURES / wind_file).read_bytes())
    rsps.add(responses.GET, SOLAR_URL, body=(FIXTURES / "coff_solar_2022-01.csv").read_bytes())


def test_parse_frame_computes_mwh_from_interval():
    raw = pd.read_csv(FIXTURES / "coff_wind_2022-01.csv", sep=";")
    out = di.parse_curtailment_frame(raw, "wind")
    assert list(out.columns) == ["timestamp", "date", "usina", "curtailed_energy_mwh", "reason_category", "source"]
    a = out[out.usina == "Usina Eolica A"]
    # (20-10) + (20-12) MW at 0.5 h
    assert a.curtailed_energy_mwh.sum() == pytest.approx((10 + 8) * 0.5)
    assert out[out.usina == "Usina Eolica B"].curtailed_energy_mwh.iloc[0] == 0.0
    assert out.reason_category.isna().sum() == 1
    assert set(out.source) == {"wind"}


def test_parse_frame_prefers_ons_reported_curtailed_power():
    raw = pd.read_csv(FIXTURES / "coff_wind_2022-01.csv", sep=";")
    raw["val_geracaonaorealizadaapurada"] = [4.0, None, None, 2.0]
    out = di.parse_curtailment_frame(raw, "wind")
    assert out.curtailed_energy_mwh.tolist() == [2.0, 0.0, 0.0, 1.0]


def test_parse_frame_missing_columns_fails_explicitly():
    with pytest.raises(di.CurtailmentDiscoveryError):
        di.parse_curtailment_frame(pd.DataFrame({"a": [1]}), "solar")


def test_select_data_resources_skips_docs_and_old_months():
    res = [
        ResourceInfo("1", "X-2021-12", "CSV", None, "u1"),
        ResourceInfo("2", "X-2022-01", "CSV", None, "u2"),
        ResourceInfo("3", "X-2022-01", "XLSX", None, "u3"),
        ResourceInfo("4", "X-2022-01", "PARQUET", None, "u4"),
        ResourceInfo("5", "Dicionario", "PDF", None, "u5"),
    ]
    chosen = di.select_data_resources(res, ["PARQUET", "CSV", "XLSX"], (2022, 1))
    assert [r.resource_id for r in chosen] == ["4"]


def test_select_data_resources_no_usable_format_raises():
    with pytest.raises(di.CurtailmentDiscoveryError):
        di.select_data_resources([ResourceInfo("1", "Dicionario", "PDF", None, "u")], ["CSV"], (2022, 1))


@responses.activate
def test_acquire_happy_path_writes_interim_parquet(tmp_database, caplog):
    _mock_happy_path(responses)
    with caplog.at_level(logging.INFO, logger=di.logger.name):
        result = di.acquire_ons_curtailment(targets=TARGETS)

    df = pd.read_parquet(result["interim_path"])
    assert Path(result["interim_path"]) == tmp_database / "interim" / "ons_curtailment_raw.parquet"
    assert set(df.source) == {"wind", "solar"}
    assert len(df) == 6
    assert (tmp_database / "raw" / "ons" / "curtailment_wind" / "Restricoes_coff_eolicas-2022-01.csv").exists()
    assert not any("should-not-be-fetched" in c.request.url for c in responses.calls)
    assert all(not p["used_fallback_search"] for p in result["packages"])
    assert "coverage found: 2022-01-01" in caplog.text


@responses.activate
def test_short_coverage_raises_coverage_error():
    _mock_happy_path(responses, wind_file="coff_wind_2023-03_short.csv")
    with pytest.raises(CoverageError):
        di.acquire_ons_curtailment(targets=TARGETS)


@responses.activate
def test_stale_package_id_falls_back_to_search_with_warning(caplog):
    responses.add(responses.GET, f"{BASE}/package_show", match=[responses.matchers.query_param_matcher({"id": "restricao_coff_fotovoltaica"})], status=404, json={"success": False})
    responses.add(responses.GET, f"{BASE}/package_search", json={"success": True, "result": {"results": [
        {"name": "unrelated", "title": "Geracao"},
        {"name": "restricao_coff_fv_novo", "title": "Restrição COFF Fotovoltaica"},
    ]}})
    responses.add(responses.GET, f"{BASE}/package_show", match=[responses.matchers.query_param_matcher({"id": "restricao_coff_fv_novo"})], json=_pkg("restricao_coff_fv_novo", [
        _res("s1", "Restricoes_coff_fotovoltaica-2022-01", "CSV", SOLAR_URL),
    ]))
    responses.add(responses.GET, SOLAR_URL, body=(FIXTURES / "coff_solar_2022-01.csv").read_bytes())

    with caplog.at_level(logging.WARNING, logger=di.logger.name):
        data, info = di.acquire_curtailment_source(CkanClient(BASE), "solar", TARGETS["ons"]["packages"]["curtailment_solar"], date(2022, 1, 1))

    assert info.used_fallback_search and info.resolved_package_id == "restricao_coff_fv_novo"
    assert "STALE" in caplog.text
    assert len(data) == 2


@responses.activate
def test_structure_change_logs_warning(caplog):
    responses.add(responses.GET, f"{BASE}/package_show", json=_pkg("restricao_coff_eolica_usi", [_res("x", "renamed-file", "PDF", "u")]))
    cfg = dict(TARGETS["ons"]["packages"]["curtailment_wind"], title="Old title")
    with caplog.at_level(logging.WARNING, logger=di.logger.name):
        di.discover_curtailment_package(CkanClient(BASE), "wind", cfg)
    assert "title changed" in caplog.text
    assert "none of the preferred formats" in caplog.text
    assert "no resource matches the monthly" in caplog.text


@responses.activate
def test_fallback_search_without_candidates_raises():
    responses.add(responses.GET, f"{BASE}/package_show", status=500, json={"success": False})
    responses.add(responses.GET, f"{BASE}/package_search", json={"success": True, "result": {"results": []}})
    with pytest.raises(di.CurtailmentDiscoveryError):
        di.discover_curtailment_package(CkanClient(BASE), "wind", TARGETS["ons"]["packages"]["curtailment_wind"])


def test_read_table_xlsx_and_parquet(tmp_path):
    raw = pd.read_csv(FIXTURES / "coff_solar_2022-01.csv", sep=";")
    raw.to_excel(tmp_path / "a.xlsx", index=False)
    raw.to_parquet(tmp_path / "a.parquet", index=False)
    for name, fmt in (("a.xlsx", "XLSX"), ("a.parquet", "PARQUET")):
        out = di.parse_curtailment_frame(di._read_table(tmp_path / name, fmt), "solar")
        assert out.curtailed_energy_mwh.sum() == pytest.approx(10 * 0.5)


@pytest.mark.integration
def test_live_ons_discovery_and_coverage(tmp_path, monkeypatch):
    """Real network call against ONS CKAN. Run manually: pytest -m integration"""
    monkeypatch.setenv("DATABASE_ROOT", str(tmp_path))
    targets = di.load_acquisition_targets()
    client = CkanClient(targets["ons"]["ckan_base_url"])
    for source, key in di._SOURCE_KEYS.items():
        info, resources = di.discover_curtailment_package(client, source, targets["ons"]["packages"][key])
        assert resources, f"{source}: no resources"
        assert not info.used_fallback_search, f"{source}: static config stale -> {info.resolved_package_id}"
