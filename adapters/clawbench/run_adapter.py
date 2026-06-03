#!/usr/bin/env python3
"""Run the ClawBench adapter from the repository root."""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(SRC))

from clawbench_adapter.main import main  # noqa: E402


if __name__ == "__main__":
    main()
