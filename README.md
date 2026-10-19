# CurtailMit

Quantifying the curtailment-driven mitigation deficit under Brazil's PTE/EPE energy
transition scenarios, with green-hydrogen valorization potential.

Target venue: DeCarbon.

## Structure

- config/   : scenario data and pipeline configuration
- docs/     : roadmap.md and methodology.md (source of truth)
- src/curtailmit/ : pipeline source code (Stages 1-6)
- tests/    : unit tests

## Data

Raw/processed data live in a separate, local-only repository (curtailmit_database,
sibling directory), not published here. Set DATABASE_ROOT in .env (copy from .env.example).

## Setup

python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env

## Pipeline stages

1. data_ingestion.py  - load config, discover/validate ONS + MCTI sources
2. calibration.py     - fit curtailment function on historical data
3. projection.py      - apply function to PTE scenarios
4. mitigation.py      - compute mitigation deficit (average vs marginal sensitivity)
5. hydrogen.py        - green-H2 valorization potential
6. results_writer.py  - persist tables/figures/reports with data-quality flags
