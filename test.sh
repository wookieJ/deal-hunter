#!/usr/bin/env bash
# Run the unit test suite (stdlib unittest, no extra dependencies).
set -euo pipefail
cd "$(dirname "$0")"
PYTHONPATH=src exec .venv/bin/python -m unittest discover -s tests -v
