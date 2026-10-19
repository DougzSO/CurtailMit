.PHONY: setup test lint stage1

setup:
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

test:
pytest -v

lint:
ruff check src tests

stage1:
python -m curtailmit.data_ingestion
