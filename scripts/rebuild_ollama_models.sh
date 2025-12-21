#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

ollama create eli-voice  -f models/Modelfile.eli-voice
ollama create eli-router -f models/Modelfile.eli-router

echo "[OK] rebuilt: eli-voice:latest and eli-router:latest"
ollama list | egrep 'eli-voice|eli-router' || true
