"""Task 6B tests: ONS dictionary check, candidate discovery, schema verification, comparison. Network is mocked with `responses`."""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path

import pandas as pd
import pytest
import responses

from curtailmit import ons_classification as oc
from curtailmit import ons_mmgd_probe as pr
from curtailmit.ons_client import CkanClient

BASE = "https://dados.ons.org.br/api/3/action"
DICT_URL = "https://files.test/dict.json"
SILENT_NOTES = "Informações da carga e oferta. A oferta é representada pelos valores de geração das usinas hidráulicas, térmicas, eólicas e fotovoltaicas, em MWmed."
MMGD_NOTES = "Dados de carga por subsistema. A partir de 29/04/2023, passou a ser incorporado o valor estimado da micro e minigeração distribuída (MMGD), com base em dados meteorológicos previstos."


@pytest.fixture(autouse=True)
def tmp_database(tmp_path, monkeypatch):
    def raw_dir(sub: str) -> Path:
        path = tmp_path / "raw" / sub
        path.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr(pr, "get_raw_dir", raw_dir)
    monkeypatch.setattr(oc, "get_raw_dir", raw_dir)
    return tmp_path


def dictionary(entries: dict[str, str]) -> bytes:
    return json.dumps({"titulo": "d", "dicionario_simplificado": [{"codigo": k, "descricao": v} for k, v in entries.items()]}, ensure_ascii=False).encode("utf-8")


def package(name: str, notes: str, resources: list[dict], title: str = "T") -> dict:
    return {"name": name, "title": title, "notes": notes, "resources": resources}


def dict_resource(url: str = DICT_URL) -> dict:
    return {"id": "d", "name": "Dicionário de Dados Json", "format": "JSON", "url": url, "last_modified": None}


def mock_package(rsps, pkg: dict, dict_entries: dict[str, str] | None, url: str = DICT_URL) -> None:
    rsps.add(responses.GET, f"{BASE}/package_show", match=[responses.matchers.query_param_matcher({"id": pkg["name"]})], json={"success": True, "result": pkg})
    if dict_entries is not None:
        rsps.add(responses.GET, url, body=dictionary(dict_entries))


BALANCO_DICT = {
    "id_subsistema": "Código do Subsistema da Usina", "val_gereolica": "Valor verificado de geração eólica, em MWmed",
    "val_gersolar": "Valor verificado de geração fotovoltaica, em MWmed",
}


# ------------------------------------------------------------------ Part A


def test_scan_keywords_is_accent_insensitive():
    assert pr.scan_keywords("Geração Distribuída estimada das usinas") == ["geracao distribuida", "estimad", "usina"]
    assert pr.scan_keywords("nada relevante") == []


@responses.activate
def test_silent_dictionary_is_reported_as_silent_with_verbatim_text(caplog):
    pkg = package("balanco", SILENT_NOTES, [dict_resource(), {"id": "r", "name": "B-2023", "format": "PARQUET", "url": "u", "last_modified": "2025-07-28T13:30:49"}])
    mock_package(responses, pkg, BALANCO_DICT)
    with caplog.at_level(logging.INFO, logger=pr.logger.name):
        chk = pr.check_package_dictionary(CkanClient(BASE), "balanco", ["val_gersolar", "val_gereolica", "val_missing"], "ons/x")
    assert chk.field_definitions["val_gersolar"] == "Valor verificado de geração fotovoltaica, em MWmed"  # verbatim
    assert "val_missing" not in chk.field_definitions
    assert not chk.states_mmgd_included and not chk.states_centralized_only
    assert chk.dictionary_url == DICT_URL and chk.resource_last_modified == {"B-2023": "2025-07-28T13:30:49"}
    assert any(h["keywords"] == "usina" for h in chk.keyword_hits)
    assert "val_gersolar (verbatim)" in caplog.text and DICT_URL in caplog.text and "val_missing is not described" in caplog.text
    assert (Path(oc.get_raw_dir("ons/x")) / "data_dictionary.json.manifest.json").exists()  # retrieval manifest via fetch_and_cache


@responses.activate
def test_mmgd_statement_in_package_notes_is_detected_verbatim():
    mock_package(responses, package("carga", MMGD_NOTES, [dict_resource()]), {"val_cargaenergiamwmed": "Valor da Carga de Energia, em MWmed"})
    chk = pr.check_package_dictionary(CkanClient(BASE), "carga", ["val_cargaenergiamwmed"], "ons/y")
    assert chk.states_mmgd_included
    hit = next(h for h in chk.keyword_hits if h["where"] == "package notes" and "29/04/2023" in h["text"])
    assert "mmgd" in hit["keywords"] and "estimad" in hit["keywords"]


@responses.activate
def test_mmgd_statement_in_field_definition_and_centralized_only_are_detected():
    mock_package(responses, package("p", "", [dict_resource()]), {"val_gersolar": "Geração fotovoltaica, incluindo MMGD estimada", "val_gereolica": "Geração eólica de usinas centralizadas"})
    chk = pr.check_package_dictionary(CkanClient(BASE), "p", ["val_gersolar", "val_gereolica"], "ons/z")
    assert chk.states_mmgd_included and chk.states_centralized_only


