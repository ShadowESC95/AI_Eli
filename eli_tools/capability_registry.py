# eli_tools/capability_registry.py
from __future__ import annotations

from typing import Any, Dict, List, Optional
import time

# Canonical registry object (simple + stable)
REGISTRY: Dict[str, Dict[str, Any]] = {}

def register(action: str,
             description: str = "",
             schema: Optional[Dict[str, Any]] = None,
             tags: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Register a capability/action. Safe to call multiple times.
    """
    action = str(action).strip()
    if not action:
        return {}
    REGISTRY[action] = {
        "action": action,
        "description": description or "",
        "schema": schema or {},
        "tags": tags or [],
        "ts": time.time(),
    }
    return REGISTRY[action]

def list_capabilities() -> List[Dict[str, Any]]:
    """
    Return a list of registered capabilities. If empty, attempt bootstrap.
    """
    if not REGISTRY:
        bootstrap_from_executor()
    return [REGISTRY[k] for k in sorted(REGISTRY.keys())]

def get(action: str) -> Optional[Dict[str, Any]]:
    if not action:
        return None
    if not REGISTRY:
        bootstrap_from_executor()
    return REGISTRY.get(action)

def bootstrap_from_executor() -> None:
    """
    Populate REGISTRY from executor_enhanced without creating circular imports.
    We only import executor_enhanced inside this function.
    """
    if REGISTRY:
        return

    try:
        import eli_tools.executor_enhanced as ex
    except Exception:
        # If executor is broken, registry stays empty (doctor will show 0)
        return

    # Common patterns across your versions:
    mapping_names = ["HANDLERS", "ACTIONS", "DISPATCH", "ROUTES", "_HANDLERS", "_ACTIONS"]
    action_names: List[str] = []

    for name in mapping_names:
        obj = getattr(ex, name, None)
        if isinstance(obj, dict) and obj:
            action_names = [str(k) for k in obj.keys()]
            break

    # Sometimes there's an allowed set/list instead
    if not action_names:
        for name in ["ALLOWED_ACTIONS", "ALLOWED", "SUPPORTED_ACTIONS"]:
            obj = getattr(ex, name, None)
            if isinstance(obj, (set, list, tuple)) and obj:
                action_names = [str(x) for x in obj]
                break

    # Final fallback: scan for functions named do_xxx
    if not action_names:
        action_names = []
        for n in dir(ex):
            if n.startswith("do_"):
                action_names.append(n[3:])

    # Register minimal entries
    for a in sorted(set([x.strip() for x in action_names if str(x).strip()])):
        register(a, description=f"(auto) action '{a}' available via executor")

# Compatibility constant some old code expects
CAPABILITIES = list_capabilities()


# --- legacy compatibility layer ---
# Some modules (executor_enhanced, GUI) expect these names to exist.

def capability_names() -> List[str]:
    """Legacy: return action names (list)."""
    return [c.get("action","") for c in list_capabilities() if isinstance(c, dict)]

def render_simple() -> str:
    """Legacy: minimal human-readable listing."""
    caps = list_capabilities()
    if not caps:
        return "ELI Capability Registry — 0 actions"
    return "ELI Capability Registry — " + ", ".join([c.get("action","") for c in caps if c.get("action")])

def render_detailed(fmt: str = "text") -> Any:
    """
    Legacy: pretty-print capability registry.
    fmt: 'text' or 'json'
    """
    caps = list_capabilities()

    if fmt and fmt.lower() == "json":
        # JSON-safe plain data
        return [{"action": c.get("action",""),
                 "description": c.get("description",""),
                 "schema": c.get("schema",{}),
                 "tags": c.get("tags",[])} for c in caps]

    # text mode
    lines = []
    lines.append(f"ELI Capability Registry (authoritative) — {len(caps)} actions")
    for c in caps:
        a = c.get("action","")
        d = c.get("description","")
        lines.append(f"- {a}: {d}".rstrip())
    return "\n".join(lines)

