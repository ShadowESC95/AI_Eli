from __future__ import annotations

import os
import time
import json
import subprocess
from pathlib import Path
from datetime import datetime

from eli_tools import config as eli_config

ART_BASE = eli_config.artifacts_dir() / "proactive"
ART_BASE.mkdir(parents=True, exist_ok=True)

SUGGESTION = ART_BASE / "suggestion.txt"
LAST_JSON   = ART_BASE / "last_context.json"
SHOT_PNG    = ART_BASE / "screen.png"

INTERVAL_SEC = float(os.environ.get("ELI_PROACTIVE_INTERVAL", "8"))
ENABLE_CHAT  = os.environ.get("ELI_PROACTIVE_CHAT", "1").strip() not in ("0","false","False","no","NO")
MODEL = eli_config.chat_model()

def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=20)
        return p.returncode, p.stdout
    except Exception as e:
        return 1, str(e)

def capture_screen() -> str:
    # X11-friendly: gnome-screenshot is the least annoying option on GNOME/X11.
    # fallback to ImageMagick import if installed.
    if os.environ.get("XDG_SESSION_TYPE","").lower() == "x11":
        code, out = _run(["gnome-screenshot", "-f", str(SHOT_PNG)])
        if code == 0 and SHOT_PNG.exists():
            return "gnome-screenshot ok"
    code, out = _run(["import", "-window", "root", str(SHOT_PNG)])
    if code == 0 and SHOT_PNG.exists():
        return "import ok"
    return f"capture failed: {out.strip()[:300]}"

def infer_context() -> dict:
    ctx = {
        "ts": time.time(),
        "iso": datetime.utcnow().isoformat() + "Z",
        "cwd": str(Path.cwd()),
        "screen_image": str(SHOT_PNG),
        "notes": [],
    }
    # Lightweight heuristics: watch recent files in project dirs
    # (You can expand this to tail logs, detect paraview, etc.)
    try:
        recent = sorted(Path(".").rglob("*"), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
        tops = []
        for p in recent:
            if not p.is_file():
                continue
            if any(part in (".venv","__pycache__",".git","artifacts") for part in p.parts):
                continue
            if p.suffix.lower() in (".py",".md",".tex",".pdf",".json",".txt",".log",".csv"):
                tops.append({"path": str(p), "mtime": p.stat().st_mtime, "size": p.stat().st_size})
            if len(tops) >= 12:
                break
        ctx["recent_files"] = tops
    except Exception as e:
        ctx["notes"].append(f"recent_files error: {e}")
    return ctx

def chat_suggestion(ctx: dict) -> str:
    # No chat model configured => don’t fake it.
    if not (MODEL and ENABLE_CHAT):
        return "Proactive is running (no chat synthesis enabled)."

    # Use your existing chat_model module if available; otherwise curl ollama.
    try:
        from eli_tools.chat_model import chat  # type: ignore
        prompt = (
            "You are ELI. You are running locally. "
            "Generate one concise proactive suggestion based on the user's current work context. "
            "Use this style: 'I see X. Want to continue Y from last time?' "
            "Do NOT be generic. If context is weak, ask one sharp question.\n\n"
            f"Context JSON:\n{json.dumps(ctx, indent=2)}\n"
        )
        r = chat(prompt, model=MODEL)
        if isinstance(r, dict):
            return (r.get("content") or r.get("response") or "").strip() or "No suggestion."
        if isinstance(r, str):
            return r.strip()
    except Exception:
        pass

    # fallback: curl ollama directly
    try:
        import requests
        host = eli_config.ollama_base()
        payload = {
            "model": MODEL,
            "stream": False,
            "messages": [
                {"role":"system","content":"You are ELI. Be concise, incisive, and specific."},
                {"role":"user","content":(
                    "Generate one proactive suggestion based on this context. "
                    "One paragraph max.\n\n"
                    f"{json.dumps(ctx)}"
                )},
            ],
            "options": {"temperature": 0.2, "num_predict": 160},
        }
        rr = requests.post(host + "/api/chat", json=payload, timeout=30)
        rr.raise_for_status()
        j = rr.json()
        return (j.get("message", {}) or {}).get("content","").strip() or "No suggestion."
    except Exception as e:
        return f"chat failed: {e}"

def main():
    SUGGESTION.write_text("Proactive daemon online.\n", encoding="utf-8")
    while True:
        cap = capture_screen()
        ctx = infer_context()
        ctx["capture"] = cap
        LAST_JSON.write_text(json.dumps(ctx, indent=2), encoding="utf-8")

        sug = chat_suggestion(ctx)
        SUGGESTION.write_text(sug + "\n", encoding="utf-8")

        time.sleep(INTERVAL_SEC)

if __name__ == "__main__":
    main()
