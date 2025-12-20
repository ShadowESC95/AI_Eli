#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

set -a
source .env
set +a

source .venv/bin/activate
export PYTHONPATH="$PWD"

exec python -u eli_voice/eli_unified.py "$@"
