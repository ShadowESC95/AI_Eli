from __future__ import annotations

from typing import Any, Dict

def _load_backend():
    from eli_tools import executor_enhanced as ex
    return ex

def backend_info() -> Dict[str, Any]:
    b = _load_backend()
    return {
        "backend_module": b.__name__,
        "backend_file": getattr(b, "__file__", ""),
        "has_execute": hasattr(b, "execute"),
    }

def execute(action: str, args: Dict[str, Any] | None = None) -> Dict[str, Any]:
    b = _load_backend()
    return b.execute(action, args or {})
