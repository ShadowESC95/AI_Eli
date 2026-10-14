#!/usr/bin/env python3
# eli_tools/capabilities.py
"""
ELI v3 capabilities: *compatibility layer*.

Your codebase has had multiple "capabilities" shapes over time:
- some callers expect: capability_names (a list)
- others expect: capability_names() (a function)
- GUI/executor may import: as_text, as_jsonable

This module is intentionally defensive: it must NEVER brick the app due to
a bad registry import. All registry access is lazy (runtime), not import-time.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# --------- Lazy registry access (no import-time coupling) ----------

def _safe_list_capabilities() -> List[Dict[str, Any]]:
    """
    Return a list of capability dicts.
    Attempts to call eli_tools.capability_registry.list_capabilities().
    Never raises on failure.
    """
    try:
        from eli_tools import capability_registry as _cr  # local import
        fn = getattr(_cr, "list_capabilities", None)
        if callable(fn):
            caps = fn()
            if isinstance(caps, list):
                return [c for c in caps if isinstance(c, dict)]
    except Exception:
        pass
    return []

def _safe_actions() -> List[str]:
    caps = _safe_list_capabilities()
    out: List[str] = []
    for c in caps:
        a = c.get("action")
        if isinstance(a, str) and a.strip():
            out.append(a.strip())
    # de-dupe, stable-ish
    return sorted(set(out))

# --------- Public compatibility exports ----------

def as_jsonable() -> List[Dict[str, Any]]:
    """JSON-safe capability listing."""
    return _safe_list_capabilities()

def as_text() -> str:
    """Pretty-printed capability listing (human text)."""
    caps = _safe_list_capabilities()
    if not caps:
        return "ELI Capability Registry: (empty or unavailable)"
    lines: List[str] = []
    lines.append(f"ELI Capability Registry (authoritative) — {len(caps)} actions")
    for c in caps:
        action = c.get("action", "UNKNOWN")
        desc = c.get("description", "")
        params = c.get("params", {}) or {}
        lines.append(f"- {action}: {desc}".rstrip())
        if isinstance(params, dict) and params:
            # keep it short; UI can show details elsewhere
            for k, v in params.items():
                lines.append(f"  - {k}: {v}")
    return "\n".join(lines)

# Some versions expect a LIST, some a FUNCTION.
capability_names_list: List[str] = _safe_actions()

def capability_names() -> List[str]:
    """Back-compat: return list of action names."""
    return _safe_actions()

# alias used by some old code
capability_map: Dict[str, Any] = {}

__all__ = [
    "as_text",
    "as_jsonable",
    "capability_names_list",
    "capability_names",
    "capability_map",
]
