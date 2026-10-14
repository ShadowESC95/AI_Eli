#!/usr/bin/env bash
# Builds the "eli-persona" Ollama model on top of any model you have pulled.
# usage: scripts/build_persona_model.sh <base-model> [name]    (any model from `ollama list`)
set -euo pipefail
base="${1:?usage: $0 <base-model> [name]}"
name="${2:-eli-persona}"
here="$(cd "$(dirname "$0")/.." && pwd)"
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
{ echo "FROM $base"; cat "$here/modelfiles/eli-persona.Modelfile"; } > "$tmp"
ollama create "$name" -f "$tmp"
echo "Built $name from $base. Set ELI_MODEL=$name"
