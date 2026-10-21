"""Task 4 tests: ONS reason-code classification (D5/D6). All network calls are mocked with `responses`."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd
import pytest
import responses

from curtailmit import ons_classification as oc
from curtailmit.ons_client import CkanClient
from curtailmit.validation import ClassificationFlag, ValidationError, attach_classification_flag, validate_classification_propagation

BASE = "https://dados.ons.org.br/api/3/action"
DICT_URLS = {"wind": "https://files.test/dict_wind.json", "solar": "https://files.test/dict_solar.json"}
PACKAGES = {"wind": "restricao_coff_eolica_usi", "solar": "restricao_coff_fotovoltaica"}

# Verbatim shape of the live ONS description: some dashes/accents arrive as U+FFFD replacement characters.
LIVE_DESCRIPTION = (
    "C�digo da Raz�o da Restri��o, podendo ser: REL � Raz�o de indisponibilidade externa (el�trica). "
    "CNF � Raz�o de atendimento a requisitos de confiabilidade. ENE � Raz�o energ�tica PAR - Restri��o indicada no parecer de acesso"
)

CLS_CFG = {
    "mapping": {"Razao Energetica": "DEB", "Confiabilidade": "REB", "Indisponibilidade Externa": "EUB"},
    "dictionary_keywords": {"Razao Energetica": ["energ"], "Confiabilidade": ["confiabilidade"], "Indisponibilidade Externa": ["indisponibilidade externa"]},
}
TARGETS = {
    "classification": CLS_CFG,
    "ons": {"ckan_base_url": BASE, "packages": {"curtailment_wind": {"package_id": PACKAGES["wind"]}, "curtailment_solar": {"package_id": PACKAGES["solar"]}}},
}


def _dictionary_json(description: str | None = LIVE_DESCRIPTION) -> bytes:
    entries = [{"descricao": "Nome da Usina", "codigo": "nom_usina"}]
    if description is not None:
        entries.append({"descricao": description, "codigo": "cod_razaorestricao"})
    return json.dumps({"titulo": "dict", "dicionario_simplificado": entries}, ensure_ascii=False).encode("utf-8")


def _interim(rows: list[tuple]) -> pd.DataFrame:
    ts = pd.date_range("2024-05-01", periods=len(rows), freq="30min")
    return pd.DataFrame({
        "timestamp": ts, "date": ts.date, "usina": "U1",
        "curtailed_energy_mwh": [r[2] for r in rows],
        "reason_category": pd.array([r[1] for r in rows], dtype="string"),
        "source": [r[0] for r in rows],
    })


@pytest.fixture(autouse=True)
def tmp_database(tmp_path, monkeypatch):
    def raw_dir(sub: str) -> Path:
        path = tmp_path / "raw" / sub
        path.mkdir(parents=True, exist_ok=True)
        return path

    def sub_dir(name: str):
        def _dir() -> Path:
            path = tmp_path / name
            path.mkdir(parents=True, exist_ok=True)
            return path
        return _dir

    monkeypatch.setattr(oc, "get_raw_dir", raw_dir)
    monkeypatch.setattr(oc, "get_interim_dir", sub_dir("interim"))
    monkeypatch.setattr(oc, "get_processed_dir", sub_dir("processed"))
    return tmp_path


def _mock_packages(rsps, with_dictionary=(True, True), description: str | None = LIVE_DESCRIPTION) -> None:
    for (source, pkg), has_dict in zip(PACKAGES.items(), with_dictionary):
        resources = [{"id": f"{source}-data", "name": "Restricoes-2024-05", "format": "CSV", "url": "https://files.test/x.csv"}]
        if has_dict:
            resources.append({"id": f"{source}-dict", "name": "Dicionário de Dados Json", "format": "JSON", "url": DICT_URLS[source]})
            rsps.add(responses.GET, DICT_URLS[source], body=_dictionary_json(description))
        rsps.add(responses.GET, f"{BASE}/package_show", match=[responses.matchers.query_param_matcher({"id": pkg})],
                 json={"success": True, "result": {"name": pkg, "title": "t", "resources": resources}})


def _run(tmp_database, rows) -> dict:
    path = tmp_database / "interim" / "ons_curtailment_raw.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    _interim(rows).to_parquet(path, index=False)
    return oc.classify_ons_curtailment(targets=TARGETS, interim_path=path)


ROWS = [
    ("wind", "CNF", 10.0), ("wind", "REL", 4.0), ("wind", "ENE", 2.0), ("wind", "PAR", 1.0), ("wind", None, 0.0),
    ("solar", "CNF", 5.0), ("solar", "ENE", 3.0),
]


def test_parse_dictionary_handles_replacement_characters():
    codes = oc.parse_reason_code_dictionary(LIVE_DESCRIPTION)
    assert list(codes) == ["REL", "CNF", "ENE", "PAR"]
    assert "indisponibilidade externa" in codes["REL"] and "confiabilidade" in codes["CNF"]


def test_parse_dictionary_handles_proper_dashes():
    codes = oc.parse_reason_code_dictionary("podendo ser: REL – Razão de indisponibilidade externa. CNF – Razão de confiabilidade.")
    assert list(codes) == ["REL", "CNF"]


def test_crosswalk_is_derived_from_dictionary_text_and_leaves_par_unmapped():
    cw = oc.derive_code_crosswalk(oc.parse_reason_code_dictionary(LIVE_DESCRIPTION), CLS_CFG)
    assert cw == {"REL": "Indisponibilidade Externa", "CNF": "Confiabilidade", "ENE": "Razao Energetica", "PAR": None}


def test_crosswalk_ambiguous_text_fails():
    with pytest.raises(oc.ClassificationError, match="several"):
        oc.derive_code_crosswalk({"XXX": "confiabilidade energetica"}, CLS_CFG)


@responses.activate
def test_classified_branch_maps_codes_and_keeps_eub_separate(tmp_database, caplog):
    _mock_packages(responses)
    with caplog.at_level(logging.INFO, logger=oc.logger.name):
        result = _run(tmp_database, ROWS)

    assert result["classification_available"] is True
    df = pd.read_parquet(result["classified_path"])
    by_code = df.groupby(df.reason_category.astype("string").fillna("(none)"), observed=True).deb_reb_eub.first()
    assert by_code["CNF"] == "REB" and by_code["ENE"] == "DEB" and by_code["REL"] == "EUB"
    assert pd.isna(by_code["PAR"]) and pd.isna(by_code["(none)"])  # never forced into a category
    assert df.classification_available.all()
    assert result["energy_mwh_by_category"] == {"REB": 15.0, "DEB": 5.0, "EUB": 4.0, "(none)": 1.0}
    assert result["unclassified_energy_share"] == pytest.approx(1 / 25)
    assert "crosswalk PAR -> UNMAPPED" in caplog.text

    flag = json.loads(Path(result["flag_path"]).read_text(encoding="utf-8"))
    assert flag["classification_available"] is True and flag["reason"] and flag["checked_at_utc"]


@responses.activate
def test_aggregate_only_branch_sets_flag_false_and_leaks_no_classified_field(tmp_database, caplog):
    _mock_packages(responses, with_dictionary=(False, False))
    with caplog.at_level(logging.WARNING, logger=oc.logger.name):
        result = _run(tmp_database, ROWS)

    assert result["classification_available"] is False
    df = pd.read_parquet(result["classified_path"])
    assert oc.CLASSIFIED_COLUMN not in df.columns
    assert not df.classification_available.any()
    assert df.curtailed_energy_mwh.sum() == pytest.approx(25.0)  # aggregate fully usable
    flag = json.loads(Path(result["flag_path"]).read_text(encoding="utf-8"))
    assert flag["classification_available"] is False
    assert "wind" in flag["reason"] and "solar" in flag["reason"] and "data-dictionary" in flag["reason"]
    assert "Classification unavailable" in caplog.text
    validate_classification_propagation(df.drop(columns=["timestamp", "date"]).head(3).to_dict("records"))  # still passes


@responses.activate
def test_dictionary_not_describing_the_field_is_unavailable(tmp_database):
    _mock_packages(responses, description=None)
    result = _run(tmp_database, ROWS)
    assert result["classification_available"] is False
    assert "cod_razaorestricao" in result["reason"]


@responses.activate
def test_dictionary_without_any_d5_match_is_unavailable(tmp_database):
    _mock_packages(responses, description="podendo ser: AAA - algo sem relacao. BBB - outra coisa.")
    result = _run(tmp_database, [("wind", "AAA", 1.0), ("solar", "BBB", 1.0)])
    assert result["classification_available"] is False and "match a D5 label" in result["reason"]


@responses.activate
def test_one_source_unclassifiable_makes_the_whole_flag_false(tmp_database):
    _mock_packages(responses, with_dictionary=(True, False))
    result = _run(tmp_database, ROWS)
    assert result["classification_available"] is False
    assert oc.CLASSIFIED_COLUMN not in pd.read_parquet(result["classified_path"]).columns  # no partial leak


@responses.activate
def test_undocumented_code_is_schema_drift_and_raises(tmp_database):
    _mock_packages(responses)
    with pytest.raises(oc.ClassificationError, match="ZZZ"):
        _run(tmp_database, ROWS + [("wind", "ZZZ", 1.0)])


def test_guard_rejects_deb_reb_eub_field_on_unavailable_records():
    flag = ClassificationFlag(False, "no dictionary")
    with pytest.raises(ValidationError):
        attach_classification_flag({"deb_reb_eub": "DEB"}, flag)
    with pytest.raises(ValidationError):
        validate_classification_propagation([{"classification_available": False, "deb_reb_eub": "REB"}])


@responses.activate
def test_check_classification_availability_wrapper(tmp_database, monkeypatch):
    from curtailmit import data_ingestion as di

    _mock_packages(responses)
    path = tmp_database / "interim" / "ons_curtailment_raw.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    _interim(ROWS).to_parquet(path, index=False)
    monkeypatch.setattr(di, "load_acquisition_targets", lambda *a, **k: TARGETS)
    discovered = {"interim_path": str(path), "packages": [{"source": s, "resolved_package_id": p} for s, p in PACKAGES.items()]}
    assert di.check_classification_availability({}, discovered) is True


@pytest.mark.integration
def test_live_dictionary_crosswalk(tmp_path, monkeypatch):
    """Real network call against ONS CKAN. Run manually: pytest -m integration"""
    from curtailmit import data_ingestion as di

    monkeypatch.setattr(oc, "get_raw_dir", lambda sub: (tmp_path / sub).mkdir(parents=True, exist_ok=True) or tmp_path / sub)
    targets = di.load_acquisition_targets()
    client = CkanClient(targets["ons"]["ckan_base_url"])
    for source, key in oc._SOURCE_KEYS.items():
        codes = oc.fetch_reason_code_dictionary(client, targets["ons"]["packages"][key]["package_id"], source)
        assert codes, f"{source}: dictionary missing"
        cw = oc.derive_code_crosswalk(codes, targets["classification"])
        assert cw.get("REL") == "Indisponibilidade Externa" and cw.get("CNF") == "Confiabilidade"
