"""
eli_tools/chat_model.py

Authoritative chat interface for ELI.

Guarantees:
- Builds system context via context_builder.build_context()
- Calls Ollama if available
- Persists structured turns: role='user' and role='assistant'
- Never lies about capabilities: system context includes CAPABILITIES

Env:
- ELI_CHAT_MODEL / ELI_MODEL / OLLAMA_MODEL
- ELI_TEMP (default 0.6)
- ELI_NUM_PREDICT (default 450)
"""

from __future__ import annotations
from typing import Any, Dict, Optional
import os

from eli_tools import config as eli_config
from eli_tools import memory_db
from eli_tools.context_builder import build_context

DEFAULT_MODEL = eli_config.chat_model()

def _ollama_available() -> bool:
    try:
        import ollama  # type: ignore
        ollama.list()
        return True
    except Exception:
        return False

def _call_ollama(model: str, system: str, user: str) -> str:
    import ollama  # type: ignore
    temp = float(os.environ.get("ELI_TEMP", "0.6"))
    num_predict = int(os.environ.get("ELI_NUM_PREDICT", "450"))

    resp = ollama.chat(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        options={"temperature": temp, "num_predict": num_predict},
    )
    return (resp.get("message") or {}).get("content", "") or ""

def chat_response(user: str, *, model: Optional[str] = None) -> str:
    mdl = (model or DEFAULT_MODEL).strip()
    system = build_context(user)

    if not mdl:
        out = "No model set. Set ELI_MODEL to an Ollama model you have pulled (see `ollama list`)."
    elif _ollama_available():
        out = _call_ollama(mdl, system, user)
    else:
        out = "Ollama unavailable. (Fix: start ollama service / ensure python ollama module.)"

    # Structured persistence: one user turn + one assistant turn
    try:
        memory_db.add_entry(user, kind="chat", role="user", tags=["chat"], meta={"model": mdl})
        memory_db.add_entry(out, kind="chat", role="assistant", tags=["chat"], meta={"model": mdl})
    except Exception:
        pass

    return out
