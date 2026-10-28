"""Boundary geometry for the context maps (Task 17, decision D36). Data-free module: a plain-`struct` ESRI shapefile reader, a `.dbf` attribute reader, Douglas-Peucker simplification in `numpy`
and drawing-ready path arrays. No `geopandas`, `pyshp` or `cartopy` (none is in the locked environment; no dependency was added).

The geometry is GADM 4.1 level 1 (Brazilian states), kept ONLY in `curtailmit_database/raw/boundaries/gadm/` and never committed to the public repository (GADM's terms: academic / non-commercial use,
no redistribution without permission; to be verified before submission, docs/pre_submission_checklist.md section 3). The repository holds its SHA-256 in `data_snapshot_manifest.json` (D33 pattern).
Coordinates are geographic (WGS 84 lon / lat), so no reprojection is done; the map aspect is set by the figure (1 / cos(mean latitude)).

    python -m curtailmit.spatial provision --source PATH/gadm41_BRA_1.shp     copy the shapefile set into raw/boundaries/gadm/ with retrieval manifests (one-off provisioning)
    python -m curtailmit.spatial inspect                                       parse the local shapefile and print its feature / vertex counts

Shapefile conventions used: outer rings are clockwise and holes counter-clockwise (ESRI specification), which is what lets one compound matplotlib path draw holes with the non-zero winding rule.
"""

from __future__ import annotations

import argparse
import json
import shutil
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from curtailmit import provenance as prov

GADM_STEM = "gadm41_BRA_1"
GADM_SIBLINGS = (".shp", ".dbf", ".prj", ".cpg")
GADM_SOURCE_URL = "https://geodata.ucdavis.edu/gadm/gadm4.1/shp/gadm41_BRA_shp.zip"  # the official GADM 4.1 download location of this layer; the file was copied from a local copy, not re-fetched
GADM_ORIGINAL_DATE = "2022-07-18"
GADM_NOTE = ("GADM 4.1 level 1 (Brazilian states), copied from a local copy (DOUTORADO/GeoFREA_data, byte-identical to DOUTORADO/database/raw/countries_borders/Brazil, file date 2022-07-18); "
             "not fetched by the pipeline, so http_status is null and retrieved_at_utc is the time of the copy. Local-only: never committed (decision D36).")
RAW_SUBDIR = ("boundaries", "gadm")
SIMPLIFY_TOLERANCE_DEG = 0.02
SHP_POLYGON_TYPES = (5, 15, 25)  # Polygon, PolygonZ, PolygonM


class SpatialError(ValueError):
    """The shapefile cannot be read as polygons, or the provisioning inputs are inconsistent."""


Ring = np.ndarray  # (n, 2) float array, closed (first point == last point)


# ============================================================================================================================================================================ shapefile reader
def read_shp(path: Path) -> list[list[Ring]]:
    """One entry per record: its rings (outer rings and holes), each a closed (n, 2) array. Null shapes give an empty list; any non-polygon shape type is an error."""
    data = Path(path).read_bytes()
    if len(data) < 100 or struct.unpack(">i", data[:4])[0] != 9994:
        raise SpatialError(f"{path}: not an ESRI shapefile (bad file code)")
    pos, shapes = 100, []
    while pos + 8 <= len(data):
        _rec, words = struct.unpack(">ii", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + words * 2]
        pos += 8 + words * 2
        stype = struct.unpack("<i", body[:4])[0]
        if stype == 0:
            shapes.append([])
            continue
        if stype not in SHP_POLYGON_TYPES:
            raise SpatialError(f"{path}: shape type {stype} is not a polygon")
        nparts, npts = struct.unpack("<ii", body[36:44])
        parts = np.frombuffer(body, dtype="<i4", count=nparts, offset=44)
        pts = np.frombuffer(body, dtype="<f8", count=npts * 2, offset=44 + 4 * nparts).reshape(npts, 2).astype(float)
        bounds = list(parts) + [npts]
        shapes.append([pts[bounds[i]:bounds[i + 1]].copy() for i in range(nparts)])
    return shapes


