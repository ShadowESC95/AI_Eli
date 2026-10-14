from __future__ import annotations

from pathlib import Path
import json
import os
import time
from typing import Any, Dict

from eli_tools import config as eli_config

STATE_FILE = eli_config.state_file()

DEFAULT_STATE: Dict[str, Any] = {
    "user": os.environ.get("ELI_USER_NAME", "").strip(),
    "mode": "safe",
    "purpose": "Local OS-level copilot governed by executor actions",
    "last_action": None,
    "session_start": time.time(),
}

def load_state() -> Dict[str, Any]:
    if not STATE_FILE.exists():
        save_state(DEFAULT_STATE)
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))

def save_state(state: Dict[str, Any]) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")

def update(**kwargs: Any) -> Dict[str, Any]:
    state = load_state()
    state.update(kwargs)
    save_state(state)
    return state
