"""Decision register (Task 15, decision D34; generated block since Task 16).

One line per decision (number, short description, status, where decided, implemented in), built from the two places the decisions live and written between GENERATED markers into
docs/reproducibility.md by `curtailmit.doc_generation` (block id `decision-register`), so that the two sources cannot disagree with the document. This module reads and renders;
the marker handling, `--write` and `--check` are in doc_generation:

- D1-D12: the changelog table of docs/roadmap.md ("Decisions closed since v3") and the "Decision D12" section of the same file. They are NOT rewritten into the YAML (the adopted texts are the audit trail).
- D13 onwards: `decisions:` in config/discovered_sources.yaml (read with a loader that refuses duplicate keys, which PyYAML would otherwise resolve silently by keeping the last one).

    python -m curtailmit.doc_generation --check     every generated block (also enforced by tests/test_doc_generation.py and tests/test_decision_registry.py)
    python -m curtailmit.doc_generation --write     regenerate them

`python -m curtailmit.decision_registry --check|--write` still works as an alias restricted to the decision-register block.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

from curtailmit import provenance as prov

ROADMAP = prov.PROJECT_ROOT / "docs" / "roadmap.md"
DOCUMENT = prov.PROJECT_ROOT / "docs" / "reproducibility.md"
BLOCK_ID = "decision-register"
STATUSES = {"adopted", "pending", "rejected", "superseded", "reference_only"}

# Identifiers that appear in older documents for something that was never a registered decision. They stay unregistered; the text that uses them must say "-candidate".
UNREGISTERED_CANDIDATES = {"D27": "sub-hourly feasibility candidate of Task 11E4 (negative result, never adopted)"}


class RegistryError(RuntimeError):
    """The decision sources are inconsistent (duplicate key, collision, gap, unknown status)."""


class _StrictLoader(yaml.SafeLoader):
    pass


def _no_duplicates(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    seen = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise RegistryError(f"duplicate YAML key {key!r} (line {key_node.start_mark.line + 1}): PyYAML would silently keep only the last one")
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


_StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicates)


def _cell(text: object, limit: int = 110) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip().replace("|", "/")
    return (s[: limit - 1].rstrip() + "...") if len(s) > limit else (s or "-")


def _number(decision_id: str) -> int:
    return int(decision_id[1:])


def yaml_decisions(path: Path = prov.DECISIONS_PATH) -> dict[str, dict]:
    data = yaml.load(Path(path).read_text(encoding="utf-8"), Loader=_StrictLoader)
    return dict(data["decisions"])


def roadmap_decisions(path: Path = ROADMAP) -> dict[str, dict]:
    """D1-D11 from the changelog table, D12 (and any later 'Decision Dn' section) from its heading and bold title."""
    text = Path(path).read_text(encoding="utf-8")
    out: dict[str, dict] = {}
    for m in re.finditer(r"^\| (D\d+) \| (.+?) \| (.+) \|\s*$", text, re.MULTILINE):
        if m.group(1) in out:
            raise RegistryError(f"{m.group(1)} appears twice in the roadmap decision table")
        out[m.group(1)] = {"topic": m.group(2).strip(), "status": "adopted", "where": "roadmap, table"}
    for m in re.finditer(r"^## Decision (D\d+)\b.*\n+\*\*(D\d+): (.+?)\.?\*\*", text, re.MULTILINE):
        if m.group(1) in out:
            raise RegistryError(f"{m.group(1)} is defined both in the roadmap table and in its own section")
        out[m.group(1)] = {"topic": m.group(3).strip(), "status": "adopted", "where": "roadmap, own section"}
    return out


def collect(yaml_path: Path = prov.DECISIONS_PATH, roadmap_path: Path = ROADMAP) -> list[dict]:
    """All decisions sorted by number. Raises RegistryError on a collision, an unknown status or a numbering gap."""
    road, ydec = roadmap_decisions(roadmap_path), yaml_decisions(yaml_path)
    clash = sorted(set(road) & set(ydec), key=_number)
    if clash:
        raise RegistryError(f"decision number(s) defined in both the roadmap and the YAML: {clash}")
    rows = []
    for i, d in road.items():
        rows.append({"id": i, "topic": d["topic"], "status": d["status"], "where": d["where"], "implemented_in": "-", "superseded_in_practice_by": None})
    for i, d in ydec.items():
        if not re.fullmatch(r"D\d+", i):
            raise RegistryError(f"malformed decision id {i!r} in the YAML")
        status = d.get("status")
        if status not in STATUSES:
            raise RegistryError(f"{i}: unknown status {status!r}")
        task = re.match(r"(Task [0-9A-Za-z]+(?:-[0-9A-Za-z]+)?)", str(d.get("source_task") or ""))
        rows.append({"id": i, "topic": d.get("topic"), "status": status, "where": f"YAML, {task.group(1) if task else d.get('date') or 'n/a'}", "implemented_in": str(d.get("implemented_in") or "-").split(";")[0], "superseded_in_practice_by": d.get("superseded_in_practice_by")})
    rows.sort(key=lambda r: _number(r["id"]))
    numbers = [_number(r["id"]) for r in rows]
    if numbers != list(range(1, len(numbers) + 1)):
        gaps = sorted(set(range(1, max(numbers) + 1)) - set(numbers))
        raise RegistryError(f"decision numbering is not contiguous from D1: missing {gaps}")
    return rows


def render(rows: list[dict]) -> str:
    """The body of the generated block (doc_generation adds the BEGIN / END markers). A decision with `superseded_in_practice_by` shows it next to its status (documentation only: the status is unchanged)."""
    lines = ["| # | Decision | Status | Decided in | Implemented in |", "|---|---|---|---|---|"]
    for r in rows:
        status = r["status"] + (f" (superseded in practice by {r['superseded_in_practice_by']})" if r.get("superseded_in_practice_by") else "")
        lines.append(f"| {r['id']} | {_cell(r['topic'])} | {status} | {_cell(r['where'], 80)} | {_cell(r['implemented_in'], 90)} |")
    lines += ["", f"{len(rows)} decisions: " + ", ".join(f"{sum(r['status'] == s for r in rows)} {s}" for s in sorted({r["status"] for r in rows})) + ".", ""]
    lines.append("**Numbering note.** " + " ".join(f"`{k}` in older documents (Task 11E4, `docs/task11e4_findings.md`) denotes the {v}; it is written `{k}-candidate` there and is NOT the adopted `{k}` of this table." for k, v in UNREGISTERED_CANDIDATES.items()))
    return "\n".join(lines)


def current_block(document: Path = DOCUMENT) -> str | None:
    """The marked block as it stands in the document (None when the markers are absent)."""
    from curtailmit import doc_generation as gen

    return gen.current_block_text(document, BLOCK_ID)


def update_document(document: Path = DOCUMENT, **sources) -> bool:
    """Rewrite the generated block; returns True when the file changed."""
    from curtailmit import doc_generation as gen

    registered = gen.BLOCKS[BLOCK_ID]
    src = gen.Sources(**{k: v for k, v in sources.items() if v is not None})
    document = Path(document)
    one = gen.Block(BLOCK_ID, document.name, registered.render, registered.sources)
    try:
        return bool(gen.write(document.parent, src, blocks={BLOCK_ID: one}))
    except gen.DocGenerationError as exc:
        raise RegistryError(str(exc)) from exc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m curtailmit.decision_registry", description="Alias of `python -m curtailmit.doc_generation --only decision-register`.")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", action="store_true")
    g.add_argument("--check", action="store_true")
    args = p.parse_args(argv)
    from curtailmit import doc_generation as gen

    try:
        if args.write:
            changed = gen.write(only=[BLOCK_ID])
            print("docs/reproducibility.md updated" if changed else "docs/reproducibility.md already up to date")
            return 0
        if gen.check(only=[BLOCK_ID]):
            print("docs/reproducibility.md decision register is out of date: run `python -m curtailmit.doc_generation --write`", file=sys.stderr)
            return 1
        print("decision register up to date")
        return 0
    except (RegistryError, gen.DocGenerationError) as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
