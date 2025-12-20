#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

source .venv/bin/activate

# wipe stale exports so .env actually wins
unset ELI_CHAT_MODEL ELI_ROUTER_MODEL ELI_MODEL OLLAMA_MODEL ELI_AUDIO_IN

# load project env
set -a
source .env
set +a

echo "[RUN] router=${ELI_ROUTER_MODEL:-unset} chat=${ELI_CHAT_MODEL:-unset} model=${ELI_MODEL:-unset}"
exec python eli_voice/eli_unified5_PC_Control2.py
