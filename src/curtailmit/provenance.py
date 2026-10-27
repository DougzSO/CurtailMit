"""Verifiable validity of pipeline stage outputs (Task 14, decisions D31/D32).

A stage output is reused only when a stamp written by the orchestrator proves it is current. The stamp records, at the time the stage ran:
- `inputs`: SHA-256 of every input file (tree of raw files, upstream stage outputs, config files);
- `decisions`: SHA-256 of the entries of the adopted decisions the stage depends on (config/discovered_sources.yaml);
- `code`: SHA-256 of the source files of the modules that produce the output (any edit, including a comment, invalidates: deliberately conservative);
- `params`: the stage parameters;
- `outputs`: SHA-256 of the produced artifacts.

The SHA-256 of a large data file may be obtained through curtailmit.hash_cache (a size / mtime_ns / inode pre-filter that only decides whether the file must be read again; the content hash stays
authoritative, see that module for the guarantees and the residual risk). Code, configuration, decision entries and small files are always hashed in full.

CONSERVATIVE DEFAULT: the stage is re-run whenever the stamp is missing, unreadable, from another schema version, or any recorded item differs from what is on disk now. File existence alone is
never a reason to skip. Nothing here guesses: `decide` returns the reason with the changed items so that the console and the run record can show it.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

STAMP_SCHEMA = 1
STAMP_DIRNAME = "pipeline_stamps"
PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parents[1]
DECISIONS_PATH = PROJECT_ROOT / "config" / "discovered_sources.yaml"
SECTIONS = ("inputs", "decisions", "code", "params")


class ProvenanceError(RuntimeError):
    """A fingerprint cannot be built (unknown module or decision id): a configuration error, never ignored."""


def sha256_file(path: Path, normalise_newlines: bool = False) -> str:
    h = hashlib.sha256()
    if normalise_newlines:  # source files: CRLF/LF differences (git autocrlf) must not change the fingerprint
        h.update(Path(path).read_bytes().replace(b"\r\n", b"\n"))
        return h.hexdigest()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _content_hash(path: Path, cache) -> str:
    """SHA-256 of a data file. `cache` (curtailmit.hash_cache.HashCache or None) may only decide that the file need not be read again; the hash returned is always the file's content hash."""
    return cache.sha256(path) if cache is not None else sha256_file(path)


def file_hashes(paths: Mapping[str, Path], cache=None) -> dict[str, str]:
    """name -> SHA-256 for the files that exist; absent files are simply not listed (so a later difference shows up as a change)."""
    return {name: _content_hash(p, cache) for name, p in sorted(paths.items()) if Path(p).is_file()}


def tree_hashes(root: Path, suffixes: Iterable[str] | None = None, cache=None) -> dict[str, str]:
    """relative posix path -> SHA-256 for every file under `root` (optionally only the given suffixes); `.gitkeep` is ignored."""
    root = Path(root)
    if not root.is_dir():
        return {}
    keep = tuple(suffixes) if suffixes is not None else None
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name != ".gitkeep" and (keep is None or p.suffix in keep):
            out[p.relative_to(root).as_posix()] = _content_hash(p, cache)
    return out


def code_hashes(modules: Iterable[str]) -> dict[str, str]:
    out = {}
    for m in modules:
        path = PACKAGE_DIR / f"{m}.py"
        if not path.is_file():
            raise ProvenanceError(f"module {m!r} listed in a stage fingerprint does not exist at {path}")
        out[m] = sha256_file(path, normalise_newlines=True)
    return out


# Keys of a decision entry that exist only for documentation (Task 16, generated limitations page and decision register). They are left out of the decision hash so that adding or rewording
# them recomputes no stage. The default stays conservative: any key NOT listed here is hashed, so a new key invalidates stamps until someone deliberately lists it.
DOC_ONLY_KEYS = frozenset({"theme", "limitation", "limitation_reason", "superseded_in_practice_by"})


