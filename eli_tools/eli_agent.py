#!/usr/bin/env python3
import os, re, json, time, subprocess, sys
from pathlib import Path
from datetime import datetime
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from eli_tools import config as eli_config

# ---------------- Config ----------------
OLLAMA_URL = os.environ.get("ELI_OLLAMA_URL") or f"{eli_config.ollama_base()}/api/chat"
MODEL      = eli_config.chat_model()
SPEAK      = os.environ.get("ELI_SPEAK", "0").strip() == "1"   # set 1 to use spd-say
POLL_SEC   = float(os.environ.get("ELI_POLL_SEC", "0.15"))

ROOT = Path(os.environ.get("ELI_ROOT", str(Path(__file__).resolve().parents[1]))).resolve()
LOCAL_HOST = os.uname().nodename.lower()

# Name your machines in ELI_ALIAS_A / ELI_ALIAS_B (their hostnames) to send "eli@<name>: ..." to one of them
ALIASES = {"both": "both", "all": "both"}
for _key in ("ELI_ALIAS_A", "ELI_ALIAS_B"):
    _name = os.environ.get(_key, "").strip().lower()
    if _name:
        ALIASES[_key[-1].lower()] = _name
        ALIASES[_name] = _name

# Accept:
#  eli: <cmd>
#  eli <cmd>
#  eli@target: <cmd>
CMD_RE = re.compile(r'^(?:eli|ELI)\s*(?:(?:@?\s*([A-Za-z0-9._-]+)\s*:)|:)?\s*(.+)$')

# ---------------- Utilities ----------------
def run(cmd, timeout=3.0):
    try:
        return subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", "timeout")

def have(cmd):
    return run(["bash","-lc", f"command -v {cmd} >/dev/null 2>&1"]).returncode == 0

def notify(title, body):
    if have("notify-send"):
        run(["notify-send", title, body[:240]])
    print(f"[{title}] {body}")

def speak(text):
    notify("ELI", text)
    if SPEAK and have("spd-say"):
        run(["spd-say", text[:300]], timeout=10.0)

def clipboard_get():
    # X11 path (your session is x11)
    p = run(["xclip","-o","-selection","clipboard"], timeout=1.0)
    return p.stdout if p.returncode == 0 else ""

def clipboard_set(text):
    p = subprocess.Popen(["xclip","-selection","clipboard"], stdin=subprocess.PIPE, text=True)
    p.communicate(text)

def safe_path(rel):
    rel = (rel or "").strip().lstrip("/")
    p = (ROOT / rel).resolve()
    if ROOT != p and ROOT not in p.parents:
        raise ValueError("Blocked path outside ELI_ROOT")
    return p

def list_dir(rel=".", max_items=200):
    p = safe_path(rel)
    if not p.exists(): return {"ok": False, "error": "path not found"}
    if not p.is_dir(): return {"ok": False, "error": "not a directory"}
    out = []
    for c in sorted(p.iterdir()):
        name = c.name + ("/" if c.is_dir() else "")
        out.append(name)
        if len(out) >= max_items: break
    return {"ok": True, "path": str(p), "items": out}

def read_file(rel, max_chars=8000):
    p = safe_path(rel)
    if not p.exists(): return {"ok": False, "error": "file not found"}
    if p.is_dir(): return {"ok": False, "error": "is a directory"}
    data = p.read_text(errors="replace")
    if len(data) > max_chars:
        data = data[:max_chars] + "\n...[truncated]..."
    return {"ok": True, "path": str(p), "text": data}

def grep(rel, pattern, max_hits=80):
    p = safe_path(rel)
    if not p.exists(): return {"ok": False, "error": "path not found"}
    hits = []
    rx = re.compile(pattern, re.IGNORECASE)
    if p.is_file():
        files = [p]
    else:
        files = []
        for f in p.rglob("*"):
            if f.is_file() and f.suffix.lower() in (".py",".md",".txt",".json",".yaml",".yml",".toml",".ini",".tex"):
                files.append(f)
    for f in files:
        try:
            text = f.read_text(errors="replace").splitlines()
        except Exception:
            continue
        for i,line in enumerate(text, start=1):
            if rx.search(line):
                hits.append({"file": str(f.relative_to(ROOT)), "line": i, "text": line[:240]})
                if len(hits) >= max_hits:
                    return {"ok": True, "hits": hits, "truncated": True}
    return {"ok": True, "hits": hits, "truncated": False}