@responses.activate
def test_package_without_dictionary_is_reported_not_crashed():
    mock_package(responses, package("nodict", "", [{"id": "x", "name": "data", "format": "CSV", "url": "u"}]), None)
    chk = pr.check_package_dictionary(CkanClient(BASE), "nodict", ["val_gersolar"], "ons/w")
    assert chk.dictionary_url is None and chk.field_definitions == {} and not chk.states_mmgd_included


# ------------------------------------------------------------------ Part B


def test_assess_candidate_rules_cover_each_rejection_reason():
    data = [{"id": "1", "name": "n", "format": "CSV", "url": "u"}]
    base = {"title": "Fator de Capacidade Solar", "notes": "", "resources": data}
    assert pr.assess_candidate(base, ["din_instante", "id_ons", "val_fatorcapacidade"])[0]
    assert "no data resource" in pr.assess_candidate({**base, "resources": [{"id": "1", "name": "d", "format": "PDF", "url": "u"}]}, ["din_instante", "id_ons"])[1]
    assert "no machine-readable" in pr.assess_candidate(base, [])[1]
    assert "not a time series" in pr.assess_candidate(base, ["dat_entradaoperacao", "id_ons"])[1]  # registry date is not a timestamp
    assert "plant level" in pr.assess_candidate(base, ["din_instante", "val_x"])[1] or "identifier" in pr.assess_candidate(base, ["din_instante", "val_x"])[1]
    assert "off-topic" in pr.assess_candidate({**base, "title": "Volume de espera"}, ["din_instante", "id_subsistema"])[1]
    assert pr.assess_candidate({**base, "title": "Programado"}, ["dat_programacao", "cod_usinapdp", "val_programado"])[1] != ""


def tiny_parquet() -> bytes:
    buf = io.BytesIO()
    pd.DataFrame({"din_instante": pd.to_datetime(["2023-04-01"]), "id_ons": ["x"]}).to_parquet(buf, index=False)
    return buf.getvalue()


@responses.activate
def test_discover_candidates_logs_accept_and_reject_with_reasons(caplog):
    ok = package("fc", "", [dict_resource("https://files.test/d1.json"), {"id": "p", "name": "FC-2023-04", "format": "PARQUET", "url": "https://files.test/fc.parquet", "last_modified": "2026-01-01"}], title="Fator de Capacidade")
    bad = package("ear", "", [dict_resource("https://files.test/d2.json"), {"id": "c", "name": "EAR-2020", "format": "CSV", "url": "https://files.test/ear.csv"}], title="EAR")
    responses.add(responses.GET, f"{BASE}/package_search", json={"success": True, "result": {"results": [ok, bad]}})
    for pkg, url, fields in ((ok, "https://files.test/d1.json", {"din_instante": "t", "id_ons": "i", "val_fatorcapacidade": "fc"}), (bad, "https://files.test/d2.json", {"id_reservatorio": "r", "val_ear": "e"})):
        mock_package(responses, pkg, fields, url)
    responses.add(responses.GET, "https://files.test/fc.parquet", body=tiny_parquet())
    with caplog.at_level(logging.INFO, logger=pr.logger.name):
        result = pr.discover_candidates(CkanClient(BASE), queries=("q1",))
    by_id = {c.package_id: c for c in result}
    assert by_id["fc"].accepted and by_id["fc"].sample_schema == ["din_instante", "id_ons"] and by_id["fc"].apparent_range == "2023-04..2023-04"
    assert not by_id["ear"].accepted and "not a time series" in by_id["ear"].reason
    assert "ACCEPT candidate fc" in caplog.text and "REJECT candidate ear" in caplog.text


# ------------------------------------------------------------------ Part C


def test_schema_verification_good_and_bad():
    pr.verify_capacity_factor_schema(list(pr.CF_REQUIRED_COLUMNS))
    with pytest.raises(pr.ProbeError, match="schema changed"):
        pr.verify_capacity_factor_schema(["din_instante"])
    pr.verify_mmgd_api_schema([{f: 0 for f in pr.MMGD_REQUIRED_FIELDS}])
    with pytest.raises(pr.ProbeError, match="no records"):
        pr.verify_mmgd_api_schema([])
    with pytest.raises(pr.ProbeError, match="schema changed"):
        pr.verify_mmgd_api_schema([{"cod_areacarga": "NE"}])


def cf_parquet_bytes(drop: str | None = None) -> bytes:
    stamps = pd.date_range("2023-04-01", periods=3, freq="h")
    df = pd.DataFrame({"din_instante": stamps, "nom_tipousina": "Solar", "nom_usina_conjunto": "U", "id_ons": "x",
                       "val_geracaoverificada": ["10.0", "20.0", "30.0"], "val_capacidadeinstalada": "100.0", "val_fatorcapacidade": "0.1"})
    if drop:
        df = df.drop(columns=[drop])
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    return buf.getvalue()


