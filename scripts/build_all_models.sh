#!/usr/bin/env bash
set -euo pipefail
# Pull whichever bases you plan to use beforehand.
# e.g., ollama pull qwen2.5-coder:14b-instruct

ollama create xichi-analyst-qwen   -f Modelfile.qwen   || true
ollama create xichi-analyst-llama  -f Modelfile.llama  || true
ollama create xichi-analyst-r1     -f Modelfile.deepseek || true
ollama create xichi-analyst-falcon -f Modelfile.falcon || true

echo "Built:"
echo "  xichi-analyst-qwen"
echo "  xichi-analyst-llama"
echo "  xichi-analyst-r1"
echo "  xichi-analyst-falcon"
