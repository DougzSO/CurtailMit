"""Metadata pre-filter for the SHA-256 of large files (Task 16, Part B of docs/task16_design.md).

THE CONTENT HASH REMAINS AUTHORITATIVE for every skip / recompute decision: a pipeline stage is skipped only when the hashes recorded in its stamp equal the hashes of the files now. This cache
answers a different and narrower question: "do I have to read this file again to know its hash?". Where it can show that the file is the one it hashed earlier, the earlier hash is returned;
in every other case the file is read and hashed in full, exactly as without the cache. It never makes a stage-level decision and never changes the conservative default (recompute when in doubt).

A recorded hash is reused only if ALL of these hold (otherwise the file is hashed and the entry replaced):
1. the file is at least MIN_SIZE (1 MiB); smaller files, code, configuration and decision entries are never looked up here (reading them costs nothing);
2. an entry exists for the path, with the same size, the same `st_mtime_ns` (equality, never "not newer than": a restored older file differs) and the same inode (when both are known);
3. racy guard: the file had already been quiet for GUARD_NS (5 s, longer than the coarsest supported timestamp tick, FAT's 2 s) when it was hashed, so a later write cannot have kept the same
   timestamp (the idea of git's "racily clean" index entries). Files written within the guard window are re-hashed on the next run, and are then old enough to be trusted;
4. the modification time is not in the future relative to the time the hash was taken (clock skew or a tampered timestamp forces a re-hash).

RESIDUAL RISK, accepted and tested by name (tests/test_hash_cache.py::test_forged_metadata_is_the_documented_residual_risk): content that changes while size, mtime and inode stay equal to the
recorded values (and the recorded mtime was already old) returns the stale hash. It is the residual weakness of every metadata quick-check (git index, rsync default) and is outside the threat
model of accidental staleness; `curtailmit-run --no-hash-cache` hashes everything in full and neither reads nor writes the cache. Supported configuration: local disk (on a network share whose clock
differs from the local clock the guard may be too lax; use --no-hash-cache there).

The cache file is `processed/pipeline_stamps/hash_cache.json` (schema 1). It is separate from the stamps, whose format is unchanged, so no stamp is invalidated by it. Deleting it is always safe.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from curtailmit import provenance as prov

CACHE_SCHEMA = 1
CACHE_NAME = "hash_cache.json"
MIN_SIZE = 1 << 20  # 1 MiB
GUARD_NS = 5_000_000_000  # 5 s


class HashCache:
    """Path -> (size, mtime_ns, ino, sha256, hashed_at_ns), consulted only through `sha256`. Not thread-safe (the pipeline is single-threaded)."""

    def __init__(self, path: Path, root: Path | None = None, enabled: bool = True, clock_ns=time.time_ns):
        self.path = Path(path)
        self.root = Path(root) if root is not None else None
        self.enabled = enabled
        self._clock = clock_ns
        self.entries: dict[str, dict] = {}
        self.dirty = False
        self.stats = {"hits": 0, "rehashed": 0, "bypassed": 0, "bytes_read": 0}
        if enabled:
            self.entries = self._load()

    # ------------------------------------------------------------------------------------------------------------------------------ persistence
    def _load(self) -> dict[str, dict]:
        """A missing, unreadable, malformed or other-schema cache is an empty cache (like provenance.read_stamp)."""
        try:
            body = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(body, dict) or body.get("schema") != CACHE_SCHEMA or not isinstance(body.get("entries"), dict):
            return {}
        good = {}
        for key, e in body["entries"].items():
            if isinstance(e, dict) and isinstance(e.get("sha256"), str) and all(isinstance(e.get(k), int) for k in ("size", "mtime_ns", "ino", "hashed_at_ns")):
                good[str(key)] = e
        return good

    def save(self) -> bool:
        """Atomic write; entries of files that no longer exist are dropped. Returns True when a file was written. Does nothing when disabled or unchanged."""
        if not self.enabled or not self.dirty:
            return False
        live = {k: e for k, e in self.entries.items() if self._resolve(k).is_file()}
        body = {"schema": CACHE_SCHEMA, "written_utc": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()), "guard_ns": GUARD_NS, "entries": dict(sorted(live.items()))}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(body, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)
        self.dirty = False
        return True

    # --------------------------------------------------------------------------------------------------------------------------------- lookup
    def _key(self, path: Path) -> str:
        p = Path(path)
        if self.root is not None:
            try:
                return p.resolve().relative_to(self.root.resolve()).as_posix()
            except ValueError:
                pass
        return p.resolve().as_posix()

    def _resolve(self, key: str) -> Path:
        k = Path(key)
        return k if k.is_absolute() else (self.root / k if self.root is not None else k)

    def _trusted(self, e: dict, st: os.stat_result) -> bool:
        if e["size"] != st.st_size or e["mtime_ns"] != st.st_mtime_ns:
            return False
        if e["ino"] and st.st_ino and e["ino"] != st.st_ino:
            return False
        if e["hashed_at_ns"] - e["mtime_ns"] < GUARD_NS:  # racy: the file was modified shortly before it was hashed
            return False
        return e["mtime_ns"] <= e["hashed_at_ns"]  # an mtime from the future is not trusted

    def sha256(self, path: Path) -> str:
        """SHA-256 of the file; reads it unless the recorded hash of the same unchanged, long-quiet file can be reused."""
        p = Path(path)
        st = p.stat()
        if not self.enabled or st.st_size < MIN_SIZE:
            self.stats["bypassed"] += 1
            return prov.sha256_file(p)
        key = self._key(p)
        e = self.entries.get(key)
        if e is not None and self._trusted(e, st):
            self.stats["hits"] += 1
            return e["sha256"]
        hashed_at = self._clock()  # taken BEFORE reading, so a write during or after the read has an mtime >= hashed_at
        digest = prov.sha256_file(p)
        self.stats["rehashed"] += 1
        self.stats["bytes_read"] += st.st_size
        after = p.stat()
        if (after.st_size, after.st_mtime_ns) == (st.st_size, st.st_mtime_ns):  # changed while being read: not recorded
            self.entries[key] = {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "ino": int(st.st_ino), "sha256": digest, "hashed_at_ns": int(hashed_at)}
            self.dirty = True
        return digest


def default_path(processed_dir: Path) -> Path:
    return Path(processed_dir) / prov.STAMP_DIRNAME / CACHE_NAME
