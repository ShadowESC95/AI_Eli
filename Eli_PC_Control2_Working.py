#!/usr/bin/env python3
import os, sys, json, re, time, queue, threading
import subprocess, shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import shlex

# Ensure project root importable when running from subdir
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import requests
import sounddevice as sd
from faster_whisper import WhisperModel

from eli_tools.executor import execute

# ----------------------------
# Ollama config
# ----------------------------
BASE = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_CHAT = os.environ.get("ELI_OLLAMA_URL", f"{BASE}/api/chat")

CHAT_MODEL   = os.environ.get("ELI_CHAT_MODEL")   or os.environ.get("ELI_MODEL") or os.environ.get("OLLAMA_MODEL")
ROUTER_MODEL = os.environ.get("ELI_ROUTER_MODEL") or CHAT_MODEL  # can be smaller/faster model

if not CHAT_MODEL:
    raise RuntimeError("No model configured. Set ELI_MODEL (or OLLAMA_MODEL).")

HTTP = requests.Session()
KEEP_ALIVE = os.environ.get("ELI_KEEP_ALIVE", "10m")  # keeps model warm in ollama

# Spotify launcher (Flatpak/Snap/native) — set in .env as ELI_SPOTIFY_CMD
SPOTIFY_CMD = os.environ.get("ELI_SPOTIFY_CMD", "").strip() or "flatpak run com.spotify.Client"

# ----------------------------
# Voice config
# ----------------------------
WAKE = tuple(x.strip().lower() for x in os.environ.get("ELI_WAKE", "eli,hey eli,okay eli").split(",") if x.strip())
ALWAYS_AWAKE = os.environ.get("ELI_ALWAYS_AWAKE", "1") == "1"

SR_TARGET = 16000
SR_IN = int(os.environ.get("ELI_SR", "44100"))
CHUNK_MS = int(os.environ.get("ELI_CHUNK_MS", "120"))  # 80–160ms is usually nice

# default: allow ~2.2s of silence before chopping utterance (you can override)
SILENCE_END_MS = int(os.environ.get("ELI_SILENCE_END_MS", "2200"))

_raw_dev = (os.environ.get("ELI_AUDIO_IN") or os.environ.get("ELI_AUDIO_DEVICE") or "").strip()
# Accept numeric index ("6") or name ("pulse"/"pipewire"/"default")
if _raw_dev.isdigit():
    DEVICE = int(_raw_dev)
else:
    DEVICE = _raw_dev
# Never pass empty string to sounddevice ("" matches all -> crash)
if DEVICE == "":
    DEVICE = "pulse"


DEBUG = os.environ.get("ELI_VOICE_DEBUG", "0") == "1"

