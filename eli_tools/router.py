# eli_tools/router.py
from __future__ import annotations

"""
Stable router entrypoint.

Goal: every script can safely do:
    from eli_tools.router import route

And it will use router_enhanced.route when available,
otherwise fall back to a minimal safe route implementation.
"""

from typing import Dict, Any
import os
import re

def _fallback_route(text: str) -> Dict[str, Any]:
    s = (text or "").strip()
    if not s:
        return {"action": "noop", "args": {}}

    # ultra-basic fallback (keep it conservative)
    cl = s.lower()

    if re.fullmatch(r"(time|what time is it)\??", cl):
        return {"action": "time", "args": {}}

    if cl.startswith("open "):
        tgt = s[5:].strip()
        # let executor sanitize
        return {"action": "open_path", "args": {"path": tgt}}

    if cl.startswith("list "):
        tgt = s[5:].strip()
        return {"action": "list_dir", "args": {"path": tgt, "depth": 2}}

    # default: chat
    return {"action": "chat", "args": {"prompt": s}}

# Prefer enhanced router if present
try:
    from .router_enhanced import route as _enhanced_route  # type: ignore
    def route(text: str) -> Dict[str, Any]:
        return _enhanced_route(text)
except Exception:
    def route(text: str) -> Dict[str, Any]:
        return _fallback_route(text)


from pathlib import Path
import json

def load_core_identity():
    return json.loads(Path("eli_core/core_identity.json").read_text())
