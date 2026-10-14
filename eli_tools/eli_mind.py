def think():
    summary = _eli_execute("MEMORY_RECALL", {"limit": 5})
    plan = _eli_execute(
        "CHAT",
        {"message": "Based on memory, suggest next useful actions without executing them."}
    )
    return {"summary": summary, "plan": plan}


# --- anti-circular-import shim (lazy import) ---
def _eli_execute(action, args=None, **kwargs):
    from eli_tools.executor_enhanced import execute as _execute
    return _execute(action, args or {}, **kwargs)
