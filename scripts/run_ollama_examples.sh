#!/usr/bin/env bash
set -euo pipefail

# 1) Install Ollama (Linux/macOS). On Linux:
# curl -fsSL https://ollama.com/install.sh | sh

# 2) Pull a model suitable for math/code:
# Examples (choose one you can fit):
#   ollama pull qwen2.5-coder:7b-instruct
#   ollama pull deepseek-coder:6.7b
#   ollama pull llama3.1:8b-instruct

# 3) Create the custom model with guardrails
ollama create xichi-analyst -f Modelfile

# 4) Test chat API
curl -s http://localhost:11434/api/chat -d '{
  "model": "xichi-analyst",
  "messages": [{"role":"user","content":"Return E=mc^2 in LaTeX only."}]
}' | jq -r .message.content

echo "Done."
