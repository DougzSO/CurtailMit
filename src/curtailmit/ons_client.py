"""Thin CKAN API client for ONS (and MCTI, where applicable) dataset discovery.

Design principle: never hardcode a resource_id without first confirming it exists
and has adequate coverage. Fail explicitly, log everything.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import requests

logger = logging.getLogger(__name__)


class CoverageError(RuntimeError):
    """Raised when a discovered dataset does not meet minimum coverage requirements."""


@dataclass
class ResourceInfo:
    resource_id: str
    name: str
    format: str
    last_modified: str | None
    url: str = ""


class CkanClient:
    def __init__(self, base_url: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def package_show(self, package_id: str) -> dict:
        url = f"{self.base_url}/package_show"
        resp = requests.get(url, params={"id": package_id}, timeout=self.timeout)
        resp.raise_for_status()
        payload = resp.json()
        if not payload.get("success"):
            raise RuntimeError(f"CKAN package_show failed for id={package_id}: {payload}")
        return payload["result"]

    def package_search(self, query: str) -> list[dict]:
        url = f"{self.base_url}/package_search"
        resp = requests.get(url, params={"q": query}, timeout=self.timeout)
        resp.raise_for_status()
        payload = resp.json()
        if not payload.get("success"):
            raise RuntimeError(f"CKAN package_search failed for q={query}: {payload}")
        return payload["result"]["results"]

    @staticmethod
    def resources_from_package(package: dict) -> list[ResourceInfo]:
        """Build ResourceInfo entries from an already-fetched package_show result."""
        return [
            ResourceInfo(
                resource_id=r["id"],
                name=r.get("name", ""),
                format=r.get("format", ""),
                last_modified=r.get("last_modified") or r.get("created"),
                url=r.get("url", ""),
            )
            for r in package.get("resources", [])
        ]

    def list_resources(self, package_id: str) -> list[ResourceInfo]:
        resources = self.resources_from_package(self.package_show(package_id))
        logger.info("Discovered %d resources for package '%s'", len(resources), package_id)
        for r in resources:
            logger.info("  - %s | %s | %s | modified=%s", r.resource_id, r.name, r.format, r.last_modified)
        return resources

    @staticmethod
    def enforce_min_coverage(earliest_date: date, min_coverage_start: date) -> None:
        if earliest_date > min_coverage_start:
            raise CoverageError(
                f"Earliest available data ({earliest_date}) does not reach the required "
                f"minimum coverage start ({min_coverage_start}). Failing explicitly - "
                f"no silent fallback allowed."
            )
