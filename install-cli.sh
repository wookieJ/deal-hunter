#!/usr/bin/env bash
# Put `deal` on your PATH so the tool can be run from any directory.
#
# The launcher installed in .venv/bin already points at this project's virtualenv
# via its shebang, and the package resolves its config/ and data/ directories
# relative to this checkout - so a symlink is all that is needed, and the working
# directory never matters.
set -euo pipefail
cd "$(dirname "$0")"
PROJECT="$(pwd)"

[[ -d .venv ]] || { echo "No .venv found - run ./setup.sh first"; exit 1; }
.venv/bin/pip install --quiet -e .

pick_bin_dir() {
    if [[ -n "${DEAL_BIN_DIR:-}" ]]; then echo "$DEAL_BIN_DIR"; return; fi
    # Prefer a directory that is already on PATH, so no shell config is needed.
    for dir in "$HOME/.local/bin" "$HOME/bin" /usr/local/bin /opt/homebrew/bin; do
        if [[ -d "$dir" && -w "$dir" && ":$PATH:" == *":$dir:"* ]]; then
            echo "$dir"; return
        fi
    done
    echo "$HOME/.local/bin"
}

BIN_DIR="$(pick_bin_dir)"
mkdir -p "$BIN_DIR"
ln -sf "$PROJECT/.venv/bin/deal" "$BIN_DIR/deal"
echo "Installed: $BIN_DIR/deal -> $PROJECT/.venv/bin/deal"

if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    cat <<HINT

$BIN_DIR is not on your PATH. Add this to ~/.zshrc (or ~/.bashrc):

    export PATH="$BIN_DIR:\$PATH"

then open a new terminal.
HINT
else
    echo "Done. From any directory: deal run"
fi
