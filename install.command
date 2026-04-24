#!/bin/bash
# One-click installer for macOS. Double-click from Finder.
# Checks / installs: Homebrew, uv, ffmpeg. Runs uv sync. Creates .env.

set -e
cd "$(dirname "$0")"

echo ""
echo "  ┌─────────────────────────────────────────────┐"
echo "  │  Delphi AI Webcam — installer (macOS)       │"
echo "  └─────────────────────────────────────────────┘"
echo ""

# Homebrew — required. We don't install it ourselves because it needs sudo
# and changes /opt/homebrew; better to let the user do that themselves.
if ! command -v brew >/dev/null 2>&1; then
  echo "✗ Homebrew is not installed."
  echo ""
  echo "  Install it first by pasting this into a Terminal window:"
  echo ""
  echo '    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
  echo ""
  echo "  Then double-click this installer again."
  echo ""
  read -n 1 -s -r -p "Press any key to close ..."
  echo ""
  exit 1
fi
echo "✓ Homebrew found"

# uv + ffmpeg — `brew install` is idempotent (no-ops if already present).
echo ""
echo "→ Checking system dependencies ..."
brew list uv >/dev/null 2>&1 || { echo "  installing uv ..."; brew install uv; }
echo "  ✓ uv"
brew list ffmpeg >/dev/null 2>&1 || { echo "  installing ffmpeg (this takes a minute) ..."; brew install ffmpeg; }
echo "  ✓ ffmpeg"

# Python deps
echo ""
echo "→ Installing Python dependencies ..."
unset VIRTUAL_ENV
uv sync

# .env bootstrap — offer to paste the key interactively if missing.
if [ ! -f .env ]; then
  echo ""
  echo "→ Setting up your Hedra API key"
  echo ""
  echo "  Sign up at https://www.hedra.com and subscribe to at least the"
  echo "  Creator plan, then open https://www.hedra.com/api-profile and"
  echo "  create a key."
  echo ""
  read -p "  Paste your Hedra API key here (or press Enter to skip): " HEDRA_KEY
  if [ -n "$HEDRA_KEY" ]; then
    printf "HEDRA_API_KEY=%s\n" "$HEDRA_KEY" > .env
    echo "  ✓ Saved to .env"
  else
    cp .env.example .env
    echo "  ⚠  Skipped — edit .env manually before running the pipeline."
  fi
fi

echo ""
echo "  ┌─────────────────────────────────────────────┐"
echo "  │  ✓ Install complete.                         │"
echo "  │                                              │"
echo "  │  Next: drop a video into in/, a character    │"
echo "  │  PNG into characters/, then double-click     │"
echo "  │  run.command to animate.                     │"
echo "  └─────────────────────────────────────────────┘"
echo ""
read -n 1 -s -r -p "Press any key to close ..."
echo ""
