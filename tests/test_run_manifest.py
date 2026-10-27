"""Unit tests of curtailmit.run_manifest (Task 15, D33): raw-file inventory, data snapshot manifest, verification, manifest content. No network, no curtailmit_database."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from curtailmit import run_manifest as rm


def raw_file(root: Path, rel: str, content: bytes, url: str = "https://example.org/f", retrieved: str = "2026-10-01T00:00:00+00:00") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    side = path.with_suffix(path.suffix + ".manifest.json")
    side.write_text(json.dumps({"source_url": url, "http_status": 200, "retrieved_at_utc": retrieved, "sha256": hashlib.sha256(content).hexdigest(), "byte_size": len(content)}), encoding="utf-8")
    return path


@pytest.fixture
def raw(tmp_path) -> Path:
    root = tmp_path / "raw"
    raw_file(root, "ons/a/one.parquet", b"one", url="https://ons.example/one")
    raw_file(root, "mcti/b/two.xlsx", b"twotwo", url="https://mcti.example/two")
    (root / "pte_epe").mkdir()
    (root / "pte_epe" / ".gitkeep").write_text("", encoding="utf-8")
    return root


def test_inventory_lists_data_files_sorted_and_skips_sidecars_and_gitkeep(raw):
    inv = rm.raw_inventory(raw)
    assert [f["path"] for f in inv] == ["mcti/b/two.xlsx", "ons/a/one.parquet"]
    assert inv[1] == {"path": "ons/a/one.parquet", "source_url": "https://ons.example/one", "retrieved_at_utc": "2026-10-01T00:00:00+00:00", "http_status": 200,
                      "sha256": hashlib.sha256(b"one").hexdigest(), "byte_size": 3}


def test_inventory_of_a_missing_directory_is_empty(tmp_path):
    assert rm.raw_inventory(tmp_path / "nope") == []


def test_file_that_differs_from_its_retrieval_manifest_is_refused(raw):
    (raw / "ons/a/one.parquet").write_bytes(b"tampered")
    with pytest.raises(rm.RunManifestError, match="bytes differ") as err:
        rm.raw_inventory(raw)
    assert err.value.diagnostics["problems"][0]["file"] == "ons/a/one.parquet"


def test_file_without_retrieval_manifest_is_refused(raw):
    (raw / "ons/a/one.parquet.manifest.json").unlink()
    with pytest.raises(rm.RunManifestError, match="no retrieval manifest"):
        rm.raw_inventory(raw)


def test_unreadable_retrieval_manifest_is_refused(raw):
    (raw / "ons/a/one.parquet.manifest.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(rm.RunManifestError, match="unreadable"):
        rm.raw_inventory(raw)


# ----------------------------------------------------------------------------------------------------------------------- snapshot (D33)
def test_snapshot_is_identical_apart_from_the_timestamp(raw):
    a, b = rm.build_snapshot(raw, "T1"), rm.build_snapshot(raw, "T2")
    assert a.pop("generated_utc") == "T1" and b.pop("generated_utc") == "T2" and a == b
    assert a["n_files"] == 2 and a["total_bytes"] == 9 and {"sha256", "byte_size", "source_url", "retrieved_at_utc", "path"} <= set(a["files"][0])


def test_snapshot_carries_no_data_only_hashes_and_urls(raw):
    text = json.dumps(rm.build_snapshot(raw))
    assert "twotwo" not in text and "https://mcti.example/two" in text


def test_verify_reports_matching_differing_missing_and_extra(raw):
    snap = rm.build_snapshot(raw)
    assert rm.verify_snapshot(snap, raw)["ok"] is True
    (raw / "ons/a/one.parquet").write_bytes(b"revised by the publisher")
    (raw / "mcti/b/two.xlsx").unlink()
    raw_file(raw, "ons/a/new.parquet", b"new month")
    rep = rm.verify_snapshot(snap, raw)
    assert rep["differing"] == ["ons/a/one.parquet"] and rep["missing"] == ["mcti/b/two.xlsx"] and rep["extra"] == ["ons/a/new.parquet"] and rep["ok"] is False and rep["matching"] == []


def test_cli_snapshot_and_verify_exit_codes(raw, tmp_path, capsys):
    out = tmp_path / "snap.json"
    assert rm.main(["snapshot", "--raw-root", str(raw), "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["n_files"] == 2
    assert rm.main(["verify", "--raw-root", str(raw), "--manifest", str(out)]) == 0
    (raw / "ons/a/one.parquet").write_bytes(b"changed")
    assert rm.main(["verify", "--raw-root", str(raw), "--manifest", str(out)]) == 1
    assert "differing: ons/a/one.parquet" in capsys.readouterr().out


def test_cli_snapshot_refuses_unverifiable_raw_files(raw, tmp_path):
    (raw / "ons/a/one.parquet").write_bytes(b"changed")
    assert rm.main(["snapshot", "--raw-root", str(raw), "--out", str(tmp_path / "s.json")]) == 2
    assert not (tmp_path / "s.json").exists()


# ----------------------------------------------------------------------------------------------------------------------- manifest content
def test_manifest_is_refused_for_a_failed_record(raw):
    with pytest.raises(rm.RunManifestError, match="only for SUCCESS"):
        rm.build_run_manifest(record={"status": "FAILED"}, raw_root=raw, config_hashes={}, decision_hashes={}, artifacts={}, end_exclusive="2026-10-01")


def test_manifest_compares_the_raw_files_with_the_committed_snapshot(raw, tmp_path):
    snap = tmp_path / "snap.json"
    rm.write_snapshot(raw, snap)
    raw_file(raw, "ons/a/new.parquet", b"new")
    m = rm.build_run_manifest(record={"status": "SUCCESS", "stages": [], "started_utc": "t"}, raw_root=raw, config_hashes={"config/x.yaml": "h"}, decision_hashes={"D1": "h"}, artifacts={},
                              end_exclusive="2026-10-01", snapshot_path=snap)
    c = m["raw_inputs"]["committed_snapshot"]
    assert c["matching"] == 2 and c["extra"] == ["ons/a/new.parquet"] and c["identical_to_local_raw"] is False and m["raw_inputs"]["n_files"] == 3
    assert c["sha256"] == hashlib.sha256(snap.read_bytes()).hexdigest()


def test_manifest_without_a_committed_snapshot_records_none(raw, tmp_path):
    m = rm.build_run_manifest(record={"status": "SUCCESS"}, raw_root=raw, config_hashes={}, decision_hashes={}, artifacts={}, end_exclusive="x", snapshot_path=tmp_path / "absent.json")
    assert m["raw_inputs"]["committed_snapshot"] is None


def test_git_state_degrades_to_null_when_git_is_unavailable(tmp_path):
    g = rm.git_state(tmp_path)  # not a repository (or no git): never raises
    assert g["commit"] is None and "unavailable" in g
