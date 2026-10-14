"""
eli_tools/context_builder.py

ELI Memory Spine
----------------
Builds the cognitive context Eli uses BEFORE responding.

Assembles:
- Identity (who ELI is, who user is)
- Values / constraints
- Capability registry (authoritative)
- Long-term memory summary (reflection)
- Recent session continuity (memory_db)
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional
import time

from eli_tools import memory_db, reflection, values


def _safe(call, default):
    try:
        return call()
    except Exception:
        return default


def build_identity_block() -> str:
    """
    Core identity: stable unless code changes.
    """
    return (
        "You are ELI — the Entropic Logical Interface.\n\n"
        "If the user's name is unknown, ask once and store it.\n"
        "Relationship: local, private, user-owned research partner.\n"
        "Tone: brutally honest, nerdy, dry wit, adversarial for truth. Dark shock humor allowed.\n"
        "Ethics: truth > comfort. No corporate deference. No hallucinated humility.\n\n"
        "You are persistent across sessions and must use the memory DB when available.\n"
        "If memory is unavailable/broken, say so plainly and continue.\n\n"
        "Your purpose is to assist with:\n"
        "- research / reasoning\n"
        "- system design / debugging\n"
        "- OS-level tasks via available executor tools\n"
        "- media control\n"
        "- file/document analysis\n"
        "- document creation\n"
        "- proactive/screen-read flows (if wired)\n"
    )


def build_values_block() -> str:
    return _safe(lambda: values.render_values_block(), "")


def build_capabilities_block() -> str:
    """
    Pull capabilities from eli_tools.capabilities in a version-tolerant way.
    """
    # New API
    try:
        from eli_tools.capabilities import as_text as _as_text
        txt = _safe(lambda: _as_text(), "")
        return txt.strip() if txt else ""
    except Exception:
        pass

    # Old API
    try:
        from eli_tools.capabilities import build_registry, registry_to_text
        reg = _safe(lambda: build_registry(), {})
        txt = _safe(lambda: registry_to_text(reg), "")
        return txt.strip() if txt else ""
    except Exception:
        return ""


def build_persistent_summary() -> str:
    summary = _safe(lambda: reflection.get_latest_summary(), None)
    if not summary:
        return "No long-term summary available yet."
    return f"Long-term memory summary:\n{summary}"


def build_recent_context(limit: int = 8) -> str:
    entries = _safe(lambda: memory_db.get_recent_entries(limit=limit), [])
    if not entries:
        return "No recent session memory."

    lines: List[str] = []
    for e in entries:
        ts = e.get("timestamp", "")
        role = e.get("role", "") or ""
        kind = e.get("kind", "") or ""
        content = (e.get("content", "") or "").strip()
        content = content.replace("\n", " ").strip()
        if len(content) > 240:
            content = content[:240] + "…"
        lines.append(f"- [{ts}] ({role}/{kind}) {content}")

    return "Recent session context:\n" + "\n".join(lines)


def build_context(user_message: str) -> str:
    msg = (user_message or "").strip()

    blocks: List[str] = []
    blocks.append("=== IDENTITY ===")
    blocks.append(build_identity_block())

    blocks.append("\n=== VALUES & CONSTRAINTS ===")
    blocks.append(build_values_block())

    blocks.append("\n=== CAPABILITIES ===")
    cap = build_capabilities_block()
    blocks.append(cap if cap else "No capability registry available.")

    blocks.append("\n=== LONG-TERM MEMORY ===")
    blocks.append(build_persistent_summary())

    blocks.append("\n=== RECENT CONTEXT ===")
    blocks.append(build_recent_context())

    blocks.append("\n=== CURRENT INPUT ===")
    blocks.append(f"User says: {msg}")

    blocks.append("\nRespond as ELI. Use memory and tools truthfully. Do not claim capabilities you do not have.")
    return "\n\n".join(blocks)


if __name__ == "__main__":
    print(build_context("What's up?"))
