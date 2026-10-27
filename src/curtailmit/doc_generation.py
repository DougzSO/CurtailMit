"""Generated documentation blocks (Task 16; design in docs/task16_design.md).

One mechanism for every document that repeats information that lives in a structured source (the decision register, the limitations of the adopted decisions, the pipeline stage sequence). A
document is a hand-written file with one or more generated blocks between markers:

    <!-- GENERATED:BEGIN id=decision-register sources=roadmap.md,discovered_sources.yaml
         do not edit by hand; regenerate with: python -m curtailmit.doc_generation --write -->
    ... generated content ...
    <!-- GENERATED:END id=decision-register -->

The generator replaces only the text from the BEGIN marker to the END marker; everything outside the markers is left byte for byte as it was (append-only history is never touched). Block bodies are
plain Python string assembly; there is no templating dependency.

    python -m curtailmit.doc_generation --check [--only ID,ID]   exit 1 when a block is stale, 2 when a source is inconsistent
    python -m curtailmit.doc_generation --write [--only ID,ID]   regenerate the blocks
    python -m curtailmit.doc_generation --list                   block id -> document -> sources

`--check` also compares the committed fixture of the production-table caveat texts (tests/fixtures/final_results/limitation_texts.json) with the live final_results.parquet when the local database
holds one; in CI there is no database and the comparison is reported as skipped.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from curtailmit import decision_registry as dr
from curtailmit import provenance as prov

PROJECT_ROOT = prov.PROJECT_ROOT
FIXTURE_PATH = PROJECT_ROOT / "tests" / "fixtures" / "final_results" / "limitation_texts.json"
COMMAND = "python -m curtailmit.doc_generation --write"

BEGIN_RE = re.compile(r"<!-- GENERATED:BEGIN id=([a-z0-9-]+)\b.*?-->", re.DOTALL)
END_RE = re.compile(r"<!-- GENERATED:END id=([a-z0-9-]+) -->")

# Fixed theme vocabulary of the limitations page: slug -> (section title, where the longer prose lives). Adding a theme is a one-line change here; a decision that fits none stops the check.
THEMES: dict[str, tuple[str, str]] = {
    "drift": ("Residual drift of the wind curtailment", "[methodology](methodology.md), sections 2.3h and 2.3j"),
    "support-extrapolation": ("Extrapolation beyond the observed support", "[methodology](methodology.md), sections 2.3j and 2.3k"),
    "flexibility-transmission": ("Flexibility held fixed; transmission expansion not modelled", "[methodology](methodology.md), sections 2.3g and 2.3j"),
    "solar-record": ("Short solar record", "[methodology](methodology.md), section 2.3j"),
    "generation-basis": ("Generation basis of the scenarios and of the calibration", "[methodology](methodology.md), sections 2.3g and 3.7"),
    "emission-factors": ("Emission factors", "[methodology](methodology.md), section 2.3k"),
    "hydrogen-sec": ("Hydrogen: fixed specific energy consumption", "[methodology](methodology.md), section 2.3k"),
    "data-provenance": ("Data availability and licensing", "[reproducibility](reproducibility.md), section 1, and [pre-submission checklist](pre_submission_checklist.md)"),
    "historical-validation": ("Historical validation", "[acceptance criteria status](acceptance_criteria_status.md), criterion 5, and [Task 11E2 findings](task11e2_findings.md)"),
    "reproducibility-scope": ("What reproducibility promises", "[reproducibility](reproducibility.md)"),
}
# Decisions from this number on must state a limitation or an explicit `none` with a reason; earlier ones may carry the fields (optional).
FIRST_REQUIRED = 23
# Ids that appear in the `known_limitations` column of the production table, and what they refer to.
ROW_LIMITATION_IDS = {"D25": "D25 (residual drift of the wind curtailment rate)", "SOLAR_SHORT_RECORD": "short solar record (30 months)", "D26_NOTE": "D26 sensitivity note on transmission", "REFERENCE_NOT_PRODUCTION": "reference, not production"}
_NUMBER = re.compile(r"\d+\.\d+|\d{2,}")


class DocGenerationError(RuntimeError):
    """A source is inconsistent or a document's markers are malformed."""


