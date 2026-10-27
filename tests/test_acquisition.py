from pathlib import Path

import responses

from curtailmit.acquisition import fetch_and_cache, load_manifest


@responses.activate
def test_fetch_and_cache_downloads_and_writes_manifest(tmp_path: Path):
    url = "https://example.com/data.csv"
    responses.add(responses.GET, url, body="a,b\n1,2\n", status=200)

    dest = tmp_path / "data.csv"
    result_path = fetch_and_cache(url, dest)

    assert result_path == dest
    assert dest.read_text() == "a,b\n1,2\n"

    manifest = load_manifest(dest)
    assert manifest.source_url == url
    assert manifest.http_status == 200
    assert manifest.byte_size == len("a,b\n1,2\n")


@responses.activate
def test_fetch_and_cache_uses_cache_without_second_call(tmp_path: Path):
    url = "https://example.com/data.csv"
    responses.add(responses.GET, url, body="x", status=200)

    dest = tmp_path / "data.csv"
    fetch_and_cache(url, dest, use_cache=True)
    fetch_and_cache(url, dest, use_cache=True)

    assert len(responses.calls) == 1


@responses.activate
def test_cache_that_no_longer_matches_its_manifest_is_fetched_again(tmp_path: Path):
    url = "https://example.com/data.csv"
    responses.add(responses.GET, url, body="original", status=200)

    dest = tmp_path / "data.csv"
    fetch_and_cache(url, dest, use_cache=True)
    dest.write_text("edited!!")  # same-size or different-size edits must both be caught by the SHA-256 check
    fetch_and_cache(url, dest, use_cache=True)

    assert len(responses.calls) == 2 and dest.read_text() == "original"


@responses.activate
def test_cached_file_without_manifest_is_not_trusted(tmp_path: Path):
    url = "https://example.com/data.csv"
    responses.add(responses.GET, url, body="fresh", status=200)

    dest = tmp_path / "data.csv"
    dest.write_text("stale")
    fetch_and_cache(url, dest, use_cache=True)

    assert len(responses.calls) == 1 and dest.read_text() == "fresh"
