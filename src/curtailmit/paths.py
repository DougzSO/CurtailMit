"""Resolve DATABASE_ROOT and standard subdirectories from .env + config/paths.yaml."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PATHS_CONFIG = _PROJECT_ROOT / "config" / "paths.yaml"

load_dotenv(_PROJECT_ROOT / ".env")


def get_database_root() -> Path:
    raw = os.getenv("DATABASE_ROOT", "../curtailmit_database")
    root = (_PROJECT_ROOT / raw).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


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
