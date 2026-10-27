"""Metadata pre-filter for stamp hashing (Task 16, Part B): the content hash stays authoritative; the cache only decides whether a large file must be read again."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import pandas as pd
import pytest

from curtailmit import hash_cache as hc
from curtailmit import pipeline as pl
from curtailmit import provenance as prov

MIB = 1 << 20
NS = 1_000_000_000


def make(path: Path, size: int = MIB + 4096, fill: int = 1, age_s: float = 600) -> Path:
    """A file of `size` bytes filled with one byte value, last modified `age_s` seconds ago (so that it is older than the racy guard)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes([fill]) * size)
    set_mtime(path, time.time_ns() - int(age_s * NS))
    return path


def set_mtime(path: Path, mtime_ns: int) -> None:
    os.utime(path, ns=(mtime_ns, mtime_ns))


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cache_for(tmp_path: Path, **kw) -> hc.HashCache:
    return hc.HashCache(tmp_path / "hash_cache.json", root=tmp_path, **kw)


def overwrite_in_place(path: Path, fill: int) -> None:
    """Same size, same inode: new content written into the existing file."""
    with open(path, "r+b") as f:
        f.write(bytes([fill]) * path.stat().st_size)


# ------------------------------------------------------------------------------------------------------------------------ basic behaviour
def test_first_lookup_reads_the_file_the_second_reuses_the_hash_after_the_guard(tmp_path):
    f = make(tmp_path / "a.bin")
    cache = cache_for(tmp_path)
    assert cache.sha256(f) == sha(f) and cache.stats["rehashed"] == 1
    assert cache.sha256(f) == sha(f) and cache.stats["hits"] == 1 and cache.stats["rehashed"] == 1


def test_the_cache_persists_between_runs_and_drops_entries_of_deleted_files(tmp_path):
    a, b = make(tmp_path / "a.bin"), make(tmp_path / "b.bin", fill=2)
    first = cache_for(tmp_path)
    first.sha256(a), first.sha256(b)
    assert first.save() is True and first.save() is False  # nothing changed the second time
    body = json.loads((tmp_path / "hash_cache.json").read_text(encoding="utf-8"))
    assert body["schema"] == 1 and body["guard_ns"] == hc.GUARD_NS and set(body["entries"]) == {"a.bin", "b.bin"}
    assert set(body["entries"]["a.bin"]) == {"size", "mtime_ns", "ino", "sha256", "hashed_at_ns"}
    b.unlink()
    second = cache_for(tmp_path)
    assert second.sha256(a) == sha(a) and second.stats == {"hits": 1, "rehashed": 0, "bypassed": 0, "bytes_read": 0}
    second.dirty = True
    second.save()
    assert set(json.loads((tmp_path / "hash_cache.json").read_text(encoding="utf-8"))["entries"]) == {"a.bin"}


# ----------------------------------------------------------------------------- 1. equivalence: the cache cannot change an outcome when metadata changed
@pytest.mark.parametrize("change", ["different_size", "same_size_new_mtime", "added", "removed", "renamed", "unchanged"])
def test_tree_hashes_are_identical_with_and_without_the_cache(tmp_path, change):
    root = tmp_path / "tree"
    make(root / "x" / "a.bin"), make(root / "b.bin", fill=2)
    cache = cache_for(tmp_path)
    assert prov.tree_hashes(root, cache=cache) == prov.tree_hashes(root)
    cache.save()
    if change == "different_size":
        (root / "b.bin").write_bytes(b"\x07" * (MIB + 9))
    elif change == "same_size_new_mtime":
        overwrite_in_place(root / "b.bin", 9)
        set_mtime(root / "b.bin", time.time_ns() - 100 * NS)
    elif change == "added":
        make(root / "c.bin", fill=3)
    elif change == "removed":
        (root / "b.bin").unlink()
    elif change == "renamed":
        (root / "b.bin").rename(root / "z.bin")
    again = cache_for(tmp_path)
    expected = prov.tree_hashes(root)
    assert prov.tree_hashes(root, cache=again) == expected
    assert (change in ("unchanged", "removed")) == (again.stats["rehashed"] == 0)  # a file that exists and did not change is not re-read; every changed, new or renamed file is


# ----------------------------------------------------------------- 2. the hash governs when it is consulted; the forged-metadata residual risk
def test_a_content_change_is_detected_when_the_cache_is_disabled(tmp_path):
    f = make(tmp_path / "a.bin")
    cache = cache_for(tmp_path)
    old = cache.sha256(f)
    mtime = f.stat().st_mtime_ns
    overwrite_in_place(f, 9)
    set_mtime(f, mtime)  # size, mtime and inode all equal to the recorded values
    off = hc.HashCache(tmp_path / "hash_cache.json", root=tmp_path, enabled=False)
    assert off.sha256(f) == sha(f) != old and off.stats["bytes_read"] == 0 and off.entries == {}
    assert prov.file_hashes({"a": f}) == {"a": sha(f)}  # the default path (no cache object) is the full hash


