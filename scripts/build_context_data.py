"""Thin shim: `python scripts/build_context_data.py [--force]` -> curtailmit.context_data (observed curtailment by state and year for the context maps, Task 17). Not a curtailmit-run stage."""

from curtailmit.context_data import main

if __name__ == "__main__":
    raise SystemExit(main())