@responses.activate
def test_acquire_capacity_factor_months_downloads_verifies_and_records_manifest(tmp_database):
    res = [{"id": "a", "name": "Fator_Capacidade_2-2023-04", "format": "PARQUET", "url": "https://files.test/cf0423.parquet"},
           {"id": "b", "name": "Fator_Capacidade_2-2023-04", "format": "CSV", "url": "https://files.test/cf0423.csv"}]
    responses.add(responses.GET, f"{BASE}/package_show", match=[responses.matchers.query_param_matcher({"id": pr.CF_PACKAGE})], json={"success": True, "result": package(pr.CF_PACKAGE, "", res)})
    responses.add(responses.GET, "https://files.test/cf0423.parquet", body=cf_parquet_bytes())
    out = pr.acquire_capacity_factor_months(CkanClient(BASE), ["2023-04"])
    assert out["2023-04"] == tmp_database / "raw" / "ons" / "capacity_factor" / "Fator_Capacidade_2-2023-04.parquet"
    assert (out["2023-04"].parent / "Fator_Capacidade_2-2023-04.parquet.manifest.json").exists()
    with pytest.raises(pr.ProbeError, match="exactly one"):
        pr.acquire_capacity_factor_months(CkanClient(BASE), ["2030-01"])


@responses.activate
def test_acquire_capacity_factor_rejects_a_changed_schema():
    res = [{"id": "a", "name": "Fator_Capacidade_2-2023-04", "format": "PARQUET", "url": "https://files.test/bad.parquet"}]
    responses.add(responses.GET, f"{BASE}/package_show", json={"success": True, "result": package(pr.CF_PACKAGE, "", res)})
    responses.add(responses.GET, "https://files.test/bad.parquet", body=cf_parquet_bytes(drop="val_geracaoverificada"))
    with pytest.raises(pr.ProbeError, match="val_geracaoverificada"):
        pr.acquire_capacity_factor_months(CkanClient(BASE), ["2023-04"])


@responses.activate
def test_acquire_mmgd_load_uses_the_api_with_params_and_verifies_schema(tmp_database):
    record = {"cod_areacarga": "NE", "dat_referencia": "2023-04-29", "din_referenciautc": "2023-04-29T03:30:00.000Z", "val_cargaglobal": 100.0, "val_cargammgd": 5.0}
    responses.add(responses.GET, pr.MMGD_API_URL, json=[record],
                  match=[responses.matchers.query_param_matcher({"dat_inicio": "2023-04-29", "dat_fim": "2023-04-30", "cod_areacarga": "NE"})])
    out = pr.acquire_mmgd_load(["NE"], "2023-04-29", "2023-04-30")
    assert out["NE"].parent == tmp_database / "raw" / "ons" / "mmgd" and json.loads(out["NE"].read_text(encoding="utf-8"))[0]["val_cargammgd"] == 5.0


# ------------------------------------------------------------------ comparison


def test_dispatched_vs_balanco_shows_the_step_that_dispatched_solar_does_not_have():
    stamps = pd.date_range("2023-04-28", periods=96, freq="h")  # 4 days
    cf = pd.DataFrame({"din_instante": stamps, "nom_tipousina": "Solar", "nom_usina_conjunto": "U", "id_ons": "x",
                       "val_geracaoverificada": ["100"] * 96, "val_capacidadeinstalada": "1", "val_fatorcapacidade": "0.1"})
    balance = pd.Series([105.0] * 24 + [2600.0] * 72, index=stamps)  # balance jumps on the 2nd day, dispatched does not
    daily = pr.dispatched_vs_balanco(cf, balance)
    assert daily.difference_mwmed.iloc[0] == pytest.approx(5.0) and daily.difference_mwmed.iloc[1] == pytest.approx(2500.0)
    assert daily.dispatched_mwmed.nunique() == 1


@pytest.mark.integration
def test_live_dictionary_candidates_and_schemas(tmp_path, monkeypatch):
    """Real network calls against ONS. Run manually: pytest -m integration"""
    def raw_dir(sub: str) -> Path:
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
        return tmp_path / sub

    monkeypatch.setattr(pr, "get_raw_dir", raw_dir)
    monkeypatch.setattr(oc, "get_raw_dir", raw_dir)
    client = CkanClient("https://dados.ons.org.br/api/3/action")
    chk = pr.check_package_dictionary(client, "balanco-energia-subsistema", ["val_gersolar", "val_gereolica"], "ons/generation_by_source")
    assert chk.field_definitions["val_gersolar"].lower().startswith("valor verificado de gera")
    carga = pr.check_package_dictionary(client, "carga-energia", ["val_cargaenergiamwmed"], "ons/carga_energia")
    assert carga.states_mmgd_included and any("29/04/2023" in h["text"] for h in carga.keyword_hits)
    files = pr.acquire_capacity_factor_months(client, ["2023-04"])
    assert files["2023-04"].exists()
    mmgd = pr.acquire_mmgd_load(["NE"], "2024-06-10", "2024-06-10")
    assert mmgd["NE"].exists()
