"""Thin shim: `python scripts/generate_figures.py` -> curtailmit.figures (all logic lives in the package; see docs/task13b_design.md). Figures are not a stage of curtailmit-run."""

from curtailmit.figures import main

if __name__ == "__main__":
    raise SystemExit(main())
