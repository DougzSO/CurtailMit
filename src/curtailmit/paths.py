"""Resolve DATABASE_ROOT and standard subdirectories from .env + config/paths.yaml."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PATHS_CONFIG = _PROJECT_ROOT / "config" / "paths.yaml"

load_dotenv(_PROJECT_ROOT / ".env")


def resolve_database_root(create: bool = True) -> Path:
    """DATABASE_ROOT (environment variable, then .env, then ../curtailmit_database) resolved against the project root; create=False never touches the file system."""
    raw = os.getenv("DATABASE_ROOT", "../curtailmit_database")
    root = (_PROJECT_ROOT / raw).resolve()
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


def get_database_root() -> Path:
    return resolve_database_root(create=True)


def planned_layout(root: Path | None = None) -> dict[str, Path]:
    """Standard directories under the database root without creating any (used by the orchestrator's dry run)."""
    base = root if root is not None else resolve_database_root(create=False)
    cfg = _load_paths_config()
    return {"root": base, "interim": base / cfg["interim"], "processed": base / cfg["processed"], "logs": base / cfg["logs"], "tables": base / cfg["outputs"]["tables"], "raw_ons": base / cfg["raw"]["ons"]}


def _load_paths_config() -> dict:
    with open(_PATHS_CONFIG, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_raw_dir(subdir: str) -> Path:
    """subdir example: ons/curtailment_wind, mcti/average_emission_factor."""
    path = get_database_root() / "raw" / subdir
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_interim_dir() -> Path:
    cfg = _load_paths_config()
    path = get_database_root() / cfg["interim"]
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_processed_dir() -> Path:
    cfg = _load_paths_config()
    path = get_database_root() / cfg["processed"]
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_validation_dir() -> Path:
    cfg = _load_paths_config()
    path = get_database_root() / cfg["validation"]
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_outputs_dir(kind: str) -> Path:
    """kind: tables | figures | reports."""
    cfg = _load_paths_config()
    path = get_database_root() / cfg["outputs"][kind]
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_logs_dir() -> Path:
    cfg = _load_paths_config()
    path = get_database_root() / cfg["logs"]
    path.mkdir(parents=True, exist_ok=True)
    return path
