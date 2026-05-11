#!/bin/bash
set -euo pipefail

# Install required Python packages
pip install -q 'pyyaml>=6.0'

# Use simple judge for validation (no LLM required)
python /tests/simple_judge.py
