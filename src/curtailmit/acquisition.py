"""Shared data-acquisition utilities: cached fetch + retrieval manifests.

Design principles (docs/claude_commands.md Global Rules #2-#5):
- API-first, always; manual downloads are last resort only.
- Every fetch produces a retrieval manifest for reproducibility.
- Default behavior always fetches the freshest data (use_cache=False by default).

Manifest writing/reading is delegated to curtailmit.manifest, which is
the single generic implementation shared by all acquisition modules
(ONS, MCTI, ANEEL, CKAN-based or not). load_manifest is re-exported
here for backward compatibility with existing callers/tests.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import requests

from curtailmit.manifest import (
    compute_sha256,
    load_manifest,
    manifest_path_for,
    write_manifest,
)

logger = logging.getLogger(__name__)

__all__ = ["fetch_and_cache", "load_manifest"]


def fetch_and_cache(
    url: str,
    dest_path: Path,
    params: dict[str, Any] | None = None,
    method: str = "GET",
    use_cache: bool = False,
    timeout: int = 60,
    headers: dict[str, str] | None = None,
) -> Path:
    """Download `url` to `dest_path`, writing a sidecar retrieval manifest.

    If use_cache=True and both dest_path and its manifest already exist, the
    network call is skipped entirely and the cached file is reused as-is.
    """
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_path_for(dest_path)

    if use_cache and dest_path.exists() and manifest_path.exists():
        cached = load_manifest(dest_path)
        logger.info(
            "Using cached file %s (originally retrieved %s from %s)",
            dest_path, cached.retrieved_at_utc, cached.source_url,
        )
        return dest_path

    logger.info("Fetching %s -> %s", url, dest_path)
    resp = requests.request(method, url, params=params, timeout=timeout, headers=headers)
    resp.raise_for_status()
    content = resp.content

    dest_path.write_bytes(content)

    write_manifest(
        dest_path=dest_path,
        source_url=resp.url,
        http_status=resp.status_code,
        sha256=compute_sha256(content),
        byte_size=len(content),
        params=params or {},
    )
    logger.info("Saved %d bytes, manifest written to %s", len(content), manifest_path)
    return dest_path