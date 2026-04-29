#!/usr/bin/env bash
# One-shot installer for Jarvis.
#   - installs Homebrew (if missing), ffmpeg, ollama
#   - pulls the coding model
#   - creates a Python venv and installs requirements
#
# Run from the folder containing this script:
#     chmod +x install.sh && ./install.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

say_step() { printf "\n\033[1;36m==> %s\033[0m\n" "$*"; }

# ----------------------------------------------------------------------
# 1. Homebrew
# ----------------------------------------------------------------------
if ! command -v brew >/dev/null 2>&1; then
  say_step "Installing Homebrew (you'll be asked for your password)"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  # Add brew to PATH for Apple Silicon
  if [ -d /opt/homebrew/bin ]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  fi
else
  say_step "Homebrew already installed"
fi

# ----------------------------------------------------------------------
# 2. ffmpeg (faster-whisper uses it for some audio paths)
# ----------------------------------------------------------------------
if ! command -v ffmpeg >/dev/null 2>&1; then
  say_step "Installing ffmpeg"
  brew install ffmpeg
else
  say_step "ffmpeg already installed"
fi

# ----------------------------------------------------------------------
# 3. Ollama
# ----------------------------------------------------------------------
if ! command -v ollama >/dev/null 2>&1; then
  say_step "Installing Ollama"
  brew install ollama
else
  say_step "Ollama already installed"
fi

# Make sure the Ollama daemon is up so we can pull a model
if ! curl -s http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
  say_step "Starting Ollama service"
  brew services start ollama || ollama serve >/tmp/ollama.log 2>&1 &
  # Wait for it to come up
  for i in {1..20}; do
    if curl -s http://127.0.0.1:11434/api/version >/dev/null 2>&1; then break; fi
    sleep 0.5
  done
fi

# ----------------------------------------------------------------------
# 4. Pull the coding model (~5GB)
# ----------------------------------------------------------------------
MODEL="${JARVIS_MODEL:-qwen2.5-coder:7b}"
say_step "Pulling Ollama model: $MODEL  (one-time, ~5GB download)"
ollama pull "$MODEL"

# ----------------------------------------------------------------------
# 5. Python venv + deps
# ----------------------------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
  say_step "Installing Python"
  brew install python
fi

if [ ! -d ".venv" ]; then
  say_step "Creating Python venv at .venv"
  python3 -m venv .venv
fi

say_step "Installing Python dependencies"
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# ----------------------------------------------------------------------
# 6. Done
# ----------------------------------------------------------------------
cat <<EOF

\033[1;32mAll set.\033[0m

To start Jarvis, double-click  start_jarvis.command
                — or in a terminal —
   ./start_jarvis.command

The first run will download the wake-word and Whisper models (~150MB).
macOS will pop up a microphone-permission prompt — click Allow.

EOF
