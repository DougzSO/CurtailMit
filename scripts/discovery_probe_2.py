"""
Follow-up discovery probe (round 2).

Not part of the pipeline. Run manually, paste the output back for analysis.

Goals:
1. MCTI: extract real <a href> links from the SIRENE landing page instead
   of guessing URLs.
2. CCEE: retry with a realistic browser User-Agent to rule out a simple
   WAF/User-Agent block before concluding it is unreachable.
"""

import sys

import requests
from bs4 import BeautifulSoup

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

KEYWORDS = ["fator", "emissao", "emissão", "margem", "sirene", "co2", "sin"]
FILE_EXTENSIONS = (".xls", ".xlsx", ".csv", ".pdf", ".zip")


def print_header(title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def probe_mcti_links() -> None:
    print_header("MCTI - extracting real links from SIRENE landing page")
    url = "https://www.gov.br/mcti/pt-br/acompanhe-o-mcti/sirene"
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
    print(f"Total <a href> tags found: {len(anchors)}")

    relevant = []
    for a in anchors:
        href = a["href"]
        text = a.get_text(strip=True)
        haystack = f"{href} {text}".lower()
        is_keyword_match = any(k in haystack for k in KEYWORDS)
        is_file_match = href.lower().endswith(FILE_EXTENSIONS)
        if is_keyword_match or is_file_match:
            relevant.append((href, text))

    print(f"\nRelevant links (keyword or file-extension match): {len(relevant)}")
    for href, text in relevant:
        print(f"  href={href!r} | text={text!r}")

    if not relevant:
        print("\nNo relevant links found. Printing first 40 raw links for manual review:")
        for a in anchors[:40]:
            print(f"  href={a['href']!r} | text={a.get_text(strip=True)!r}")


def probe_ccee_with_browser_headers() -> None:
    print_header("CCEE - retry with browser-like headers")
    urls = [
        "https://dadosabertos.ccee.org.br/",
        "https://dadosabertos.ccee.org.br/api/3/action/package_list",
    ]
    for url in urls:
        try:
            resp = requests.get(url, headers=BROWSER_HEADERS, timeout=30)
        except requests.RequestException as exc:
            print(f"GET {url} -> request failed: {exc}")
            continue
        print(f"GET {url} -> status {resp.status_code}, content-type={resp.headers.get('content-type')}")
        print(f"First 300 chars:\n{resp.text[:300]}\n")


def main() -> int:
    probe_mcti_links()
    probe_ccee_with_browser_headers()
    print_header("DONE - copy this entire output and paste it back for analysis.")
    return 0


if __name__ == "__main__":
    sys.exit(main())