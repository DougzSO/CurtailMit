"""Shared data-acquisition utilities: cached fetch + retrieval manifests.

Design principles (docs/claude_commands.md Global Rules #2-#5):
- API-first, always; manual downloads are last resort only.
- Every fetch produces a retrieval manifest for reproducibility.
- Default behavior always fetches the freshest data (use_cache=False by default).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from curtailmit.schemas import RetrievalManifest

logger = logging.getLogger(__name__)


def _sha256_of_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _manifest_path(dest_path: Path) -> Path:
    return dest_path.with_suffix(dest_path.suffix + ".manifest.json")


def fetch_and_cache(
    url: str,
    dest_path: Path,
    params: dict[str, Any] | None = None,
    method: str = "GET",
    use_cache: bool = False,
    timeout: int = 60,
) -> Path:
    """Download `url` to `dest_path`, writing a sidecar retrieval manifest.

    If use_cache=True and both dest_path and its manifest already exist, the
    network call is skipped entirely and the cached file is reused as-is.
    """
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = _manifest_path(dest_path)

    if use_cache and dest_path.exists() and manifest_path.exists():
        cached = load_manifest(dest_path)
        logger.info(
            "Using cached file %s (originally retrieved %s from %s)",
            dest_path, cached.retrieved_at_utc, cached.source_url,
        )
        return dest_path

    logger.info("Fetching %s -> %s", url, dest_path)
    resp = requests.request(method, url, params=params, timeout=timeout)
    resp.raise_for_status()
    content = resp.content

    dest_path.write_bytes(content)

    manifest = RetrievalManifest(
        source_url=resp.url,
        http_status=resp.status_code,
        retrieved_at_utc=datetime.now(timezone.utc).isoformat(),
        sha256=_sha256_of_bytes(content),
        byte_size=len(content),
        params=params or {},
    )
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    logger.info("Saved %d bytes, manifest written to %s", len(content), manifest_path)
    return dest_path


def load_manifest(dest_path: Path) -> RetrievalManifest:
    manifest_path = _manifest_path(dest_path)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return RetrievalManifest(**data)
