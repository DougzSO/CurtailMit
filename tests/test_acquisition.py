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
