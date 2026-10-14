#!/usr/bin/env bash
# Downloads a Piper voice into eli_tools/voices (default en_US-amy-medium).
# usage: scripts/get_piper_voice.sh [voice]    e.g. en_GB-alan-medium
set -euo pipefail
voice="${1:-en_US-amy-medium}"
IFS=- read -r lang name quality <<< "$voice"
dest="$(cd "$(dirname "$0")/.." && pwd)/eli_tools/voices"
mkdir -p "$dest"
base="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/${lang%%_*}/$lang/$name/$quality"
for f in "$voice.onnx" "$voice.onnx.json"; do
  curl -fL --progress-bar -o "$dest/$f" "$base/$f"
done
echo "Saved to $dest/$voice.onnx"
