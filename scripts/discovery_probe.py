"""
Exploratory discovery probe - NOT part of the automated pipeline or test suite.

Run this manually, once, to gather real intelligence about actual CKAN packages/
resources and MCTI/CCEE page structures BEFORE handing implementation tasks to
Claude Code. Saves Claude Code from spending tokens on trial-and-error discovery
that we can do ourselves, right now, with a live connection.

Usage:
    python scripts/discovery_probe.py
"""

from __future__ import annotations

import requests

ONS_BASE = "https://dados.ons.org.br/api/3/action"
ANEEL_BASE = "https://dadosabertos.aneel.gov.br/api/3/action"
CCEE_CANDIDATES = [
    "https://dadosabertos.ccee.org.br/api/3/action/package_list",
    "https://dadosabertos.ccee.org.br/",
]
MCTI_CANDIDATES = [
    "https://www.gov.br/mcti/pt-br/acompanhe-o-mcti/sirene",
    "https://www.gov.br/mcti/pt-br/acompanhe-o-mcti/sirene/fator-medio-de-emissao",
    "https://www.gov.br/mcti/pt-br/busca?SearchableText=fator+medio+emissao+co2+sin",
]


def hr(title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def probe_ons_wind() -> None:
    hr("ONS - wind curtailment package (known id: restricao_coff_eolica_usi)")
    try:
        r = requests.get(f"{ONS_BASE}/package_show", params={"id": "restricao_coff_eolica_usi"}, timeout=30)
        r.raise_for_status()
        result = r.json()["result"]
        print(f"Title: {result.get('title')}")
        print(f"Resources ({len(result.get('resources', []))}):")
        for res in result.get("resources", []):
            print(f"  - id={res['id']} | name={res.get('name')} | format={res.get('format')} "
                  f"| last_modified={res.get('last_modified') or res.get('created')}")
    except Exception as e:
        print(f"FAILED: {e}")


def probe_ons_search(queries: list[str], label: str) -> None:
    hr(f"ONS - package_search candidates for: {label}")
    for q in queries:
        try:
            r = requests.get(f"{ONS_BASE}/package_search", params={"q": q}, timeout=30)
            r.raise_for_status()
            results = r.json()["result"]["results"]
            print(f"\nQuery: '{q}' -> {len(results)} result(s)")
            for res in results[:8]:
                print(f"  - id={res['id']} | name={res.get('name')} | title={res.get('title')}")
        except Exception as e:
            print(f"Query '{q}' FAILED: {e}")


def probe_aneel() -> None:
    hr("ANEEL - base CKAN API reachability")
    try:
        r = requests.get(f"{ANEEL_BASE}/package_search", params={"q": "geracao"}, timeout=30)
        r.raise_for_status()
        results = r.json()["result"]["results"]
        print(f"ANEEL CKAN reachable. 'geracao' search -> {len(results)} result(s)")
        for res in results[:8]:
            print(f"  - id={res['id']} | title={res.get('title')}")
    except Exception as e:
        print(f"FAILED: {e}")


def probe_ccee() -> None:
    hr("CCEE - checking whether dadosabertos.ccee.org.br is CKAN-based")
    for url in CCEE_CANDIDATES:
        try:
            r = requests.get(url, timeout=30)
            print(f"\nGET {url} -> status {r.status_code}, content-type={r.headers.get('content-type')}")
            print(f"First 300 chars:\n{r.text[:300]}")
        except Exception as e:
            print(f"GET {url} FAILED: {e}")


def probe_mcti() -> None:
    hr("MCTI - candidate landing pages")
    for url in MCTI_CANDIDATES:
        try:
            r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            print(f"\nGET {url} -> status {r.status_code}")
            if r.status_code == 200:
                text = r.text.lower()
                for keyword in ["fator", "médio", "margem", ".xlsx", ".xls", ".csv"]:
                    print(f"    occurrences of '{keyword}': {text.count(keyword.lower())}")
        except Exception as e:
            print(f"GET {url} FAILED: {e}")


def main() -> None:
    probe_ons_wind()
    probe_ons_search(
        ["restricao fotovoltaica", "corte geracao fotovoltaica", "curtailment solar",
         "restricao geracao eolica fotovoltaica", "geracao fotovoltaica"],
        "solar/PV curtailment",
    )
    probe_ons_search(
        ["geracao usina", "geracao fonte", "balanco energia subsistema", "geracao energia mensal"],
        "generation by source",
    )
    probe_aneel()
    probe_ccee()
    probe_mcti()
    hr("DONE - copy this entire output and paste it back for analysis.")


if __name__ == "__main__":
    main()
