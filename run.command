#!/bin/bash
# Double-click to run on macOS. Opens a terminal, runs the pipeline,
# and keeps the window open so you can read the output.

set -e
cd "$(dirname "$0")"

# Clear any system-wide virtualenv that would shadow uv's project env.
unset VIRTUAL_ENV

# Make sure deps are installed (idempotent — no-op if already synced).
if [ ! -d ".venv" ]; then
  echo "First run — installing dependencies ..."
  uv sync
fi

echo ""
echo "  ┌─────────────────────────────────────────────┐"
echo "  │  Delphi AI Webcam — animated anon guest     │"
echo "  └─────────────────────────────────────────────┘"
echo ""

uv run delphi "$@"

echo ""
read -n 1 -s -r -p "Press any key to close ..."
echo ""
