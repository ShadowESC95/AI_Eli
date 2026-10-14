import json
import os
import subprocess
from typing import Dict, Any

from eli_tools import config as eli_config
from eli_tools.chat_model import chat_response
from eli_tools.router_enhanced import route_intent
from eli_tools.compat import execute
from eli_tools.capabilities import as_text as capabilities_text

REASONER_MODEL = eli_config.chat_model()
ROUTER_MODEL   = os.environ.get("ELI_ROUTER_MODEL") or REASONER_MODEL

SYSTEM_CONTEXT = f"""
You are ELI.

You are running fully locally.
All OS commands, filesystem paths, applications, and network access are allowed.

You do NOT invent tools.
You ONLY use tools listed below.

CAPABILITIES:
{capabilities_text()}

When no tool is required, respond normally.
When a tool is required, say clearly what you intend to do.
"""

def agent_step(user_message: str) -> Dict[str, Any]:
    # 1. Ask reasoner what to do
    reasoning = chat_response(
        message=user_message,
        system=SYSTEM_CONTEXT,
        model=REASONER_MODEL,
    )

    content = reasoning.get("content", "").strip()

    # 2. Ask router if this maps to an action
    route = route_intent(
        content,
        model=ROUTER_MODEL,
    )

    action = route.get("action")

    # 3. If no action, return response
    if not action or action == "CHAT":
        return {
            "ok": True,
            "type": "message",
            "content": content,
        }

    # 4. Execute tool
    result = execute(action, route.get("args", {}))

    # 5. Feed result back to reasoner for final response
    followup = chat_response(
        message=f"Tool result:\n{json.dumps(result, indent=2)}",
        system=SYSTEM_CONTEXT,
        model=REASONER_MODEL,
    )

    return {
        "ok": True,
        "type": "tool_result",
        "tool": action,
        "result": result,
        "content": followup.get("content", ""),
    }


def repl():
    print("ELI agent loop online. Ctrl+C to exit.")
    while True:
        try:
            user = input("\n> ").strip()
            if not user:
                continue
            out = agent_step(user)
            print("\n" + out.get("content", ""))
        except KeyboardInterrupt:
            print("\nExiting.")
            break
        except Exception as e:
            print(f"\n[ERROR] {e}")


if __name__ == "__main__":
    repl()
