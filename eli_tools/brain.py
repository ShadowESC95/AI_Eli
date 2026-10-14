from __future__ import annotations

from eli_tools.router import route
def handle_text(text: str) -> dict:
    cmd = route(text)
    res = _eli_execute(cmd["action"], cmd.get("args", {}))
    return {"text": text, "cmd": cmd, "res": res}


# --- anti-circular-import shim (lazy import) ---
def _eli_execute(action, args=None, **kwargs):
    from eli_tools.executor_enhanced import execute as _execute
    return _execute(action, args or {}, **kwargs)