def decision_hash(entry: Mapping) -> str:
    """SHA-256 of a decision entry without its documentation-only keys."""
    content = {k: v for k, v in entry.items() if k not in DOC_ONLY_KEYS}
    return hashlib.sha256(json.dumps(content, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")).hexdigest()


def decision_hashes(ids: Iterable[str], path: Path | None = None) -> dict[str, str]:
    with open(path or DECISIONS_PATH, encoding="utf-8") as f:
        decisions = yaml.safe_load(f)["decisions"]
    out = {}
    for i in ids:
        if i not in decisions:
            raise ProvenanceError(f"decision {i} listed in a stage fingerprint is not in discovered_sources.yaml")
        out[i] = decision_hash(decisions[i])
    return out


def stamp_path(processed_dir: Path, stage: str) -> Path:
    return Path(processed_dir) / STAMP_DIRNAME / f"{stage}.json"


def write_stamp(processed_dir: Path, stage: str, fingerprint: dict, outputs: Mapping[str, Path], extra: dict | None = None, cache=None) -> Path:
    """Record the fingerprint (computed AFTER the stage ran) together with the hashes of the artifacts it produced. Atomic replace."""
    path = stamp_path(processed_dir, stage)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"schema": STAMP_SCHEMA, "stage": stage, "created_utc": datetime.now(timezone.utc).isoformat(), "fingerprint": fingerprint, "outputs": file_hashes(outputs, cache), "extra": extra or {}}
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(body, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


def read_stamp(processed_dir: Path, stage: str) -> dict | None:
    path = stamp_path(processed_dir, stage)
    if not path.is_file():
        return None
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return body if isinstance(body, dict) and body.get("schema") == STAMP_SCHEMA and body.get("stage") == stage else None


@dataclass(frozen=True)
class Decision:
    """action: 'skip' | 'run'; kind: 'cached' | 'missing' | 'stale' | 'forced'; detail: human-readable reason."""

    action: str
    kind: str
    detail: str

    @property
    def label(self) -> str:
        return f"SKIPPED (cached, {self.detail})" if self.action == "skip" else f"RAN ({self.kind}: {self.detail})"


def _diff(old: Mapping, new: Mapping) -> list[str]:
    keys = sorted(set(old) | set(new))
    return [k for k in keys if old.get(k) != new.get(k)]


def compare(stamp: dict, fingerprint: dict, outputs: Mapping[str, Path], cache=None) -> list[str]:
    """Everything that differs between the stamp and the present state (empty list = verified current)."""
    problems = []
    recorded = stamp.get("fingerprint", {})
    for section in SECTIONS:
        old, new = recorded.get(section, {}), fingerprint.get(section, {})
        changed = _diff(old, new)
        if changed:
            shown = ", ".join(changed[:4]) + (f" (+{len(changed) - 4} more)" if len(changed) > 4 else "")
            problems.append(f"{section} changed: {shown}")
    now = file_hashes(outputs, cache)
    out_changed = _diff(stamp.get("outputs", {}), now)
    if out_changed or set(now) != set(outputs):
        missing = sorted(set(outputs) - set(now))
        problems.append("outputs " + (f"missing: {', '.join(missing)}" if missing else f"modified since the stamp: {', '.join(out_changed[:4])}"))
    return problems


def decide(processed_dir: Path, stage: str, fingerprint: dict, outputs: Mapping[str, Path], force: bool = False, trust_blocker: str | None = None, cache=None) -> Decision:
    """Skip only when the stamp verifies the existing outputs against the CURRENT fingerprint. `trust_blocker` is a reason the stamp cannot be trusted even when it matches (for example
    Stage 1: remote data freshness cannot be verified offline); it turns an otherwise valid cache into a re-run."""
    if force:
        return Decision("run", "forced", "override flag")
    stamp = read_stamp(processed_dir, stage)
    if stamp is None:
        return Decision("run", "missing", "no valid stamp: outputs cannot be verified, so the stage is recomputed")
    if not all(Path(p).is_file() for p in outputs.values()):
        return Decision("run", "missing", "output artifact(s) not found")
    problems = compare(stamp, fingerprint, outputs, cache)
    if problems:
        return Decision("run", "stale", "; ".join(problems))
    if trust_blocker:
        return Decision("run", "stale", trust_blocker)
    return Decision("skip", "cached", f"stamp {stamp['created_utc'][:19]}Z verified: inputs, decisions, code, params and outputs unchanged")