def read_dbf(path: Path) -> list[dict]:
    """Attribute rows of a dBase III table (character, numeric, logical, date as text). Rows flagged as deleted are skipped. Encoding: the `.cpg` next to it, else UTF-8."""
    path = Path(path)
    cpg = path.with_suffix(".cpg")
    enc = cpg.read_text(encoding="ascii", errors="ignore").strip() if cpg.is_file() else "utf-8"
    raw = path.read_bytes()
    n, header_len, rec_len = struct.unpack("<IHH", raw[4:12])
    fields, off = [], 32
    while raw[off] != 0x0D:
        d = raw[off:off + 32]
        fields.append((d[:11].split(b"\0")[0].decode("ascii"), chr(d[11]), d[16], d[17]))
        off += 32
    rows = []
    for i in range(n):
        rec = raw[header_len + i * rec_len: header_len + (i + 1) * rec_len]
        if rec[:1] == b"*":
            continue
        row, o = {}, 1
        for name, ftype, length, _dec in fields:
            txt = rec[o:o + length].decode(enc, errors="replace").strip()
            o += length
            if ftype in "NF":
                row[name] = None if txt == "" else (float(txt) if any(c in txt for c in ".eE") else int(txt))
            elif ftype == "L":
                row[name] = {"T": True, "Y": True, "F": False, "N": False}.get(txt.upper())
            else:
                row[name] = txt
        rows.append(row)
    return rows


# ==================================================================================================================================================================================== geometry
def signed_area(ring: Ring) -> float:
    """Shoelace area; negative for a clockwise ring (the shapefile convention for an outer ring), positive for a hole."""
    x, y = ring[:, 0], ring[:, 1]
    return float(0.5 * np.sum(x[:-1] * y[1:] - x[1:] * y[:-1]))


def is_hole(ring: Ring) -> bool:
    return signed_area(ring) > 0


def shape_area(rings: list[Ring]) -> float:
    """Net area in square degrees: outer rings minus holes (orientation decides)."""
    return float(-sum(signed_area(r) for r in rings))


def shape_bounds(rings: list[Ring]) -> tuple[float, float, float, float]:
    allp = np.vstack(rings)
    return float(allp[:, 0].min()), float(allp[:, 1].min()), float(allp[:, 0].max()), float(allp[:, 1].max())


def _dp_keep(pts: np.ndarray, tol: float) -> np.ndarray:
    """Boolean mask of the points kept by Douglas-Peucker on an open polyline (iterative; no recursion limit)."""
    n = len(pts)
    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        seg = pts[i + 1:j]
        a, b = pts[i], pts[j]
        d = b - a
        norm = np.hypot(d[0], d[1])
        if norm == 0.0:
            dist = np.hypot(seg[:, 0] - a[0], seg[:, 1] - a[1])
        else:
            dist = np.abs(d[0] * (seg[:, 1] - a[1]) - d[1] * (seg[:, 0] - a[0])) / norm
        k = int(np.argmax(dist))
        if dist[k] > tol:
            m = i + 1 + k
            keep[m] = True
            stack.append((i, m))
            stack.append((m, j))
    return keep


def simplify_ring(ring: Ring, tol: float = SIMPLIFY_TOLERANCE_DEG) -> Ring:
    """Douglas-Peucker on a closed ring: split at the point farthest from the start so that the closing segment is never degenerate. Returns a closed ring with at least 4 points, or the input unchanged
    when it has too few points to simplify."""
    if len(ring) <= 5:
        return ring
    pts = ring[:-1]
    far = int(np.argmax(np.hypot(pts[:, 0] - pts[0, 0], pts[:, 1] - pts[0, 1])))
    first = pts[:far + 1]
    second = np.vstack([pts[far:], pts[:1]])
    kept = np.vstack([first[_dp_keep(first, tol)], second[_dp_keep(second, tol)][1:]])
    if len(kept) < 4:
        return ring
    if not np.array_equal(kept[0], kept[-1]):
        kept = np.vstack([kept, kept[:1]])
    return kept


def simplify_shape(rings: list[Ring], tol: float = SIMPLIFY_TOLERANCE_DEG) -> list[Ring]:
    """Simplify every ring of a shape. No ring is dropped (a ring too small to simplify is returned as it is), so a state or an island never disappears from the map."""
    return [simplify_ring(r, tol) for r in rings]


def path_arrays(rings: list[Ring]) -> tuple[np.ndarray, np.ndarray]:
    """(vertices, codes) for one compound `matplotlib.path.Path` (MOVETO, LINETO..., CLOSEPOLY per ring). Codes are the matplotlib integers 1 / 2 / 79; opposite ring orientation makes holes."""
    verts, codes = [], []
    for r in rings:
        n = len(r)
        verts.append(r)
        codes.extend([1] + [2] * (n - 2) + [79])
    return np.vstack(verts), np.array(codes, dtype=np.uint8)


