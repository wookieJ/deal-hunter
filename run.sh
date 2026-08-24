#!/usr/bin/env bash
# Convenience wrapper: activates the local venv and runs the CLI.
#   ./run.sh run --profile gravel
#   ./run.sh top -n 20
set -euo pipefail
cd "$(dirname "$0")"
[[ -d .venv ]] || { echo "Brak .venv - uruchom najpierw: ./setup.sh"; exit 1; }
PYTHONPATH=src exec .venv/bin/python -m dealhunter "$@"
