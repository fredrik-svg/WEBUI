#!/usr/bin/env bash
set -euo pipefail

# Enkel installerare för Raspberry Pi (64-bit)
# - Installerar Ollama
# - Skapar Python-venv och startar appen

if ! command -v curl >/dev/null 2>&1; then
  sudo apt-get update && sudo apt-get install -y curl ffmpeg
fi

# Installera Ollama om den saknas
if ! command -v ollama >/dev/null 2>&1; then
  curl -fsSL https://ollama.com/install.sh | sh
  sudo systemctl enable ollama
  sudo systemctl start ollama
fi

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Skapa .env om den saknas
if [ ! -f .env ]; then
  cp .env.example .env
fi

echo "Tips: Hämta en liten modell först (går snabbare och funkar på Pi):"
echo "  ollama pull llama3.2:1b"
echo
echo "Starta appen med: python -m app.main"
