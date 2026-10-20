"""
Generic, reusable CKAN API client helpers.

This module is intentionally source-agnostic: it works against any
CKAN-based Dados Abertos portal (ONS and ANEEL both confirmed CKAN-based)
by passing a different base_url. Source-specific logic (which package
IDs to use, how to interpret column schemas, how to map classification
categories) belongs in source-specific acquisition modules, not here.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30
PREFERRED_FORMATS_DEFAULT = ("PARQUET", "CSV", "XLSX")

MONTHLY_NAME_PATTERN = re.compile(r"^(?P<prefix>.+)-(?P<year>\d{4})-(?P<month>\d{2})$")


class CkanApiError(Exception):
    """Raised when a CKAN API call fails or returns an unsuccessful response."""


@dataclass
class CkanResource:
    id: str
    name: str
    format: str
    url: str
    last_modified: Optional[str] = None

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "CkanResource":
        return cls(
            id=raw["id"],
            name=raw.get("name", ""),
            format=(raw.get("format") or "").upper(),
            url=raw.get("url", ""),
            last_modified=raw.get("last_modified"),
        )


def ckan_action(
    base_url: str,
    action: str,
    params: dict[str, Any] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """
    Call a CKAN action API endpoint and return the parsed 'result' field.

    Raises CkanApiError if the HTTP call fails or the API reports
    success=False. Never fails silently.
    """
    url = base_url.rstrip("/") + "/" + action
    try:
        resp = requests.get(url, params=params or {}, timeout=timeout)
    except requests.RequestException as exc:
        raise CkanApiError(f"Request to {url} failed: {exc}") from exc

    if resp.status_code != 200:
        raise CkanApiError(f"GET {url} returned HTTP {resp.status_code}")

    payload = resp.json()
    if not payload.get("success", False):
        raise CkanApiError(f"CKAN action '{action}' reported success=false: {payload}")

    return payload["result"]


def package_show(base_url: str, package_id: str, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Fetch full package metadata, including the resource list."""
    return ckan_action(base_url, "package_show", {"id": package_id}, timeout=timeout)


def package_search(
    base_url: str, query: str, rows: int = 10, timeout: int = DEFAULT_TIMEOUT
) -> list[dict[str, Any]]:
    """Search for packages matching a free-text query. Returns the raw result list."""
    result = ckan_action(base_url, "package_search", {"q": query, "rows": rows}, timeout=timeout)
    return result.get("results", [])


def get_resources(package_metadata: dict[str, Any]) -> list[CkanResource]:
    """Extract a typed resource list from a package_show() result."""
    return [CkanResource.from_api(r) for r in package_metadata.get("resources", [])]


def pick_best_resource(
    resources: list[CkanResource],
    preferred_formats: tuple[str, ...] = PREFERRED_FORMATS_DEFAULT,
) -> Optional[CkanResource]:
    """
    Among a list of resources (expected to be duplicates of the same
    logical dataset in different formats), pick the first available
    match in order of preference. Returns None if no match exists.
    """
    for fmt in preferred_formats:
        for r in resources:
            if r.format == fmt:
                return r
    return None


def group_monthly_resources(resources: list[CkanResource]) -> dict[tuple[int, int], list[CkanResource]]:
    """
    Group resources whose `name` follows the '<prefix>-YYYY-MM' pattern
    (as used by ONS monthly datasets, e.g. 'Restricoes_coff_eolicas-2024-05')
    by (year, month). Resources that do not match the pattern are ignored
    (e.g. 'Dicionario de Dados' metadata resources).
    """
    grouped: dict[tuple[int, int], list[CkanResource]] = {}
    for r in resources:
        match = MONTHLY_NAME_PATTERN.match(r.name)
        if not match:
            continue
        key = (int(match.group("year")), int(match.group("month")))
        grouped.setdefault(key, []).append(r)
    return grouped