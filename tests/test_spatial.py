"""Geometry module of the context maps (Task 17, D36): exact parse of a SYNTHETIC shapefile (no GADM data is committed), ring orientation and holes, simplification limits, provisioning of the local-only
boundary files, and the guarantee that those files change no pipeline stamp."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from curtailmit import pipeline as pl
from curtailmit import provenance as prov
from curtailmit import run_manifest as rm
from curtailmit import spatial as sp

PROJECT = Path(__file__).resolve().parents[1]
FIX = PROJECT / "tests" / "fixtures" / "spatial"
_spec = importlib.util.spec_from_file_location("make_spatial_fixture", FIX / "make_fixture.py")
mk = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mk)

SHP = FIX / "synthetic_states.shp"


@pytest.fixture(scope="module")
def shapes():
    return sp.read_shp(SHP)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------- exact parse
def test_synthetic_fixture_is_reproducible_byte_for_byte(tmp_path):
    for p in mk.build(tmp_path):
        assert p.read_bytes() == (FIX / p.name).read_bytes(), p.name


def test_parse_is_exact_feature_ring_and_vertex_counts_and_coordinates(shapes):
    assert len(shapes) == len(mk.FEATURES) == 6
    for rings, (_name, _hasc, expected) in zip(shapes, mk.FEATURES, strict=True):
        assert [len(r) for r in rings] == [len(e) for e in expected]
        for got, want in zip(rings, expected, strict=True):
            assert np.array_equal(got, np.asarray(want, dtype=float))
            assert np.array_equal(got[0], got[-1])  # every ring is closed


def test_ring_orientation_outer_clockwise_holes_counter_clockwise_and_holes_are_preserved(shapes):
    square_hole, triangle, two_parts = shapes[0], shapes[1], shapes[2]
    assert [sp.is_hole(r) for r in square_hole] == [False, True]  # one outer ring, one hole
    assert [sp.is_hole(r) for r in triangle] == [False] and [sp.is_hole(r) for r in two_parts] == [False, False]
    assert sp.shape_area(square_hole) == pytest.approx(16.0 - 4.0) and sp.shape_area(triangle) == pytest.approx(2.0) and sp.shape_area(two_parts) == pytest.approx(2.0)
    assert sp.signed_area(square_hole[0]) < 0 < sp.signed_area(square_hole[1])
    big = shapes[5]
    assert [sp.is_hole(r) for r in big] == [False, True]


def test_attributes_are_read_exactly_including_numbers_and_the_cpg_encoding():
    rows = sp.read_dbf(FIX / "synthetic_states.dbf")
    assert [r["HASC_1"] for r in rows] == [h for _, h, _ in mk.FEATURES]
    assert [r["NAME_1"] for r in rows] == [n for n, _, _ in mk.FEATURES]
    assert [r["AREA_N"] for r in rows] == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]


def test_deleted_dbf_records_are_skipped_and_bad_shapefiles_are_refused(tmp_path):
    raw = bytearray((FIX / "synthetic_states.dbf").read_bytes())
    header_len = int.from_bytes(raw[8:10], "little")
    raw[header_len] = ord("*")
    p = tmp_path / "x.dbf"
    p.write_bytes(bytes(raw))
    assert len(sp.read_dbf(p)) == 5
    bad = tmp_path / "bad.shp"
    bad.write_bytes(b"\x00" * 120)
    with pytest.raises(sp.SpatialError, match="not an ESRI shapefile"):
        sp.read_shp(bad)
    line = bytearray(SHP.read_bytes())
    line[108:112] = (3).to_bytes(4, "little")  # first record's shape type -> polyline
    bad.write_bytes(bytes(line))
    with pytest.raises(sp.SpatialError, match="not a polygon"):
        sp.read_shp(bad)


def test_path_arrays_build_one_compound_path_that_renders_the_hole_empty(shapes):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import PathPatch
    from matplotlib.path import Path as MPath

    verts, codes = sp.path_arrays(shapes[0])
    assert len(verts) == len(codes) == 10 and list(codes) == [1, 2, 2, 2, 79, 1, 2, 2, 2, 79]
    fig, ax = plt.subplots(figsize=(2, 2), dpi=50)
    ax.add_patch(PathPatch(MPath(verts, codes), facecolor="k", edgecolor="none"))
    ax.set(xlim=(-1, 5), ylim=(-1, 5))
    ax.axis("off")
    fig.canvas.draw()
    img = np.asarray(fig.canvas.buffer_rgba())[:, :, 0]
    plt.close(fig)
    h, w = img.shape

    def pixel(x, y):  # (data -> pixel): the filled ring is black (0), the hole and the outside are white (255)
        return int(img[int((1 - (y + 1) / 6) * h), int((x + 1) / 6 * w)])

    assert pixel(0.5, 0.5) == 0 and pixel(2.0, 2.0) == 255 and pixel(4.8, 4.8) == 255


# ------------------------------------------------------------------------------------------------------------------------------------------------------------- simplification
def test_simplification_keeps_each_polygon_area_within_half_a_percent_and_never_drops_a_polygon_or_ring(shapes):
    for rings in shapes:
        simp = sp.simplify_shape(rings, 0.02)
        assert len(simp) == len(rings)  # no ring dropped, no polygon dropped
        a0, a1 = sp.shape_area(rings), sp.shape_area(simp)
        assert abs(a1 - a0) <= 0.005 * abs(a0) + 1e-12, (a0, a1)
        for r in simp:
            assert len(r) >= 4 and np.array_equal(r[0], r[-1])


def test_simplification_reduces_a_fine_ring_keeps_original_vertices_and_the_orientation(shapes):
    wavy = shapes[3][0]
    simp = sp.simplify_ring(wavy, 0.02)
    assert len(simp) < len(wavy) / 3
    original = {tuple(p) for p in wavy}
    assert all(tuple(p) in original for p in simp)  # Douglas-Peucker only removes points
    assert sp.signed_area(simp) < 0  # still clockwise
    # every original vertex is within the tolerance of the simplified outline
    for p in wavy[::7]:
        a, b = simp[:-1], simp[1:]
        d = b - a
        t = np.clip(np.sum((p - a) * d, axis=1) / np.maximum(np.sum(d * d, axis=1), 1e-300), 0, 1)
        dist = np.hypot(*(a + t[:, None] * d - p).T).min()
        assert dist <= 0.02 + 1e-9


def test_small_rings_pass_through_unchanged_and_a_zero_tolerance_changes_nothing(shapes):
    tiny = shapes[4][0]
    assert np.array_equal(sp.simplify_ring(tiny, 0.02), tiny)
    islet = shapes[5][1]
    assert len(sp.simplify_ring(islet, 0.02)) >= 4
    wavy = shapes[3][0]
    assert len(sp.simplify_ring(wavy, 0.0)) >= len(wavy) - 1  # (almost) all points kept; collinear points may go


def test_read_states_joins_geometry_to_attributes_and_refuses_duplicates(tmp_path):
    st = sp.read_states(SHP, tol=None)
    assert list(st) == ["AA", "BB", "CC", "DD", "EE", "FF"] and st["AA"]["name"] == "Square with hole" and len(st["AA"]["rings"]) == 2
    assert sp.uf_of("BR.BA") == "BA"
    dup = tmp_path / "d.shp"
    mk.write_shp(dup, mk._ring_arrays())
    mk.write_dbf(dup.with_suffix(".dbf"), [("XX.AA", "a", 1.0)] * 6)
    with pytest.raises(sp.SpatialError, match="appears twice"):
        sp.read_states(dup)
    mk.write_dbf(dup.with_suffix(".dbf"), [("XX.AA", "a", 1.0)] * 5)
    with pytest.raises(sp.SpatialError, match="attribute rows"):
        sp.read_states(dup)


# -------------------------------------------------------------------------------------------------------------------------------------------------------------------- provisioning
def _fake_gadm_source(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    for ext, name in ((".shp", "synthetic_states.shp"), (".dbf", "synthetic_states.dbf"), (".cpg", "synthetic_states.cpg")):
        (src / f"gadm41_BRA_1{ext}").write_bytes((FIX / name).read_bytes())
    (src / "gadm41_BRA_1.prj").write_text("GEOGCS[synthetic]", encoding="ascii")
    return src / "gadm41_BRA_1.shp"


def test_provision_copies_the_set_writes_retrieval_manifests_and_feeds_the_snapshot(tmp_path):
    raw = tmp_path / "raw"
    written = sp.provision(_fake_gadm_source(tmp_path), raw, now_utc="2026-10-28T00:00:00+00:00")
    assert [p.suffix for p in written] == [".shp", ".dbf", ".prj", ".cpg"] and all(p.parent == raw / "boundaries" / "gadm" for p in written)
    for p in written:
        meta = json.loads(p.with_suffix(p.suffix + ".manifest.json").read_text(encoding="utf-8"))
        assert meta["sha256"] == prov.sha256_file(p) and meta["byte_size"] == p.stat().st_size and meta["http_status"] is None
        assert meta["source_url"] == sp.GADM_SOURCE_URL and "Local-only" in meta["note"] and meta["original_file_date"] == "2022-07-18"
    inv = {e["path"]: e for e in rm.raw_inventory(raw)}
    assert set(inv) == {f"boundaries/gadm/gadm41_BRA_1{e}" for e in sp.GADM_SIBLINGS}
    assert all("GADM 4.1" in e["note"] for e in inv.values())
    assert sp.provision(_fake_gadm_source(tmp_path), raw)  # idempotent: the same bytes are not an error


def test_provision_refuses_a_different_stem_a_missing_sibling_and_differing_bytes(tmp_path):
    with pytest.raises(sp.SpatialError, match="expected gadm41_BRA_1.shp"):
        sp.provision(FIX / "synthetic_states.shp", tmp_path / "raw")
    src = _fake_gadm_source(tmp_path)
    raw = tmp_path / "raw"
    sp.provision(src, raw)
    src.with_suffix(".dbf").write_bytes(b"changed")
    with pytest.raises(sp.SpatialError, match="different bytes"):
        sp.provision(src, raw)
    src.with_suffix(".prj").unlink()
    with pytest.raises(sp.SpatialError, match="missing"):
        sp.provision(src, tmp_path / "raw2")


def test_no_geometry_file_is_tracked_by_git_and_the_ignore_rule_is_in_place():
    ignore = (PROJECT / ".gitignore").read_text(encoding="utf-8")
    assert "gadm41_*" in ignore
    tracked = [p for p in (PROJECT / "tests" / "fixtures" / "spatial").iterdir() if p.suffix in {".shp", ".dbf"} and not p.name.startswith("synthetic_")]
    assert tracked == []


def test_boundaries_in_the_raw_tree_do_not_enter_the_stage1_fingerprint(tmp_path):
    raw = tmp_path / "raw"
    (raw / "ons").mkdir(parents=True)
    (raw / "ons" / "a.parquet").write_bytes(b"a")
    ctx = pl.Context(tmp_path, raw, tmp_path / "interim", tmp_path / "processed", tmp_path / "logs", tmp_path / "tables")
    before = pl._fp_stage1(ctx)["inputs"]
    sp.provision(_fake_gadm_source(tmp_path), raw)
    after = pl._fp_stage1(ctx)["inputs"]
    assert before == after and "raw/ons/a.parquet" in after and not [k for k in after if "boundaries" in k]
    assert pl.NON_PIPELINE_RAW == ("boundaries",)
