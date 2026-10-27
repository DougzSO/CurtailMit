"""Decision register consistency (Task 15, D34): docs/reproducibility.md must equal what the YAML and the roadmap table say, and no decision number may be reused or left ambiguous."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from curtailmit import decision_registry as dr
from curtailmit import provenance as prov

PROJECT = Path(__file__).resolve().parents[1]
D_REF = re.compile(r"(?<![A-Za-z0-9_])D(\d{1,3})(?![0-9A-Za-z_-])")


def _scanned_files() -> list[Path]:
    return sorted([*(PROJECT / "docs").glob("*.md"), *(PROJECT / "config").glob("*.yaml"), PROJECT / "README.md", *(PROJECT / "analysis").glob("*.py"), *(PROJECT / "src" / "curtailmit").glob("*.py")])


def test_register_covers_every_decision_exactly_once_and_is_contiguous():
    rows = dr.collect()
    ids = [r["id"] for r in rows]
    assert ids == [f"D{i}" for i in range(1, len(ids) + 1)] and len(ids) == len(set(ids))
    assert len(ids) >= 34


def test_yaml_ids_and_statuses_are_reflected_in_the_register_without_mismatch():
    raw = yaml.safe_load((PROJECT / "config" / "discovered_sources.yaml").read_text(encoding="utf-8"))["decisions"]
    by_id = {r["id"]: r for r in dr.collect()}
    for i, d in raw.items():
        assert by_id[i]["status"] == d["status"], f"{i}: register says {by_id[i]['status']}, YAML says {d['status']}"
    assert {r["id"] for r in by_id.values() if r["where"].startswith("roadmap")} == {f"D{i}" for i in range(1, 13)}


def test_generated_register_in_the_document_is_current():
    assert dr.current_block() == dr.render(dr.collect()), "docs/reproducibility.md is out of date: python -m curtailmit.decision_registry --write"


def test_adopted_decisions_from_d27_on_state_where_they_are_implemented():
    for r in dr.collect():
        if r["status"] == "adopted" and int(r["id"][1:]) >= 27:
            assert r["implemented_in"] not in ("-", ""), f"{r['id']} is adopted but has no implemented_in"


def test_the_decisions_the_pipeline_hashes_exist_and_are_adopted():
    from curtailmit import pipeline as pl

    adopted = {r["id"] for r in dr.collect() if r["status"] == "adopted"}
    used = {*pl.STAGE1_DECISIONS, *pl.CALIBRATION_DECISIONS, *pl.PROJECTION_DECISIONS, *pl.RESULTS_DECISIONS}
    assert used <= adopted, f"decisions hashed into stage stamps but not adopted: {sorted(used - adopted)}"


def test_no_document_cites_a_decision_number_that_is_not_registered():
    highest = int(dr.collect()[-1]["id"][1:])
    offenders = []
    for path in _scanned_files():
        for n, line in enumerate(path.read_text(encoding="utf-8-sig", errors="replace").splitlines(), 1):
            for m in D_REF.finditer(line):
                if int(m.group(1)) > highest:
                    offenders.append(f"{path.relative_to(PROJECT).as_posix()}:{n}: D{m.group(1)}")
    assert not offenders, offenders


def test_the_unregistered_d27_candidate_is_always_labelled_as_a_candidate():
    """The Task 11E4 'D27' (sub-hourly feasibility, never adopted) collides with the adopted D27 (results_writer, Task 13). Wherever the sub-hourly meaning is used it must say 'D27-candidate'."""
    sub_hourly = re.compile(r"sub-hourly|not registered|never adopted|30-minute", re.IGNORECASE)
    this_test = Path(__file__).resolve()
    offenders = []
    for path in _scanned_files() + [PROJECT / "docs" / "task15_design.md"]:
        if path.resolve() in (this_test, PROJECT / "src" / "curtailmit" / "decision_registry.py"):
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8-sig", errors="replace").splitlines(), 1):
            for m in re.finditer(r"D27(?!-candidate)", line):
                if sub_hourly.search(line) and "D27 (results" not in line and "task15_design" not in path.name and "adopted D27" not in line and "numbering note" not in line.lower():
                    offenders.append(f"{path.relative_to(PROJECT).as_posix()}:{n}")
                    break
    assert not offenders, f"unlabelled sub-hourly 'D27' references: {offenders}"


# ------------------------------------------------------------------------------------------------------------------------ the generator itself
def _roadmap(tmp_path, extra_row: str = "", extra_section: str = "") -> Path:
    p = tmp_path / "roadmap.md"
    p.write_text("| # | Topic | Decision taken |\n|---|---|---|\n| D1 | First | text |\n| D2 | Second | text |\n" + extra_row + "\n## Decision D3 (added)\n\n**D3: Third thing.**\n" + extra_section, encoding="utf-8")
    return p


def _yaml(tmp_path, body: str) -> Path:
    p = tmp_path / "d.yaml"
    p.write_text("decisions:\n" + body, encoding="utf-8")
    return p


def test_generator_merges_roadmap_and_yaml(tmp_path):
    y = _yaml(tmp_path, '  D4:\n    status: adopted\n    topic: "Fourth"\n    source_task: "Task 9 (x)"\n    implemented_in: "mod.f; more"\n')
    rows = dr.collect(y, _roadmap(tmp_path))
    assert [(r["id"], r["status"]) for r in rows] == [("D1", "adopted"), ("D2", "adopted"), ("D3", "adopted"), ("D4", "adopted")]
    assert rows[3]["implemented_in"] == "mod.f" and rows[3]["where"] == "YAML, Task 9"


def test_collision_between_roadmap_and_yaml_is_refused(tmp_path):
    y = _yaml(tmp_path, '  D2:\n    status: adopted\n    topic: "Reused number"\n')
    with pytest.raises(dr.RegistryError, match="both"):
        dr.collect(y, _roadmap(tmp_path))


def test_duplicate_yaml_key_is_refused_instead_of_silently_keeping_the_last(tmp_path):
    y = _yaml(tmp_path, '  D4:\n    status: adopted\n    topic: "one"\n  D4:\n    status: pending\n    topic: "two"\n')
    with pytest.raises(dr.RegistryError, match="duplicate YAML key"):
        dr.collect(y, _roadmap(tmp_path))


def test_gap_in_the_numbering_and_unknown_status_are_refused(tmp_path):
    with pytest.raises(dr.RegistryError, match="not contiguous"):
        dr.collect(_yaml(tmp_path, '  D5:\n    status: adopted\n    topic: "skips D4"\n'), _roadmap(tmp_path))
    with pytest.raises(dr.RegistryError, match="unknown status"):
        dr.collect(_yaml(tmp_path, '  D4:\n    status: maybe\n    topic: "x"\n'), _roadmap(tmp_path))


def test_the_real_yaml_has_no_duplicate_keys():
    assert dr.yaml_decisions(prov.DECISIONS_PATH)


def test_update_document_rewrites_only_the_marked_block(tmp_path):
    doc = tmp_path / "r.md"
    doc.write_text(f"before\n{dr.START}\nstale\n{dr.END}\nafter\n", encoding="utf-8")
    y = _yaml(tmp_path, '  D4:\n    status: pending\n    topic: "Fourth"\n')
    assert dr.update_document(doc, yaml_path=y, roadmap_path=_roadmap(tmp_path)) is True
    text = doc.read_text(encoding="utf-8")
    assert text.startswith("before\n") and text.endswith("after\n") and "| D4 | Fourth | pending |" in text and "stale" not in text
    assert dr.update_document(doc, yaml_path=y, roadmap_path=_roadmap(tmp_path)) is False
