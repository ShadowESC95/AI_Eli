import time, json, subprocess, requests, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from eli_tools import config as eli_config


def _eli_read_clipboard():
    """
    Reads clipboard text.
    - Wayland: wl-paste
    - X11:     xclip
    Returns "" on failure.
    """
    import os, subprocess
    try:
        if os.environ.get("WAYLAND_DISPLAY"):
            return subprocess.check_output(["wl-paste", "-n"], text=True, stderr=subprocess.DEVNULL)
        if os.environ.get("DISPLAY"):
            return subprocess.check_output(["xclip", "-selection", "clipboard", "-o"], text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return ""
    return ""
OLLAMA_URL = f"{eli_config.ollama_base()}/api/chat"
MODEL      = eli_config.chat_model()

PREFIXES = ("eli:", "ELI:")

SYSTEM = """Return ONLY strict JSON:
{"action": "...", "args": {...}}
Allowed actions: open_url, open_app, volume, mute_toggle, media, noop
"""

def wl_paste():
    try:
        out = _eli_read_clipboard()
        return out.strip()
    except subprocess.CalledProcessError:
        return ""

def open_url(url): subprocess.Popen(["xdg-open", url])
def open_app(desktop_id): subprocess.Popen(["gtk-launch", desktop_id])
def volume(delta): subprocess.Popen(["pactl","set-sink-volume","@DEFAULT_SINK@", f"{delta:+d}%"])
def mute_toggle(): subprocess.Popen(["pactl","set-sink-mute","@DEFAULT_SINK@","toggle"])
def media(cmd): subprocess.Popen(["playerctl", cmd])

ACTIONS = {
    "open_url": lambda a: open_url(a.get("url","")),
    "open_app": lambda a: open_app(a.get("desktop_id","")),
    "volume":   lambda a: volume(int(a.get("delta",0))),
    "mute_toggle": lambda a: mute_toggle(),
    "media":    lambda a: media(a.get("cmd","play-pause")),
}

def ollama_intent(text: str) -> dict:
    payload = {
        "model": MODEL,
        "stream": False,
        "messages": [
            {"role":"system","content": SYSTEM},
            {"role":"user","content": text},
        ],
        "options": {"temperature": 0.2}
    }
    r = requests.post(OLLAMA_URL, json=payload, timeout=120)
    r.raise_for_status()
    return json.loads(r.json()["message"]["content"].strip())

def main():
    last = ""
    print("Clipboard agent running. Prefix commands with 'eli:' then copy on phone.")
    while True:
        cur = wl_paste()
        if cur and cur != last and cur.startswith(PREFIXES):
            cmd = cur.split(":",1)[1].strip()
            print("CMD:", cmd)
            try:
                intent = ollama_intent(cmd)
                print("Intent:", intent)
                action = intent.get("action","noop")
                args   = intent.get("args",{}) or {}
                if action in ACTIONS:
                    ACTIONS[action](args)
                else:
                    print("Blocked action:", action)
            except Exception as e:
                print("Error:", e)
        last = cur
        time.sleep(0.4)

if __name__ == "__main__":
    main()