def test_forged_metadata_is_the_documented_residual_risk(tmp_path):
    """ACCEPTED RESIDUAL RISK, not a bug: when content changes while size, mtime_ns and inode stay equal to the recorded values (and the recorded mtime was old), the cache returns the STALE
    hash. This test documents that behaviour. It does not claim the optimisation defends against forged metadata; it claims that bypassing the cache (--no-hash-cache) restores detection (see
    test_a_content_change_is_detected_when_the_cache_is_disabled) and that the risk is limited to exactly this case (all the tests below show every other change is detected)."""
    f = make(tmp_path / "a.bin")
    cache = cache_for(tmp_path)
    stale = cache.sha256(f)
    mtime = f.stat().st_mtime_ns
    overwrite_in_place(f, 9)
    set_mtime(f, mtime)
    assert sha(f) != stale
    assert cache.sha256(f) == stale  # knowingly returned: this is what the metadata shortcut means
    assert cache.stats["hits"] == 1


def test_a_changed_inode_with_equal_size_and_mtime_is_not_trusted(tmp_path):
    f = make(tmp_path / "a.bin")
    cache = cache_for(tmp_path)
    cache.sha256(f)
    mtime = f.stat().st_mtime_ns
    cache.entries["a.bin"]["ino"] = (f.stat().st_ino or 1) + 1  # as if the file had been replaced by a different one
    overwrite_in_place(f, 9)
    set_mtime(f, mtime)
    if f.stat().st_ino:  # filesystems that report no inode cannot be tested
        assert cache.sha256(f) == sha(f) and cache.stats["rehashed"] == 2


# ------------------------------------------------------------------------------------------------------------------------- 3. racy guard
def test_a_file_modified_within_the_guard_window_is_rehashed_and_the_change_is_detected(tmp_path):
    f = make(tmp_path / "a.bin", age_s=0)  # modified "now": inside the 5 s guard when it is hashed
    cache = cache_for(tmp_path)
    first = cache.sha256(f)
    mtime = f.stat().st_mtime_ns
    overwrite_in_place(f, 9)
    set_mtime(f, mtime)  # same size, same mtime tick: exactly the case a racy file hides
    assert cache.sha256(f) == sha(f) != first and cache.stats["hits"] == 0
    # once the file is old enough the (new) entry is trusted
    set_mtime(f, time.time_ns() - 600 * NS)
    cache.sha256(f)
    cache.sha256(f)
    assert cache.stats["hits"] == 1


def test_the_hashing_time_is_taken_before_the_read_so_a_write_during_the_read_is_not_recorded(tmp_path, monkeypatch):
    f = make(tmp_path / "a.bin")
    cache = cache_for(tmp_path)
    real = prov.sha256_file

    def writing_while_reading(path, normalise_newlines=False):
        digest = real(path, normalise_newlines)
        overwrite_in_place(Path(path), 7)
        set_mtime(Path(path), time.time_ns())  # the file changes while it is being hashed
        return digest

    monkeypatch.setattr(prov, "sha256_file", writing_while_reading)
    cache.sha256(f)
    assert cache.entries == {}  # size/mtime changed between the stat before and the stat after the read: nothing recorded


# --------------------------------------------------------------------------------------------- 4. older file restored; 5. future mtime / skew
def test_an_older_file_restored_over_a_newer_one_is_detected(tmp_path):
    f = make(tmp_path / "a.bin", age_s=300)
    cache = cache_for(tmp_path)
    first = cache.sha256(f)
    older = f.stat().st_mtime_ns - 200 * NS
    overwrite_in_place(f, 9)
    set_mtime(f, older)  # a restored backup: older than the recorded mtime (what Make's "newer than" test misses)
    assert cache.sha256(f) == sha(f) != first and cache.stats["hits"] == 0


def test_an_mtime_in_the_future_relative_to_the_hashing_time_is_never_trusted(tmp_path):
    f = make(tmp_path / "a.bin")
    set_mtime(f, time.time_ns() + 3600 * NS)
    cache = cache_for(tmp_path)
    cache.sha256(f), cache.sha256(f), cache.sha256(f)
    assert cache.stats["hits"] == 0 and cache.stats["rehashed"] == 3
    skewed = cache_for(tmp_path / "other", clock_ns=lambda: time.time_ns() - 3600 * NS)  # a clock that runs behind the file system
    g = make(tmp_path / "g.bin")
    skewed.sha256(g), skewed.sha256(g)
    assert skewed.stats["hits"] == 0


