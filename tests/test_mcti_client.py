"""Task 5 tests: MCTI emission-factor acquisition. All network calls are mocked with `responses`."""

from __future__ import annotations

import io
import logging
from pathlib import Path

import openpyxl
import pandas as pd
import pytest
import responses

from curtailmit import mcti_client as mc
from curtailmit.manual_ingestion import ManualIngestionRequired
from curtailmit.validation import ValidationError

LANDING = "https://www.gov.br/mcti/pt-br/acompanhe-o-mcti/sirene/dados-e-ferramentas/fatores-de-emissao"
FILES = LANDING + "/arquivo"
LEGACY = "https://antigo.mctic.gov.br/mctic/opencms/ciencia/SEPED/clima/arquivos/emissoes_co2"
MONTH_NAMES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]

CFG = {
    "mcti": {
        "landing_page": LANDING,
        "required_years": [2020, 2021],
        "average_sin_factor": {"sheet_name": "inventário-todos", "file_prefix": "Inventario_"},
        "operating_margin_build_margin": {"sheet_name": "MDL", "file_name_patterns": ["despacho", "margemdeconstru", "analise-de-despacho"]},
    }
}
OM = {2020: [0.5 + 0.01 * i for i in range(12)], 2021: [0.6] * 12}
BM = {2020: 0.10, 2021: 0.05}
AVG_ANNUAL = {2019: 0.075, 2020: 0.0617, 2021: 0.1263}