# Whisper config
WHISPER_SIZE    = os.environ.get("ELI_WHISPER", "base")
WHISPER_DEVICE  = os.environ.get("ELI_WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE = os.environ.get("ELI_WHISPER_COMPUTE", "int8")
WHISPER_LANG    = os.environ.get("ELI_WHISPER_LANG", "en")

# Bias Whisper toward your vocab / commands
DEFAULT_WHISPER_PROMPT = (
    "Eli. hey eli. okay eli. "
    "open path. list directory. read file. run command. search web. "
    "ollama. python. linux. ubuntu. fedora. "
    "xichi. xi chi. paraview. fenics. openfoam. "
)
WHISPER_PROMPT = os.environ.get("ELI_WHISPER_PROMPT", DEFAULT_WHISPER_PROMPT)

# Executor concurrency (prevents backlog making it feel “stuck”)
MAX_INFLIGHT = int(os.environ.get("ELI_MAX_INFLIGHT", "1"))
WORKERS      = int(os.environ.get("ELI_WORKERS", "1"))
_LAST_INTENT = None
_LAST_DOC_ARGS = None

# ----------------------------
# TTS (pyttsx3)
# ----------------------------
_TTS_ENGINE = None
_MIC_IGNORE_UNTIL = 0.0  # ignore mic until this monotonic time
_BUSY_UNTIL = 0.0  # ignore mic while executing actions
_STOP_REQUESTED = False


def _init_tts():
    global _TTS_ENGINE
    if _TTS_ENGINE is not None:
        return
    try:
        import pyttsx3
    except Exception as e:
        if DEBUG:
            print(f"[TTS] pyttsx3 not available: {e}")
        _TTS_ENGINE = None

        return

    eng = pyttsx3.init()
    voice_name = os.environ.get("ELI_TTS_VOICE", "").strip().lower()
    rate       = os.environ.get("ELI_TTS_RATE", "").strip()

    # optional: choose a different voice by partial name
    if voice_name:
        try:
            for v in eng.getProperty("voices"):
                if voice_name in v.name.lower():
                    eng.setProperty("voice", v.id)
                    break
        except Exception as e:
            if DEBUG:
                print(f"[TTS] voice selection failed: {e}")

    if rate:
        try:
            eng.setProperty("rate", int(rate))
        except Exception as e:
            if DEBUG:
                print(f"[TTS] rate set failed: {e}")

    _TTS_ENGINE = eng

def _speak(text: str):
    global _MIC_IGNORE_UNTIL
    text = (text or "").strip()
    if not text:
        return
    # always print transcript
    print(f"[ELI-VOICE] {text}")
    try:
        ignore_ms = int(os.environ.get("ELI_TTS_IGNORE_MS","1200"))
    except Exception:
        ignore_ms = 1200
    _MIC_IGNORE_UNTIL = time.monotonic() + (ignore_ms/1000.0)

    try:
        _init_tts()
        if _TTS_ENGINE is None:
            return
        _TTS_ENGINE.say(text)
        _TTS_ENGINE.runAndWait()
    except Exception as e:
        if DEBUG:
            print(f"[TTS-ERR] {e}")

# ----------------------------
# Router system prompt
# ----------------------------
ROUTER_SYSTEM = r"""
Return ONLY strict JSON:
{"action": one of [
 "open_url","search","open_path",
 "create_doc",
 "list_dir","read_file",
 "write_note","append_note",
 "volume","mute_toggle","media",
 "timer","alarm","calendar_event",
 "open_app","run",
 "chat","noop"
], "args": { ... }}

Rules:
- For web search use: {"action":"search","args":{"q":"..."}}
- For opening a folder/file: {"action":"open_path","args":{"path":"~/Desktop/AI_Eli/..." }}
- For listing a folder: {"action":"list_dir","args":{"path":"...","depth":2}}
- For reading a file: {"action":"read_file","args":{"path":"..."}}
- For creating documents/notes: {"action":"create_doc","args":{"doc_type":"md|txt|tex","title":"...","content":"...","filename":"optional","convert_to":"pdf|odt|omit","open_after":true}}
- For notes: write_note {title, content, filename?, open_after?}
- For timer: {"seconds": N, "message":"..."}
- For alarm: {"time":"HH:MM", "message":"..."}
- For calendar_event: {"title":"...", "start":"YYYY-MM-DDTHH:MM", "duration_min":30, "location":"", "notes":""}
- For running commands: {"cmd":"python3 ...","cwd":"~/Desktop/AI_Eli","timeout":60}
- If user is just talking / asking / brainstorming: action="chat" with args={"prompt":"..."}
"""

# ----------------------------
# Helpers

def _slugify(name: str) -> str:
    name = (name or "doc").strip().lower()
    name = re.sub(r"[^a-z0-9]+", "_", name).strip("_")
    return name or "doc"

def _open_file(path: str) -> None:
    try:
        subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
def _allowed_cmds_set():
    raw = (os.environ.get("ELI_ALLOWED_CMDS") or "").strip()
    if not raw:
        return None  # None => no allowlist enforcement here (executor may still enforce)
    return {x.strip() for x in raw.split(",") if x.strip()}

def _allow_or_block(argv0: str) -> bool:
    allowed = _allowed_cmds_set()
    if allowed is None:
        return True
    return argv0 in allowed

def _run_argv(argv, timeout=6):
    if not argv:
        return {"ok": False, "error": "empty argv"}
    if not _allow_or_block(argv[0]):
        return {"ok": False, "error": f"command not allowed: {argv[0]} (ELI_ALLOWED_CMDS)"}

    try:
        r = subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            shell=False,
        )
        return {
            "ok": (r.returncode == 0),
            "returncode": r.returncode,
            "stdout": (r.stdout or "")[-2000:],
            "stderr": (r.stderr or "")[-2000:],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _spotify_player_name():
    # Pick a player name that actually exists (flatpak spotify usually exposes "spotify")
    r = _run_argv(["playerctl", "-l"], timeout=2)
    if r.get("ok") and r.get("stdout"):
        players = [p.strip() for p in r["stdout"].splitlines() if p.strip()]
        for p in players:
            if "spotify" in p.lower():
                return p
    return "spotify"

def _spotify_launch():
    argv = shlex.split(SPOTIFY_CMD)
    if not argv:
        return {"ok": False, "error": "ELI_SPOTIFY_CMD is empty"}

    if not _allow_or_block(argv[0]):
        return {"ok": False, "error": f"command not allowed: {argv[0]} (ELI_ALLOWED_CMDS)"}

    try:
        subprocess.Popen(
            argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return {"ok": True, "launched": True, "cmd": argv}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _spotify_ctl(command: str, auto_launch: bool = True):
    """
    command: play|pause|stop|status|next|previous|play-pause
    """
    player = _spotify_player_name()
    r = _run_argv(["playerctl", "-p", player, command], timeout=3)

    # If play fails because spotify isn't running/registered, optionally launch and retry
    if (not r.get("ok")) and auto_launch and command in {"play", "play-pause"}:
        launch = _spotify_launch()
        time.sleep(2)
        player = _spotify_player_name()
        r2 = _run_argv(["playerctl", "-p", player, command], timeout=3)
        return {"ok": r2.get("ok", False), "launch": launch, "result": r2, "player": player}

    return {"ok": r.get("ok", False), "result": r, "player": player}

def _builtin_create_doc(args: dict) -> dict:
    try:
        doc_type  = (args.get("doc_type") or "txt").strip().lower()
        title     = (args.get("title") or "document").strip()
        content   = args.get("content") or ""
        filename  = (args.get("filename") or "").strip()
        convert_to = (args.get("convert_to") or "omit").strip().lower()
        open_after = bool(args.get("open_after", False))

        ext = doc_type if doc_type in {"md","txt","tex"} else "txt"

        outdir = Path(os.environ.get("ELI_DOC_DIR", str(ROOT / "eli_docs"))).expanduser()
        outdir.mkdir(parents=True, exist_ok=True)

        if filename:
            fn = filename if filename.endswith(f".{ext}") else filename + f".{ext}"
        else:
            fn = _slugify(title) + f".{ext}"

        outpath = outdir / fn
        outpath.write_text(content, encoding="utf-8")

        if open_after:
            _open_file(str(outpath))

        # (optional) conversion hook is left as a no-op unless you already have tooling in executor
        return {"ok": True, "path": str(outpath)}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ----------------------------
def _notify(title: str, msg: str):
    try:
        if os.environ.get("ELI_NOTIFY", "1") == "1":
            os.system(f'notify-send "{title}" "{msg}" >/dev/null 2>&1')
        if DEBUG:
            print(f"[NOTIFY] {title}: {msg}")
    except Exception:
        if DEBUG:
            print(f"[NOTIFY] {title}: {msg}")


def _set_busy(ms: int = 900):
    global _BUSY_UNTIL
    try:
        ms = int(ms)
    except Exception:
        ms = 900
    _BUSY_UNTIL = time.monotonic() + (ms / 1000.0)
def _rms(x: np.ndarray) -> float:
    x = np.asarray(x, dtype=np.float32)
    if x.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(x * x) + 1e-12))

