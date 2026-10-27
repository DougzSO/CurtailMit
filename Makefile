.PHONY: setup setup-locked test lint stage1 run discover

# setup        = flexible / development install: newest releases allowed by the floors in requirements.txt (what the CI "unit-tests" job tests).
# setup-locked = exact-pin reproducibility install: requirements.lock.txt, the environment in which the published results were verified (what the CI "unit-tests-locked" job tests).
#                See docs/reproducibility.md section 2. Recipes are Windows-style (.venv\Scripts); on Linux/macOS use .venv/bin/pip.
setup:
	python -m venv .venv
	.venv\Scripts\pip install -r requirements.txt

setup-locked:
	python -m venv .venv
	.venv\Scripts\pip install -r requirements.lock.txt
	.venv\Scripts\pip install -e . --no-deps

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
