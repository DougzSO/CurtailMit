"""Manual-ingestion fallback - LAST RESORT ONLY (docs/claude_commands.md, Global Rule #2).

Used only when an automated discovery/scraping path fails (e.g. a source page's
structure changes and cannot be parsed programmatically). Must never be invoked
silently - any caller falling back to it must log a clear WARNING and record the
fallback in the data-quality report.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


class ManualIngestionRequired(RuntimeError):
    """Raised when automated acquisition failed and a manually placed file is needed."""


def load_manually_placed_file(
    expected_path: Path,
    instructions: str,
    reader: str = "excel",
    read_kwargs: dict | None = None,
) -> pd.DataFrame:
    """Attempt to load a manually placed file; raise an actionable error if absent.

    `instructions` should tell the human exactly what to download, from where,
    and where to place it (expected_path). `read_kwargs` is forwarded to the pandas reader
    (e.g. {"sheet_name": 0, "header": None} to get the raw cell grid).
    """
    if not expected_path.exists():
        raise ManualIngestionRequired(
            f"Manual ingestion required - file not found at {expected_path}.\n{instructions}"
        )

    if reader == "excel":
        return pd.read_excel(expected_path, **(read_kwargs or {}))
    elif reader == "csv":
        return pd.read_csv(expected_path, **(read_kwargs or {}))
    else:
        raise ValueError(f"Unsupported reader: {reader}")
