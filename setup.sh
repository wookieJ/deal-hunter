#!/usr/bin/env bash
# One-time setup: create the venv and install dependencies.
set -euo pipefail
cd "$(dirname "$0")"
python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt
echo "Done. Run: ./run.sh run --profile gravel"
