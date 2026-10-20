"""Tests for curtailmit.manifest."""

from pathlib import Path

from curtailmit.manifest import (
    compute_sha256,
    manifest_path_for,
    write_manifest,
    load_manifest,
)


def test_manifest_path_for_appends_suffix():
    dest = Path("data.csv")
    assert manifest_path_for(dest) == Path("data.csv.manifest.json")


def test_manifest_path_for_handles_no_suffix():
    dest = Path("data")
    assert manifest_path_for(dest) == Path("data.manifest.json")


def test_compute_sha256_matches_known_value():
    # sha256("abc") is a well-known test vector.
    assert compute_sha256(b"abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"[:64]
    )


def test_compute_sha256_deterministic():
    content = b"some bytes of test content"
    assert compute_sha256(content) == compute_sha256(content)


def test_write_and_load_manifest_roundtrip_minimal(tmp_path: Path):
    dest = tmp_path / "data.csv"
    dest.write_bytes(b"a,b\n1,2\n")

    written = write_manifest(
        dest_path=dest,
        source_url="https://example.com/data.csv",
        http_status=200,
        sha256=compute_sha256(b"a,b\n1,2\n"),
        byte_size=len(b"a,b\n1,2\n"),
    )

    assert written.source_url == "https://example.com/data.csv"
    assert written.source is None
    assert written.package_id is None
    assert written.resource_id is None
    assert written.row_count is None

    loaded = load_manifest(dest)
    assert loaded == written


def test_write_manifest_with_full_metadata(tmp_path: Path):
    dest = tmp_path / "ons_curtailment.parquet"
    content = b"fake parquet bytes"
    dest.write_bytes(content)

    written = write_manifest(
        dest_path=dest,
        source_url="https://dados.ons.org.br/api/3/action/package_show",
        http_status=200,
        sha256=compute_sha256(content),
        byte_size=len(content),
        params={"id": "curtailment-package"},
        source="ONS",
        package_id="curtailment-package",
        resource_id="resource-123",
        row_count=8760,
    )

    assert written.source == "ONS"
    assert written.package_id == "curtailment-package"
    assert written.resource_id == "resource-123"
    assert written.row_count == 8760
    assert written.params == {"id": "curtailment-package"}

    loaded = load_manifest(dest)
    assert loaded.source == "ONS"
    assert loaded.row_count == 8760


def test_manifest_file_written_at_expected_sidecar_path(tmp_path: Path):
    dest = tmp_path / "mcti_factors.csv"
    dest.write_bytes(b"year,factor\n2020,0.1\n")

    write_manifest(
        dest_path=dest,
        source_url="https://example.com/mcti_factors.csv",
        http_status=200,
        sha256=compute_sha256(b"year,factor\n2020,0.1\n"),
        byte_size=len(b"year,factor\n2020,0.1\n"),
        source="MCTI",
    )

    expected_sidecar = tmp_path / "mcti_factors.csv.manifest.json"
    assert expected_sidecar.exists()


def test_write_manifest_retrieved_at_utc_defaults_when_not_provided(tmp_path: Path):
    dest = tmp_path / "data.csv"
    dest.write_bytes(b"x")

    written = write_manifest(
        dest_path=dest,
        source_url="https://example.com/data.csv",
        http_status=200,
        sha256=compute_sha256(b"x"),
        byte_size=1,
    )

    assert written.retrieved_at_utc is not None
    assert len(written.retrieved_at_utc) > 0


def test_write_manifest_retrieved_at_utc_respects_explicit_value(tmp_path: Path):
    dest = tmp_path / "data.csv"
    dest.write_bytes(b"x")

    written = write_manifest(
        dest_path=dest,
        source_url="https://example.com/data.csv",
        http_status=200,
        sha256=compute_sha256(b"x"),
        byte_size=1,
        retrieved_at_utc="2022-01-01T00:00:00+00:00",
    )

    assert written.retrieved_at_utc == "2022-01-01T00:00:00+00:00"