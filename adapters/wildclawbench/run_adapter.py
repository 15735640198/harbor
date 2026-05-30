#!/usr/bin/env python3
"""Compatibility wrapper for running the WildClawBench adapter from the repo root."""

from pathlib import Path
import sys

ADAPTER_SRC = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(ADAPTER_SRC))

from wildclawbench_adapter.main import main  # noqa: E402


if __name__ == "__main__":
    main()