def _resample_to_16k(x: np.ndarray, sr_in: int) -> np.ndarray:
    if sr_in == SR_TARGET:
        return x.astype(np.float32, copy=False)
    n_in = x.shape[0]
    if n_in <= 1:
        return np.zeros((1,), dtype=np.float32)
    t_in = np.linspace(0.0, 1.0, n_in, endpoint=False)
    n_out = max(1, int(round(n_in * (SR_TARGET / sr_in))))
    t_out = np.linspace(0.0, 1.0, n_out, endpoint=False)
    return np.interp(t_out, t_in, x).astype(np.float32)

def _extract_json(s: str) -> dict:
    s = (s or "").strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    m = re.search(r"\{.*\}", s, flags=re.DOTALL)
    if not m:
        return {"action": "noop", "args": {}}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {"action": "noop", "args": {}}

def _ollama(model: str, system: str, user: str,
            temperature: float = 0.0, num_predict: int = 256) -> str:
    payload = {
        "model": model,
        "stream": False,
        "keep_alive": KEEP_ALIVE,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "options": {
            "temperature": float(temperature),
            "num_predict": int(num_predict),
            "num_ctx": int(os.environ.get("ELI_NUM_CTX", "2048")),
            "top_p": float(os.environ.get("ELI_TOP_P", "0.9")),
        },
    }
    r = HTTP.post(OLLAMA_CHAT, json=payload, timeout=120)
    r.raise_for_status()
    return r.json()["message"]["content"]

def _router_llm(text: str) -> dict:
    out = _ollama(ROUTER_MODEL, ROUTER_SYSTEM, text, temperature=0.0, num_predict=60)
    return _extract_json(out)

def _chat_llm(text: str) -> str:
    # optional tone bias: drop a style file in eli_voice/style.txt
    style_path = ROOT / "eli_voice" / "style.txt"
    style = ""
    if style_path.exists():
        style = style_path.read_text(encoding="utf-8", errors="ignore").strip()

    sysmsg = (
        "You are Eli.\n"
        "Be concise, practical, and honest.\n"
        "If user asks to DO something on this PC, propose a concrete command/action.\n"
    )
    if style:
        sysmsg += "\nUser tone preferences:\n" + style[:2000]

    return _ollama(
        CHAT_MODEL,
        sysmsg,
        text,
        temperature=float(os.environ.get("ELI_CHAT_TEMP", "0.35")),
        num_predict=320,
    )

