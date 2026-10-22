"""Task 6 tests: ANEEL fallback (generation-by-source capacity). All network calls are mocked with `responses`."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest
import responses

from curtailmit import aneel_client as ac
from curtailmit.ons_client import CkanClient

BASE = "https://dadosabertos.aneel.gov.br/api/3/action"
CSV_URL = "https://files.test/siga-empreendimentos-geracao-diario.csv"
NOW = datetime(2026, 10, 22, tzinfo=timezone.utc)
CFG = {"queries": ["geracao usina", "geracao fonte"], "resource_name_hint": "empreendimentos-geracao"}
TARGETS = {"aneel": {"ckan_base_url": BASE, "generation_fallback": CFG}}


def _pkg(name: str, title: str, resources: list[tuple[str, str]], modified: str = "2026-10-01T00:00:00") -> dict:
    return {"name": name, "title": title, "metadata_modified": modified,
            "resources": [{"id": f"{name}-{i}", "name": n, "format": f, "url": CSV_URL if "empreendimentos-geracao" in n else f"https://files.test/{n}", "last_modified": modified}
                          for i, (n, f) in enumerate(resources)]}


SIGA = _pkg("siga-sistema-de-informacoes-de-geracao-da-aneel", "SIGA - Sistema de Informações de Geração da ANEEL",
            [("Dicionário de dados", "PDF"), ("siga-empreendimentos-geracao.csv", "CSV"), ("siga-empreendimentos-geracao-diario.csv", "CSV")])
SIGA["resources"][2]["last_modified"] = "2026-10-21T10:00:00"  # the daily extract is the most recent
OTHERS = [
    _pkg("capacidade-instalada-por-unidade-da-federacao", "Capacidade Instalada por Unidade da Federação", [("capacidade-instalada-geracao-uf.csv", "CSV")]),
    _pkg("geracao", "Fiscalização da Geração (descontinuado)", [("FiscalizacaoGeracao.csv", "CSV")], modified="2021-11-30T00:00:00"),
    _pkg("relacao-de-empreendimentos-de-geracao-distribuida", "Relação de empreendimentos de Mini e Micro Geração Distribuída", [("empreendimentos-geracao-distribuida.csv", "CSV")]),
    _pkg("pdf-only", "Geração documentos", [("doc", "PDF")]),
]


def siga_csv(rows: list[tuple]) -> bytes:
    df = pd.DataFrame(rows, columns=["SigTipoGeracao", "DscFaseUsina", "DatEntradaOperacao", "MdaPotenciaFiscalizadaKw"])
    return df.to_csv(sep=";", index=False, decimal=",").encode("utf-8")


PLANTS = [
    ("UFV", "Operação", "2019-06-01", 2000), ("UFV", "Operação", "2022-03-01", 5000), ("UFV", "Construção", "2030-01-01", 9000),
    ("EOL", "Operação", "2010-01-01", 10000), ("UHE", "Operação", "1980-01-01", 100000), ("PCH", "Operação", "2000-01-01", 4000),
    ("UTE", "Operação", "2005-01-01", 30000), ("UTN", "Operação", "1985-01-01", 2000),
]


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

    monkeypatch.setattr(ac, "get_raw_dir", raw_dir)
    monkeypatch.setattr(ac, "get_interim_dir", interim_dir)
    return tmp_path


def _mock_search(rsps, results: list[dict]) -> None:
    rsps.add(responses.GET, f"{BASE}/package_search", json={"success": True, "result": {"results": results}})


def test_score_prefers_the_plant_registry_and_penalises_discontinued_and_mmgd():
    scores = {p["name"]: ac.score_candidate(p, "empreendimentos-geracao", NOW)[0] for p in [SIGA, *OTHERS]}
    assert scores["siga-sistema-de-informacoes-de-geracao-da-aneel"] == 7
    registry = scores["siga-sistema-de-informacoes-de-geracao-da-aneel"]
    assert scores["geracao"] < 0 and scores["relacao-de-empreendimentos-de-geracao-distribuida"] < registry
    assert scores["pdf-only"] == -100


@responses.activate
def test_discovery_chooses_siga_and_logs_why_alternatives_lost(caplog):
    _mock_search(responses, [*OTHERS, SIGA])
    with caplog.at_level(logging.INFO, logger=ac.logger.name):
        choice, resource = ac.discover_generation_package(CkanClient(BASE), CFG, NOW)
    assert choice.package_id == "siga-sistema-de-informacoes-de-geracao-da-aneel" and choice.n_candidates == 5
    assert resource.name == "siga-empreendimentos-geracao-diario.csv"  # the most recent extract of the registry
    assert "geracao" in choice.rejected and "score" in choice.rejected["geracao"]
    assert "candidate geracao" in caplog.text and "rejected geracao" in caplog.text


@responses.activate
def test_discovery_without_a_registry_like_candidate_fails_explicitly():
    _mock_search(responses, OTHERS)
    with pytest.raises(ac.AneelFallbackError, match="refusing to guess"):
        ac.discover_generation_package(CkanClient(BASE), CFG, NOW)


@responses.activate
def test_discovery_without_any_candidates_fails():
    _mock_search(responses, [])
    with pytest.raises(ac.AneelFallbackError, match="no candidates"):
        ac.discover_generation_package(CkanClient(BASE), CFG, NOW)


def test_parse_keeps_only_operating_plants_and_maps_types():
    plants = ac.parse_siga_plants(pd.read_csv(pd.io.common.BytesIO(siga_csv(PLANTS)), sep=";", decimal=","))
    assert len(plants) == 7  # the plant under construction is excluded
    assert set(plants.source_type) == {"solar", "eolica", "hidraulica", "termica"}
    assert plants.loc[plants.source_type == "hidraulica", "capacity_mw"].sum() == pytest.approx(104.0)


def test_parse_schema_change_unmapped_type_and_bad_dates_fail_explicitly():
    base = pd.read_csv(pd.io.common.BytesIO(siga_csv(PLANTS)), sep=";", decimal=",")
    with pytest.raises(ac.AneelFallbackError, match="schema changed"):
        ac.parse_siga_plants(base.drop(columns=["SigTipoGeracao"]))
    with pytest.raises(ac.AneelFallbackError, match="Unmapped generation types"):
        ac.parse_siga_plants(pd.concat([base, pd.DataFrame([("XYZ", "Operação", "2020-01-01", 10)], columns=base.columns)]))
    with pytest.raises(ac.AneelFallbackError, match="DatEntradaOperacao"):
        ac.parse_siga_plants(base.assign(DatEntradaOperacao=[None] + list(base.DatEntradaOperacao[1:])))


def test_capacity_by_source_is_cumulative_flagged_and_rejects_too_early_years():
    plants = ac.parse_siga_plants(pd.read_csv(pd.io.common.BytesIO(siga_csv(PLANTS)), sep=";", decimal=","))
    table = ac.capacity_by_source(plants, [2020, 2022])
    solar = table[table.source_type == "solar"].set_index("year").installed_capacity_mw
    assert solar[2020] == pytest.approx(2.0) and solar[2022] == pytest.approx(7.0)
    for year in (2020, 2022):
        assert table[table.year == year].capacity_share_pct.sum() == pytest.approx(100.0)
    assert (table.quantity == "installed_capacity_mw").all() and not table.is_generation_energy.any()
    with pytest.raises(ac.AneelFallbackError, match="precede"):
        ac.capacity_by_source(plants, [1970])


def test_fallback_requires_an_explicit_reason():
    with pytest.raises(ValueError, match="reason"):
        ac.fetch_generation_fallback([2020], reason="  ", targets=TARGETS)


@responses.activate
def test_fetch_generation_fallback_logs_invocation_and_writes_flagged_output(tmp_database, caplog):
    _mock_search(responses, [*OTHERS, SIGA])
    responses.add(responses.GET, CSV_URL, body=siga_csv(PLANTS))
    with caplog.at_level(logging.WARNING, logger=ac.logger.name):
        _table, choice = ac.fetch_generation_fallback([2020, 2022], reason="ONS CoverageError on generation_by_source (test)", targets=TARGETS, write=True)
    assert "ANEEL FALLBACK INVOKED" in caplog.text and "ONS CoverageError" in caplog.text
    assert "INSTALLED CAPACITY" in caplog.text and choice.score == 7
    out = pd.read_parquet(tmp_database / "interim" / ac.OUTPUT_FILENAME)
    assert len(out) == 8 and not out.is_generation_energy.any()
    assert (tmp_database / "raw" / "aneel" / "generation_fallback" / "siga-empreendimentos-geracao-diario.csv").exists()


def test_fallback_is_not_wired_into_the_default_pipeline():
    src = Path(ac.__file__).with_name("data_ingestion.py").read_text(encoding="utf-8")
    assert "aneel_client" not in src and "fetch_generation_fallback" not in src


@pytest.mark.integration
def test_live_aneel_fallback(tmp_path, monkeypatch):
    """Real network call against ANEEL CKAN. Run manually: pytest -m integration"""
    from curtailmit import data_ingestion as di

    monkeypatch.setattr(ac, "get_raw_dir", lambda sub: (tmp_path / sub).mkdir(parents=True, exist_ok=True) or tmp_path / sub)
    table, choice = ac.fetch_generation_fallback([2020, 2024], reason="integration test", targets=di.load_acquisition_targets())
    assert choice.package_id == "siga-sistema-de-informacoes-de-geracao-da-aneel"
    solar = table[table.source_type == "solar"].set_index("year").installed_capacity_mw
    assert 3_000 < solar[2020] < 4_000 and 15_000 < solar[2024] < 20_000  # D14 corroborating context: ~3.3 GW and ~17.2 GW
