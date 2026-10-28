"""Synthetic shapefile fixture for tests/test_spatial.py (Task 17). NOT derived from any GADM or other real geometry: a handful of invented polygons (a square with a hole, a triangle, a two-part
polygon, a finely wavy circle for simplification, a tiny square and a big polygon with a tiny island). Regenerate with:  python tests/fixtures/spatial/make_fixture.py

Conventions of the ESRI specification: outer rings clockwise, holes counter-clockwise, every ring closed.
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
STEM = "synthetic_states"

_theta = np.linspace(0.0, 2.0 * np.pi, 361)[:-1]
# clockwise: decreasing angle
_WAVY = np.column_stack([60.0 + (12.0 + 0.004 * np.sin(20 * _theta)) * np.cos(-_theta), 20.0 + (12.0 + 0.004 * np.sin(20 * _theta)) * np.sin(-_theta)])
_WAVY = np.vstack([_WAVY, _WAVY[:1]])

# name, HASC code, rings (each closed)
FEATURES = [
    ("Square with hole", "XX.AA", [[(0, 0), (0, 4), (4, 4), (4, 0), (0, 0)], [(1, 1), (3, 1), (3, 3), (1, 3), (1, 1)]]),
    ("Triangle", "XX.BB", [[(5, 0), (6, 2), (7, 0), (5, 0)]]),
    ("Two parts", "XX.CC", [[(8, 0), (8, 1), (9, 1), (9, 0), (8, 0)], [(10, 0), (10, 1), (11, 1), (11, 0), (10, 0)]]),
    ("Wavy circle", "XX.DD", [[tuple(p) for p in _WAVY]]),
    ("Tiny square", "XX.EE", [[(30, 30), (30, 30.005), (30.005, 30.005), (30.005, 30), (30, 30)]]),
    ("Big with islet", "XX.FF", [[(40, 0), (40, 6), (46, 6), (46, 0), (40, 0)], [(48, 1), (48.004, 1.002), (48.006, 1.006), (48.004, 1.01), (48, 1.012), (47.996, 1.006), (47.994, 1.002), (48, 1)]]),
]


def _ring_arrays() -> list[list[np.ndarray]]:
    return [[np.asarray(r, dtype="<f8") for r in rings] for _, _, rings in FEATURES]


def write_shp(path: Path, shapes: list[list[np.ndarray]]) -> None:
    records = []
    for i, rings in enumerate(shapes, start=1):
        pts = np.vstack(rings)
        parts, off = [], 0
        for r in rings:
            parts.append(off)
            off += len(r)
        content = struct.pack("<i4dii", 5, pts[:, 0].min(), pts[:, 1].min(), pts[:, 0].max(), pts[:, 1].max(), len(rings), len(pts)) + struct.pack(f"<{len(parts)}i", *parts) + pts.astype("<f8").tobytes()
        records.append(struct.pack(">ii", i, len(content) // 2) + content)
    allp = np.vstack([np.vstack(s) for s in shapes])
    body = b"".join(records)
    header = struct.pack(">i5ii", 9994, 0, 0, 0, 0, 0, (100 + len(body)) // 2) + struct.pack("<ii4d4d", 1000, 5, allp[:, 0].min(), allp[:, 1].min(), allp[:, 0].max(), allp[:, 1].max(), 0.0, 0.0, 0.0, 0.0)
    Path(path).write_bytes(header + body)


def write_dbf(path: Path, rows: list[tuple[str, str, float]]) -> None:
    fields = [("HASC_1", "C", 8, 0), ("NAME_1", "C", 20, 0), ("AREA_N", "N", 10, 2)]
    rec_len = 1 + sum(f[2] for f in fields)
    header_len = 32 + 32 * len(fields) + 1
    out = bytearray(struct.pack("<BBBBIHH20x", 3, 126, 10, 28, len(rows), header_len, rec_len))
    for name, ftype, length, dec in fields:
        out += name.encode("ascii").ljust(11, b"\0") + ftype.encode("ascii") + b"\0\0\0\0" + bytes([length, dec]) + b"\0" * 14
    out += b"\r"
    for hasc, name, area in rows:
        out += b" " + hasc.encode("utf-8").ljust(8)[:8] + name.encode("utf-8").ljust(20)[:20] + f"{area:10.2f}".encode("ascii")
    out += b"\x1a"
    Path(path).write_bytes(bytes(out))


def build(dest: Path = HERE) -> list[Path]:
    dest = Path(dest)
    shp, dbf, cpg = dest / f"{STEM}.shp", dest / f"{STEM}.dbf", dest / f"{STEM}.cpg"
    write_shp(shp, _ring_arrays())
    write_dbf(dbf, [(h, n, float(i)) for i, (n, h, _) in enumerate(FEATURES, start=1)])
    cpg.write_text("UTF-8", encoding="ascii")
    return [shp, dbf, cpg]


if __name__ == "__main__":
    for p in build():
        print(p)
