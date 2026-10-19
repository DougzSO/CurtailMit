"""Entry point to run the full CurtailMit pipeline, stage by stage."""

import logging

from curtailmit.data_ingestion import run_stage1

logging.basicConfig(level=logging.INFO)


def main():
    report = run_stage1()
    print("Stage 1 complete:", report)
    # TODO: Stage 2 (calibration), Stage 3 (projection), Stage 4 (mitigation),
    # Stage 5 (hydrogen), Stage 6 (results_writer) - to be added incrementally.


if __name__ == "__main__":
    main()
