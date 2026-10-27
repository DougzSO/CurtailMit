"""Reproducibility records (Task 15; decisions D33, D34).

Two artifacts, both derived from facts on disk (nothing is guessed, nothing in the modelling path reads them):

- `logs/run_manifest_<UTC>.json` - written by `curtailmit-run` at the end of every run that reaches SUCCESS or SUCCESS_PARTIAL (never for a failed run: failures are diagnosed in
  `pipeline_run_*.json`; the two record types are deliberately not mixed). It records the code commit, the environment (installed vs locked versions), END_EXCLUSIVE, the configuration and
  adopted-decision hashes, every raw input file with its retrieval metadata (verified against the file at write time) and the hashes of the produced artifacts.
- `data_snapshot_manifest.json` (repository root, committed) - the raw-file part only: relative path, source URL, retrieval time, SHA-256 and size of every raw data file (D33 option 1). An
  external reader re-downloads from the public sources (Stage 1) and checks hash-by-hash with `python -m curtailmit.run_manifest verify`.

A raw file whose bytes do not match its own retrieval manifest, or that has no retrieval manifest, makes the run manifest step fail (a hard gate, exit code 2): the provenance of the inputs
cannot then be stated.

Command line:
    python -m curtailmit.run_manifest snapshot [--raw-root DIR] [--out FILE]   write the data snapshot manifest from the local database
    python -m curtailmit.run_manifest verify   [--raw-root DIR] [--manifest FILE]   compare the local raw files with a committed snapshot manifest (exit 1 on any difference)
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import subprocess
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

from curtailmit import provenance as prov

MANIFEST_SCHEMA = 1
SNAPSHOT_SCHEMA = 1
LOCK_PATH = prov.PROJECT_ROOT / "requirements.lock.txt"
SNAPSHOT_PATH = prov.PROJECT_ROOT / "data_snapshot_manifest.json"
SIDECAR_SUFFIX = ".manifest.json"


class RunManifestError(RuntimeError):
    """The inputs' provenance cannot be stated (raw file without or contradicting its retrieval manifest). A hard gate."""

    def __init__(self, message: str, diagnostics: dict | None = None):
        super().__init__(message)
        self.diagnostics = diagnostics or {}


# ------------------------------------------------------------------------------------------------------------------------------ environment
def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_lock(path: Path = LOCK_PATH) -> dict[str, str]:
    """normalised package name -> pinned version for every `name==version` line (markers after `;` ignored, comments skipped)."""
    pins: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = line.split("#", 1)[0].split(";", 1)[0].strip()
        if not line:
            continue
        m = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9.!+_-]+)", line)
        if not m:
            raise RunManifestError(f"{Path(path).name}: line is not an exact '==' pin: {line!r}")
        pins[_norm(m.group(1))] = m.group(2)
    return pins


def environment_report(lock_path: Path = LOCK_PATH) -> dict:
    """Locked vs installed version of every locked package. A mismatch is recorded, not an error: a run outside the lock is valid but flagged."""
    pins = parse_lock(lock_path) if Path(lock_path).is_file() else {}
    packages, mismatches = {}, []
    for name, locked in sorted(pins.items()):
        try:
            installed = metadata.version(name)
        except metadata.PackageNotFoundError:
            installed = None  # e.g. a platform-restricted pin (colorama on Linux)
        packages[name] = {"locked": locked, "installed": installed}
        if installed is not None and installed != locked:
            mismatches.append(name)
    return {
        "lock_file": Path(lock_path).name if pins else None,
        "lock_file_sha256": prov.sha256_file(Path(lock_path)) if pins else None,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": packages,
        "environment_matches_lock": bool(pins) and not mismatches,
        "mismatches": mismatches,
    }


