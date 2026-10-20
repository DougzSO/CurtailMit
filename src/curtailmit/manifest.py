"""
manifest.py

Generic retrieval-manifest writer/reader, shared by all CurtailMit
acquisition modules (ONS, MCTI, ANEEL, CKAN-based or not).

This module exists so that every acquisition module writes retrieval
manifests in a single, consistent format and location, instead of each
module (data_ingestion.py, ckan.py, future ONS/MCTI/ANEEL-specific
clients) reimplementing manifest-writing logic independently.

A retrieval manifest is a JSON sidecar file, written next to the data
file it describes, recording: source identity, URL, package/resource
ids (when applicable, e.g. CKAN), HTTP status, retrieval timestamp
(UTC), content hash (SHA-256), byte size, row count (when known), and
any request parameters used.

This module performs no network calls itself. Callers (acquisition.py,
future ONS/MCTI/ANEEL clients) are responsible for actually fetching
data; they then pass the resulting metadata to write_manifest().

acquisition.py::fetch_and_cache delegates to this module for its own
manifest writing, so there is a single source of truth for the sidecar
manifest file format and path convention.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from curtailmit.schemas import RetrievalManifest


def manifest_path_for(dest_path: Path) -> Path:
    """
    Return the canonical sidecar manifest path for a given data file.

    Convention: <dest_path><original suffix>.manifest.json
    e.g. data.csv -> data.csv.manifest.json
    """
    dest_path = Path(dest_path)
    return dest_path.with_suffix(dest_path.suffix + ".manifest.json")


def compute_sha256(content: bytes) -> str:
    """Return the SHA-256 hex digest of `content`."""
    return hashlib.sha256(content).hexdigest()


def write_manifest(
    dest_path: Path,
    source_url: str,
    http_status: int,
    sha256: str,
    byte_size: int,
    params: dict[str, Any] | None = None,
    source: str | None = None,
    package_id: str | None = None,
    resource_id: str | None = None,
    row_count: int | None = None,
    retrieved_at_utc: str | None = None,
) -> RetrievalManifest:
    """
    Write a retrieval manifest as a JSON sidecar file next to dest_path.

    This is the single, generic manifest-writing entry point for all
    CurtailMit acquisition modules. It does not perform any network
    call itself; callers fetch data and supply the resulting metadata.

    Parameters
    ----------
    dest_path : Path
        Path to the data file the manifest describes. The manifest
        itself is written to a sidecar path (see manifest_path_for).
    source_url : str
        The URL (or equivalent identifier) data was retrieved from.
    http_status : int
        HTTP status code of the retrieval, if applicable. Use 0 for
        non-HTTP sources (e.g. manually placed files) when no status
        code exists.
    sha256 : str
        SHA-256 hex digest of the retrieved content.
    byte_size : int
        Size in bytes of the retrieved content.
    params : dict, optional
        Query parameters or equivalent request metadata used in the
        retrieval.
    source : str, optional
        Logical source name, e.g. "ONS", "MCTI", "ANEEL", "CCEE".
    package_id : str, optional
        CKAN package id, if applicable.
    resource_id : str, optional
        CKAN resource id, if applicable.
    row_count : int, optional
        Number of data rows represented by this file, if known/
        applicable (e.g. tabular CSV/parquet data).
    retrieved_at_utc : str, optional
        ISO-8601 UTC timestamp of retrieval. Defaults to now(UTC) if
        not provided.

    Returns
    -------
    RetrievalManifest
        The manifest object that was written.
    """
    dest_path = Path(dest_path)
    manifest = RetrievalManifest(
        source_url=source_url,
        http_status=http_status,
        retrieved_at_utc=retrieved_at_utc or datetime.now(timezone.utc).isoformat(),
        sha256=sha256,
        byte_size=byte_size,
        params=params or {},
        source=source,
        package_id=package_id,
        resource_id=resource_id,
        row_count=row_count,
    )
    path = manifest_path_for(dest_path)
    path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return manifest


def load_manifest(dest_path: Path) -> RetrievalManifest:
    """Load a previously written retrieval manifest for dest_path."""
    path = manifest_path_for(dest_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    return RetrievalManifest(**data)