# --------------------------------------------------------------------------------------------------------------------- 6. failure modes
@pytest.mark.parametrize("content", [None, "", '{"schema": 1, "entries": {', "not json", '{"schema": 2, "entries": {}}', '["a"]', '{"schema": 1, "entries": []}',
                                     '{"schema": 1, "entries": {"a.bin": {"size": "x"}}}'])
def test_a_missing_truncated_malformed_or_other_schema_cache_behaves_as_empty(tmp_path, content):
    f = make(tmp_path / "a.bin")
    if content is not None:
        (tmp_path / "hash_cache.json").write_text(content, encoding="utf-8")
    cache = cache_for(tmp_path)
    assert cache.entries == {}
    assert cache.sha256(f) == sha(f)


def test_an_unreadable_cache_path_is_an_empty_cache(tmp_path):
    (tmp_path / "hash_cache.json").mkdir()  # a directory where the file should be
    assert cache_for(tmp_path).entries == {}


def test_deleting_the_cache_changes_no_stage_decision(tmp_path):
    f = make(tmp_path / "in.bin")
    fp = {"inputs": {"in": sha(f)}, "decisions": {}, "code": {}, "params": {}}
    out = make(tmp_path / "out.bin", fill=5)
    processed = tmp_path / "processed"
    cache = hc.HashCache(hc.default_path(processed), root=tmp_path)
    prov.write_stamp(processed, "s", fp, {"o": out}, cache=cache)
    cache.save()
    with_cache = prov.decide(processed, "s", fp, {"o": out}, cache=hc.HashCache(hc.default_path(processed), root=tmp_path))
    hc.default_path(processed).unlink()
    without_file = prov.decide(processed, "s", fp, {"o": out}, cache=hc.HashCache(hc.default_path(processed), root=tmp_path))
    plain = prov.decide(processed, "s", fp, {"o": out})
    assert with_cache == without_file == plain and plain.action == "skip"


# ------------------------------------------------------------------------------------------------------------------------ 7. scope limits
def test_files_below_one_mib_are_never_cached_and_the_other_hashes_never_touch_the_cache(tmp_path):
    small = make(tmp_path / "small.bin", size=MIB - 1)
    cache = cache_for(tmp_path)
    assert cache.sha256(small) == sha(small) and cache.entries == {} and cache.stats["bypassed"] == 1
    assert hc.MIN_SIZE == MIB

    class Counting(hc.HashCache):
        calls = 0

        def sha256(self, path):
            type(self).calls += 1
            return super().sha256(path)

    counting = Counting(tmp_path / "c.json", root=tmp_path)
    prov.code_hashes(["provenance"])  # code
    prov.decision_hashes(["D25"])  # decisions
    pl._config_hashes()  # configuration
    assert Counting.calls == 0
    prov.file_hashes({"s": small}, counting)  # data files do go through the cache object (and are then bypassed by size)
    assert Counting.calls == 1


# ------------------------------------------------------------------------------------------------- 8. stamps and pipeline are unchanged
def _stamp_body(path: Path) -> dict:
    body = json.loads(path.read_text(encoding="utf-8"))
    body.pop("created_utc")
    return body


def test_stamps_written_with_and_without_the_cache_are_identical_and_the_second_decision_reads_nothing(tmp_path):
    f = make(tmp_path / "out.bin", fill=4)
    fp = {"inputs": {}, "decisions": {}, "code": {}, "params": {"k": 1}}
    cached_dir, plain_dir = tmp_path / "p1", tmp_path / "p2"
    cache = hc.HashCache(hc.default_path(cached_dir), root=tmp_path)
    a = prov.write_stamp(cached_dir, "s", fp, {"o": f}, cache=cache)
    b = prov.write_stamp(plain_dir, "s", fp, {"o": f})
    assert _stamp_body(a) == _stamp_body(b)
    cache.save()
    second = hc.HashCache(hc.default_path(cached_dir), root=tmp_path)
    assert prov.decide(cached_dir, "s", fp, {"o": f}, cache=second) == prov.decide(plain_dir, "s", fp, {"o": f})
    assert second.stats["bytes_read"] == 0 and second.stats["hits"] == 1


def _raw_big(path: Path) -> None:
    make(path, size=MIB + 123, fill=3, age_s=3600)
    data = path.read_bytes()
    path.with_suffix(path.suffix + ".manifest.json").write_text(json.dumps({"source_url": "https://example.org/d", "http_status": 200, "retrieved_at_utc": "2026-10-27T00:00:00+00:00",
                                                                           "sha256": hashlib.sha256(data).hexdigest(), "byte_size": len(data)}), encoding="utf-8")


