import os
import json
from typing import List, Dict, Any
from pathlib import Path

import requests

# --- Persistent memory files (always injected every call) ---
MEM_FILES = [
    Path("data/memory/consistency_gate.md"),
    Path("data/memory/personal_memory.yaml"),
    Path("data/memory/journal.md"),
]

# --- Runtime options (env-overridable) ---
DEFAULT_OPTIONS: Dict[str, Any] = {
    "num_ctx": int(os.environ.get("XICHI_NUM_CTX", "8192")),
    # Set XICHI_NUM_GPU=0 for CPU-only, or e.g. 20 for hybrid offload
    **({"num_gpu": int(os.environ["XICHI_NUM_GPU"])} if "XICHI_NUM_GPU" in os.environ else {}),
    "temperature": float(os.environ.get("XICHI_TEMPERATURE", "0.1")),
    "repeat_penalty": float(os.environ.get("XICHI_REPEAT_PENALTY", "1.12")),
}

HTTP_TIMEOUT = int(os.environ.get("XICHI_HTTP_TIMEOUT", "3600"))
FORCE_JSON   = os.environ.get("XICHI_FORCE_JSON") == "1"

def _load_memory_text() -> str:
    """Concatenate memory files (if present) to prepend every call."""
    parts: List[str] = []
    for p in MEM_FILES:
        if p.exists():
            try:
                txt = p.read_text(encoding="utf-8", errors="ignore").strip()
                if txt:
                    parts.append(f"\n### MEMORY:{p.name}\n{txt}\n")
            except Exception:
                # Ignore unreadable files
                pass
    return "\n".join(parts).strip()

class OllamaClient:
    def __init__(self, base_url: str | None = None, model: str | None = None):
        self.base_url = base_url or os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        self.model = model or os.environ.get("ELI_MODEL") or os.environ.get("OLLAMA_MODEL", "xichi-analyst-qwen14")
        import sys
        print(f"[OllamaClient] base_url={self.base_url} model={self.model}", file=sys.stderr)

        self._chat_url = f"{self.base_url}/api/chat"
        self._memory = _load_memory_text()

    def chat(
        self,
        messages: List[Dict[str, str]],
        stream: bool = False,
        options: Dict[str, Any] | None = None,
    ) -> str:
        """Send a chat to Ollama with persistent memory prepended."""
        # Prepend memory to system message (or create one)
        sys_idx = next((i for i, m in enumerate(messages) if m.get("role") == "system"), None)
        if sys_idx is not None:
            messages[sys_idx]["content"] = (self._memory + "\n\n" + messages[sys_idx]["content"]).strip()
        else:
            messages = [{"role": "system", "content": self._memory}] + messages

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            "options": {**DEFAULT_OPTIONS, **(options or {})},
        }
        if FORCE_JSON:
            payload["format"] = "json"

        r = requests.post(self._chat_url, json=payload, timeout=HTTP_TIMEOUT)
        r.raise_for_status()

        if stream:
            text = ""
            for line in r.iter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except Exception:
                    continue
                text += data.get("message", {}).get("content", "")
            return text

        data = r.json()
        return data.get("message", {}).get("content", "")