# ------------------------------------------------------------------------------------------------------------------------------------ sources
@dataclass
class Sources:
    """Every input of a block, loaded once and lazily. Tests pass synthetic paths."""

    yaml_path: Path = prov.DECISIONS_PATH
    roadmap_path: Path = dr.ROADMAP
    fixture_path: Path = FIXTURE_PATH
    _cache: dict = field(default_factory=dict, repr=False)

    def decisions(self) -> dict[str, dict]:
        if "decisions" not in self._cache:
            self._cache["decisions"] = dr.yaml_decisions(self.yaml_path)
        return self._cache["decisions"]

    def register_rows(self) -> list[dict]:
        if "rows" not in self._cache:
            self._cache["rows"] = dr.collect(self.yaml_path, self.roadmap_path)
        return self._cache["rows"]

    def row_texts(self) -> dict:
        if "fixture" not in self._cache:
            try:
                self._cache["fixture"] = json.loads(Path(self.fixture_path).read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise DocGenerationError(f"limitation-text fixture {self.fixture_path} cannot be read: {exc}") from exc
        return self._cache["fixture"]


# ----------------------------------------------------------------------------------------------------------------------- limitation schema
def _own_text(entry: Mapping) -> str:
    """All text of a decision entry except the documentation-only keys (what a number in a limitation has to be found in)."""

    def flat(v: object) -> list[str]:
        if isinstance(v, Mapping):
            return [s for x in v.values() for s in flat(x)]
        if isinstance(v, (list, tuple)):
            return [s for x in v for s in flat(x)]
        return [str(v)]

    return " ".join(s for k, v in entry.items() if k not in prov.DOC_ONLY_KEYS for s in flat(v))


def schema_problems(decisions: Mapping[str, Mapping]) -> list[str]:
    """Every violation of the `limitation` schema (S2: a list of {theme, text}, or `none` + `limitation_reason`); an empty list means the YAML is consistent."""
    problems = []
    for did, d in decisions.items():
        number = int(did[1:])
        typos = [k for k in d if k not in prov.DOC_ONLY_KEYS and re.match(r"(limit|theme|supersed)", str(k)) and k != "superseded_in_part_by"]
        if typos:
            problems.append(f"{did}: unknown key(s) {typos}; the documentation keys are {sorted(prov.DOC_ONLY_KEYS)}")
        if "theme" in d:
            problems.append(f"{did}: a top-level `theme` key is not part of the schema; use `limitation: [{{theme, text}}]`")
        lim = d.get("limitation")
        if lim is None:
            if number >= FIRST_REQUIRED and d.get("status") == "adopted":
                problems.append(f"{did}: adopted decision without `limitation` (a list of {{theme, text}} or `none` with `limitation_reason`)")
            if "limitation_reason" in d:
                problems.append(f"{did}: `limitation_reason` without `limitation`")
            continue
        if d.get("status") != "adopted":
            problems.append(f"{did}: a limitation is only allowed on an adopted decision (status is {d.get('status')!r})")
        if lim == "none":
            if not str(d.get("limitation_reason") or "").strip():
                problems.append(f"{did}: `limitation: none` needs a non-empty `limitation_reason`")
            continue
        if "limitation_reason" in d:
            problems.append(f"{did}: `limitation_reason` goes only with `limitation: none`")
        if not isinstance(lim, list) or not lim:
            problems.append(f"{did}: `limitation` must be `none` or a non-empty list of {{theme, text}}")
            continue
        own = _own_text(d)
        for item in lim:
            if not isinstance(item, Mapping) or set(item) != {"theme", "text"}:
                problems.append(f"{did}: each limitation needs exactly the keys theme and text, got {item!r}")
                continue
            if item["theme"] not in THEMES:
                problems.append(f"{did}: unknown theme {item['theme']!r}; known themes: {sorted(THEMES)}")
            text = str(item["text"] or "").strip()
            if not text:
                problems.append(f"{did}: empty limitation text for theme {item['theme']!r}")
            missing = sorted({n for n in _NUMBER.findall(text) if n not in own})
            if missing:
                problems.append(f"{did}: number(s) {missing} in the {item['theme']!r} limitation do not occur in the decision's own text")
    return problems


def _require_valid(src: Sources) -> None:
    problems = schema_problems(src.decisions())
    if problems:
        raise DocGenerationError("limitation schema: " + "; ".join(problems))


def limitation_entries(decisions: Mapping[str, Mapping]) -> list[dict]:
    """[{id, status, themes, items:[{theme,text}], reason, superseded_in_practice_by}] for every decision carrying a `limitation`, ordered by number."""
    out = []
    for did in sorted(decisions, key=lambda k: int(k[1:])):
        d = decisions[did]
        if "limitation" not in d:
            continue
        items = [] if d["limitation"] == "none" else [{"theme": i["theme"], "text": " ".join(str(i["text"]).split())} for i in d["limitation"]]
        out.append({"id": did, "status": d["status"], "items": items, "reason": " ".join(str(d.get("limitation_reason") or "").split()), "superseded_in_practice_by": d.get("superseded_in_practice_by")})
    return out


# ----------------------------------------------------------------------------------------------------------------------------- block bodies
def _link(did: str) -> str:
    return f"[{did}](../config/discovered_sources.yaml)"


def render_limitations_themes(src: Sources) -> str:
    _require_valid(src)
    entries = limitation_entries(src.decisions())
    lines = []
    for slug, (title, pointer) in THEMES.items():
        hits = [(e, i) for e in entries for i in e["items"] if i["theme"] == slug]
        if not hits:
            continue
        lines += [f"### {title}", "", f"Longer prose: {pointer}.", ""]
        lines += [f"- **{_link(e['id'])}** ({e['status']}): {i['text']}" for e, i in hits]
        lines.append("")
    return "\n".join(lines).rstrip()


def render_limitations_appendix(src: Sources) -> str:
    _require_valid(src)
    lines = ["| Decision | Status | Themes | Limitation statement |", "|---|---|---|---|"]
    for e in limitation_entries(src.decisions()):
        themes = ", ".join(f"`{i['theme']}`" for i in e["items"]) or "-"
        status = e["status"] + (f"; superseded in practice by {e['superseded_in_practice_by']}" if e["superseded_in_practice_by"] else "")
        if e["items"]:
            body = " ".join(f"{i['text']}" for i in e["items"]).replace("|", "/")
        else:
            body = f"No reader-facing limitation: {e['reason']}".replace("|", "/")
        lines.append(f"| {_link(e['id'])} | {status} | {themes} | {body} |")
    return "\n".join(lines)


def _scenario_years(pairs: list) -> str:
    by: dict[str, list[int]] = {}
    for scenario, year in pairs:
        by.setdefault(scenario, []).append(int(year))
    return "; ".join(f"{s} {', '.join(str(y) for y in sorted(ys))}" for s, ys in sorted(by.items()))


def render_limitations_row_caveats(src: Sources) -> str:
    fx = src.row_texts()
    lines = [f"The production table `final_results` ({fx['rows_total']} rows) carries {len(fx['texts'])} distinct caveat texts in `known_limitations_text`, reproduced verbatim. Each row also carries the ids in `known_limitations`.", ""]
    for n, t in enumerate(fx["texts"], 1):
        ids = [i for i in str(t["known_limitations"]).split(";") if i]
        unknown = [i for i in ids if i not in ROW_LIMITATION_IDS]
        if unknown:
            raise DocGenerationError(f"fixture caveat {n} carries known_limitations id(s) {unknown} that this module cannot map to a decision or note")
        lines += [f"**Caveat {n}** - `support_status` = `{t['support_status']}`; ids: {', '.join(ROW_LIMITATION_IDS[i] for i in ids)}; {t['n_rows']} rows; scenario-years: {_scenario_years(t['scenario_years'])}.", "", f"> {t['text']}", ""]
    return "\n".join(lines).rstrip()


def render_decision_register(src: Sources) -> str:
    return dr.render(src.register_rows())


def render_pipeline_sequence(src: Sources) -> str:
    from curtailmit.pipeline import PIPELINE_SEQUENCE

    return "`" + " -> ".join(PIPELINE_SEQUENCE) + "`\n\n(Generated from `curtailmit.pipeline.PIPELINE_SEQUENCE`; each stage is skipped only when its stamp verifies.)"


# ----------------------------------------------------------------------------------------------------------------------------------- blocks
@dataclass(frozen=True)
class Block:
    id: str
    document: str
    render: Callable[[Sources], str]
    sources: tuple[str, ...]
    needs_database: bool = False


BLOCKS: dict[str, Block] = {b.id: b for b in (
    Block("decision-register", "docs/reproducibility.md", render_decision_register, ("roadmap.md", "discovered_sources.yaml")),
    Block("pipeline-sequence", "docs/orchestration.md", render_pipeline_sequence, ("pipeline.py",)),
    Block("limitations-themes", "docs/limitations_summary.md", render_limitations_themes, ("discovered_sources.yaml",)),
    Block("limitations-row-caveats", "docs/limitations_summary.md", render_limitations_row_caveats, ("limitation_texts.json",)),
    Block("limitations-decision-appendix", "docs/limitations_summary.md", render_limitations_appendix, ("discovered_sources.yaml",)),
)}


def begin_marker(block: Block) -> str:
    return f"<!-- GENERATED:BEGIN id={block.id} sources={','.join(block.sources)}\n     do not edit by hand; regenerate with: {COMMAND} -->"


def end_marker(block: Block) -> str:
    return f"<!-- GENERATED:END id={block.id} -->"


def render_block(block: Block, src: Sources) -> str:
    """The complete marked block: BEGIN marker, blank line, body, blank line, END marker."""
    return f"{begin_marker(block)}\n\n{block.render(src).strip(chr(10))}\n\n{end_marker(block)}"


# --------------------------------------------------------------------------------------------------------------------------- marker handling
def find_blocks(text: str, name: str = "document") -> dict[str, tuple[int, int]]:
    """id -> (start of the BEGIN marker, end of the END marker). Raises DocGenerationError on unpaired, nested or repeated markers."""
    events = sorted([(m.start(), m.end(), "B", m.group(1)) for m in BEGIN_RE.finditer(text)] + [(m.start(), m.end(), "E", m.group(1)) for m in END_RE.finditer(text)])
    found: dict[str, tuple[int, int]] = {}
    open_id, open_at = None, 0
    for start, end, kind, bid in events:
        if kind == "B":
            if open_id is not None:
                raise DocGenerationError(f"{name}: block {bid!r} begins inside block {open_id!r} (nesting is not allowed)")
            if bid in found:
                raise DocGenerationError(f"{name}: block id {bid!r} appears twice")
            open_id, open_at = bid, start
        else:
            if open_id != bid:
                raise DocGenerationError(f"{name}: END marker of {bid!r} without a matching BEGIN" if open_id is None else f"{name}: END marker of {bid!r} inside block {open_id!r}")
            found[bid] = (open_at, end)
            open_id = None
    if open_id is not None:
        raise DocGenerationError(f"{name}: block {open_id!r} has no END marker")
    return found


def _read_text(path: Path) -> tuple[str, str]:
    """(text with LF newlines, newline used by the file). Line endings follow git autocrlf; blocks are compared and written with LF and the file's own newline is restored."""
    raw = Path(path).read_bytes().decode("utf-8-sig")
    return raw.replace("\r\n", "\n"), ("\r\n" if "\r\n" in raw else "\n")


def _has_bom(path: Path) -> bool:
    return Path(path).read_bytes()[:3] == b"\xef\xbb\xbf"


def current_block_text(document: Path, block_id: str) -> str | None:
    text, _ = _read_text(document)
    span = find_blocks(text, Path(document).name).get(block_id)
    return None if span is None else text[span[0]:span[1]]


def _selected(only: list[str] | None, blocks: Mapping[str, Block] | None = None) -> list[Block]:
    registry = BLOCKS if blocks is None else blocks
    ids = list(registry) if not only else only
    unknown = [i for i in ids if i not in registry]
    if unknown:
        raise DocGenerationError(f"unknown block id(s) {unknown}; registered: {list(registry)}")
    return [registry[i] for i in ids]


def check(root: Path = PROJECT_ROOT, src: Sources | None = None, only: list[str] | None = None, blocks: Mapping[str, Block] | None = None) -> list[str]:
    """Names of the stale blocks (empty = every document matches its sources). A registered block without markers is an error, not a no-op."""
    src = src or Sources()
    stale = []
    for block in _selected(only, blocks):
        doc = Path(root) / block.document
        text, _ = _read_text(doc)
        span = find_blocks(text, doc.name).get(block.id)
        if span is None:
            raise DocGenerationError(f"{block.document} has no markers for registered block {block.id!r}")
        if text[span[0]:span[1]] != render_block(block, src):
            stale.append(block.id)
    return stale


def write(root: Path = PROJECT_ROOT, src: Sources | None = None, only: list[str] | None = None, blocks: Mapping[str, Block] | None = None) -> list[str]:
    """Regenerate the blocks; returns the documents that changed. Text outside the marker pairs is never touched."""
    src = src or Sources()
    changed = []
    by_doc: dict[str, list[Block]] = {}
    for block in _selected(only, blocks):
        by_doc.setdefault(block.document, []).append(block)
    for document, doc_blocks in by_doc.items():
        doc = Path(root) / document
        text, nl = _read_text(doc)
        new = text
        for block in doc_blocks:
            span = find_blocks(new, doc.name).get(block.id)
            if span is None:
                raise DocGenerationError(f"{document} has no markers for registered block {block.id!r}")
            new = new[:span[0]] + render_block(block, src) + new[span[1]:]
        if new != text:
            out = new.replace("\n", nl) if nl == "\r\n" else new
            Path(doc).write_bytes((b"\xef\xbb\xbf" if _has_bom(doc) else b"") + out.encode("utf-8"))
            changed.append(document)
    return changed


# ------------------------------------------------------------------------------------------------------------- fixture vs the production table
def limitation_texts_from_table(df) -> dict:
    """The fixture content for a final_results DataFrame: its distinct known_limitations_text strings with ids, support status and the scenario-years they apply to."""
    texts = []
    for text, g in df.groupby("known_limitations_text", sort=False):
        pairs = sorted({(str(r.scenario), int(r.year)) for r in g.itertuples()})
        texts.append({"text": text, "known_limitations": str(g["known_limitations"].iloc[0]), "support_status": str(g["support_status"].iloc[0]), "n_rows": len(g), "scenario_years": [list(p) for p in pairs]})
    texts.sort(key=lambda t: (t["scenario_years"][0][1], t["scenario_years"][0][0], t["text"]))
    return {"rows_total": len(df), "texts": texts}


def fixture_vs_table(fixture_path: Path = FIXTURE_PATH, table_path: Path | None = None) -> str | None:
    """None when the committed fixture equals what the live table contains, otherwise a description; returns "skipped: ..." when there is no local table."""
    if table_path is None:
        from curtailmit import paths

        table_path = paths.planned_layout()["tables"] / "final_results.parquet"
    if not Path(table_path).is_file():
        return f"skipped: no production table at {table_path} (the comparison needs the local database)"
    from curtailmit.results_writer import read_final_results

    live = limitation_texts_from_table(read_final_results(table_path))
    committed = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
    return None if json.dumps(live, sort_keys=True) == json.dumps({k: committed.get(k) for k in live}, sort_keys=True) else "the committed fixture differs from final_results.parquet: regenerate it with limitation_texts_from_table and review the change"


# ------------------------------------------------------------------------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m curtailmit.doc_generation", description="Generate / check the marked blocks of the documentation.")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", action="store_true")
    g.add_argument("--check", action="store_true")
    g.add_argument("--list", action="store_true")
    p.add_argument("--only", help="comma-separated block ids")
    args = p.parse_args(argv)
    only = [s for s in (args.only or "").split(",") if s] or None
    try:
        if args.list:
            for b in BLOCKS.values():
                print(f"{b.id:<32} {b.document:<32} {','.join(b.sources)}{'  [needs database]' if b.needs_database else ''}")
            return 0
        if args.write:
            changed = write(only=only)
            print("updated: " + ", ".join(changed) if changed else "all generated blocks already up to date")
            return 0
        stale = check(only=only)
        if stale:
            print(f"generated block(s) out of date: {', '.join(stale)}; run `{COMMAND}`", file=sys.stderr)
            return 1
        note = fixture_vs_table()
        if note and note.startswith("skipped"):
            print(note)
        elif note:
            print(f"FAILED: {note}", file=sys.stderr)
            return 1
        print("generated blocks up to date")
        return 0
    except (DocGenerationError, dr.RegistryError) as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
