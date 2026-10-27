"""Documentation stays in step with the code (Task 15, audit findings): links resolve, the acceptance-criteria map names real tests, status markers are not stale, the README matches the CLI."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]
DOCS = PROJECT / "docs"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def test_markdown_links_between_documents_resolve():
    broken = []
    for md in sorted([*DOCS.glob("*.md"), PROJECT / "README.md"]):
        for target in re.findall(r"\]\(([^)\s]+)\)", _text(md)):
            if re.match(r"[a-z]+://|mailto:|#", target):
                continue
            if not (md.parent / target.split("#", 1)[0]).exists():
                broken.append(f"{md.name}: {target}")
    assert not broken, broken


@pytest.mark.parametrize("doc", ["README.md", "docs/reproducibility.md", "docs/acceptance_criteria_status.md", "docs/orchestration.md"])
def test_paths_cited_in_the_entry_documents_exist(doc):
    """Backticked repository paths (docs/..., src/..., tests/..., config/..., scripts/...) must exist."""
    missing = []
    for ref in set(re.findall(r"`((?:docs|src|tests|config|scripts|analysis)/[A-Za-z0-9_./*-]+\.(?:md|py|yaml|json|txt|yml))`", _text(PROJECT / doc))):
        if "*" in ref or "<" in ref:
            continue
        if not (PROJECT / ref).exists():
            missing.append(ref)
    assert not missing, f"{doc} cites paths that do not exist: {sorted(missing)}"


def test_acceptance_criteria_map_has_one_row_per_criterion_and_every_named_test_exists():
    text = _text(DOCS / "acceptance_criteria_status.md")
    rows = [ln for ln in text.splitlines() if re.match(r"\| [1-9] \|", ln)]
    roadmap = _text(DOCS / "roadmap.md").split("## 7. Acceptance criteria", 1)[1].split("## 8.", 1)[0]
    assert len(rows) == len(re.findall(r"^- ", roadmap, re.MULTILINE)) == 5
    names = re.findall(r"`(tests/[A-Za-z0-9_]+\.py)::(?:[A-Za-z0-9_]+::)?([A-Za-z0-9_]+)`", text)
    assert len(names) >= 8
    for file, func in names:
        assert re.search(rf"def {func}\(", _text(PROJECT / file)), f"{file}::{func} does not exist"


def test_status_table_has_no_duplicate_task_rows_and_no_open_marker_on_finished_tasks():
    cc = _text(DOCS / "claude_commands.md")
    table = [ln for ln in cc.splitlines() if re.match(r"\| (\d+[A-Z0-9]*) \|", ln)]
    ids = [re.match(r"\| (\w+) \|", ln).group(1) for ln in table]
    assert len(ids) == len(set(ids)), f"duplicate task rows: {sorted({i for i in ids if ids.count(i) > 1})}"
    for ln in table:
        if re.match(r"\| (14|15) \|", ln):
            assert "DONE" in ln and "~~⬜~~" in ln
        stale = re.sub(r"~~.*?~~", "", ln)  # struck-through text is the preserved history
        assert "findings pending review" not in stale and "awaiting confirmation" not in stale and "NOT started" not in stale, ln


def test_superseded_design_headers_and_methodology_sections_carry_a_visible_update():
    for name in ("task11f_design.md", "task13_design.md", "task14_design.md"):
        head = _text(DOCS / name).splitlines()[2]
        assert "~~PROPOSAL, awaiting explicit approval.~~" in head and "Update (Task 15 sync)" in head and "implemented in commit" in head, name
    meth = _text(DOCS / "methodology.md")
    for heading in ("## 2.3. Step 1", "## 2.4. Step 2", "## 2.5. Step 3", "### 3.7 Limitations"):
        before = meth.split(heading, 1)[0].rstrip().splitlines()[-1]
        assert "Task 15 sync" in before, heading


def test_unregistered_decision_numbers_are_not_presented_as_decisions_in_the_roadmap_history():
    assert "D27-candidate" in _text(DOCS / "roadmap.md") and "D27-candidate" in _text(DOCS / "task11e4_findings.md")


def test_readme_describes_the_current_pipeline():
    readme = _text(PROJECT / "README.md")
    for needed in ("curtailmit-run", "requirements.lock.txt", "docs/reproducibility.md", "Option E", "Updated for Task 15"):
        assert needed in readme, needed
    assert "calibration.py" not in readme and "fit curtailment function" not in readme


def test_reproducibility_document_does_not_overclaim_data_availability():
    text = _text(DOCS / "reproducibility.md")
    assert "D33" in text and "not** a promise that the data are bundled" in text and "data_snapshot_manifest.json" in text
    assert "bitwise identity is **not** promised" in text and "1e-9" in text


def test_licensing_checklist_exists_is_discoverable_and_states_that_nothing_was_verified():
    check = _text(DOCS / "pre_submission_checklist.md")
    assert "NOT VERIFIED" in check and "not formally verified" in check and "D33" in check and "absence of evidence" in check
    assert "pre_submission_checklist.md" in _text(DOCS / "reproducibility.md") and "pre_submission_checklist.md" in _text(PROJECT / "README.md")


def test_makefile_has_working_tab_recipes_and_both_install_targets():
    lines = (PROJECT / "Makefile").read_text(encoding="utf-8-sig").splitlines()
    recipes, target = {}, None
    for ln in lines:
        if re.match(r"[A-Za-z0-9_-]+:", ln):
            target = ln.split(":")[0]
            recipes[target] = []
        elif ln.strip() and not ln.startswith("#") and target:
            assert ln.startswith("\t"), f"recipe line of '{target}' must start with a tab: {ln!r}"
            recipes[target].append(ln.strip())
    assert any("requirements.txt" in c for c in recipes["setup"])
    assert any("requirements.lock.txt" in c for c in recipes["setup-locked"]) and any("-e . --no-deps" in c for c in recipes["setup-locked"])
    assert "setup-locked" in lines[0] and "flexible" in "\n".join(lines) and "exact-pin" in "\n".join(lines)


def test_criterion_5_is_presented_as_superseded_by_d35_and_the_decision_is_adopted():
    from curtailmit import decision_registry as dr

    row = next(ln for ln in _text(DOCS / "acceptance_criteria_status.md").splitlines() if ln.startswith("| 5 |"))
    assert "Superseded (D35)" in row and "11E2" in row and "open" not in row.lower().replace("open item", "") and "Not applicable" not in row
    assert {r["id"]: r["status"] for r in dr.collect()}["D35"] == "adopted"


def test_orchestration_documents_the_makefile_defect_honestly():
    text = _text(DOCS / "orchestration.md")
    assert "Makefile targets were non-functional (missing TAB indentation) until Task 15-2" in text and "intended, not verified" in text
