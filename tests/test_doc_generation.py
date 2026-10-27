"""Generated documentation blocks (Task 16): the documents equal their sources, the markers are handled strictly, the limitation schema rejects what it must, and the decision hash ignores documentation-only keys."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pandas as pd
import pytest
import yaml

from curtailmit import decision_registry as dr
from curtailmit import doc_generation as gen
from curtailmit import limitations as lim
from curtailmit import pipeline as pl
from curtailmit import provenance as prov
from curtailmit import results_writer as rw

PROJECT = Path(__file__).resolve().parents[1]
DECISIONS = yaml.safe_load((PROJECT / "config" / "discovered_sources.yaml").read_text(encoding="utf-8"))["decisions"]
FIXTURE = json.loads((PROJECT / "tests" / "fixtures" / "final_results" / "limitation_texts.json").read_text(encoding="utf-8"))


def _doc_block(block_id: str = "x") -> gen.Block:
    return gen.Block(block_id, "doc.md", lambda s: "generated body", ("none",))


def _begin(block: gen.Block) -> str:
    return gen.begin_marker(block)


# ---------------------------------------------------------------------------------------------------------------- the real documents
def test_every_generated_block_in_the_repository_equals_what_its_sources_produce():
    assert gen.check() == [], "run `python -m curtailmit.doc_generation --write`"


def test_every_registered_block_is_marked_once_in_its_document_and_no_marker_names_an_unregistered_id():
    ids_found = {}
    for md in sorted([*(PROJECT / "docs").glob("*.md"), PROJECT / "README.md"]):
        text = md.read_text(encoding="utf-8-sig")
        if md.name in ("task16_design.md", "task13b_design.md"):
            continue  # design documents quote the marker syntax as an example
        for bid in gen.find_blocks(text.replace("\r\n", "\n"), md.name):
            ids_found.setdefault(bid, []).append(md.relative_to(PROJECT).as_posix())
    assert set(ids_found) == set(gen.BLOCKS), f"markers {sorted(ids_found)} vs registered {sorted(gen.BLOCKS)}"
    for bid, docs in ids_found.items():
        assert docs == [gen.BLOCKS[bid].document], (bid, docs)


def test_real_yaml_passes_the_limitation_schema_and_every_adopted_decision_from_d23_states_a_limitation_or_none():
    assert gen.schema_problems(DECISIONS) == []
    for did, d in DECISIONS.items():
        if int(did[1:]) >= gen.FIRST_REQUIRED and d["status"] == "adopted":
            assert "limitation" in d, did
    assert {int(e["id"][1:]) for e in gen.limitation_entries(DECISIONS)} >= set(range(23, 36))


def test_every_theme_of_the_vocabulary_is_used_and_there_are_ten():
    used = {i["theme"] for e in gen.limitation_entries(DECISIONS) for i in e["items"]}
    assert used == set(gen.THEMES) and len(gen.THEMES) == 10 and "reproducibility-scope" in gen.THEMES


def test_the_generated_page_lists_d23_to_d35_and_the_decisions_without_a_limitation_give_their_reason():
    src = gen.Sources()
    appendix = gen.render_limitations_appendix(src)
    for n in range(23, 36):
        assert f"[D{n}](" in appendix, n
    for did in ("D27", "D31", "D32"):
        row = next(ln for ln in appendix.splitlines() if ln.startswith(f"| [{did}]"))
        assert "No reader-facing limitation:" in row, did


def test_d21_and_d22_keep_their_status_and_show_the_cross_reference_in_the_register_and_the_appendix():
    assert DECISIONS["D21"]["status"] == DECISIONS["D22"]["status"] == "adopted"
    assert DECISIONS["D21"]["superseded_in_practice_by"] == DECISIONS["D22"]["superseded_in_practice_by"] == "D24"
    body = gen.render_decision_register(gen.Sources())
    for did in ("D21", "D22"):
        row = next(ln for ln in body.splitlines() if ln.startswith(f"| {did} |"))
        assert "adopted (superseded in practice by D24)" in row, row
    assert "superseded in practice by" not in next(ln for ln in body.splitlines() if ln.startswith("| D23 |"))
    appendix = gen.render_limitations_appendix(gen.Sources())
    assert "adopted; superseded in practice by D24" in next(ln for ln in appendix.splitlines() if ln.startswith("| [D21]"))
    assert {r["id"]: r["status"] for r in dr.collect()}["D21"] == "adopted"  # the cross-reference never changes the status


def test_only_adopted_decisions_are_rendered_as_limitations_and_d33_says_the_terms_are_not_verified():
    for e in gen.limitation_entries(DECISIONS):
        assert e["status"] == "adopted", e["id"]
    d33 = " ".join(i["text"] for i in next(e for e in gen.limitation_entries(DECISIONS) if e["id"] == "D33")["items"])
    assert "not verified" in d33


def test_generated_limitation_text_contains_no_probabilistic_interval_vocabulary():
    src = gen.Sources()
    for text in (gen.render_limitations_themes(src), gen.render_limitations_appendix(src), gen.render_limitations_row_caveats(src)):
        assert not rw.FORBIDDEN_LANGUAGE.search(text), rw.FORBIDDEN_LANGUAGE.search(text)


def test_the_d25_limitation_numbers_are_the_quantified_constants_of_the_code():
    text = " ".join(i["text"] for i in next(e for e in gen.limitation_entries(DECISIONS) if e["id"] == "D25")["items"])
    allowed = " ".join(str(v) for v in lim.D25_QUANTIFIED.values())
    for n in re.findall(r"\d+\.\d+|\d{2,}", text):
        assert n in allowed, f"{n} in the D25 limitation is not in D25_QUANTIFIED"


# ------------------------------------------------------------------- the row caveat text (F-4): one source of numbers, output unchanged
def _row(**kw) -> pd.Series:
    base = {"known_limitations": "D25;SOLAR_SHORT_RECORD", "support_status": "within_support", "in_support_fraction": 1.0, "horizon_treatment": "empirical_band"}
    return pd.Series({**base, **kw})


def test_row_caveat_text_is_byte_identical_to_the_pre_task16_literals():
    drift = "Central values are more likely low than high: residual upward drift of the wind curtailment rate at fixed hourly VRE share (D25; +1.4 to +1.6 pp per year over 2022-2026, not corrected)."
    solar = " Solar curve fitted on 30 months (shorter record than wind)."
    out = " Part of the projected curtailment (42 percent) comes from hours with no historical analogue (mostly_out_of_support)."
    flex = " 2050 values are a range conditional on a flexibility assumption (phi 1.5 to L=1), not a calibrated forecast; the emission factor is a fixed point value (D28)."
    assert rw.limitations_text(_row()) == drift + solar
    assert rw.limitations_text(_row(known_limitations="D25")) == drift
    assert rw.limitations_text(_row(support_status="mostly_out_of_support", in_support_fraction=0.58, horizon_treatment=rw.HORIZON_CONDITIONAL)) == drift + solar + out + flex
    assert lim.SOLAR_NOTE.startswith("Solar curve fitted on 30 months of dispatched-generation data")


def test_numbers_of_the_row_text_occur_in_the_adopted_decision_texts():
    d25 = lim.adopted_text(DECISIONS["D25"])
    for n in re.findall(r"\d+\.\d+|\d{2,}", f"{lim.D25_DRIFT_RANGE} {lim.D25_DRIFT_PERIOD}"):
        assert n in d25, n
    d24 = " ".join(str(DECISIONS["D24"]["decided"]).split())
    assert str(lim.SOLAR_MONTHS) in d24 and "1.5" in lim.FLEX_2050_RANGE and "phi = 1.5" in d24 and "L = 1" in d24


# -------------------------------------------------------------------------------------------------------------------- the fixture
def test_fixture_has_the_five_texts_covering_the_156_rows_and_the_12_scenario_years_with_mappable_ids():
    assert FIXTURE["rows_total"] == 156 and len(FIXTURE["texts"]) == 5
    assert sum(t["n_rows"] for t in FIXTURE["texts"]) == 156
    pairs = {tuple(p) for t in FIXTURE["texts"] for p in t["scenario_years"]}
    assert len(pairs) == 12 and {y for _, y in pairs} == {2025, 2030, 2040, 2050}
    for t in FIXTURE["texts"]:
        assert set(t["known_limitations"].split(";")) <= set(gen.ROW_LIMITATION_IDS)
        assert t["text"].startswith("Central values are more likely low than high")


def test_fixture_matches_the_row_text_function_for_every_support_status():
    for t in FIXTURE["texts"]:
        out_frac = 1.0 if t["support_status"] == "within_support" else 0.5
        horizon = rw.HORIZON_CONDITIONAL if any(y == 2050 for _, y in t["scenario_years"]) else "empirical_band"
        built = rw.limitations_text(_row(known_limitations=t["known_limitations"], support_status=t["support_status"], in_support_fraction=out_frac, horizon_treatment=horizon))
        assert built.split(" Part of the projected")[0].split(" 2050 values")[0] in t["text"]


@pytest.mark.integration
def test_fixture_equals_the_live_production_table():
    from curtailmit import paths

    table = paths.planned_layout()["tables"] / "final_results.parquet"
    if not table.is_file():
        pytest.skip("no local production table")
    assert gen.fixture_vs_table(table_path=table) is None


# ----------------------------------------------------------------------------------------------------------------------- schema checks
def _d(**kw) -> dict:
    base = {"status": "adopted", "decided": "Rate drifts by 1.4 pp and 20 percent in 2026.", "limitation": [{"theme": "drift", "text": "Drift of 1.4 pp."}]}
    base.update(kw)
    return {"D30": base}


@pytest.mark.parametrize("change, fragment", [
    ({"limitation": [{"theme": "nonsense", "text": "x"}]}, "unknown theme"),
    ({"limitation": [{"theme": "drift", "text": ""}]}, "empty limitation text"),
    ({"limitation": [{"theme": "drift"}]}, "exactly the keys theme and text"),
    ({"limitation": [{"theme": "drift", "text": "t", "extra": 1}]}, "exactly the keys theme and text"),
    ({"limitation": []}, "non-empty list"),
    ({"limitation": "none"}, "needs a non-empty `limitation_reason`"),
    ({"limitation_reason": "why"}, "only with `limitation: none`"),
    ({"limitation": [{"theme": "drift", "text": "Drift of 9.9 pp."}]}, "do not occur"),
    ({"theme": "drift"}, "top-level `theme`"),
    ({"limitations": []}, "unknown key"),
    ({"status": "pending"}, "only allowed on an adopted"),
])
def test_schema_rejects(change, fragment):
    problems = gen.schema_problems(_d(**change))
    assert any(fragment in p for p in problems), problems


def test_schema_accepts_the_valid_forms_and_none_with_a_reason():
    assert gen.schema_problems(_d()) == []
    assert gen.schema_problems(_d(limitation="none", limitation_reason="schema decision")) == []


def test_missing_field_detection_removing_the_limitation_of_an_adopted_decision_fails():
    broken = copy.deepcopy(DECISIONS)
    del broken["D25"]["limitation"]
    problems = gen.schema_problems(broken)
    assert any(p.startswith("D25:") and "without `limitation`" in p for p in problems), problems
    optional = copy.deepcopy(DECISIONS)
    del optional["D16"]["limitation"]  # D13-D22 are optional
    assert gen.schema_problems(optional) == []


def test_generator_refuses_to_render_from_an_invalid_schema(tmp_path):
    bad = tmp_path / "d.yaml"
    bad.write_text("decisions:\n  D23:\n    status: adopted\n    decided: x\n", encoding="utf-8")
    with pytest.raises(gen.DocGenerationError, match="limitation schema"):
        gen.render_limitations_themes(gen.Sources(yaml_path=bad))


# -------------------------------------------------------------------------------------------------------------------- marker handling
def test_find_blocks_rejects_nesting_unpaired_and_repeated_markers():
    b = _doc_block("a")
    other = _doc_block("b")
    end_a, end_b = gen.end_marker(b), gen.end_marker(other)
    with pytest.raises(gen.DocGenerationError, match="inside block"):
        gen.find_blocks(f"{_begin(b)}\n{_begin(other)}\n{end_b}\n{end_a}\n")
    with pytest.raises(gen.DocGenerationError, match="no END"):
        gen.find_blocks(f"{_begin(b)}\ntext\n")
    with pytest.raises(gen.DocGenerationError, match="without a matching BEGIN"):
        gen.find_blocks(f"text\n{end_a}\n")
    with pytest.raises(gen.DocGenerationError, match="appears twice"):
        gen.find_blocks(f"{_begin(b)}\n{end_a}\n{_begin(b)}\n{end_a}\n")
    with pytest.raises(gen.DocGenerationError, match="inside block"):
        gen.find_blocks(f"{_begin(b)}\n{end_b}\n")


def test_a_registered_block_without_markers_is_an_error_not_a_silent_no_op(tmp_path):
    (tmp_path / "doc.md").write_text("no markers here\n", encoding="utf-8")
    with pytest.raises(gen.DocGenerationError, match="no markers"):
        gen.check(tmp_path, blocks={"x": _doc_block()})
    with pytest.raises(gen.DocGenerationError, match="no markers"):
        gen.write(tmp_path, blocks={"x": _doc_block()})
    with pytest.raises(gen.DocGenerationError, match="unknown block id"):
        gen.check(tmp_path, only=["nope"])


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_write_replaces_only_the_block_is_idempotent_and_keeps_the_text_outside_byte_for_byte(tmp_path, newline):
    b = _doc_block()
    before, after = "# Title\n\nHand-written narrative, kept exactly.\n\n", "\n## History\n\nAppend-only text.\n"
    stale = f"{before}{_begin(b)}\n\nstale\n\n{gen.end_marker(b)}\n{after}"
    raw = stale.replace("\n", newline).encode("utf-8")
    doc = tmp_path / "doc.md"
    doc.write_bytes(raw)
    assert gen.check(tmp_path, blocks={"x": b}) == ["x"]
    assert gen.write(tmp_path, blocks={"x": b}) == ["doc.md"]
    out = doc.read_bytes()
    head, tail = before.replace("\n", newline).encode(), after.replace("\n", newline).encode()
    assert out.startswith(head) and out.endswith(tail) and b"generated body" in out and b"stale" not in out
    assert (b"\r\n" in out) == (newline == "\r\n")
    assert gen.check(tmp_path, blocks={"x": b}) == [] and gen.write(tmp_path, blocks={"x": b}) == []
    assert doc.read_bytes() == out


def test_write_on_every_real_document_leaves_the_text_outside_the_markers_unchanged(tmp_path):
    for block in gen.BLOCKS.values():
        target = tmp_path / block.document
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes((PROJECT / block.document).read_bytes())
    originals = {}
    for document in {b.document for b in gen.BLOCKS.values()}:
        path = tmp_path / document
        text = path.read_bytes().decode("utf-8-sig").replace("\r\n", "\n")
        for bid, (s, e) in sorted(gen.find_blocks(text, document).items(), key=lambda kv: -kv[1][0]):
            text = text[:s] + f"<!-- GENERATED:BEGIN id={bid} -->\nSTALE\n<!-- GENERATED:END id={bid} -->" + text[e:]
        path.write_bytes(text.encode("utf-8"))
        outside = re.sub(r"<!-- GENERATED:BEGIN.*?<!-- GENERATED:END id=[a-z0-9-]+ -->", "@@", text, flags=re.DOTALL)
        originals[document] = outside
    assert gen.write(tmp_path)  # regenerates everything
    assert gen.check(tmp_path) == []
    for document, outside in originals.items():
        text = (tmp_path / document).read_bytes().decode("utf-8-sig").replace("\r\n", "\n")
        assert re.sub(r"<!-- GENERATED:BEGIN.*?<!-- GENERATED:END id=[a-z0-9-]+ -->", "@@", text, flags=re.DOTALL) == outside, document


# ------------------------------------------------------------------------------------------------------------------------------- CLI
def test_cli_check_list_and_the_decision_registry_alias(capsys):
    assert gen.main(["--check"]) == 0
    assert gen.main(["--list"]) == 0
    listing = capsys.readouterr().out
    assert all(bid in listing for bid in gen.BLOCKS)
    assert gen.main(["--check", "--only", "nope"]) == 2
    assert dr.main(["--check"]) == 0


# ------------------------------------------------------------------------------------------------------------------- pipeline sequence
def test_pipeline_sequence_constant_matches_the_stages_and_the_steps_run_pipeline_executes():
    assert pl.PIPELINE_SEQUENCE[0] == "pre-check" and pl.PIPELINE_SEQUENCE[-3:] == ("reference-value check", "run manifest", "summary")
    assert tuple(pl.STAGE_NAMES) == pl.STAGES == tuple(s.key for s in pl.SPECS)
    assert pl.PIPELINE_SEQUENCE[1:-3] == tuple(pl.STAGE_NAMES[k] for k in pl.STAGES)
    source = (PROJECT / "src" / "curtailmit" / "pipeline.py").read_text(encoding="utf-8")
    for marker in ("precheck(ctx, args)", "check_reference(ctx", "_write_run_manifest(ctx, record)"):
        assert marker in source, marker  # the three inline steps of the sequence still exist
    assert gen.render_pipeline_sequence(gen.Sources()).startswith("`pre-check -> Stage 1 -> hourly calibration -> Option E projection -> final results -> reference-value check -> run manifest -> summary`")


# ------------------------------------------------------------------------------------------------ the decision hash ignores documentation keys
def test_doc_only_keys_are_exactly_the_documentation_fields():
    assert prov.DOC_ONLY_KEYS == {"theme", "limitation", "limitation_reason", "superseded_in_practice_by"}


def test_doc_only_keys_do_not_change_the_decision_hash_but_any_other_key_does():
    entry = {"status": "adopted", "decided": "text", "date": "2026-10-27"}
    base = prov.decision_hash(entry)
    for key, value in (("limitation", [{"theme": "drift", "text": "x"}]), ("limitation_reason", "r"), ("theme", "drift"), ("superseded_in_practice_by", "D24")):
        assert prov.decision_hash({**entry, key: value}) == base, key
    assert prov.decision_hash({**entry, "decided": "other text"}) != base
    assert prov.decision_hash({**entry, "new_unlisted_key": "x"}) != base  # conservative default: an unlisted key is hashed
    assert prov.decision_hash({**entry, "status": "superseded"}) != base


def test_real_decision_hashes_are_the_hashes_of_the_entries_without_documentation_keys(tmp_path):
    ids = [f"D{i}" for i in range(13, 36)]
    hashes = prov.decision_hashes(ids)
    stripped = {i: {k: v for k, v in DECISIONS[i].items() if k not in prov.DOC_ONLY_KEYS} for i in ids}
    import hashlib

    for i in ids:
        assert hashes[i] == hashlib.sha256(json.dumps(stripped[i], sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")).hexdigest()
    edited = tmp_path / "d.yaml"
    d = copy.deepcopy(DECISIONS)
    d["D25"]["limitation"][0]["text"] += " Reworded."
    edited.write_text(yaml.safe_dump({"decisions": d}), encoding="utf-8")
    assert prov.decision_hashes(["D25"], edited) == prov.decision_hashes(["D25"])
