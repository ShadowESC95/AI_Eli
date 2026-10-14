def reflect():
    try:
        return _eli_execute(
            "CHAT",
            {"message": "Summarize recent conversation and extract key goals."}
        )
    except Exception:
        return None


# --- anti-circular-import shim (lazy import) ---
def _eli_execute(action, args=None, **kwargs):
    from eli_tools.executor_enhanced import execute as _execute
    return _execute(action, args or {}, **kwargs)
