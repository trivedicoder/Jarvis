#!/usr/bin/env bash
# Double-clickable launcher for Jarvis.
# - cd's to the script's folder
# - makes sure Ollama is running
# - activates the venv and runs jarvis.py

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Make sure Ollama is up (it usually is, since brew services keeps it running)
if ! curl -s http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
  echo "Starting Ollama..."
  if command -v brew >/dev/null 2>&1; then
    brew services start ollama >/dev/null 2>&1 || ollama serve >/tmp/ollama.log 2>&1 &
  else
    ollama serve >/tmp/ollama.log 2>&1 &
  fi
  for i in {1..20}; do
    if curl -s http://127.0.0.1:11434/api/version >/dev/null 2>&1; then break; fi
    sleep 0.5
  done
fi

# Activate venv
if [ ! -d ".venv" ]; then
  echo "No .venv found. Run ./install.sh first."
  exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# Off we go
exec python jarvis.py
