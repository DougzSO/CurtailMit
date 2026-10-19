.PHONY: setup test lint stage1 run discover

setup:
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

test:
pytest -v -m "not integration"

lint:
ruff check src tests

stage1:
python -m curtailmit.data_ingestion

run:
python scripts/run_pipeline.py

discover:
python scripts/discovery_probe.py