def write_file(rel, content, mode="w"):
    p = safe_path(rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    if mode not in ("w","a"): mode = "w"
    with open(p, mode, encoding="utf-8") as f:
        f.write(content or "")
    return {"ok": True, "path": str(p), "bytes": len(content or "")}

# ---------------- Desktop actions ----------------
def open_url(url):
    if not url: return
    subprocess.Popen(["xdg-open", url])

def search_web(q):
    q = (q or "").strip()
    if q:
        open_url("https://www.google.com/search?q=" + q.replace(" ", "+"))

def open_app(app=None, desktop_id=None):
    if desktop_id and have("gtk-launch"):
        run(["gtk-launch", desktop_id])
        return
    if app and have("gtk-launch"):
        guess = f"{app}.desktop" if not app.endswith(".desktop") else app
        p = run(["gtk-launch", guess])
        if p.returncode == 0:
            return
    if app:
        subprocess.Popen([app])

def wpctl_default_sink():
    p = run(["wpctl","status"], timeout=2.0)
    if p.returncode != 0: return "@DEFAULT_AUDIO_SINK@"
    in_sinks = False
    for line in p.stdout.splitlines():
        if "Sinks:" in line:
            in_sinks = True
            continue
        if in_sinks and ("Sink endpoints:" in line or "Sources:" in line):
            break
        if in_sinks and "*" in line:
            m = re.search(r"\*\s*(\d+)\.", line)
            if m: return m.group(1)
    return "@DEFAULT_AUDIO_SINK@"

def volume(delta_percent=None, set_abs=None):
    sink = wpctl_default_sink()
    if set_abs is not None:
        v = max(0.0, min(1.5, float(set_abs)))
        run(["wpctl","set-volume", str(sink), str(v)])
        return
    if delta_percent is None: return
    n = abs(int(delta_percent)) or 5
    arg = f"{n}%+" if int(delta_percent) >= 0 else f"{n}%-"
    run(["wpctl","set-volume", str(sink), arg])

def mute_toggle():
    sink = wpctl_default_sink()
    run(["wpctl","set-mute", str(sink), "toggle"])

def media(cmd):
    cmd = (cmd or "play-pause").strip()
    if cmd not in ("play-pause","next","previous","stop"):
        cmd = "play-pause"
    run(["playerctl", cmd])

def gsettings_set(schema, key, value):
    if schema and key and value:
        run(["gsettings","set", schema, key, value])

# ---------------- LLM routing ----------------
SCHEMA = {
  "type": "object",
  "properties": {
    "action": {"type":"string","enum":[
      "reply",
      "open_url","search","open_app",
      "volume","mute_toggle","media","gsettings",
      "list_dir","read_file","grep","write_file","clipboard_set",
      "noop"
    ]},
    "args": {"type":"object"}
  },
  "required":["action","args"],
  "additionalProperties": False
}

SYSTEM = f"""You are ELI, the local desktop + project assistant.

Project root (ELI_ROOT): {ROOT}
You can inspect scripts/data under this root safely.

Return JSON ONLY matching the schema. No prose outside JSON.

Guidelines:
- Be conversational via action=reply for questions or chat.
- Do NOT open a browser unless the user explicitly asks to open/search.
- Prefer local project operations (list_dir/read_file/grep) when user asks about "files, scripts, structure, modelfile, data".
- For 'time' questions: reply with the current local time.
- Never request running arbitrary shell commands.

Actions:
- reply: {{"text":"..."}}
- open_url: {{"url":"https://..."}}
- search: {{"q":"..."}}
- open_app: {{"app":"firefox"}} or {{"desktop_id":"firefox.desktop"}}
- volume: {{"delta_percent": -5}} or {{"set": 0.6}}
- mute_toggle: {{}}
- media: {{"cmd":"play-pause"|"next"|"previous"|"stop"}}
- gsettings: {{"schema":"...","key":"...","value":"'prefer-dark'"}}
- list_dir: {{"path":"relative/path"}}
- read_file: {{"path":"relative/path","max_chars":8000}}
- grep: {{"path":"relative/path","pattern":"...","max_hits":80}}
- write_file: {{"path":"relative/path","content":"...","mode":"w"|"a"}}
- clipboard_set: {{"text":"..."}}
- noop: {{}}
"""

def extract_json(s):
    s = (s or "").strip()
    try:
        return json.loads(s)
    except Exception:
        m = re.search(r"\{.*\}", s, flags=re.DOTALL)
        if not m:
            raise ValueError("No JSON found in model output")
        return json.loads(m.group(0))

def ollama_route(text):
    payload = {
        "model": MODEL,
        "stream": False,
        "format": SCHEMA,
        "keep_alive": "24h",
        "messages": [
            {"role":"system","content": SYSTEM},
            {"role":"user","content": text}
        ],
        "options": {
            "temperature": 0,
            "num_ctx": 2048,
            "num_predict": 140
        }
    }
    r = requests.post(OLLAMA_URL, json=payload, timeout=120)
    r.raise_for_status()
    msg = r.json().get("message", {}).get("content", "")
    return extract_json(msg)

def quick_route(text):
    tl = (text or "").strip().lower()

    # chatty basics (instant, no LLM)
    if tl in ("are you there", "you there", "eli are you there", "hello", "hi", "hey"):
        return {"action":"reply","args":{"text":"Yep. I’m here. Say 'eli open youtube' or 'eli list project'."}}

    # time (instant)
    if "what time" in tl or tl in ("time", "the time", "tell me the time"):
        now = datetime.now().strftime("%H:%M:%S")
        return {"action":"reply","args":{"text":f"It’s {now} (local)."}}

    # common opens (instant)
    if tl.startswith("open youtube") or tl.startswith("open you tube") or tl.startswith("open you"):
        return {"action":"open_url","args":{"url":"https://www.youtube.com/"}}
    if tl.startswith("open google") or tl.startswith("open g"):
        return {"action":"open_url","args":{"url":"https://www.google.com/"}}

    # search (instant)
    if tl.startswith("search "):
        return {"action":"search","args":{"q": text.strip()[7:] }}

    # volume (instant)
    if "volume down" in tl:
        return {"action":"volume","args":{"delta_percent": -10}}
    if "volume up" in tl:
        return {"action":"volume","args":{"delta_percent": +10}}
    m = re.search(r"volume\s*(\d{1,3})\s*%?", tl)
    if m:
        pct = max(0, min(150, int(m.group(1))))
        return {"action":"volume","args":{"set": pct/100.0}}

    if tl in ("mute","toggle mute","mute toggle"):
        return {"action":"mute_toggle","args":{}}

    # project shortcuts
    if tl in ("list project","list my project","project tree","list files","list structure"):
        return {"action":"list_dir","args":{"path":"."}}

    if tl.startswith("find ") or tl.startswith("grep "):
        pat = text.split(" ",1)[1].strip() if " " in text else ""
        if pat:
            return {"action":"grep","args":{"path":".","pattern":pat,"max_hits":60}}

    return None

def dispatch(act):
    action = act.get("action","noop")
    args   = act.get("args",{}) or {}

    try:
        if action == "reply":
            speak(args.get("text","").strip() or "…")
        elif action == "open_url":
            open_url(args.get("url",""))
        elif action == "search":
            search_web(args.get("q",""))
        elif action == "open_app":
            open_app(args.get("app"), args.get("desktop_id"))
        elif action == "volume":
            if "set" in args:
                volume(set_abs=float(args["set"]))
            else:
                volume(delta_percent=int(args.get("delta_percent",0)))
        elif action == "mute_toggle":
            mute_toggle()
        elif action == "media":
            media(args.get("cmd","play-pause"))
        elif action == "gsettings":
            gsettings_set(args.get("schema",""), args.get("key",""), args.get("value",""))
        elif action == "list_dir":
            res = list_dir(args.get("path","."))
            speak(json.dumps(res, indent=2)[:900])
        elif action == "read_file":
            res = read_file(args.get("path",""), int(args.get("max_chars",8000)))
            speak((res.get("text","")[:900] if res.get("ok") else str(res)) )
        elif action == "grep":
            res = grep(args.get("path","."), args.get("pattern",""), int(args.get("max_hits",80)))
            speak(json.dumps(res, indent=2)[:900])
        elif action == "write_file":
            res = write_file(args.get("path",""), args.get("content",""), args.get("mode","w"))
            speak(f"Wrote {res.get('bytes',0)} bytes to {args.get('path','')}")
        elif action == "clipboard_set":
            clipboard_set(args.get("text",""))
            speak("Clipboard updated.")
        else:
            # noop
            pass
    except Exception as e:
        speak(f"Action error: {e}")

def normalize_target(t):
    if not t: return LOCAL_HOST
    t = t.strip().lower()
    return ALIASES.get(t, t)

def is_for_me(target):
    if target in ("both","all"):
        return True
    return target == LOCAL_HOST

def main():
    speak(f"ELI control online. model={MODEL}. root={ROOT.name}")
    last = ""
    while True:
        cur = (clipboard_get() or "").strip()
        if cur and cur != last:
            m = CMD_RE.match(cur)
            if m:
                target_raw, cmd_text = m.group(1), m.group(2)
                cmd_text = cmd_text.strip()
                if cmd_text.startswith(":"):
                    cmd_text = cmd_text[1:].strip()

                target = normalize_target(target_raw)
                if is_for_me(target):
                    # fast-path
                    q = quick_route(cmd_text)
                    if q is None:
                        try:
                            q = ollama_route(cmd_text)
                        except Exception as e:
                            speak(f"Ollama error: {e}")
                            last = cur
                            time.sleep(POLL_SEC)
                            continue
                    dispatch(q)
            last = cur
        time.sleep(POLL_SEC)

if __name__ == "__main__":
    main()
