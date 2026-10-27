"""Known limitations carried with the production outputs of option E (Task 11F-3).

The adopted text of D25 (residual upward drift of the wind curtailment rate at fixed r) is read from config/discovered_sources.yaml, the single source of truth, so the
output tables cannot drift away from the recorded decision. The loader fails loudly if the decision is not `adopted`. Rows carry short ids (`known_limitations`); the full
text and the quantified bounds travel in a sidecar JSON next to the table and in the parquet file-level metadata.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

DECISIONS_PATH = Path(__file__).resolve().parents[2] / "config" / "discovered_sources.yaml"
LIMITATIONS_SIDECAR_SUFFIX = ".limitations.json"
D25 = "D25"
SOLAR_SHORT_RECORD = "SOLAR_SHORT_RECORD"
REFERENCE_NOT_PRODUCTION = "REFERENCE_NOT_PRODUCTION"
DRIFT_DIRECTION = "upward"  # the central values of option E are more likely low than high (D25)

# Quantified bounds transcribed from the adopted D25 text (tests assert that each figure appears in the text). The row caveat text of results_writer.limitations_text is built from the same
# constants, so the numbers exist once in code.
D25_DRIFT_RANGE = "+1.4 to +1.6"
D25_DRIFT_PERIOD = "2022-2026"
SOLAR_MONTHS = 30  # months of dispatched solar generation in the calibration record (D14 floor 2024-04); wind has 57
FLEX_2050_RANGE = "phi 1.5 to L=1"  # the flexibility-conditional 2050 range (D24)
D25_QUANTIFIED = {
    "rate_drift_pp_per_year": f"{D25_DRIFT_RANGE} (95 percent interval 0.5 to 2.7), {D25_DRIFT_PERIOD}",
    "wind_additional_2030": "+10-14 percent of wind curtailment",
    "wind_additional_2050": "+1-4 percent (step); +15-20 TWh (saturating); at most +34-52 TWh (linear, capped) = 3-15 percent of the 2050 wind + solar total",
    "direction": DRIFT_DIRECTION,
}
SOLAR_NOTE = f"Solar curve fitted on {SOLAR_MONTHS} months of dispatched-generation data (from 2024-04); shorter record than wind (57 months)."
D26_NOTE = ("Transmission-expansion (PDE/PET) extension retired (D26); sensitivity note: in 2026, 38 percent of Northeast wind curtailment is still attributable to network-element "
            "limits and 23 percent is internal to the Northeast.")


class LimitationError(RuntimeError):
    pass


def load_adopted_decision(decision_id: str, path: Path | None = None) -> dict:
    """The decision entry from discovered_sources.yaml; raises LimitationError unless its status is `adopted`."""
    with open(path or DECISIONS_PATH, encoding="utf-8") as f:
        decisions = yaml.safe_load(f)["decisions"]
    d = decisions.get(decision_id)
    if d is None:
        raise LimitationError(f"decision {decision_id} not found in {path or DECISIONS_PATH}")
    if d.get("status") != "adopted":
        raise LimitationError(f"decision {decision_id} is '{d.get('status')}', not 'adopted': its limitation text cannot be attached to production outputs.")
    return d


def adopted_text(decision: dict) -> str:
    """The adopted decision text (whitespace-normalised); the preamble of the `decided` field up to 'verbatim:' is dropped."""
    text = " ".join(str(decision["decided"]).split())
    return text.split("verbatim:", 1)[1].strip() if "verbatim:" in text else text


def d25_limitation(path: Path | None = None) -> dict:
    d = load_adopted_decision(D25, path)
    return {"id": D25, "adopted": str(d.get("date_adopted", "")), "text": adopted_text(d), "quantified": D25_QUANTIFIED}


def limitations_payload(path: Path | None = None) -> dict:
    """Sidecar content for an option-E table: D25 (wind), the solar short-record note, the D26 sensitivity note."""
    return {"known_limitations": [d25_limitation(path), {"id": SOLAR_SHORT_RECORD, "text": SOLAR_NOTE}, {"id": "D26_NOTE", "text": D26_NOTE}], "drift_direction": DRIFT_DIRECTION}


def write_table_with_limitations(table: pd.DataFrame, dest: Path, payload: dict | None = None) -> Path:
    """Write the parquet table with the limitations JSON in its file-level metadata and as <dest>.limitations.json next to it."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    payload = payload if payload is not None else limitations_payload()
    blob = json.dumps(payload, ensure_ascii=False)
    arrow = pa.Table.from_pandas(table, preserve_index=False)
    arrow = arrow.replace_schema_metadata({**(arrow.schema.metadata or {}), b"curtailmit_limitations": blob.encode("utf-8")})
    pq.write_table(arrow, dest)
    dest.with_name(dest.name + LIMITATIONS_SIDECAR_SUFFIX).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return dest


def read_table_limitations(path: Path) -> dict:
    """Limitations payload stored in the parquet file-level metadata."""
    import pyarrow.parquet as pq

    meta = pq.read_schema(path).metadata or {}
    return json.loads(meta[b"curtailmit_limitations"].decode("utf-8"))
