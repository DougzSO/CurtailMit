from pathlib import Path

from curtailmit import paths


def test_get_database_root_respects_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_ROOT", str(tmp_path / "custom_db"))
    root = paths.get_database_root()
    assert root == (tmp_path / "custom_db").resolve()
    assert root.exists()


def test_get_raw_dir_creates_subdir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_ROOT", str(tmp_path / "custom_db"))
    d = paths.get_raw_dir("ons/curtailment_wind")
    assert d.exists()
    assert d.name == "curtailment_wind"
