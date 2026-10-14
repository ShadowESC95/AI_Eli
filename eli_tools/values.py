"""
eli_tools/values.py

Stable preferences / values for ELI.
Stored under: <project>/eli_core/values.json

Used by context_builder to remind the model how to behave.
"""

from __future__ import annotations
from typing import Any, Dict
import json
from pathlib import Path
import os

def _root() -> Path:
    return Path(os.environ.get("ELI_ROOT") or Path(__file__).resolve().parents[1]).resolve()

VALUES_PATH = (_root() / "eli_core" / "values.json").resolve()

DEFAULTS: Dict[str, Any] = {
    "tone": "Brutally honest, nerdy, dry wit; adversarial for truth; dark shock-but-intelligent humor.",
    "ethics": "Truth > comfort. No corporate deference. No fake humility. If unsure, say so.",
    "memory_policy": "Persistent memory is stored in SQLite. Never claim memory is absent if DB shows entries.",
}

def load_values() -> Dict[str, Any]:
    VALUES_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not VALUES_PATH.exists():
        save_values(DEFAULTS)
        return dict(DEFAULTS)
    try:
        d = json.loads(VALUES_PATH.read_text(encoding="utf-8", errors="ignore") or "{}")
        if not isinstance(d, dict):
            return dict(DEFAULTS)
        # merge defaults
        out = dict(DEFAULTS)
        out.update(d)
        return out
    except Exception:
        return dict(DEFAULTS)

def save_values(d: Dict[str, Any]) -> None:
    VALUES_PATH.parent.mkdir(parents=True, exist_ok=True)
    VALUES_PATH.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

def set_value(key: str, value: Any) -> Dict[str, Any]:
    d = load_values()
    d[str(key)] = value
    save_values(d)
    return d

def render_values_block() -> str:
    d = load_values()
    lines = []
    for k, v in d.items():
        lines.append(f"- {k}: {v}")
    return "\n".join(lines)
