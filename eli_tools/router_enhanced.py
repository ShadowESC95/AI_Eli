# eli_tools/router_enhanced.py
# Deterministic lightweight router for voice/CLI utterances -> executor actions.
# Keep this conservative: only route when intent is clear; otherwise fall back to CHAT.

from __future__ import annotations

import re
from typing import Dict, Any

# NOTE: The executor expects dict: {"action": <ACTION>, "args": {...}}
# Router is intentionally "dumb" and fast.

_DOC_PAT = re.compile(r"\b(?:create|write|generate|draft|make)\s+(?:a\s+)?(?:doc|document|report|notes?)\s+(?:about|on|for)\s+(.+)$", re.I)

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()

def route(text: str) -> Dict[str, Any]:
    raw = text or ""
    s = _norm(raw)

    # --- high-signal, fixed commands ---
    if re.search(r"\b(check|verify)\s+chronal\s+alignment\b", s):
        return {"action": "TIME", "args": {}}

    if re.search(r"\b(access|open)\s+(?:neural\s+archive|memory|archive)\b", s):
        # Allow optional query: "access neural archive about X"
        m = re.search(r"\babout\s+(.+)$", raw, flags=re.I)
        q = (m.group(1).strip() if m else "")
        return {"action": "MEMORY_RECALL", "args": {"q": q, "limit": 10}}

    if re.search(r"\b(access|open)\s+(?:network\s+browser|browser|web)\b", s):
        return {"action": "OPEN_NETWORK_BROWSER", "args": {}}

    if re.search(r"\b(initiate|open)\s+(?:audio\s+interface|music|media)\b", s):
        # User expectation: this should open music/spotify/youtube, not just settings.
        return {"action": "OPEN_MEDIA_HUB", "args": {"open_settings": True}}

    if re.search(r"\b(access|open)\s+(?:communication\s+hub|mail|gmail|inbox)\b", s):
        return {"action": "OPEN_COMMUNICATION_HUB", "args": {}}

    if re.search(r"\b(access|open)\s+(?:storage\s+matrix|files?|file\s+system|directory)\b", s):
        # Optional: "access storage matrix at /path"
        m = re.search(r"\b(?:at|in)\s+(.+)$", raw, flags=re.I)
        path = (m.group(1).strip() if m else "~")
        return {"action": "OPEN_FILE_SYSTEM", "args": {"path": path}}

    if re.search(r"\bfabricate\s+data\s+construct\b", s):
        # If they say "fabricate data construct about X" treat as doc request.
        m = re.search(r"\babout\s+(.+)$", raw, flags=re.I)
        topic = (m.group(1).strip() if m else "")
        return {"action": "DATA_FABRICATOR", "args": {"topic": topic} if topic else {}}

    # --- document generation natural language ---
    m = _DOC_PAT.search(raw.strip())
    if m:
        topic = m.group(1).strip()
        return {"action": "DOC_GENERATE", "args": {"topic": topic, "format": "md"}}

    # Shortcut: "create a document about X" without "about"
    if re.search(r"\bcreate\s+a\s+document\b", s):
        # try to extract trailing topic
        m2 = re.search(r"\bcreate\s+a\s+document\s*(?:about|on|for)?\s*(.+)$", raw, flags=re.I)
        topic = (m2.group(1).strip() if m2 and m2.group(1) else "")
        if topic:
            return {"action": "DOC_GENERATE", "args": {"topic": topic, "format": "md"}}

    # --- fallback: chat ---
    return {"action": "CHAT", "args": {"message": raw}}
