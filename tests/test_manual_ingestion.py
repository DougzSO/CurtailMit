from pathlib import Path

import pandas as pd
import pytest

from curtailmit.manual_ingestion import load_manually_placed_file, ManualIngestionRequired


def test_raises_actionable_error_when_missing(tmp_path: Path):
    missing = tmp_path / "does_not_exist.xlsx"
    with pytest.raises(ManualIngestionRequired) as exc:
        load_manually_placed_file(missing, instructions="Download X and place it here.")
    assert "Download X" in str(exc.value)


def test_loads_existing_csv(tmp_path: Path):
    f = tmp_path / "data.csv"
    pd.DataFrame({"a": [1, 2]}).to_csv(f, index=False)
    df = load_manually_placed_file(f, instructions="n/a", reader="csv")
    assert list(df["a"]) == [1, 2]