# ================================================================================================================================================================================ GADM states
def uf_of(hasc: str) -> str:
    """`BR.BA` -> `BA` (the ONS `id_estado` code)."""
    return str(hasc).split(".")[-1]


def read_states(shp_path: Path, tol: float | None = SIMPLIFY_TOLERANCE_DEG) -> dict[str, dict]:
    """{UF: {"name", "hasc", "rings"}} from a GADM level-1 shapefile (simplified when `tol` is given). Refuses a layer whose feature and attribute counts differ or whose HASC codes repeat."""
    shp_path = Path(shp_path)
    shapes = read_shp(shp_path)
    rows = read_dbf(shp_path.with_suffix(".dbf"))
    if len(shapes) != len(rows):
        raise SpatialError(f"{shp_path.name}: {len(shapes)} shapes but {len(rows)} attribute rows")
    states: dict[str, dict] = {}
    for rings, row in zip(shapes, rows, strict=True):
        uf = uf_of(row["HASC_1"])
        if uf in states:
            raise SpatialError(f"{shp_path.name}: state code {uf} appears twice")
        states[uf] = {"name": row.get("NAME_1", uf), "hasc": row["HASC_1"], "rings": simplify_shape(rings, tol) if tol else rings}
    return states


def default_dir(raw_root: Path | None = None) -> Path:
    if raw_root is None:
        from curtailmit import paths

        raw_root = paths.planned_layout()["root"] / "raw"
    return Path(raw_root).joinpath(*RAW_SUBDIR)


def default_shp(raw_root: Path | None = None) -> Path:
    return default_dir(raw_root) / f"{GADM_STEM}.shp"


# ===================================================================================================================================================================== provisioning (one-off)
def provision(source_shp: Path, raw_root: Path | None = None, now_utc: str | None = None) -> list[Path]:
    """Copy `gadm41_BRA_1.{shp,dbf,prj,cpg}` into raw/boundaries/gadm/ and write a retrieval manifest next to each (SHA-256, size, source URL, note), so that the file enters the data snapshot manifest
    (D33). Refuses a source with a different stem and refuses to overwrite a file whose bytes differ."""
    source_shp = Path(source_shp)
    if source_shp.stem != GADM_STEM:
        raise SpatialError(f"expected {GADM_STEM}.shp, got {source_shp.name}")
    dest = default_dir(raw_root)
    dest.mkdir(parents=True, exist_ok=True)
    stamp = now_utc or datetime.now(timezone.utc).isoformat()
    written = []
    for ext in GADM_SIBLINGS:
        src, dst = source_shp.with_suffix(ext), dest / f"{GADM_STEM}{ext}"
        if not src.is_file():
            raise SpatialError(f"missing {src}")
        if dst.is_file() and prov.sha256_file(dst) != prov.sha256_file(src):
            raise SpatialError(f"{dst} exists with different bytes; not overwritten")
        if not dst.is_file():
            shutil.copy2(src, dst)
        meta = {"source_url": GADM_SOURCE_URL, "http_status": None, "retrieved_at_utc": stamp, "sha256": prov.sha256_file(dst), "byte_size": dst.stat().st_size, "params": {},
                "source": "GADM 4.1", "package_id": None, "resource_id": None, "row_count": None, "original_file_date": GADM_ORIGINAL_DATE, "note": GADM_NOTE}
        side = dst.with_suffix(dst.suffix + ".manifest.json")
        if not side.is_file():
            side.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        written.append(dst)
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="GADM boundary geometry for the context maps (decision D36; local-only data).")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("provision", help="copy the GADM shapefile set into raw/boundaries/gadm/ with retrieval manifests")
    p.add_argument("--source", type=Path, required=True)
    sub.add_parser("inspect", help="parse the local shapefile and print counts")
    args = ap.parse_args(argv)
    try:
        if args.command == "provision":
            for f in provision(args.source):
                print(f"provisioned {f}")
            return 0
        shp = default_shp()
        full = read_states(shp, tol=None)
        simp = read_states(shp)
        n_full = sum(len(r) for s in full.values() for r in s["rings"])
        n_simp = sum(len(r) for s in simp.values() for r in s["rings"])
        print(f"{shp.name}: {len(full)} states, {n_full} vertices, {n_simp} after simplification (tolerance {SIMPLIFY_TOLERANCE_DEG} degrees)")
        return 0
    except (SpatialError, OSError) as exc:
        print(f"spatial: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