def git_state(root: Path = prov.PROJECT_ROOT) -> dict:
    """Commit hash and dirty flag of the code checkout; `commit: null` with a reason when git or the repository is not available."""

    def _git(*args: str) -> str:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True, timeout=60).stdout.strip()

    try:
        return {"commit": _git("rev-parse", "HEAD"), "dirty": bool(_git("status", "--porcelain")), "branch": _git("rev-parse", "--abbrev-ref", "HEAD")}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"commit": None, "dirty": None, "branch": None, "unavailable": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------------------------------------------------------------- raw files
def raw_inventory(raw_root: Path) -> list[dict]:
    """One entry per raw data file (sidecar manifests and .gitkeep excluded), sorted by relative path, verified against the file's own retrieval manifest."""
    raw_root = Path(raw_root)
    entries, problems = [], []
    if not raw_root.is_dir():
        return entries
    for path in sorted(raw_root.rglob("*")):
        if not path.is_file() or path.name == ".gitkeep" or path.name.endswith(SIDECAR_SUFFIX):
            continue
        rel = path.relative_to(raw_root).as_posix()
        sidecar = path.with_suffix(path.suffix + SIDECAR_SUFFIX)
        if not sidecar.is_file():
            problems.append({"file": rel, "problem": "no retrieval manifest"})
            continue
        try:
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
            expected_sha, expected_size = meta["sha256"], int(meta["byte_size"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            problems.append({"file": rel, "problem": f"unreadable retrieval manifest ({type(exc).__name__})"})
            continue
        sha, size = prov.sha256_file(path), path.stat().st_size
        if sha != expected_sha or size != expected_size:
            problems.append({"file": rel, "problem": "bytes differ from the retrieval manifest", "manifest_sha256": expected_sha, "file_sha256": sha, "manifest_size": expected_size, "file_size": size})
            continue
        entries.append({"path": rel, "source_url": meta.get("source_url"), "retrieved_at_utc": meta.get("retrieved_at_utc"), "http_status": meta.get("http_status"), "sha256": sha, "byte_size": size})
    if problems:
        shown = "; ".join(f"{p['file']}: {p['problem']}" for p in problems[:3]) + (f" (+{len(problems) - 3} more)" if len(problems) > 3 else "")
        raise RunManifestError(f"raw input provenance cannot be stated for {len(problems)} file(s): {shown}", {"problems": problems[:50], "n_problems": len(problems)})
    return entries


def build_snapshot(raw_root: Path, generated_utc: str | None = None) -> dict:
    files = raw_inventory(raw_root)
    return {
        "schema": SNAPSHOT_SCHEMA,
        "description": "SHA-256, size, source URL and retrieval time of every raw data file used by the CurtailMit production pipeline (decision D33). The data themselves are NOT redistributed: "
                       "re-download from the sources with Stage 1 and verify with `python -m curtailmit.run_manifest verify`. Publishers may revise or remove historical files, so a "
                       "difference is reported, never assumed away.",
        "generated_utc": generated_utc or datetime.now(timezone.utc).isoformat(),
        "n_files": len(files),
        "total_bytes": sum(f["byte_size"] for f in files),
        "files": files,
    }


def write_snapshot(raw_root: Path, out: Path = SNAPSHOT_PATH) -> dict:
    snap = build_snapshot(raw_root)
    Path(out).write_text(json.dumps(snap, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return snap


def verify_snapshot(snapshot: Mapping, raw_root: Path) -> dict:
    """Compare the committed snapshot with the local raw tree. `matching`/`differing`/`missing`/`extra` list relative paths; `ok` only when everything matches and nothing is extra."""
    raw_root = Path(raw_root)
    expected = {f["path"]: f for f in snapshot["files"]}
    local = {}
    for path in sorted(raw_root.rglob("*")) if raw_root.is_dir() else []:
        if path.is_file() and path.name != ".gitkeep" and not path.name.endswith(SIDECAR_SUFFIX):
            local[path.relative_to(raw_root).as_posix()] = path
    matching, differing, missing = [], [], []
    for rel, f in expected.items():
        p = local.get(rel)
        if p is None:
            missing.append(rel)
        elif p.stat().st_size == f["byte_size"] and prov.sha256_file(p) == f["sha256"]:
            matching.append(rel)
        else:
            differing.append(rel)
    extra = sorted(set(local) - set(expected))
    return {"matching": matching, "differing": differing, "missing": missing, "extra": extra, "ok": not (differing or missing or extra)}


# ------------------------------------------------------------------------------------------------------------------------------- run manifest
def build_run_manifest(*, record: Mapping, raw_root: Path, config_hashes: Mapping[str, str], decision_hashes: Mapping[str, str], artifacts: Mapping[str, Path], end_exclusive: str,
                       snapshot_path: Path = SNAPSHOT_PATH, lock_path: Path = LOCK_PATH, project_root: Path = prov.PROJECT_ROOT) -> dict:
    if record.get("status") not in ("SUCCESS", "SUCCESS_PARTIAL"):
        raise RunManifestError(f"a run manifest is written only for SUCCESS or SUCCESS_PARTIAL runs, not {record.get('status')!r}")
    raw_files = raw_inventory(raw_root)
    committed = None
    if Path(snapshot_path).is_file():
        snap = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
        rep = verify_snapshot(snap, raw_root)
        committed = {"file": Path(snapshot_path).name, "sha256": prov.sha256_file(Path(snapshot_path)), "matching": len(rep["matching"]), "differing": rep["differing"][:20],
                     "missing": rep["missing"][:20], "extra": rep["extra"][:20], "identical_to_local_raw": rep["ok"]}
    return {
        "schema": MANIFEST_SCHEMA,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": record["status"],
        "partial": bool(record.get("partial")),
        "run_started_utc": record.get("started_utc"),
        "code": git_state(project_root),
        "environment": environment_report(lock_path),
        "end_exclusive": end_exclusive,
        "config_sha256": dict(config_hashes),
        "decisions_sha256": dict(decision_hashes),
        "stages": [{k: s.get(k) for k in ("stage", "status", "kind", "detail")} for s in record.get("stages", [])],
        "reference_check": record.get("reference_check", {}),
        "raw_inputs": {"n_files": len(raw_files), "total_bytes": sum(f["byte_size"] for f in raw_files), "verified_against_retrieval_manifests": True, "committed_snapshot": committed, "files": raw_files},
        "artifacts_sha256": prov.file_hashes(dict(artifacts)),
    }


def write_run_manifest(logs_dir: Path, **kwargs) -> Path:
    manifest = build_run_manifest(**kwargs)
    Path(logs_dir).mkdir(parents=True, exist_ok=True)
    path = Path(logs_dir) / f"run_manifest_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.json"
    path.write_text(json.dumps(manifest, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    return path


# ------------------------------------------------------------------------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m curtailmit.run_manifest", description=__doc__.split("Command line:")[0].strip().splitlines()[0])
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("snapshot", help="write the data snapshot manifest from the local raw files")
    s.add_argument("--raw-root")
    s.add_argument("--out", default=str(SNAPSHOT_PATH))
    v = sub.add_parser("verify", help="compare the local raw files with a snapshot manifest")
    v.add_argument("--raw-root")
    v.add_argument("--manifest", default=str(SNAPSHOT_PATH))
    args = p.parse_args(argv)

    from curtailmit import paths

    raw_root = Path(args.raw_root) if args.raw_root else paths.resolve_database_root(create=False) / "raw"
    try:
        if args.command == "snapshot":
            snap = write_snapshot(raw_root, Path(args.out))
            print(f"snapshot manifest written: {args.out} ({snap['n_files']} files, {snap['total_bytes']} bytes)")
            return 0
        report = verify_snapshot(json.loads(Path(args.manifest).read_text(encoding="utf-8")), raw_root)
    except RunManifestError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 2
    print(f"snapshot verification: {len(report['matching'])} matching, {len(report['differing'])} differing, {len(report['missing'])} missing, {len(report['extra'])} extra")
    for key in ("differing", "missing", "extra"):
        for rel in report[key][:20]:
            print(f"  {key}: {rel}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