def margin_xlsx(year: int, bm: float | None, om: list[float | None], sheet: str = "MDL", old_block: bool = True, string_first: bool = False) -> bytes:
    """Workbook with the real layout: BM on the year row, OM months below the header, plus an 'old (with errors)' block."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    ws.cell(1, 6, "MARGEM DE CONSTRUÇÃO")
    ws.cell(3, 6, "Fator de Emissão Médio (tCO2/MWh) - ANUAL")
    ws.cell(4, 1, year)
    if bm is not None:
        ws.cell(4, 7, bm)
    else:
        ws.cell(4, 3, "Este fator de emissão será disponibilizado após o fim do ano")
    if old_block:
        ws.cell(4, 17, 0.9999)  # previously published value (with error): must be ignored
    ws.cell(7, 6, "MARGEM DE OPERAÇÃO")
    ws.cell(9, 6, "Fator de Emissão Médio (tCO2/MWh) - MENSAL")
    ws.cell(10, 1, year)
    for i, name in enumerate(MONTH_NAMES):
        ws.cell(11, 3 + i, name)
        value = om[i]
        if value is not None:
            ws.cell(12, 3 + i, str(value) if (string_first and i == 0) else value)
    if old_block:
        ws.cell(11, 16, "Setembro")
        ws.cell(12, 16, 9.99)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def inventory_xlsx(blocks: dict[int, tuple[float | None, list[float | None]]]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "inventário-todos"
    row = 2
    for year, (annual, months) in blocks.items():
        ws.cell(row, 1, "Fator Médio Mensal (tCO2/MWh)")
        ws.cell(row, 15, "Fator Médio Anual (tCO2/MWh)")
        ws.cell(row + 1, 1, year)
        ws.cell(row + 1, 3, "MÊS")
        ws.cell(row + 1, 15, f"ANO - {year}")
        for i, name in enumerate(MONTH_NAMES):
            ws.cell(row + 2, 3 + i, name)
            if months[i] is not None:
                ws.cell(row + 3, 3 + i, months[i])
        if annual is not None:
            ws.cell(row + 2, 15, annual)
        row += 5
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def landing_html(hrefs: list[tuple[str, str]]) -> str:
    return "<html><body>" + "".join(f'<a href="{h}">{t}</a>' for t, h in hrefs) + '<a href="/other.pdf">doc</a></body></html>'


DEFAULT_LINKS = [
    ("Aqui", f"{FILES}/Inventario_2026_janset.xlsx"),
    ("Clique Aqui", f"{FILES}/Despacho_2021_jandez.xlsx"),
    ("", f"{LEGACY}/Despacho_2021_jan-a-jun.xlsx"),
    ("Clique Aqui", f"{LEGACY.replace('antigo.mctic.gov.br/mctic/opencms/ciencia/SEPED/clima/arquivos/emissoes_co2', 'www.gov.br/mcti/pt-br/acompanhe-o-mcti/cgcl/Banner')}/metodo-da-analise-de-despacho/fatores-de-emissao-de-co2-pela-geracao-de-energia-eletrica-no-sistema-interligado-nacional-do-brasil-ano-base-2020-com-correcoes.xlsx"),
    ("", f"{LEGACY}/Despacho_2020_dezembro_corrigido.xlsx"),
    ("Aqui", f"{FILES}/FE_simplesajustado_2025_web.xlsx"),
]
URL_2020 = DEFAULT_LINKS[3][1]


@pytest.fixture(autouse=True)
def tmp_database(tmp_path, monkeypatch):
    def raw_dir(sub: str) -> Path:
        path = tmp_path / "raw" / sub
        path.mkdir(parents=True, exist_ok=True)
        return path

    def processed_dir() -> Path:
        path = tmp_path / "processed"
        path.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr(mc, "get_raw_dir", raw_dir)
    monkeypatch.setattr(mc, "get_processed_dir", processed_dir)
    return tmp_path


def _mock_site(rsps, links=None, avg_blocks=None, files: dict[str, bytes] | None = None) -> None:
    links = DEFAULT_LINKS if links is None else links
    rsps.add(responses.GET, LANDING, body=landing_html(links), match=[responses.matchers.header_matcher({"User-Agent": mc.USER_AGENT})])
    blocks = avg_blocks or {2019: (0.075, [0.07] * 12), 2020: (0.0617, [0.06] * 12), 2021: (0.1263, [0.12] * 12), 2026: (None, [0.04] * 9 + [None] * 3)}
    rsps.add(responses.GET, f"{FILES}/Inventario_2026_janset.xlsx", body=inventory_xlsx(blocks))
    rsps.add(responses.GET, f"{FILES}/Despacho_2021_jandez.xlsx", body=(files or {}).get("2021", margin_xlsx(2021, BM[2021], OM[2021], sheet="Planilha1", old_block=False)))
    rsps.add(responses.GET, URL_2020, body=(files or {}).get("2020", margin_xlsx(2020, BM[2020], OM[2020], sheet="Planilha1", string_first=True)))
    rsps.add(responses.GET, f"{LEGACY}/Despacho_2021_jan-a-jun.xlsx", body=b"should-not-be-fetched")
    rsps.add(responses.GET, f"{LEGACY}/Despacho_2020_dezembro_corrigido.xlsx", body=b"should-not-be-fetched")


# ------------------------------------------------------------------ parsing


def test_parse_margin_grid_reads_bm_and_first_twelve_months_ignoring_old_block():
    grid = pd.read_excel(io.BytesIO(margin_xlsx(2020, 0.1, OM[2020], string_first=True)), header=None)
    parsed = mc.parse_margin_grid(grid, 2020)
    assert parsed.bm == pytest.approx(0.10)  # not the 0.9999 'previously published' value
    assert parsed.om_monthly == pytest.approx(OM[2020])  # string '0.5' coerced; not the 9.99 old value
    assert parsed.complete


def test_parse_margin_grid_incomplete_year_is_flagged_not_silently_filled():
    grid = pd.read_excel(io.BytesIO(margin_xlsx(2026, None, [0.4] * 9 + [None] * 3)), header=None)
    parsed = mc.parse_margin_grid(grid, 2026)
    assert parsed.bm is None and parsed.om_monthly[9:] == [None] * 3 and not parsed.complete


def test_parse_margin_grid_wrong_year_or_layout_fails_explicitly():
    grid = pd.read_excel(io.BytesIO(margin_xlsx(2020, 0.1, OM[2020])), header=None)
    with pytest.raises(mc.McTiStructureError, match="year 2021"):
        mc.parse_margin_grid(grid, 2021)
    with pytest.raises(mc.McTiStructureError, match="not found"):
        mc.parse_margin_grid(pd.DataFrame([["nothing", "here"]]), 2020)


def test_parse_average_grid_monthly_annual_and_partial_year():
    grid = pd.read_excel(io.BytesIO(inventory_xlsx({2025: (0.0461, [0.05] * 12), 2026: (None, [0.04] * 9 + [None] * 3)})), header=None)
    monthly, annual = mc.parse_average_grid(grid)
    assert annual == {2025: 0.0461}
    assert monthly.groupby("year").month.nunique().to_dict() == {2025: 12, 2026: 9}
    with pytest.raises(mc.McTiStructureError):
        mc.parse_average_grid(pd.DataFrame([["x"]]))


# ------------------------------------------------------------------ link selection


def _links(pairs) -> list[mc.McTiLink]:
    return [mc.McTiLink(t, u) for t, u in pairs]


def test_select_margin_file_prefers_current_domain_over_legacy():
    chosen = mc.select_margin_file(_links(DEFAULT_LINKS), 2021, CFG["mcti"]["operating_margin_build_margin"]["file_name_patterns"])
    assert chosen.filename == "Despacho_2021_jandez.xlsx" and not chosen.is_legacy


def test_select_margin_file_matches_year_as_a_token_not_a_substring():
    links = _links([("x", f"{FILES}/Despacho_20210_x.xlsx")])
    with pytest.raises(mc.McTiStructureError, match="No margin"):
        mc.select_margin_file(links, 2021, ["despacho"])


def test_select_margin_file_ambiguous_fails_instead_of_guessing():
    links = _links([("a", f"{FILES}/Despacho_2021_a.xlsx"), ("b", f"{FILES}/Margemdeconstruo_2021_b.xlsx")])
    with pytest.raises(mc.McTiStructureError, match="Ambiguous"):
        mc.select_margin_file(links, 2021, ["despacho", "margemdeconstru"])


def test_select_margin_file_uses_link_text_for_the_year():
    links = _links([("Despacho 2019", f"{FILES}/arquivo123.xlsx"), ("other", f"{FILES}/Inventario_2026.xlsx")])
    assert mc.select_margin_file(links, 2019, ["arquivo"]).filename == "arquivo123.xlsx"


def test_select_average_file_requires_exactly_one():
    assert mc.select_average_file(_links(DEFAULT_LINKS), "Inventario_").filename == "Inventario_2026_janset.xlsx"
    with pytest.raises(mc.McTiStructureError):
        mc.select_average_file(_links([("x", f"{FILES}/Despacho_2021.xlsx")]), "Inventario_")


# ------------------------------------------------------------------ acquisition


@responses.activate
def test_acquire_happy_path_derives_om_and_cm_and_flags_them(tmp_database, caplog):
    _mock_site(responses)
    with caplog.at_level(logging.INFO, logger=mc.logger.name):
        result = mc.acquire_mcti_factors(targets=CFG)

    margins = pd.read_parquet(result["margin_path"]).set_index("year")
    assert margins.index.tolist() == [2020, 2021]
    assert margins.loc[2020, "om"] == pytest.approx(sum(OM[2020]) / 12)  # derived: simple mean of 12 monthly values
    assert margins.loc[2020, "bm"] == pytest.approx(0.10)
    assert margins.loc[2020, "cm"] == pytest.approx(0.5 * margins.loc[2020, "om"] + 0.5 * 0.10)  # D12
    assert margins.om_is_derived.all() and margins.cm_is_derived.all() and margins.bm_is_published.all()
    assert not margins.manual_ingestion.any()

    monthly = pd.read_parquet(result["average_path"])
    assert set(monthly.columns) == {"year", "month", "factor_tco2_per_mwh"}
    annual = pd.read_parquet(result["average_annual_path"]).set_index("year")
    assert annual.loc[2020, "factor_tco2_per_mwh"] == pytest.approx(0.0617)
    assert result["average_partial_years"] == [2026] and 2026 in result["margin_skipped"]
    assert result["manual_ingestion_used"] == []
    assert not any("should-not-be-fetched" in c.request.url or "jan-a-jun" in c.request.url for c in responses.calls)
    assert "legacy-domain duplicate" in caplog.text and "partial years [2026]" in caplog.text
    assert (tmp_database / "raw" / "mcti" / "average_emission_factor" / "Inventario_2026_janset.xlsx").exists()


@responses.activate
def test_average_coverage_gap_raises_validation_error_naming_the_years():
    _mock_site(responses, avg_blocks={2019: (0.075, [0.07] * 12), 2021: (0.1263, [0.12] * 12)})  # 2020 absent
    with pytest.raises(ValidationError, match="2020"):
        mc.acquire_mcti_factors(targets=CFG)


@responses.activate
def test_missing_margin_file_for_a_required_year_fails_explicitly():
    links = [lnk for lnk in DEFAULT_LINKS if "2020" not in lnk[1]]
    _mock_site(responses, links=links)
    with pytest.raises(mc.McTiStructureError, match="2020"):
        mc.acquire_mcti_factors(targets=CFG)


@responses.activate
def test_incomplete_required_year_fails_explicitly():
    _mock_site(responses, files={"2020": margin_xlsx(2020, 0.1, OM[2020][:11] + [None], sheet="Planilha1")})
    with pytest.raises(mc.McTiStructureError, match="incomplete"):
        mc.acquire_mcti_factors(targets=CFG)


@responses.activate
def test_html_instead_of_spreadsheet_is_detected():
    _mock_site(responses)
    responses.replace(responses.GET, URL_2020, body="<!DOCTYPE html><html>blocked</html>")
    with pytest.raises(mc.McTiStructureError, match="did not return a spreadsheet"):
        mc.acquire_mcti_factors(targets=CFG)


# ------------------------------------------------------------------ manual-ingestion fallback


@responses.activate
def test_unusable_landing_page_without_placed_file_raises_actionable_error(tmp_database, caplog):
    responses.add(responses.GET, LANDING, body="<html><body>no links here</body></html>")
    with caplog.at_level(logging.WARNING, logger=mc.logger.name), pytest.raises(ManualIngestionRequired) as exc:
        mc.acquire_mcti_factors(targets=CFG)
    message = str(exc.value)
    assert "Inventario_manual.xlsx" in message and LANDING in message and "place it at" in message
    assert "MANUAL INGESTION" in caplog.text


@responses.activate
def test_manual_files_are_used_and_declared_when_landing_is_unusable(tmp_database):
    responses.add(responses.GET, LANDING, status=403, body="blocked")
    manual = tmp_database / "raw" / "mcti" / "manual"
    manual.mkdir(parents=True)
    (manual / "Inventario_manual.xlsx").write_bytes(inventory_xlsx({2020: (0.0617, [0.06] * 12), 2021: (0.1263, [0.12] * 12)}))
    (manual / "Despacho_2020_manual.xlsx").write_bytes(margin_xlsx(2020, BM[2020], OM[2020]))
    (manual / "Despacho_2021_manual.xlsx").write_bytes(margin_xlsx(2021, BM[2021], OM[2021]))
    result = mc.acquire_mcti_factors(targets=CFG)
    assert len(result["manual_ingestion_used"]) == 3
    assert pd.read_parquet(result["margin_path"]).manual_ingestion.all()


@pytest.mark.integration
def test_live_mcti_average_and_margin(tmp_path, monkeypatch):
    """Real network call against the MCTI landing page. Run manually: pytest -m integration"""
    from curtailmit import data_ingestion as di

    monkeypatch.setattr(mc, "get_raw_dir", lambda sub: (tmp_path / sub).mkdir(parents=True, exist_ok=True) or tmp_path / sub)
    cfg = di.load_acquisition_targets()["mcti"]
    links = mc.discover_excel_links(cfg["landing_page"])
    avg = mc.discover_average_factor_file(cfg["landing_page"], cfg["average_sin_factor"], links)
    assert {2020, 2021, 2022}.issubset(set(avg["monthly"].year)) and avg["annual"][2020] == pytest.approx(0.0617, abs=1e-3)
    margin = mc.discover_margin_factor_file(cfg["landing_page"], 2025, cfg["operating_margin_build_margin"], links)["parsed"]
    assert margin.complete and 0 < margin.bm < 0.2 and all(0 < v < 1 for v in margin.om_monthly)
