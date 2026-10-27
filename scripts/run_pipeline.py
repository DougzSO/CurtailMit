"""Thin shim: `make run` / `python scripts/run_pipeline.py` -> curtailmit.pipeline (all logic lives in the package; see docs/orchestration.md)."""

from curtailmit.pipeline import main

if __name__ == "__main__":
    raise SystemExit(main())
