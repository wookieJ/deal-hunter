#!/usr/bin/env bash
# Convenience wrapper: activates the local venv and runs the CLI.
#   ./run.sh run --profile gravel
#   ./run.sh top -n 20
set -euo pipefail
cd "$(dirname "$0")"
[[ -d .venv ]] || { echo "No .venv found - run ./setup.sh first"; exit 1; }
PYTHONPATH=src exec .venv/bin/python -m dealhunter "$@"
