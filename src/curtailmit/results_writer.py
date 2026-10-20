"""
results_writer.py

Final output schema and mechanical writer for the CurtailMit pipeline
final per-scenario/year results table.

This module defines the schema for the final combined output (one row
per scenario x year) and provides CSV/JSON writers and loaders. It does
not compute any values itself - it is a mechanical schema + writer
layer, consuming already-computed rows produced by projection.py,
mitigation.py, hydrogen.py, and emission_factors.py. Real wiring of the
full pipeline into this writer is deferred to Claude Code Task 13.

Schema notes
------------
- Marginal mitigation deficit is reported as a breakdown of BOTH the
  Operating Margin (OM) proxy value (DEB proxy) and the Combined Margin
  (CM) proxy value (REB proxy), never collapsed into one undifferentiated
  "marginal" number. This allows downstream analysis and the DeCarbon
  manuscript to present DEB- and REB-specific deficit sensitivity
  independently, consistent with docs/methodology.md Section 2.5 and
  decision D12.
- classification_available is always recorded explicitly. It reflects
  whether ONS curtailment classification (DEB/REB/EUB) was available at
  the data stage; it does not gate whether OM/CM columns are present
  (those are always computed, as general marginal proxies), but it does
  affect how the OM/CM figures should be interpreted in the manuscript
  (classification-specific proxies vs. generic marginal proxies).
- H2 potential is always a min/central/max range, never a single point.
- is_interpolated / source follow projection.py labeling convention
  exactly (source in {"historical_ons", "pte_projection",
  "interpolated"}).
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Iterable

from curtailmit.validation import ValidationError

VALID_SOURCES = ("historical_ons", "pte_projection", "interpolated")


@dataclass(frozen=True)
class ResultsRow:
    """One row of the final CurtailMit output table: one scenario x year."""

    scenario: str
    year: int
    source: str
    is_interpolated: bool
    classification_available: bool

    E_curt_twh: float

    mitigation_deficit_avg_tco2: float
    mitigation_deficit_marginal_om_tco2: float
    mitigation_deficit_marginal_cm_tco2: float
    marginal_proxy_note: str

    h2_potential_min_kg: float
    h2_potential_central_kg: float
    h2_potential_max_kg: float

    def __post_init__(self) -> None:
        if self.source not in VALID_SOURCES:
            raise ValidationError(
                f"source must be one of {VALID_SOURCES}, got {self.source!r}."
            )
        if self.source == "historical_ons" and self.is_interpolated:
            raise ValidationError(
                "A row sourced from historical_ons cannot be is_interpolated=True."
            )
        if self.source == "interpolated" and not self.is_interpolated:
            raise ValidationError(
                "A row with source='interpolated' must have is_interpolated=True."
            )
        if self.E_curt_twh < 0:
            raise ValidationError(f"E_curt_twh must be non-negative, got {self.E_curt_twh}.")
        if self.mitigation_deficit_avg_tco2 < 0:
            raise ValidationError("mitigation_deficit_avg_tco2 must be non-negative.")
        if self.mitigation_deficit_marginal_om_tco2 < 0:
            raise ValidationError("mitigation_deficit_marginal_om_tco2 must be non-negative.")
        if self.mitigation_deficit_marginal_cm_tco2 < 0:
            raise ValidationError("mitigation_deficit_marginal_cm_tco2 must be non-negative.")
        if not (self.h2_potential_min_kg <= self.h2_potential_central_kg <= self.h2_potential_max_kg):
            raise ValidationError(
                "H2 potential range must satisfy min <= central <= max "
                f"(got min={self.h2_potential_min_kg}, "
                f"central={self.h2_potential_central_kg}, "
                f"max={self.h2_potential_max_kg})."
            )


RESULTS_COLUMNS: tuple[str, ...] = tuple(f.name for f in fields(ResultsRow))


def write_results_csv(rows: Iterable[ResultsRow], path: Path) -> Path:
    """Write rows to a CSV file at path, creating parent dirs as needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RESULTS_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))
    return path


def write_results_json(rows: Iterable[ResultsRow], path: Path) -> Path:
    """Write rows to a JSON file at path, creating parent dirs as needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    data = [asdict(row) for row in rows]
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def load_results_csv(path: Path) -> list[ResultsRow]:
    """Load and reconstruct ResultsRow objects from a CSV file."""
    path = Path(path)
    rows: list[ResultsRow] = []
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            rows.append(_row_from_raw_dict(raw))
    return rows


def load_results_json(path: Path) -> list[ResultsRow]:
    """Load and reconstruct ResultsRow objects from a JSON file."""
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    return [_row_from_raw_dict(raw) for raw in data]


def _row_from_raw_dict(raw: dict[str, Any]) -> ResultsRow:
    coerced: dict[str, Any] = dict(raw)
    coerced["year"] = int(raw["year"])
    coerced["is_interpolated"] = _coerce_bool(raw["is_interpolated"])
    coerced["classification_available"] = _coerce_bool(raw["classification_available"])
    for key in (
        "E_curt_twh",
        "mitigation_deficit_avg_tco2",
        "mitigation_deficit_marginal_om_tco2",
        "mitigation_deficit_marginal_cm_tco2",
        "h2_potential_min_kg",
        "h2_potential_central_kg",
        "h2_potential_max_kg",
    ):
        coerced[key] = float(raw[key])
    return ResultsRow(**coerced)


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)