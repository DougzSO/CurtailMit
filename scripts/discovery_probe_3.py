"""
Discovery probe round 3.

Not part of the pipeline. Run manually, paste the output back for analysis.

Goals:
1. Inspect the actual resource schema of the two ONS generation-by-source
   candidates (geracao-usina-2, balanco-energia-subsistema) by downloading
   one sample CSV resource from each and printing its columns.
2. Extract real downloadable file links from the two confirmed MCTI
   candidate pages.
"""

import io
import sys

import pandas as pd
import requests
from bs4 import BeautifulSoup

from curtailmit.ckan import package_show, get_resources

ONS_BASE_URL = "https://dados.ons.org.br/api/3/action"
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}


def print_header(title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def inspect_package_schema(package_id: str) -> None:
    print_header(f"ONS - schema inspection for package: {package_id}")
    try:
        pkg = package_show(ONS_BASE_URL, package_id)
    except Exception as exc:
        print(f"package_show failed: {exc}")
        return

    resources = get_resources(pkg)
    print(f"Total resources: {len(resources)}")
    csv_resources = [r for r in resources if r.format == "CSV"]
    if not csv_resources:
        print("No CSV resource found; listing first 10 resources instead:")
        for r in resources[:10]:
            print(f"  id={r.id} | name={r.name} | format={r.format}")
        return

    sample = csv_resources[len(csv_resources) // 2]
    print(f"Sampling resource: id={sample.id} | name={sample.name} | url={sample.url}")

    try:
        resp = requests.get(sample.url, headers=BROWSER_HEADERS, timeout=60)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"Download failed: {exc}")
        return

    df = None
    for sep in (None, ";", ","):
        try:
            if sep is None:
                df = pd.read_csv(io.BytesIO(resp.content), sep=None, engine="python", nrows=20)
            else:
                df = pd.read_csv(io.BytesIO(resp.content), sep=sep, nrows=20)
            break
        except Exception:
            continue

    if df is None:
        print("CSV parsing failed with all attempted separators. First 500 raw bytes:")
        print(resp.content[:500])
        return

    print(f"\nColumns ({len(df.columns)}):")
    for col in df.columns:
        print(f"  - {col!r} (dtype: {df[col].dtype})")
    print(f"\nFirst 5 rows:\n{df.head(5).to_string()}")


def inspect_mcti_page(url: str, label: str) -> None:
    print_header(f"MCTI - file link extraction: {label}")
    try:
        resp = requests.get(url, headers=BROWSER_HEADERS, timeout=30)
    except requests.RequestException as exc:
        print(f"Request failed: {exc}")
        return

    print(f"GET {url} -> status {resp.status_code}")
    if resp.status_code != 200:
        return

    soup = BeautifulSoup(resp.text, "lxml")
    anchors = soup.find_all("a", href=True)
    file_links = [
        (a["href"], a.get_text(strip=True))
        for a in anchors
        if a["href"].lower().endswith((".xls", ".xlsx", ".csv", ".zip", ".pdf", ".ods"))
    ]
    print(f"Total links: {len(anchors)} | File-like links: {len(file_links)}")
    for href, text in file_links:
        print(f"  href={href!r} | text={text!r}")

    if not file_links:
        print(
            "\nNo direct file links found. Printing all links containing "
            "'fator', 'emiss', 'margem', 'sin', or 'download' for manual review:"
        )
        keywords = ["fator", "emiss", "margem", "sin", "download"]
        for a in anchors:
            haystack = f"{a['href']} {a.get_text(strip=True)}".lower()
            if any(k in haystack for k in keywords):
                print(f"  href={a['href']!r} | text={a.get_text(strip=True)!r}")


def main() -> int:
    inspect_package_schema("geracao-usina-2")
    inspect_package_schema("balanco-energia-subsistema")

    inspect_mcti_page(
        "https://www.gov.br/mcti/pt-br/acompanhe-o-mcti/sirene/dados-e-ferramentas/fatores-de-emissao",
        "primary candidate (fatores-de-emissao)",
    )
    inspect_mcti_page(
        "https://www.gov.br/mcti/pt-br/acompanhe-o-mcti/cgcl",
        "secondary candidate (cgcl)",
    )

    print_header("DONE - copy this entire output and paste it back for analysis.")
    return 0


if __name__ == "__main__":
    sys.exit(main())