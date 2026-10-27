"""Task 14: extract tests/fixtures/final_results/reference_totals.json from the validated Task 13 final_results (all `total` rows). One-off; re-run only as a conscious decision to re-baseline."""

from __future__ import annotations

import json
from pathlib import Path

from curtailmit.paths import get_outputs_dir
from curtailmit.results_writer import read_final_results

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "final_results" / "reference_totals.json"


def main() -> None:
    df = read_final_results(get_outputs_dir("tables") / "final_results.parquet")
    tot = df[df.component == "total"].sort_values(["quantity", "scenario", "year"])
    body = {
        "description": "Central values of every `total` row of final_results (Task 13, commit 57d9488; curtailed energy reconciled to Task 11F to 1e-12). Used by the orchestrator's reference-value check (Task 14).",
        "rtol": 1e-9,
        "n_rows": int(len(df)),
        "totals": [{"scenario": r.scenario, "year": int(r.year), "quantity": r.quantity, "component": r.component, "unit": r.unit, "central_value": float(r.central_value)} for r in tot.itertuples()],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(body, indent=1) + "\n", encoding="utf-8")
    print(OUT, len(body["totals"]))


if __name__ == "__main__":
    main()
