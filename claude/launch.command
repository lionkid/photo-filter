#!/bin/bash
# launch.command — double-click on macOS to start the Photo Filter web app

set -e

# cd to the directory containing this script
cd "$(dirname "$0")"

# ── Find Python 3 ──────────────────────────────────────────────────────────────
PYTHON=""
for candidate in \
    /opt/homebrew/bin/python3 \
    /usr/local/bin/python3 \
    /usr/bin/python3 \
    python3; do
    if command -v "$candidate" &>/dev/null; then
        PYTHON="$candidate"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "ERROR: Python 3 not found. Install from https://www.python.org or via Homebrew:"
    echo "  brew install python"
    read -rp "Press Enter to exit…"
    exit 1
fi

echo "Using Python: $($PYTHON --version)"

# ── Create virtual environment if missing ─────────────────────────────────────
if [ ! -d "venv" ]; then
    echo "Creating virtual environment…"
    "$PYTHON" -m venv venv
fi

VENV_PYTHON="venv/bin/python"
VENV_PIP="venv/bin/pip"

# ── Install dependencies if sentinel missing ──────────────────────────────────
SENTINEL="venv/.deps_installed"
if [ ! -f "$SENTINEL" ]; then
    echo "Installing dependencies (this may take a minute on first run)…"
    "$VENV_PIP" install --upgrade pip -q
    "$VENV_PIP" install -r requirements.txt
    touch "$SENTINEL"
    echo "Dependencies installed."
fi

# ── Open browser after short delay ────────────────────────────────────────────
(sleep 2 && open http://127.0.0.1:5000) &

echo ""
echo "Starting Photo Filter at http://127.0.0.1:5000"
echo "Press Ctrl+C to stop."
echo ""

"$VENV_PYTHON" app.py