def _has_wake(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    # allow punctuation after wake word: "eli.", "eli,", "eli:"
    for w in WAKE:
        if re.match(rf"^{re.escape(w)}(?:[\s\W]+|$)", t, flags=re.IGNORECASE):
            return True
    return False

def _strip_wake(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    for w in WAKE:
        m = re.match(rf"^{re.escape(w)}(?:[\s\W]+|$)", t, flags=re.IGNORECASE)
        if m:
            return t[m.end():].strip()
    return t

def _local_intent(cmd: str):
    c  = (cmd or "").strip()
    if not c:
        return None
    cl = c.lower().strip()

    # SPOTIFY_FIX_LOCAL_INTENT
    # Create document with numbers 1..N (fast-path, no LLM)
    if ("create" in cl or "make" in cl) and ("document" in cl or "doc" in cl) and "number" in cl:
        import re as _re
        m = _re.search(r"\b1\s*(?:to|-)\s*(\d+)\b", cl)
        n = None
        if m:
            n = int(m.group(1))
        else:
            # small word map for common cases
            wmap = {"ten":10,"twenty":20,"thirty":30,"forty":40,"fifty":50,"sixty":60,"seventy":70,"eighty":80,"ninety":90,"hundred":100}
            m2 = _re.search(r"\bone\s*(?:to|-)\s*(\w+)\b", cl)
            if m2:
                n = wmap.get(m2.group(1), None)
        if isinstance(n, int) and 1 <= n <= 5000:
            content = "\n".join(str(i) for i in range(1, n+1)) + "\n"
            return {"action":"create_doc","args":{"doc_type":"txt","title":f"numbers_1_to_{n}","content":content,"open_after":True}}

    # Spotify overrides BEFORE generic media handlers (NO SHELL)
    if "spotify" in cl:
        import re as _re
        if _re.match(r"^(open|launch|start)\b", cl):
            return {"action":"spotify","args":{"command":"launch"}}
        if _re.match(r"^(resume|play)\b", cl):
            return {"action":"spotify","args":{"command":"play"}}
        if _re.match(r"^(pause|stop)\b", cl):
            # "stop" maps to playerctl stop; if you prefer pause, use "pause"
            cmd = "stop" if cl.startswith("stop") else "pause"
            return {"action":"spotify","args":{"command":cmd}}



    # ---- TIME (keep this local, router shouldn't touch it)
    if re.search(r"\b(what(?:'s| is)? the time|what time is it|what time is this|tell me (?:the )?time|current time|time is it)\b", cl):
        return {"action": "time", "args": {}}

    # ---- SEARCH (supports "search for ...")
    m = re.match(r'^(search|google)\s+(?:for\s+)?(.+)$', cl)
    if m:
        q = c.split(None, 1)[1]
        q = re.sub(r'^\s*for\s+', '', q, flags=re.IGNORECASE)
        q = q.strip().strip("\"'")
        q = q.rstrip(" .!?")
        return {"action": "search", "args": {"q": q}}

    # ---- DOC: "create a document ... numbers 1 to N" OR "do the same again ... 1 to N"
    m = re.search(r"\b(?:create|make)\b.*\b(?:document|doc)\b.*\b(?:numbers?|contents?)\b.*\b1\b\s*(?:to|through|thru|-)\s*(\d+)\b", cl)
    if not m:
        m = re.search(r"\bdo the same again\b.*\b1\b\s*(?:to|through|thru|-)\s*(\d+)\b", cl)
    if m:
        try:
            n = int(m.group(1))
        except Exception:
            n = 10
        n = max(1, min(n, 5000))
        content = "\n".join(str(i) for i in range(1, n + 1)) + "\n"
        return {"action": "create_doc", "args": {"doc_type": "txt", "title": f"numbers_1_to_{n}", "content": content, "open_after": True}}

    # ---- OPEN PATH (explicit)
    m = re.match(r'^(open\s+path)\s+(.+)$', cl)
    if m:
        path = c.split(None, 2)[2].strip().strip("\"'").rstrip(" .!?,")
        return {"action": "open_path", "args": {"path": path}}

    # ---- OPEN (URLs/apps/notes)
    m = re.match(r'^(open|go to|launch)\s+(.+)$', cl)
    if m:
        target = c.split(None, 1)[1].strip().strip("\"'")
        target = re.sub(r"^(the\s+)?app(?:lication)?s?\b[\s:,-]*", "", target, flags=re.IGNORECASE).strip()
        target = target.rstrip(" .!?,")
        key = target.lower()

        # common services
        if key in {"youtube", "youtube.com", "www.youtube.com"}:
            return {"action": "open_url", "args": {"url": "https://www.youtube.com"}}
        if key in {"spotify", "spotify.com", "open.spotify.com", "www.spotify.com"}:
            return {"action": "open_url", "args": {"url": "https://open.spotify.com"}}

        # notes: open notes.txt in doc dir (create if missing)
        if key in {"notes", "note", "notepad"}:
            doc_dir = os.path.expanduser(os.environ.get("ELI_DOC_DIR", str(ROOT / "eli_docs")))
            notes = Path(doc_dir) / "notes.txt"
            if notes.exists():
                return {"action": "open_path", "args": {"path": str(notes)}}
            return {"action": "create_doc", "args": {"doc_type": "txt", "title": "notes", "content": "", "open_after": True}}

        # treat as filesystem path ONLY if it looks like one
        if target.startswith(("~", "/", "./", "../")) or "/" in target:
            return {"action": "open_path", "args": {"path": target}}

        # treat domain-like strings as URLs
        if key.startswith(("http://", "https://")):
            return {"action": "open_url", "args": {"url": target}}
        if re.match(r"^[a-z0-9][a-z0-9\.-]*\.[a-z]{2,}(/.*)?$", key):
            return {"action": "open_url", "args": {"url": "https://" + key}}

        # otherwise let router decide (open_app etc.)
        return None

    # ---- LIST DIR
    m = re.match(r'^(list|ls|dir)\s+(.+)$', cl)
    if m:
        return {"action": "list_dir", "args": {"path": c.split(None, 1)[1], "depth": 2}}

    # ---- READ FILE
    m = re.match(r'^(read|cat)\s+(.+)$', cl)
    if m:
        return {"action": "read_file", "args": {"path": c.split(None, 1)[1]}}

    # ---- RUN
    m = re.match(r'^(run)\s+(.+)$', cl)
    if m:
        return {"action": "run", "args": {"cmd": c.split(None, 1)[1], "cwd": str(ROOT), "timeout": 120}}

    # "python" alone should NOT run (it hangs waiting for input)
    if cl in {"python", "python3"}:
        return {"action": "noop", "args": {}}

    # allow "python <script or -c ...>" as shorthand
    if cl.startswith("python "):
        return {"action": "run", "args": {"cmd": "python3 " + c.split(None, 1)[1], "cwd": str(ROOT), "timeout": 120}}
    if cl.startswith("python3 "):
        return {"action": "run", "args": {"cmd": c, "cwd": str(ROOT), "timeout": 120}}

    # alarm for N seconds/minutes -> timer
    m = re.match(r'^alarm\s+for\s+(\d+)\s*(s|sec|secs|seconds|m|min|mins|minutes)\b\s*(.*)$', cl)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        msg = (m.group(3) or "").strip() or "alarm"
        if unit.startswith("m"):
            n *= 60
        return {"action": "timer", "args": {"seconds": n, "message": msg}}

    # ---- TIMER N seconds/minutes
    m = re.match(r'^timer\s+(\d+)\s*(s|sec|secs|seconds|m|min|mins|minutes)?\s*(.*)$', cl)
    if m:
        n    = int(m.group(1))
        unit = (m.group(2) or "seconds")
        msg  = (m.group(3) or "").strip() or "timer"
        if unit.startswith("m"):
            n *= 60
        return {"action": "timer", "args": {"seconds": n, "message": msg}}

    return None

def list_devices():
    devs = sd.query_devices()
    print("\nInput devices:")
    for i, d in enumerate(devs):
        if d.get("max_input_channels", 0) > 0:
            print(f"  [{i}] {d['name']}  in={d['max_input_channels']}  sr={d.get('default_samplerate')}")
    print()

def calibrate_noise(seconds=1.0) -> float:
    frames = int(SR_IN * seconds)
    x = sd.rec(frames, samplerate=SR_IN, channels=1, dtype="float32", device=DEVICE)
    sd.wait()
    return _rms(x[:, 0])

# ----------------------------
# Worker: STT -> intent -> execute
# ----------------------------
def _handle_utterance(audio: np.ndarray, whisper: WhisperModel):
    global _BUSY_UNTIL, _LAST_INTENT, _LAST_DOC_ARGS
    if _STOP_REQUESTED:
        return
    t0 = time.perf_counter()

    audio16 = _resample_to_16k(audio, SR_IN)

    # condition_on_previous_text=False avoids “bleed” between utterances
    segments, info = whisper.transcribe(
        audio16,
        vad_filter=True,
        language=WHISPER_LANG,
        beam_size=1,
        temperature=0.0,
        initial_prompt=WHISPER_PROMPT,
        condition_on_previous_text=False,
    )
    text = " ".join(s.text.strip() for s in segments).strip()
    t1 = time.perf_counter()

    if not text:
        return

    # ignore garbage like only punctuation/dots from silence
    if not re.search(r"[A-Za-z0-9]", text):
        if DEBUG:
            print("[SKIP] non-speech")
        return

    has_wake = _has_wake(text)
    if DEBUG or ALWAYS_AWAKE or has_wake:
        print(f"[HEARD] {text}")
        # ANTI_SPAM_FILTER
        w = [t for t in re.findall(r"[A-Za-z']+", text.lower()) if t]
        if len(w) >= 12:
            # if one token dominates, it's usually hallucinated garbage
            from collections import Counter
            c = Counter(w)
            top = c.most_common(1)[0][1]
            if (top / max(1, len(w))) > 0.70:
                if DEBUG:
                    print('[SKIP] spammy transcript')
                return

    if not ALWAYS_AWAKE and not has_wake:
        if DEBUG:
            print("[SKIP] no wake word")
        return

    cmd = _strip_wake(text)
    if not cmd:
        return

    # Fast path first
    intent = _local_intent(cmd)
    t2 = time.perf_counter()

    # Fallback to router only if needed
    if intent is None:
        intent = _router_llm(cmd)

    action = intent.get("action", "noop")
    args   = intent.get("args", {}) or {}
    # normalize legacy builtin markers
    if action == 'noop' and isinstance(args, dict) and args.get('__builtin') == 'time':
        action, args = 'time', {}
    print(f"[INTENT] {action} {args}")

    # SPOTIFY_FIX_NORMALIZE (NO SHELL)
    cl_cmd = cmd.lower()
    if "spotify" in cl_cmd:
        # If router returns open_app "Spotify", treat as launch
        if action == "open_app":
            action, args = "spotify", {"command": "launch"}
            intent = {"action": action, "args": args}

        # If router returns media, target spotify explicitly
        if action == "media" and isinstance(args, dict):
            mcmd = (args.get("command") or "").lower()
            if mcmd in {"resume", "play", "play-pause", "toggle"}:
                action, args = "spotify", {"command": "play"}
                intent = {"action": action, "args": args}
            elif mcmd in {"pause", "stop"}:
                action, args = "spotify", {"command": ("pause" if mcmd == "pause" else "stop")}
                intent = {"action": action, "args": args}

        # If router returns run with spotify-ish text, force spotify builtin
        if action == "run" and isinstance(args, dict):
            s = (args.get("cmd") or "").lower()
            if "spotify" in s or "playerctl" in s:
                if "pause" in s or "stop" in s:
                    action, args = "spotify", {"command": ("pause" if "pause" in s else "stop")}
                elif "play" in s or "resume" in s:
                    action, args = "spotify", {"command": "play"}
                elif "flatpak" in s or "launch" in s or "start" in s:
                    action, args = "spotify", {"command": "launch"}
                intent = {"action": action, "args": args}

    # executor compatibility: normalize arg keys
    if action == "open_app" and isinstance(args, dict):
        app = args.get("app") or args.get("app_name") or args.get("name") or ""
        intent["args"] = {"app": app}
        args = intent["args"]

    # repair empty numbers doc (router sometimes emits empty content)
    if action == 'create_doc' and isinstance(args, dict):
        title = (args.get('title') or '')
        content = args.get('content')
        if (content is None or content == '') and re.match(r'^numbers_(\d+)_to_(\d+)$', title):
            m = re.match(r'^numbers_(\d+)_to_(\d+)$', title)
            a = int(m.group(1)); b = int(m.group(2))
            if a <= b and (b-a) <= 5000:
                args['content'] = '\n'.join(str(i) for i in range(a, b+1)) + '\n'
# guard_alarm_seconds_to_timer

    # If router gives an alarm but the user said 'in X seconds/minutes', treat it as a timer.
    cl = (cmd or '').lower()
    mm = re.search(r"\b(\d+)\s*(s|sec|secs|second|seconds|m|min|mins|minute|minutes)\b", cl)
    if action == 'alarm' and mm and (' at ' not in cl):
        n = int(mm.group(1))
        unit = mm.group(2)
        if unit.startswith('m'):
            n *= 60
        action = 'timer'
        args = {'seconds': n, 'message': 'alarm'}
        intent = {'action': action, 'args': args}
        print(f"[INTENT-FIX] {action} {args}")

    # BUILTIN: time (bypass router/executor)
    if action == "time" or (isinstance(args, dict) and args.get("__builtin") == "time"):
        now = time.strftime("%H:%M:%S")
        _speak(f"It's {now}.")
        print(f"[DONE] {{'ok': True, 'action': 'time', 'time': {now!r}}}")
        return

    # BUILTIN: create_doc (bypass router/executor)
    if action == "create_doc":
        try:
            doc_dir = Path(os.environ.get("ELI_DOC_DIR", str(ROOT / "eli_docs"))).expanduser()
            doc_dir.mkdir(parents=True, exist_ok=True)
            doc_type  = (args.get("doc_type") or "txt").strip().lower()
            title     = (args.get("title") or "document").strip()
            content   = (args.get("content") or "")
            filename  = (args.get("filename") or "").strip()

            ext = doc_type if doc_type in {"md","txt","tex"} else "txt"
            slug = re.sub(r"[^a-zA-Z0-9]+", "_", title).strip("_") or "document"
            fn = filename or f"{slug}.{ext}"
            if not fn.endswith(f".{ext}"):
                fn += f".{ext}"

            outpath = (doc_dir / fn)
            outpath.write_text(content, encoding="utf-8")

            if bool(args.get("open_after", True)):
                try:
                    import subprocess
                    subprocess.Popen(["xdg-open", str(outpath)],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass

            res = {"ok": True, "path": str(outpath)}
            print(f"[DONE] {res}")
            _speak("Document created.")
        except Exception as e:
            res = {"ok": False, "error": str(e)}
            print(f"[DONE] {res}")
            _speak("There was an error creating the document.")
        return


    # Builtins (bypass executor allowlists)
    if action == "time":
        now = time.strftime("%H:%M:%S")
        _speak(f"It's {now}.")
        print(f"[DONE] {{'ok': True, 'action': 'time', 'time': {now!r}}}")
        return

    if action == "create_doc":
        result = _builtin_create_doc(args if isinstance(args, dict) else {})
        print(f"[DONE] {result}")
        _speak("Document created." if result.get("ok") else "There was an error creating the document.")
        return

    # Built-in actions (bypass executor allowlist)
    if isinstance(args, dict) and args.get("__builtin") == "time":
        now = time.strftime("%H:%M:%S")
        _speak(f"It's {now}.")
        print(f"[DONE] {{'ok': True, 'action': 'time', 'time': now}}")
        return
        
        # BUILTIN: spotify (bypass executor & NO SHELL)
    # BUILTIN: spotify (bypass executor & NO SHELL)
    if action == "spotify":
        cmd0 = (args.get("command") or "").lower().strip()
        if cmd0 in {"launch","open","start"}:
            res = _spotify_launch()
            print(f"[DONE] {res}")
            _speak("Opening Spotify." if res.get("ok") else "Could not open Spotify.")
            return

        if cmd0 in {"play","resume"}:
            res = _spotify_ctl("play", auto_launch=True)
            print(f"[DONE] {res}")
            _speak("Playing Spotify." if res.get("ok") else "Could not control Spotify.")
            return

        if cmd0 in {"pause"}:
            res = _spotify_ctl("pause", auto_launch=False)
            print(f"[DONE] {res}")
            _speak("Paused Spotify." if res.get("ok") else "Could not pause Spotify.")
            return

        if cmd0 in {"stop"}:
            res = _spotify_ctl("stop", auto_launch=False)
            print(f"[DONE] {res}")
            _speak("Stopped Spotify." if res.get("ok") else "Could not stop Spotify.")
            return

        res = {"ok": False, "error": f"unknown spotify command: {cmd0!r}"}
        print(f"[DONE] {res}")
        _speak("I did not understand the Spotify command.")
        return

    cmd0 = (args.get("command") or "").lower().strip()
    if cmd0 in {"launch","open","start"}:
        res = _spotify_launch()
        print(f"[DONE] {res}")
        _speak("Opening Spotify." if res.get("ok") else "Could not open Spotify.")
        return

    if cmd0 in {"play","resume"}:
        res = _spotify_ctl("play", auto_launch=True)
        print(f"[DONE] {res}")
        _speak("Playing Spotify." if res.get("ok") else "Could not control Spotify.")
        return

    if cmd0 in {"pause"}:
        res = _spotify_ctl("pause", auto_launch=False)
        print(f"[DONE] {res}")
        _speak("Paused Spotify." if res.get("ok") else "Could not pause Spotify.")
        return

    if cmd0 in {"stop"}:
        res = _spotify_ctl("stop", auto_launch=False)
        print(f"[DONE] {res}")
        _speak("Stopped Spotify." if res.get("ok") else "Could not stop Spotify.")
        return

    # fallback
    res = {"ok": False, "error": f"unknown spotify command: {cmd0!r}"}
    print(f"[DONE] {res}")
    _speak("I didn't understand the Spotify command.")
    return



    if action == "chat":
        reply = _chat_llm(args.get("prompt") or cmd)
        _speak(reply)
        t3 = time.perf_counter()
        if DEBUG:
            print(f"[LAT] stt={t1-t0:.2f}s parse={t2-t1:.2f}s llm+chat={t3-t2:.2f}s total={t3-t0:.2f}s")
        return

    t_llm = time.perf_counter()
    try:
        ms = int(os.environ.get("ELI_ACTION_IGNORE_MS","900"))
    except Exception:
        ms = 900
    _BUSY_UNTIL = max(_BUSY_UNTIL, time.monotonic() + (ms/1000.0))
    result = execute(intent)
    _set_busy(int(os.environ.get('ELI_ACTION_IGNORE_MS','900')))
    _BUSY_UNTIL = max(_BUSY_UNTIL, time.monotonic() + (ms/1000.0))
    _LAST_INTENT = dict(intent) if isinstance(intent, dict) else None
    if action == 'create_doc' and isinstance(args, dict) and result.get('ok', False):
        _LAST_DOC_ARGS = dict(args)
    t4 = time.perf_counter()

    # verbal summary for non-chat actions
    summary = None
    if action in {"timer"}:
        secs = args.get("seconds")
        if isinstance(secs, (int, float)):
            summary = f"Timer set for {int(secs)} seconds."
    elif action in {"alarm"}:
        summary = "Alarm set."
    elif action in {"calendar_event"}:
        summary = f"Calendar event created: {args.get('title','event')}."
    elif action in {"write_note", "append_note"}:
        summary = "Note updated."
    elif action == "open_path":
        summary = "Path opened."
    elif action == "search":
        summary = f"Searching for {args.get('q','')!r}."
    elif action == "run":
        out = (result.get("stdout") or result.get("out") or result.get("output") or "").strip()
        summary = out.splitlines()[0][:200] if out else "Done."

    print(f"[DONE] {result}")
    if not result.get("ok", True):
        _notify("ELI error", result.get("error", ""))
        _speak("There was an error executing that.")
    else:
        if action in {"timer", "alarm", "calendar_event", "write_note"}:
            _notify("ELI", f"{action} set")
        if summary:
            _speak(summary)

    if DEBUG:
        print(f"[LAT] stt={t1-t0:.2f}s local={t2-t1:.2f}s route={t_llm-t2:.2f}s exec={t4-t_llm:.2f}s total={t4-t0:.2f}s")

# ----------------------------
# Main
# ----------------------------
def main():
    if "--list-devices" in sys.argv:
        list_devices()
        return

    print(f"[ELI] Voice online. in_sr={SR_IN} device={DEVICE} router={ROUTER_MODEL} chat={CHAT_MODEL}")
    print(f"[ELI] Wake={WAKE} AlwaysAwake={ALWAYS_AWAKE}")

    whisper = WhisperModel(WHISPER_SIZE, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE)

    noise = calibrate_noise(float(os.environ.get("ELI_CAL_SEC", "1.0")))
    start_thr = max(0.02,  noise * 1.8)
    stop_thr  = max(0.015, noise * 1.2)

    # env overrides for thresholds
    _st = os.environ.get("ELI_START_THR", "").strip()
    _sp = os.environ.get("ELI_STOP_THR", "").strip()
    if _st:
        start_thr = float(_st)
    if _sp:
        stop_thr = float(_sp)
    if stop_thr >= start_thr:
        stop_thr = max(0.0, start_thr * 0.75)

    SILENCE_CHUNKS_TO_END = max(1, int(np.ceil(SILENCE_END_MS / CHUNK_MS)))
    MIN_UTTER_CHUNKS      = max(2, int(np.ceil(300 / CHUNK_MS)))  # 300ms min

    # Max utterance: one source of truth
    _ms = os.environ.get("ELI_MAX_UTTER_MS", "").strip()
    if _ms:
        max_chunks = max(3, int(np.ceil(int(_ms) / CHUNK_MS)))
    else:
        max_utter_sec = float(os.environ.get("ELI_MAX_UTTER_SEC", "8"))
        max_chunks = max(3, int(np.ceil(max_utter_sec * 1000 / CHUNK_MS)))

    if DEBUG:
        print(f"[CAL] noise_rms={noise:.6f} start_thr={start_thr:.6f} stop_thr={stop_thr:.6f}")
        print(f"[CAL] silence_chunks={SILENCE_CHUNKS_TO_END} "
              f"min_chunks={MIN_UTTER_CHUNKS} max_chunks={max_chunks}")

    frames_per_chunk = int(SR_IN * CHUNK_MS / 1000)
    audio_q = queue.Queue(maxsize=200)

    def cb(indata, frames, time_info, status):
        try:
            audio_q.put_nowait(indata[:, 0].copy())
        except queue.Full:
            pass

    started = False
    silent  = 0
    buf     = []

    # Concurrency gate (avoid “lag spiral”)
    inflight = threading.Semaphore(MAX_INFLIGHT)
    pool     = ThreadPoolExecutor(max_workers=WORKERS)

    def submit(audio):
        if _STOP_REQUESTED:
            return
        if not inflight.acquire(blocking=False):
            if DEBUG:
                print("[SKIP] busy (inflight max)")
            return

        def _run():
            try:
                _handle_utterance(audio, whisper)
            finally:
                inflight.release()

        pool.submit(_run)

    try:
        with sd.InputStream(
            samplerate=SR_IN,
            channels=1,
            dtype="float32",
            blocksize=frames_per_chunk,
            device=DEVICE,
            callback=cb,
        ):
            while True:
                try:
                    x = audio_q.get(timeout=1.0)
                except queue.Empty:
                    continue

                now_m = time.monotonic()
                if now_m < _MIC_IGNORE_UNTIL or now_m < _BUSY_UNTIL:
                    continue
                now_m = time.monotonic()
                if now_m < _MIC_IGNORE_UNTIL or now_m < _BUSY_UNTIL:
                    continue
                r = _rms(x)
                if DEBUG:
                    print(f"[RMS] {r:.5f} started={started} silent={silent} len={len(buf)}")

                if not started:
                    if r >= start_thr:
                        started = True
                        silent  = 0
                        buf     = [x]
                    continue

                buf.append(x)

                if r < stop_thr:
                    silent += 1
                else:
                    silent = 0

                # end utterance only when we've had enough silence OR hit max length
                if silent < SILENCE_CHUNKS_TO_END and len(buf) < max_chunks:
                    continue

                audio = np.concatenate(buf, axis=0).astype(np.float32, copy=False)
                started = False
                silent  = 0
                buf     = []

                # Too short? ignore
                if len(audio) < int(MIN_UTTER_CHUNKS * frames_per_chunk):
                    if DEBUG:
                        print("[SKIP] too short")
                    continue

                submit(audio)

    except KeyboardInterrupt:
        global _STOP_REQUESTED
        _STOP_REQUESTED = True
        print("\n[ELI] stopped.")
    finally:
        pool.shutdown(wait=True, cancel_futures=True)

if __name__ == "__main__":
    main()

