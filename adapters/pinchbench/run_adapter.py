#!/usr/bin/env python3
"""Compatibility wrapper for running the packaged Pinchbench adapter."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from pinchbench_adapter.main import main


if __name__ == "__main__":
    main()
