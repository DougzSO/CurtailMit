"""Task 5 - MCTI emission-factor acquisition (D8 average factor, D9 marginal OM/BM, D12 combined margin).

Source: the MCTI "fatores de emissao" landing page. There is no API: the page is scraped for <a href> links to .xlsx
files (BeautifulSoup) and files are selected by file-name pattern and by year substring - never by a guessed URL.

- Average SIN factor (D8): ONE consolidated `Inventario_*.xlsx` (sheet `inventario-todos`), monthly + published annual.
- Margins (D9): ONE file per year (`Despacho_*`, `Margemdeconstruo_*` or the older long "...metodo-da-analise-de-despacho..."
  names). Sheet name is NOT stable (MDL / "MDL 2022" / Planilha1), so the layout is anchored on its labels instead:
  "MARGEM DE CONSTRUCAO" (annual BM on the row that starts with the year) and "MARGEM DE OPERACAO" (12 monthly OM values
  under the month header). Values to the right of the first block are "previously published (with errors)" and ignored.
- Annual OM is DERIVED (simple mean of the 12 monthly values, emission_factors.derive_annual_om_from_monthly) and CM is
  COMPUTED (0.5 OM + 0.5 BM, D12). Both are flagged as derived in every output; only BM and the average factor are published.

Failures are explicit: no file for a required year, a layout that no longer matches, or incomplete coverage raise. If the
landing page itself cannot be used (blocked / layout changed) the manual-ingestion fallback (manual_ingestion.py) is the only
remaining path; it raises an instructional error naming the file to place, and its use is recorded in the result.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup

from curtailmit.acquisition import fetch_and_cache
from curtailmit.emission_factors import compute_combined_margin, derive_annual_om_from_monthly
from curtailmit.manual_ingestion import ManualIngestionRequired, load_manually_placed_file
from curtailmit.paths import get_processed_dir, get_raw_dir
from curtailmit.validation import validate_mcti_factor_coverage

logger = logging.getLogger(__name__)

AVERAGE_FILENAME = "mcti_average_factor.parquet"
AVERAGE_ANNUAL_FILENAME = "mcti_average_factor_annual.parquet"
MARGIN_FILENAME = "mcti_margin_factors.parquet"
LEGACY_DOMAIN = "antigo.mctic.gov.br"
_MONTHS = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")
_EXCEL_SUFFIXES = (".xlsx", ".xls", ".xlsm")
# Probed 2026-10-21: gov.br serves a stripped page (no spreadsheet links) to python-requests' default User-Agent but the
# full page to any explicit one. We identify ourselves honestly instead of impersonating a browser.
USER_AGENT = "curtailmit/0.1 (research data pipeline)"


class McTiStructureError(RuntimeError):
    """Raised when the MCTI page or a workbook no longer matches the documented structure."""


@dataclass(frozen=True)
class McTiLink:
    text: str
    url: str

    @property
    def filename(self) -> str:
        return unquote(Path(urlparse(self.url).path).name)

    @property
    def is_legacy(self) -> bool:
        return urlparse(self.url).netloc == LEGACY_DOMAIN


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode().lower().strip()


# ---------------------------------------------------------------- landing page


def discover_excel_links(landing_url: str, html: str | None = None) -> list[McTiLink]:
    """All spreadsheet links on the landing page (absolute URLs). Raises McTiStructureError if there are none."""
    if html is None:
        resp = requests.get(landing_url, headers={"User-Agent": USER_AGENT}, timeout=60)
        resp.raise_for_status()
        html = resp.text
    soup = BeautifulSoup(html, "lxml")
    seen: dict[str, McTiLink] = {}
    for a in soup.find_all("a", href=True):
        url = urljoin(landing_url, a["href"].strip())
        if urlparse(url).path.lower().endswith(_EXCEL_SUFFIXES):
            seen.setdefault(url, McTiLink(a.get_text(" ", strip=True), url))
    links = list(seen.values())
    if not links:
        raise McTiStructureError(f"No .xlsx/.xls links found on {landing_url} - page layout changed, or the server returned a stripped page (access blocked / User-Agent).")
    logger.info("Landing page %s: %d spreadsheet links discovered", landing_url, len(links))
    for link in links:
        logger.info("  link: %s | %s%s", link.filename, link.url, " [legacy domain]" if link.is_legacy else "")
    return links


def _year_in(text: str, year: int) -> bool:
    return re.search(rf"(?<!\d){year}(?!\d)", text) is not None


def select_average_file(links: list[McTiLink], file_prefix: str) -> McTiLink:
    prefix = _norm(file_prefix)
    matches = [link for link in links if _norm(link.filename).startswith(prefix)]
    if len(matches) != 1:
        raise McTiStructureError(f"Expected exactly one '{file_prefix}*' file on the landing page, found {len(matches)}: {[m.filename for m in matches]}")
    return matches[0]


def select_margin_file(links: list[McTiLink], year: int, name_patterns: list[str]) -> McTiLink:
    """The file for `year`: name matches a margin pattern and the year appears as a token in the href or link text.

    Legacy-domain duplicates are only used if no current-domain file exists. More than one remaining candidate is
    ambiguous and fails explicitly (no guessing).
    """
    patterns = [_norm(p) for p in name_patterns]
    candidates = [
        link for link in links
        if any(p in _norm(unquote(urlparse(link.url).path)) for p in patterns) and (_year_in(link.url, year) or _year_in(link.text, year))
    ]
    if not candidates:
        raise McTiStructureError(f"No margin (OM/BM) file found on the landing page for year {year} (patterns={name_patterns}).")
    current = [c for c in candidates if not c.is_legacy]
    chosen_pool = current or candidates
    if len(chosen_pool) > 1:
        raise McTiStructureError(f"Ambiguous margin files for {year}: {[c.url for c in chosen_pool]} - refusing to guess.")
    if current and len(candidates) > len(current):
        logger.info("[%d] legacy-domain duplicate(s) ignored: %s", year, [c.filename for c in candidates if c.is_legacy])
    if not current:
        logger.warning("[%d] only a legacy-domain file exists: %s", year, chosen_pool[0].url)
    return chosen_pool[0]


# ---------------------------------------------------------------- download + workbook parsing


def _download_excel(url: str, dest: Path, use_cache: bool) -> Path:
    """fetch_and_cache with our User-Agent, then verify it is really a spreadsheet.

    Probed 2026-10-21: with python-requests' default User-Agent gov.br answers HTTP 200 with an HTML page instead of the
    .xlsx, which would otherwise be saved under an .xlsx name and fail confusingly later.
    """
    path = fetch_and_cache(url, dest, use_cache=use_cache, headers={"User-Agent": USER_AGENT})
    magic = Path(path).read_bytes()[:4]
    if magic[:2] != b"PK" and magic != b"\xd0\xcf\x11\xe0":  # xlsx = zip, legacy xls = OLE2
        raise McTiStructureError(f"{url} did not return a spreadsheet (first bytes {magic!r}); the server likely returned an HTML/blocked page.")
    return Path(path)


def _read_sheet(path: Path, preferred_sheet: str, sheet_prefix_ok: bool = True) -> pd.DataFrame:
    """Read the sheet as a raw grid (header=None). Sheet names drift, so fall back (with a WARNING) to the first sheet."""
    book = pd.ExcelFile(path)
    target = _norm(preferred_sheet)
    names = book.sheet_names
    chosen = next((n for n in names if _norm(n) == target), None) or (next((n for n in names if _norm(n).startswith(target)), None) if sheet_prefix_ok else None)
    if chosen is None:
        chosen = names[0]
        logger.warning("%s: sheet %r not found (sheets=%s) - using %r; layout is verified by its labels instead", path.name, preferred_sheet, names, chosen)
    return book.parse(chosen, header=None)


def _as_float(value) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip().replace(",", "."))
    except ValueError:
        return None


def _month_columns(header_row: list) -> list[int]:
    """Column index of the first occurrence of each month name, in calendar order (later blocks are 'previously published')."""
    cols: list[int] = []
    for month in _MONTHS:
        idx = next((i for i, v in enumerate(header_row) if isinstance(v, str) and _norm(v).startswith(month)), None)
        if idx is None:
            return []
        cols.append(idx)
    return cols


def parse_average_grid(grid: pd.DataFrame) -> tuple[pd.DataFrame, dict[int, float]]:
    """Inventario sheet -> (monthly [year, month, factor_tco2_per_mwh], {year: published annual value}).

    Layout: per year a block whose first row has the year in column 0 and 'MES' in column 2, followed by the month header row
    (the published annual factor sits in column 14 of that header row) and the row of 12 monthly values.
    """
    rows = grid.values.tolist()
    monthly: list[dict] = []
    annual: dict[int, float] = {}
    for i, row in enumerate(rows):
        year = _as_float(row[0]) if row else None
        if year is None or not float(year).is_integer() or not (1990 <= year <= 2100) or "mes" not in _norm(str(row[2] if len(row) > 2 else "")):
            continue
        year = int(year)
        if i + 2 >= len(rows):
            raise McTiStructureError(f"Inventario block for {year} is truncated.")
        header, values = rows[i + 1], rows[i + 2]
        cols = _month_columns(header)
        if not cols:
            raise McTiStructureError(f"Inventario block for {year}: month header row not found (got {header[:15]}).")
        annual_value = _as_float(header[14]) if len(header) > 14 else None
        if annual_value is not None:
            annual[year] = annual_value
        for month_no, col in enumerate(cols, start=1):
            value = _as_float(values[col]) if col < len(values) else None
            if value is not None:
                monthly.append({"year": year, "month": month_no, "factor_tco2_per_mwh": value})
    if not monthly:
        raise McTiStructureError("Inventario sheet: no year blocks parsed - layout changed.")
    return pd.DataFrame(monthly), annual


@dataclass(frozen=True)
class MarginYear:
    year: int
    bm: float | None
    om_monthly: list[float | None]

    @property
    def complete(self) -> bool:
        return self.bm is not None and all(v is not None for v in self.om_monthly)


def parse_margin_grid(grid: pd.DataFrame, year: int) -> MarginYear:
    """Margin workbook -> BM (annual) and 12 monthly OM values for `year`, anchored on the section labels."""
    rows = grid.values.tolist()

    def find(label: str) -> int:
        for i, row in enumerate(rows):
            if any(isinstance(v, str) and label in _norm(v) for v in row):
                return i
        raise McTiStructureError(f"Margin workbook for {year}: label '{label}' not found - layout changed.")

    bm_label, om_label = find("margem de constru"), find("margem de opera")
    bm_row = next((r for r in rows[bm_label + 1:om_label] if (_as_float(r[0]) == year)), None)
    if bm_row is None:
        raise McTiStructureError(f"Margin workbook: no row starting with year {year} under the build-margin label.")
    # The current BM is the FIRST non-empty cell after the year; if that is text (e.g. "will be available after year end") the
    # year has no BM yet - a later numeric cell would be a "previously published (with errors)" value and must not be used.
    first_cell = next((c for c in bm_row[1:] if not (c is None or (isinstance(c, float) and pd.isna(c)))), None)
    bm = _as_float(first_cell)
    header_idx = next((i for i in range(om_label + 1, len(rows)) if _month_columns(rows[i])), None)
    if header_idx is None or header_idx + 1 >= len(rows):
        raise McTiStructureError(f"Margin workbook for {year}: monthly OM header not found under the operating-margin label.")
    year_row = next((r for r in rows[om_label + 1:header_idx] if _as_float(r[0]) is not None), None)
    if year_row is not None and _as_float(year_row[0]) != year:
        raise McTiStructureError(f"Margin workbook says year {_as_float(year_row[0])} in its OM block, expected {year}.")
    cols = _month_columns(rows[header_idx])
    values = rows[header_idx + 1]
    om = [_as_float(values[c]) if c < len(values) else None for c in cols]
    return MarginYear(year=year, bm=bm, om_monthly=om)


# ---------------------------------------------------------------- acquisition


def _landing_links(landing_url: str, links: list[McTiLink] | None) -> list[McTiLink]:
    return links if links is not None else discover_excel_links(landing_url)


def discover_average_factor_file(landing_url: str, cfg: dict | None = None, links: list[McTiLink] | None = None, use_cache: bool = False) -> dict:
    """Find, download and parse the single consolidated Inventario_*.xlsx (D8)."""
    cfg = cfg or {}
    link = select_average_file(_landing_links(landing_url, links), cfg.get("file_prefix", "Inventario_"))
    dest = _download_excel(link.url, get_raw_dir("mcti/average_emission_factor") / link.filename, use_cache)
    monthly, annual = parse_average_grid(_read_sheet(dest, cfg.get("sheet_name", "inventário-todos")))
    logger.info("average factor: %s -> %d monthly values, years %d-%d, %d published annual values", link.filename, len(monthly), monthly.year.min(), monthly.year.max(), len(annual))
    return {"url": link.url, "path": str(dest), "monthly": monthly, "annual": annual, "manual": False}


def discover_margin_factor_file(landing_url: str, year: int, cfg: dict | None = None, links: list[McTiLink] | None = None, use_cache: bool = False) -> dict:
    """Find, download and parse the per-year OM/BM workbook for `year` (D9). Annual OM is derived, CM computed."""
    cfg = cfg or {}
    patterns = cfg.get("file_name_patterns", ["despacho", "margemdeconstru", "analise-de-despacho"])
    link = select_margin_file(_landing_links(landing_url, links), year, patterns)
    dest = _download_excel(link.url, get_raw_dir("mcti/margin_factors") / f"{year}_{link.filename}", use_cache)
    parsed = parse_margin_grid(_read_sheet(dest, cfg.get("sheet_name", "MDL")), year)
    logger.info("[%d] margin file %s: BM=%s, monthly OM=%s", year, link.filename, parsed.bm, parsed.om_monthly)
    return {"url": link.url, "path": str(dest), "parsed": parsed, "manual": False}


def margin_row(parsed: MarginYear, source_url: str, manual: bool = False) -> dict:
    """One output row. OM (annual) and CM are derived/computed and flagged as such; BM is MCTI-published."""
    om_annual = derive_annual_om_from_monthly(parsed.om_monthly)
    cm = compute_combined_margin(om_annual, parsed.bm)
    return {
        "year": parsed.year, "om": om_annual, "bm": parsed.bm, "cm": cm.cm,
        "om_is_derived": True, "cm_is_derived": True, "bm_is_published": True,
        "om_derivation": "simple mean of 12 MCTI monthly OM values", "cm_methodology": cm.methodology_reference,
        "source_url": source_url, "manual_ingestion": manual,
    }


_MANUAL_AVERAGE_INSTRUCTIONS = (
    "Download the consolidated 'Inventario_*.xlsx' (average SIN emission factor, sheet 'inventario-todos') from the MCTI page "
    "{landing} and place it at {path}. This is a declared manual-ingestion limitation and will be reported in the data-quality report."
)
_MANUAL_MARGIN_INSTRUCTIONS = (
    "Download the OM/BM workbook for {year} (Despacho_*/Margemdeconstruo_* file) from the MCTI page {landing} and place it at {path}. "
    "This is a declared manual-ingestion limitation and will be reported in the data-quality report."
)


def acquire_mcti_factors(targets: dict | None = None, use_cache: bool = False, links: list[McTiLink] | None = None) -> dict:
    """Task 5 entry point -> processed/mcti_average_factor(.parquet|_annual.parquet) and processed/mcti_margin_factors.parquet."""
    from curtailmit.data_ingestion import load_acquisition_targets  # local import avoids a module cycle

    targets = targets or load_acquisition_targets()
    cfg = targets["mcti"]
    landing = cfg["landing_page"]
    start, end = (int(y) for y in cfg["required_years"])
    required = list(range(start, end + 1))
    avg_cfg, margin_cfg = cfg["average_sin_factor"], cfg["operating_margin_build_margin"]

    manual_used: list[str] = []
    try:
        links = _landing_links(landing, links)
    except (requests.RequestException, McTiStructureError) as exc:
        logger.warning("MCTI landing page unusable (%s) - MANUAL INGESTION is the only remaining path (declared limitation).", exc)
        links = None

    # ---- average factor (D8)
    manual_dir = get_raw_dir("mcti/manual")
    if links is not None:
        avg = discover_average_factor_file(landing, avg_cfg, links, use_cache=use_cache)
    else:
        path = manual_dir / "Inventario_manual.xlsx"
        frame = load_manually_placed_file(path, _MANUAL_AVERAGE_INSTRUCTIONS.format(landing=landing, path=path), reader="excel", read_kwargs={"sheet_name": 0, "header": None})
        monthly, annual = parse_average_grid(frame)
        avg = {"url": str(path), "path": str(path), "monthly": monthly, "annual": annual, "manual": True}
        manual_used.append(str(path))
    monthly, annual = avg["monthly"], avg["annual"]
    complete_years = sorted(y for y, g in monthly.groupby("year") if g.month.nunique() == 12)
    partial = sorted(set(monthly.year) - set(complete_years))
    if partial:
        logger.warning("average factor: partial years %s have fewer than 12 monthly values and are not used for annual coverage", partial)
    validate_mcti_factor_coverage(complete_years, required)  # ValidationError names the missing years
    logger.info("average factor coverage OK: complete years %s..%s cover required %s..%s", complete_years[0], complete_years[-1], start, end)

    # ---- margins (D9/D12)
    # Later years present in the average series (e.g. an in-progress year) are tried too, but only used if complete.
    extra = range(end + 1, int(monthly.year.max()) + 1) if links is not None else range(0)
    candidate_years = sorted({*required, *extra})
    rows: list[dict] = []
    skipped: dict[int, str] = {}
    for year in candidate_years:
        try:
            if links is not None:
                result = discover_margin_factor_file(landing, year, margin_cfg, links, use_cache=use_cache)
                parsed, url, is_manual = result["parsed"], result["url"], False
            else:
                path = manual_dir / f"Despacho_{year}_manual.xlsx"
                frame = load_manually_placed_file(path, _MANUAL_MARGIN_INSTRUCTIONS.format(year=year, landing=landing, path=path), reader="excel", read_kwargs={"sheet_name": 0, "header": None})
                parsed, url, is_manual = parse_margin_grid(frame, year), str(path), True
                manual_used.append(url)
        except ManualIngestionRequired:
            raise
        except McTiStructureError as exc:
            if year in required:
                raise
            skipped[year] = str(exc)
            logger.warning("[%d] beyond the required window and not available: %s", year, exc)
            continue
        if not parsed.complete:
            reason = f"incomplete (BM={parsed.bm}, monthly OM present={sum(v is not None for v in parsed.om_monthly)}/12)"
            if year in required:
                raise McTiStructureError(f"[{year}] margin data {reason} but the year is required ({start}-{end}).")
            skipped[year] = reason
            logger.warning("[%d] not used: %s", year, reason)
            continue
        rows.append(margin_row(parsed, url, is_manual))
    margins = pd.DataFrame(rows)
    validate_mcti_factor_coverage(margins["year"].tolist() if len(margins) else [], required)

    processed = get_processed_dir()
    monthly.to_parquet(processed / AVERAGE_FILENAME, index=False)
    annual_df = pd.DataFrame({"year": sorted(annual), "factor_tco2_per_mwh": [annual[y] for y in sorted(annual)]})
    annual_df["source"] = "mcti_published_annual"
    annual_df.to_parquet(processed / AVERAGE_ANNUAL_FILENAME, index=False)
    margins.to_parquet(processed / MARGIN_FILENAME, index=False)
    logger.info("Wrote MCTI factors: %s, %s, %s", AVERAGE_FILENAME, AVERAGE_ANNUAL_FILENAME, MARGIN_FILENAME)
    if manual_used:
        logger.warning("MANUAL INGESTION used for: %s - must be declared in the data-quality report", manual_used)
    return {
        "average_path": str(processed / AVERAGE_FILENAME),
        "average_annual_path": str(processed / AVERAGE_ANNUAL_FILENAME),
        "margin_path": str(processed / MARGIN_FILENAME),
        "average_years": complete_years,
        "average_partial_years": partial,
        "margin_years": margins["year"].tolist(),
        "margin_skipped": skipped,
        "manual_ingestion_used": manual_used,
        "average_source_url": avg["url"],
    }


__all__ = ["McTiStructureError", "acquire_mcti_factors", "discover_average_factor_file", "discover_margin_factor_file"]
