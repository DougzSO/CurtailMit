"""
Discovery probe round 4.

Not part of the pipeline. Run manually, paste the output back for analysis.

Goals:
1. Download and extract text from MCTI's emission factor technical note
   (NT_FE_jun25.pdf) to understand the real methodology and terminology
   before guessing which .xlsx file corresponds to average/OM/BM/CM.
2. Inspect sheet names and header rows of the most promising candidate
   .xlsx files without parsing full datasets.
"""

import io
import sys

import pandas as pd
import requests
from pypdf import PdfReader

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

PDF_URL = "https://www.gov.br/mcti/pt-br/acompanhe-o-mcti/cgcl/paginas/NT_FE_jun25.pdf"

XLSX_CANDIDATES = {
    "FE_simplesajustado_2025_web": "https://www.gov.br/mcti/pt-br/acompanhe-o-mcti/sirene/dados-e-ferramentas/fatores-de-emissao/arquivo/FE_simplesajustado_2025_web.xlsx",
    "Despacho_2025_jandez": "https://www.gov.br/mcti/pt-br/acompanhe-o-mcti/sirene/dados-e-ferramentas/fatores-de-emissao/arquivo/Despacho_2025_jandez_corrigidacomMO.xlsx",
    "Margemdeconstrucao_2023": "https://www.gov.br/mcti/pt-br/acompanhe-o-mcti/sirene/dados-e-ferramentas/fatores-de-emissao/arquivo/Margemdeconstruo_2023corrigido.xlsx",
    "Inventario_2026_janset": "https://www.gov.br/mcti/pt-br/acompanhe-o-mcti/sirene/dados-e-ferramentas/fatores-de-emissao/arquivo/Inventario_2026_janset.xlsx",
}


def print_header(title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def extract_pdf_text() -> None:
    print_header("MCTI - extracting text from NT_FE_jun25.pdf")
    try:
        resp = requests.get(PDF_URL, headers=BROWSER_HEADERS, timeout=60)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"Download failed: {exc}")
        return

    try:
        reader = PdfReader(io.BytesIO(resp.content))
    except Exception as exc:
        print(f"PDF parsing failed: {exc}")
        return

    print(f"Number of pages: {len(reader.pages)}")
    full_text = ""
    for page in reader.pages:
        full_text += page.extract_text() or ""

    print(f"Total extracted characters: {len(full_text)}")
    print("\n--- FULL TEXT (may be long) ---\n")
    print(full_text)


def inspect_xlsx_candidates() -> None:
    for label, url in XLSX_CANDIDATES.items():
        print_header(f"MCTI - inspecting workbook: {label}")
        try:
            resp = requests.get(url, headers=BROWSER_HEADERS, timeout=60)
            resp.raise_for_status()
        except requests.RequestException as exc:
            print(f"Download failed: {exc}")
            continue

        try:
            sheets = pd.read_excel(io.BytesIO(resp.content), sheet_name=None, header=None, nrows=15)
        except Exception as exc:
            print(f"Excel parsing failed: {exc}")
            continue

        print(f"Sheet names: {list(sheets.keys())}")
        for sheet_name, df in sheets.items():
            print(f"\n--- Sheet: {sheet_name!r} (first 15 rows, no header assumed) ---")
            print(df.to_string())


def main() -> int:
    extract_pdf_text()
    inspect_xlsx_candidates()
    print_header("DONE - copy this entire output and paste it back for analysis.")
    return 0


if __name__ == "__main__":
    sys.exit(main())