class _Recorder:
    def __init__(self):
        self.calls: list[str] = []

    def actions(self):
        def make_action(spec):
            def action(ctx, args):
                self.calls.append(spec.key)
                for p in spec.outputs(ctx).values():
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(f"{spec.key}:v1", encoding="utf-8")
                return {}

            return action

        return {s.key: make_action(s) for s in pl.SPECS}


@pytest.fixture
def reference(tmp_path, monkeypatch):
    ref = {"rtol": 1e-9, "n_rows": 2, "totals": [{"scenario": "TB", "year": 2025, "quantity": "curtailed_energy", "component": "total", "central_value": 43.8}]}
    path = tmp_path / "ref.json"
    path.write_text(json.dumps(ref), encoding="utf-8")
    df = pd.DataFrame({"scenario": ["TB", "TB"], "year": [2025, 2030], "quantity": ["curtailed_energy"] * 2, "component": ["total"] * 2, "central_value": [43.8, 60.0]})
    monkeypatch.setattr("curtailmit.results_writer.read_final_results", lambda p: df)
    return path


def _two_runs(tmp_path, monkeypatch, reference, *flags):
    root = tmp_path / ("db_" + "_".join(flags or ("cache",)).replace("-", ""))
    monkeypatch.setenv("DATABASE_ROOT", str(root))
    _raw_big(root / "raw" / "ons" / "capacity_factor" / "big.parquet")
    big = root / "raw" / "ons" / "capacity_factor" / "big.parquet"
    pl.run_pipeline(pl.build_parser().parse_args(list(flags)), actions=_Recorder().actions(), reference_path=reference)
    reads = []
    real = prov.sha256_file

    def counting(path, normalise_newlines=False):
        if Path(path) == big:
            reads.append(str(path))
        return real(path, normalise_newlines)

    monkeypatch.setattr(prov, "sha256_file", counting)
    rec = _Recorder()
    record = pl.run_pipeline(pl.build_parser().parse_args(["--use-cache", *flags]), actions=rec.actions(), reference_path=reference)
    monkeypatch.setattr(prov, "sha256_file", real)
    return record, rec.calls, len(reads), root


def test_pipeline_decisions_are_the_same_with_and_without_the_cache_and_the_cache_reads_less(tmp_path, monkeypatch, reference):
    with_cache, calls_a, reads_a, root_a = _two_runs(tmp_path, monkeypatch, reference)
    without, calls_b, reads_b, root_b = _two_runs(tmp_path, monkeypatch, reference, "--no-hash-cache")
    assert calls_a == calls_b == []  # every stage verified and skipped, both ways
    assert [(s["stage"], s["status"], s["kind"]) for s in with_cache.stages] == [(s["stage"], s["status"], s["kind"]) for s in without.stages]
    assert reads_a < reads_b
    assert reads_a == 1  # only the run manifest, which keeps full hashing of the raw files (no pre-filter shortcut there)
    assert (root_a / "processed" / "pipeline_stamps" / "hash_cache.json").is_file()
    assert not (root_b / "processed" / "pipeline_stamps" / "hash_cache.json").exists()  # --no-hash-cache neither reads nor writes the cache
    for key in pl.STAGES:
        a, b = (_stamp_body(r / "processed" / "pipeline_stamps" / f"{key}.json") for r in (root_a, root_b))
        assert a["fingerprint"] == b["fingerprint"] and a["outputs"].keys() == b["outputs"].keys()


def test_no_hash_cache_flag_is_parsed_and_the_stamp_format_has_no_cache_fields(tmp_path, monkeypatch, reference):
    assert pl.build_parser().parse_args(["--no-hash-cache"]).no_hash_cache is True
    assert pl.build_parser().parse_args([]).no_hash_cache is False
    _, _, _, root = _two_runs(tmp_path, monkeypatch, reference)
    stamp = json.loads((root / "processed" / "pipeline_stamps" / "stage1.json").read_text(encoding="utf-8"))
    assert stamp["schema"] == prov.STAMP_SCHEMA == 1 and set(stamp) == {"schema", "stage", "created_utc", "fingerprint", "outputs", "extra"}


def test_run_manifest_verification_does_not_use_the_cache():
    import inspect

    from curtailmit import run_manifest

    source = inspect.getsource(run_manifest)
    assert "cache" not in source.replace("pip cache", "")  # the raw-file inventory and the artifact hashes are full hashes


def test_the_cache_module_is_outside_every_stage_code_fingerprint():
    modules = {*pl.STAGE1_MODULES, *pl.CALIBRATION_MODULES, *pl.PROJECTION_MODULES, *pl.RESULTS_MODULES}
    assert not ({"hash_cache", "provenance", "pipeline", "doc_generation", "decision_registry"} & modules)
