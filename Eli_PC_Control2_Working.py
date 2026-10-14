#!/usr/bin/env python3
import os
import time

_T0 = time.monotonic()

def _t(tag: str):
    import os
    if os.environ.get('ELI_TIMING','0') in ('0','', 'false','False','no','No'):
        return
    print(f"[+{time.monotonic()-_T0:8.3f}s] {tag}", flush=True)

import sys, json, re, queue, threading
import subprocess, shutil
from pathlib import Path

def _resolve_user_path(raw: str) -> str:
    """Resolve fuzzy paths."""
    import os
    from pathlib import Path
    p = str(raw or "").strip()
    if not p:
        return p
    home = os.path.expanduser("~")
    desktop = os.environ.get("ELI_DESKTOP_DIR", os.path.join(home, "Desktop"))
    # ... simplified version ...
    return p

from concurrent.futures import ThreadPoolExecutor
import shlex

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eli_tools import config as eli_config  # loads ~/.eli_config (or $ELI_CONFIG) into the environment

DATA_DIR = ROOT / "data"
MEMORY_DIR = DATA_DIR / "memory"
MEMORY_LOG = MEMORY_DIR / "utterances.jsonl"
TTS_PREF_FILE = MEMORY_DIR / "tts_voice.json"

def _ensure_dir(p: Path):
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

def _memory_append(obj: dict):
    try:
        _ensure_dir(MEMORY_DIR)
        with open(MEMORY_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    except Exception:
        pass

try:
    if not os.environ.get("ELI_TTS_VOICE") and TTS_PREF_FILE.exists():
        pref = json.loads(TTS_PREF_FILE.read_text(encoding="utf-8"))
        if isinstance(pref, dict) and pref.get("voice"):
            os.environ["ELI_TTS_VOICE"] = str(pref["voice"])
except Exception:
    pass

import numpy as np
import requests

# Try to import faster_whisper with venv fallback
try:
    from faster_whisper import WhisperModel
except ImportError:
    # Try adding venv path
    import sys
    import os
    venv_path = os.path.join(os.path.dirname(__file__), '.venv', 'lib', 
                            f'python{sys.version_info.major}.{sys.version_info.minor}', 
                            'site-packages')
    if os.path.exists(venv_path):
        sys.path.insert(0, venv_path)
        try:
            from faster_whisper import WhisperModel
            print(f"[ELI] Using faster_whisper from venv")
        except ImportError:
            WhisperModel = None
            print("[ELI] WARNING: faster_whisper not available")
    else:
        WhisperModel = None
        print("[ELI] WARNING: faster_whisper not available")

try:
    import sounddevice as sd
except Exception as _sd_error:  # not installed, or no sound server to talk to (PortAudioError)
    sd = None
    _SD_ERROR = _sd_error

from eli_tools.compat import execute

try:
    from eli_tools.runlog import log_event
except Exception:
    log_event = None

CONTROL_ARMED = False
REQUIRE_ARM = (os.environ.get('ELI_REQUIRE_ARM','1').strip() != '0')


# Ensure project root importable when running from subdir
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ----------------------------
# Local storage (notes/skills/memory)
# ----------------------------
DATA_DIR = ROOT / "data"
MEMORY_DIR = DATA_DIR / "memory"
MEMORY_LOG = MEMORY_DIR / "utterances.jsonl"
TTS_PREF_FILE = MEMORY_DIR / "tts_voice.json"

def _ensure_dir(p: Path):
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
# =================================================================
# SMART IMPORT HANDLING
# =================================================================
import sys
import os

def _try_import_faster_whisper():
    """Try multiple strategies to import faster_whisper."""
    strategies = [
        # Try direct import first
        lambda: __import__('faster_whisper'),
        
        # Try adding venv path
        lambda: (sys.path.insert(0, os.path.join(os.path.dirname(__file__), '.venv', 'lib', 
                                                 f'python{sys.version_info.major}.{sys.version_info.minor}', 
                                                 'site-packages')) or __import__('faster_whisper')),
        
        # Try common site-packages locations
        lambda: (sys.path.insert(0, os.path.expanduser('~/.local/lib/') + 
                                 f'python{sys.version_info.major}.{sys.version_info.minor}/site-packages') 
                or __import__('faster_whisper')),
    ]
    
    for strategy in strategies:
        try:
            return strategy()
        except ImportError:
            continue
    
    return None

# Try to import faster_whisper
_faster_whisper_module = _try_import_faster_whisper()

if _faster_whisper_module:
    from faster_whisper import WhisperModel
    print(f"[ELI] Using faster_whisper from: {_faster_whisper_module.__file__}")
else:
    # Create a dummy that provides better error
    class WhisperModel:
        def __init__(self, *args, **kwargs):
            raise ImportError(
                "faster_whisper not found.\n"
                "Install it with: pip install faster-whisper\n"
                "Or activate your virtual environment first.\n"
                "If you have a venv, run: source .venv/bin/activate"
            )
    print("[ELI] WARNING: faster_whisper not available - voice recognition disabled")
# =================================================================

from eli_tools.compat import execute


try:
    from eli_tools.runlog import log_event
except Exception:
    log_event = None

# ----------------------------
# Ollama config
# ----------------------------
BASE = eli_config.ollama_base()
OLLAMA_CHAT = os.environ.get("ELI_OLLAMA_URL", f"{BASE}/api/chat")

CHAT_MODEL   = eli_config.chat_model()
ROUTER_MODEL = os.environ.get("ELI_ROUTER_MODEL") or CHAT_MODEL  # can be smaller/faster model

if not CHAT_MODEL:
    raise SystemExit("No model configured. Set ELI_MODEL to an Ollama model you have pulled (see `ollama list`), "
                     "in ~/.eli_config or the environment.")
import requests

HTTP = requests.Session()
try:
    _ht = (os.environ.get('ELI_HTTP_TIMEOUT') or '900').strip()
    HTTP_TIMEOUT = int(_ht) if _ht else 900
except Exception:
    HTTP_TIMEOUT = 900  # seconds

KEEP_ALIVE = os.environ.get("ELI_KEEP_ALIVE", "10m")  # keeps model warm in ollama
_SPEAKING = False
_SPEAKING_UNTIL = 0.0   # small tail to avoid capturing the end of TTS
# Spotify launcher (Flatpak/Snap/native) — set in .env as ELI_SPOTIFY_CMD
SPOTIFY_CMD = os.environ.get("ELI_SPOTIFY_CMD", "").strip() or "spotify"

# ----------------------------
# Voice config
# ----------------------------
WAKE = tuple(x.strip().lower() for x in os.environ.get("ELI_WAKE", "computer,eli,hey eli,okay eli").split(",") if x.strip())
ALWAYS_AWAKE = os.environ.get("ELI_ALWAYS_AWAKE", "0") == "1"

SR_TARGET = 16000
CHUNK_MS = int(os.environ.get("ELI_CHUNK_MS", "120"))  # 80–160ms is usually nice

# default: allow ~2.2s of silence before chopping utterance (you can override)
SILENCE_END_MS = int(os.environ.get("ELI_SILENCE_END_MS", "2200"))

_raw_dev = (os.environ.get("ELI_AUDIO_IN") or os.environ.get("ELI_AUDIO_DEVICE") or "").strip()
# Accept numeric index ("6") or name ("pulse"/"pipewire"/"default")
if _raw_dev.isdigit():
    DEVICE = int(_raw_dev)
else:
    DEVICE = _raw_dev
# Never pass empty string to sounddevice ("" matches all -> crash); None is the system default
if DEVICE == "":
    DEVICE = None


def _input_rate(device) -> int:
    """ELI_SR if set, else the microphone's own default rate."""
    if os.environ.get("ELI_SR", "").strip():
        return int(os.environ["ELI_SR"])
    try:
        return int(sd.query_devices(device, "input")["default_samplerate"])
    except Exception:
        return 44100


SR_IN = _input_rate(DEVICE)



DEBUG = os.environ.get("ELI_VOICE_DEBUG", "0") == "1"

RMS_DEBUG = os.environ.get("ELI_RMS_DEBUG","0") == "1"
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


# ----------------------------
# Wake session + stop/resume words
# ----------------------------
# Wake word opens a short "listening window" so you don't need to repeat wake every sentence.
# Stop word pauses listening until you resume with wake+resume.
def _env_int(name: str, default: int) -> int:
    try:
        v = (os.environ.get(name) or "").strip()
        return int(v) if v else int(default)
    except Exception:
        return int(default)

DOC_NUM_PREDICT    = _env_int("ELI_DOC_NUM_PREDICT", 1600)
DOC_NUM_CTX        = _env_int("ELI_DOC_NUM_CTX", 4096)
DOC_MAX_CHARS      = _env_int("ELI_DOC_MAX_CHARS", 35000)
DOC_CONTINUE_TRIES = _env_int("ELI_DOC_CONTINUE_TRIES", 3)
DOC_TAIL_CHARS     = _env_int("ELI_DOC_TAIL_CHARS", 1800)


# ---- ENV HELPERS (moved up so they exist before first use) ----
# ----------------------------------------------------------------

WAKE_SESSION_MS = _env_int('ELI_WAKE_SESSION_MS', 8000)

# --- RULE_INTENT_MEDIA_V2 ---
_LAST_MEDIA_PLAYER = (os.environ.get("ELI_MEDIA_PLAYER","spotify") or "spotify").strip().lower()

def _strip_wake_prefix(spoken: str) -> str:
    # Remove one or MORE wake words at the beginning (Whisper sometimes repeats them).
    try:
        for w in WAKE:
            spoken = re.sub(
                rf"^(?:\s*{re.escape(w)}\s*[,.:;!?\-]*\s*)+",
                "",
                spoken or "",
                flags=re.I,
            )
    except Exception:
        pass
    return (spoken or "").strip()

def _rule_intent_media(spoken_text: str):
    # Deterministic layer: do NOT trust the router for media verbs.
    if not isinstance(spoken_text, str):
        return None
    raw = spoken_text.strip()
    if not raw:
        return None

    s = _strip_wake_prefix(raw).lower()
    # Normalize punctuation to spaces so regexes match more reliably.
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return None

    # Explicit system mute/unmute ONLY.
    if re.search(r"\b(unmute|mute)\b", s):
        return {"action": "mute_toggle", "args": {}}

    wants_pause = re.search(r"\b(pause|paus|stop)\b", s) is not None
    wants_play  = re.search(r"\b(play|resume|continue)\b", s) is not None
    wants_next  = re.search(r"\b(next|skip)\b", s) is not None
    wants_prev  = re.search(r"\b(prev|previous|back)\b", s) is not None

    mentions_spotify = "spotify" in s

    global _LAST_MEDIA_PLAYER
    target_spotify = mentions_spotify or (_LAST_MEDIA_PLAYER == "spotify")

    if target_spotify:
        if wants_pause: return {"action": "spotify", "args": {"command": "pause"}}
        if wants_play:  return {"action": "spotify", "args": {"command": "play"}}
        if wants_next:  return {"action": "spotify", "args": {"command": "next"}}
        if wants_prev:  return {"action": "spotify", "args": {"command": "previous"}}
    # Generic playerctl media controls
    if wants_pause or wants_play:
        return {"action": "media", "args": {"cmd": "play-pause"}}
    if wants_next:
        return {"action": "media", "args": {"cmd": "next"}}
    if wants_prev:
        return {"action": "media", "args": {"cmd": "previous"}}

    return None

def _normalize_intent_media(intent: dict, spoken_text: str):
    # Fix known router failure modes: pause->mute_toggle, pause->noop
    if not isinstance(intent, dict):
        return intent
    action = str(intent.get("action") or "").strip()
    st = (spoken_text or "").lower()

    global _LAST_MEDIA_PLAYER
    if action.startswith("spotify"):
        _LAST_MEDIA_PLAYER = "spotify"
    # If router produced mute_toggle but user said pause/play/etc, override.
    if action == "mute_toggle":
        if re.search(r"\b(pause|paus|play|resume|continue|next|prev|previous|stop)\b", st) or ("spotify" in st):
            forced = _rule_intent_media(spoken_text)
            if forced:
                return forced

    # If router produced noop but user said pause/play/etc, override.
    if action in ("noop", ""):
        forced = _rule_intent_media(spoken_text)
        if forced:
            return forced

    return intent

def _apply_rule_intent_media(intent: dict, spoken_text: str):
    forced = _rule_intent_media(spoken_text)
    if forced:
        return forced
    return _normalize_intent_media(intent, spoken_text)


def _intent_fixups(intent: dict, spoken_text: str) -> dict:
    """Deterministic cleanup of router/local intents to prevent common misroutes."""
    if not isinstance(intent, dict):
        return {"action": "noop", "args": {}}
    action = str(intent.get("action") or "noop").strip()
    args = intent.get("args") or {}
    if not isinstance(args, dict):
        args = {}

    # ---- SCHEMA_COMPAT_V1: normalize common router arg-name drift ----
    if action == "search" and "q" not in args and "query" in args:
        args["q"] = str(args.pop("query") or "").strip()
    if action == "alarm" and "at" not in args and "time" in args:
        args["at"] = str(args.pop("time") or "").strip()
    if action == "read_file":
        if "max_bytes" not in args and "max_lines" in args:
            try:
                ml = int(args.get("max_lines") or 0)
                args["max_bytes"] = max(20000, ml * 200)
            except Exception:
                args["max_bytes"] = 20000


    # ---- SPOTIFY_INTENT_COMPAT_V1 ----
    # Older code/router outputs spotify_resume/spotify_pause/etc.
    # Normalize all of them to builtin action="spotify" with args={"command": ...}
    if action in ("spotify_resume", "spotify_play"):
        action = "spotify"
        args = {"command": "play"}
    elif action in ("spotify_pause",):
        action = "spotify"
        args = {"command": "pause"}
    elif action in ("spotify_next", "spotify_skip"):
        action = "spotify"
        args = {"command": "next"}
    elif action in ("spotify_prev", "spotify_previous", "spotify_back"):
        action = "spotify"
        args = {"command": "previous"}

    # Also accept router variants that used media cmd keys
    if action == "spotify" and isinstance(args, dict):
        if "command" not in args and "cmd" in args:
            args["command"] = str(args.get("cmd") or "").strip().lower()

    st = (spoken_text or "").strip()
    cl = st.lower()

    # 1) Fix app-name key mismatch for open_app
    if action == "open_app":
        # ELI_OPEN_APP_SPAWN_FORCE_v1
        import subprocess
        nm = ""
        try:
            nm = str(args.get("name") or args.get("app") or "").strip().lower()
        except Exception:
            nm = ""
        if nm in ("settings","gnome-control-center","control center","control-centre"):
            subprocess.Popen(["gnome-control-center"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return {"ok": True, "spawned": ["gnome-control-center"]}
        if nm in ("thunderbird","mail","email","e-mail"):
            subprocess.Popen(["thunderbird"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return {"ok": True, "spawned": ["thunderbird"]}

        if "name" not in args:
            if "app_name" in args:
                args = {"name": args.get("app_name")}
            elif "app" in args:
                args = {"name": args.get("app")}
        nm = (args.get("name") or "").strip().lower()
        if nm in ("settings", "control center", "control-center"):
            args["name"] = "settings"

    # 2) Fix macOS hallucinated settings path
    if action == "open_path":
        p = ((_resolve_user_path(args.get("path") or ""))).strip()
        if p.lower() == "/applications/settings.app":
            action, args = "open_app", {"name": "settings"}
        elif p.startswith("~"):
            args["path"] = os.path.expanduser(p)

    # 3) If router opened paraview.org but user likely meant the app
    if action == "open_url":
        u = (args.get("url") or "").lower()
        if "paraview.org" in u and re.search(r"\bparaview\b", cl):
            action, args = "run", {"cmd": "paraview"}

    # 4) Sanitize run command prefix leakage ("run command ...", "command ...")
    if action == "run":
        c = (args.get("cmd") or "").strip()
        c = re.sub(r"^(?:run\s+command|command)\b[ .,:;-]*", "", c, flags=re.I).strip()
        c = re.sub(r"\s+", " ", c)
        args["cmd"] = c
        cwd = args.get("cwd")
        if isinstance(cwd, str) and cwd:
            cwd2 = os.path.expandvars(os.path.expanduser(cwd.strip()))
            home = os.path.expanduser("~")
            if cwd2.startswith("/home/user/"):
                cwd2 = home + cwd2[len("/home/user"):]
            args["cwd"] = cwd2


    # ELI_LISTDIR_NORMALIZE_v1
    if action == "list_dir" and isinstance(args, dict):
        raw = str(args.get("path") or "").strip().lower()
        # strip common STT filler
        raw = re.sub(r"^(list\s+)?files?\s+(in|and)\s+", "", raw).strip()
        raw = re.sub(r"^\.+\s*", "", raw).strip()
        # friendly aliases
        if raw in ("downloads","download","my downloads"):
            args["path"] = os.path.expanduser("~/Downloads")
        elif raw in ("desktop","my desktop"):
            args["path"] = os.path.expanduser("~/Desktop")
        elif raw in ("home","home directory","home folder"):
            args["path"] = os.path.expanduser("~")
        else:
            args["path"] = raw

    # 5) Router emits type_text; map to existing paste_text builtin (mode=type)
    if action == "type_text":
        t = (args.get("text") or "").strip()
        if t:
            t = re.sub(r"^(?:enter\s+)?text\s+mode\b[ .,:;-]*", "", t, flags=re.I)
            t = re.sub(r"^type\s+(?:the\s+following\s+)?", "", t, flags=re.I)
            t = re.sub(r"^the\s+following\s+", "", t, flags=re.I)
        action, args = "paste_text", {"text": t, "mode": "type"}

    # 6) Media controls: if we got noop/chat/open_url-to-spotify-site, force media intent
    if action in ("noop", "", "chat") or (action == "open_url" and "spotify.com" in (args.get("url") or "").lower()):
        if re.search(r"\b(pause|play|resume|continue|next|previous|prev|back|skip|stop)\b", cl) or ("spotify" in cl):
            forced = _rule_intent_media(st)
            if forced:
                return forced

    # 7) Normalize media skip -> next; prefer spotify builtin when configured
    if action == "media":
        cmd0 = (args.get("cmd") or args.get("command") or "").strip().lower()
        if cmd0 == "skip":
            cmd0 = "next"
        if (MEDIA_PLAYER or "").lower() == "spotify" or (_LAST_MEDIA_PLAYER or "").lower() == "spotify" or ("spotify" in cl):
            action, args = "spotify", {"command": ("previous" if cmd0 in ("previous", "prev", "back") else cmd0)}
        else:
            args["cmd"] = cmd0

    intent["action"] = action
    intent["args"] = args
    return intent


# --- MEDIA_DUCK_V1 ---
MEDIA_DUCK = str(os.environ.get("ELI_MEDIA_DUCK", "1")).strip().lower() not in ("0","false","no","off")
MEDIA_PLAYER = (os.environ.get("ELI_MEDIA_PLAYER", "spotify") or "spotify").strip()

_DUCKED_MEDIA = False
_DUCK_TIMER = None
_DUCK_LOCK = threading.Lock()

def _playerctl_run(argv):
    # import subprocess  # FIXPACK: rely on top-level import
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except Exception as e:
        return 1, "", str(e)

def _playerctl_p(*args):
    if MEDIA_PLAYER:
        return _playerctl_run(["playerctl", "-p", MEDIA_PLAYER, *args])
    return _playerctl_run(["playerctl", *args])

def _duck_media_pause():
    # Pause ONLY if it was actually playing; remember we ducked it.
    global _DUCKED_MEDIA
    if not MEDIA_DUCK:
        return
    if _DUCKED_MEDIA:
        return
    rc, out, _ = _playerctl_p("status")
    if rc == 0 and out.lower() == "playing":
        _playerctl_p("pause")
        _DUCKED_MEDIA = True

def _duck_media_resume():
    global _DUCKED_MEDIA
    if not MEDIA_DUCK:
        return
    if not _DUCKED_MEDIA:
        return
    _playerctl_p("play")
    _DUCKED_MEDIA = False

def _duck_schedule_resume(deadline_s: float):
    # Reset timer each time wake window is extended.
    global _DUCK_TIMER
    if not MEDIA_DUCK:
        return
    import time
    with _DUCK_LOCK:
        if _DUCK_TIMER is not None:
            try:
                _DUCK_TIMER.cancel()
            except Exception:
                pass
            _DUCK_TIMER = None
        delay = max(0.0, float(deadline_s) - time.time())
        t = threading.Timer(delay, _duck_media_resume)
        t.daemon = True
        _DUCK_TIMER = t
        t.start()

AUTO_SLEEP_AFTER_COMMAND = os.environ.get("ELI_AUTO_SLEEP_AFTER_COMMAND", "1") == "1"

_WAKE_UNTIL = 0.0
_LISTEN_PAUSED = False

STOP_WORDS = tuple(
    x.strip().lower() for x in os.environ.get(
        "ELI_STOP_WORDS",
        "stop listening,go quiet,sleep,shut up"
    ).split(",") if x.strip()
)

RESUME_WORDS = tuple(
    x.strip().lower() for x in os.environ.get(
        "ELI_RESUME_WORDS",
        "resume,listen,wake up,start listening,come back"
    ).split(",") if x.strip()
)

def _is_stop_cmd(t: str) -> bool:
    tl = (t or "").strip().lower()
    return any(sw == tl or sw in tl for sw in STOP_WORDS)

def _is_resume_cmd(t: str) -> bool:
    tl = (t or "").strip().lower()
    return any(rw == tl or rw in tl for rw in RESUME_WORDS)



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


def _tts_list_voices() -> dict:
    _init_tts()
    eng = _TTS_ENGINE
    voices = []
    try:
        for v in (eng.getProperty("voices") or []):
            voices.append({
                "id": getattr(v, "id", "") or "",
                "name": getattr(v, "name", "") or "",
            })
    except Exception:
        pass
    return {"current": os.environ.get("ELI_TTS_VOICE", ""), "voices": voices, "count": len(voices)}

def _tts_set_voice(target: str) -> dict:
    _init_tts()
    eng = _TTS_ENGINE
    target_l = (target or "").strip().lower()
    if not target_l:
        raise ValueError("empty voice target")
    chosen_id = None
    chosen_name = None
    try:
        for v in (eng.getProperty("voices") or []):
            vid = (getattr(v, "id", "") or "").lower()
            vname = (getattr(v, "name", "") or "").lower()
            if target_l in vid or target_l in vname:
                chosen_id = getattr(v, "id", None)
                chosen_name = getattr(v, "name", None) or target
                break
    except Exception:
        pass
    if not chosen_id:
        raise ValueError(f"Voice not found: {target}")
    try:
        eng.setProperty("voice", chosen_id)
    except Exception:
        # still persist preference; engine may apply on next init
        pass
    os.environ["ELI_TTS_VOICE"] = str(chosen_name)
    try:
        _ensure_dir(MEMORY_DIR)
        TTS_PREF_FILE.write_text(json.dumps({"voice": os.environ["ELI_TTS_VOICE"]}, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return {"voice": os.environ["ELI_TTS_VOICE"], "id": chosen_id}


def _speak_legacy(text: str):
    """
    Speak text aloud. Never fail silently.
    - If ELI_TTS_ENGINE=piper and ELI_PIPER_MODEL is set, try piper.
    - Otherwise fall back to espeak-ng/espeak.
    - Always play with paplay/pw-play/aplay (first found).
    - If ELI_TTS_DEBUG=1, prints commands and stderr.
    """
    try:
        import os, re, subprocess
        from pathlib import Path
        from shutil import which

        t = "" if text is None else str(text)
        # strip common model tokens
        t = re.sub(r"<\|[^\|]*\|>", "", t).replace("<|end|>", "").replace("<|im_end|>", "").strip()
        if not t:
            return

        print(f"[ELI-VOICE] {t}")

        if os.environ.get("ELI_MUTE", "0") == "1":
            return

        env = os.environ.copy()
        sink = (env.get("ELI_OUTPUT_DEVICE") or "").strip()
        if sink:
            env["PULSE_SINK"] = sink

        debug = env.get("ELI_TTS_DEBUG", "0") == "1"
        tmpwav = Path(env.get("ELI_TTS_WAV", "/tmp/eli_tts.wav"))

        def run(cmd, *, input_text=None):
            if debug:
                print("[ELI-TTS] RUN:", cmd)
                if env.get("PULSE_SINK"):
                    print("[ELI-TTS] PULSE_SINK:", env["PULSE_SINK"])
            r = subprocess.run(cmd, input=input_text, text=(input_text is not None),
                               env=env, capture_output=True)
            if r.returncode != 0:
                print(f"[ELI-TTS] rc={r.returncode} cmd={' '.join(map(str,cmd))}")
                if r.stderr:
                    print("[ELI-TTS] stderr:", r.stderr.strip())
            return r

        def play(path: Path) -> bool:
            player = which("paplay") or which("pw-play") or which("aplay")
            if not player:
                print("[ELI-TTS] No audio player found (paplay/pw-play/aplay).")
                return False
            r = run([player, str(path)])
            return r.returncode == 0

        engine = (env.get("ELI_TTS_ENGINE") or "espeak").strip().lower()

        if engine == "piper":
            piper = which("piper")
            model = (env.get("ELI_PIPER_MODEL") or "").strip()
            if piper and model:
                r = run([piper, "--model", model, "--output_file", str(tmpwav)], input_text=t)
                if r.returncode == 0 and tmpwav.exists() and tmpwav.stat().st_size > 44:
                    if play(tmpwav):
                        return
                print("[ELI-TTS] Piper failed/empty -> falling back to espeak.")
            elif debug:
                print("[ELI-TTS] piper selected but missing piper binary or ELI_PIPER_MODEL -> falling back to espeak.")

        espeak = which("espeak-ng") or which("espeak")
        if not espeak:
            print("[ELI-TTS] espeak-ng/espeak not found in PATH.")
            return

        rate = (env.get("ELI_ESPEAK_RATE") or "175").strip()
        voice = (env.get("ELI_ESPEAK_VOICE") or "").strip()
        cmd = [espeak, "-s", rate]
        if voice:
            cmd += ["-v", voice]
        cmd += ["-w", str(tmpwav), t]

        r = run(cmd)
        if r.returncode != 0:
            return
        if not tmpwav.exists() or tmpwav.stat().st_size <= 44:
            print("[ELI-TTS] espeak produced invalid wav:", tmpwav)
            return
        play(tmpwav)

    except Exception as e:
        print("[ELI-TTS] exception:", repr(e))
        return

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
    """
    Allowed executables for sandboxed run().

    Accept BOTH comma-separated and whitespace-separated formats.
    Also include both './x' and 'x' variants so normpath quirks don't brick you.
    """
    import os
    import os.path
    from pathlib import Path as _Path

    raw = (os.environ.get("ELI_ALLOWED_CMDS") or "").strip()
    if not raw:
        return None

    # commas OR spaces
    raw = raw.replace(",", " ")
    parts = [p for p in raw.split() if p]

    allowed = set()

    def add(tok: str):
        if not tok:
            return
        t = str(tok).strip()
        if not t:
            return

        # keep raw
        allowed.add(t)

        # normpath form
        try:
            n = os.path.normpath(t)
            allowed.add(n)
        except Exception:
            n = t

        # add "./" and no-"./" variants
        try:
            if n.startswith("./"):
                allowed.add(n[2:])
            else:
                allowed.add("./" + n)
        except Exception:
            pass

    for p in parts:
        add(p)

    # Always allow venv python in common forms (belt + suspenders)
    add("./.venv/bin/python")
    add(".venv/bin/python")
    try:
        add(str((_Path(__file__).resolve().parent.parent / ".venv/bin/python").resolve()))
    except Exception:
        pass

    return allowed


def _allow_or_block(argv0: str) -> bool:
    """Allow or block executables based on sandbox rules."""
    import os
    
    # FULL CONTROL MODE: allow everything
    if os.environ.get("ELI_FULL_CONTROL", "0") == "1":
        return True
    
    allowed = _allowed_cmds_set()
    if allowed is None:
        return True  # No restrictions
    
    # Wildcard allows everything
    if "*" in allowed:
        return True
    
    return argv0 in allowed
def _run_argv(argv, timeout=30):

    ### ELI_FASTFIX_BUNDLE_V2 ###
    # Normalize timeouts (router sometimes sends None)
    # None/"" => env ELI_RUN_TIMEOUT_SEC (default 120s)
    import os as _os
    if timeout is None or timeout == "":
        try:
            timeout = float(_os.environ.get("ELI_RUN_TIMEOUT_SEC", "120"))
        except Exception:
            timeout = 120.0
    else:
        try:
            timeout = float(timeout)
        except Exception:
            timeout = 120.0


    if not argv:
        return {"ok": False, "error": "empty argv"}
    if not _allow_or_block(argv[0]):

        # --- ALLOW_VENV_PYTHON_V1 ---
        # Normalize doubled venv paths and allow our own venv python binary under the allowlist sandbox.
        try:
            import os
            _v = str(argv[0])
            # collapse accidental duplication
            _v = _v.replace("./.venv/bin/./.venv/bin/python", "./.venv/bin/python")
            _v = _v.replace(".venv/bin/.venv/bin/python", ".venv/bin/python")
            _v = os.path.normpath(_v)
            # allow exactly the project venv python
            _venv_py_rel = os.path.normpath("./.venv/bin/python")
            _venv_py_abs = os.path.normpath(str((Path(__file__).resolve().parent / ".venv/bin/python")))
            if _v in (_venv_py_rel, _venv_py_abs) or _v.endswith("/.venv/bin/python"):
                # overwrite the checked value if it's a simple name
                if isinstance(argv[0], str):
                    argv[0] = _v
                # skip raising
                raise SystemExit("__ELI_ALLOW_VENV_PYTHON_SKIP__")
        except SystemExit as _e:
            if str(_e) == "__ELI_ALLOW_VENV_PYTHON_SKIP__":
                pass
            else:
                raise
        except Exception:
            pass

        # If we didn't early-allow venv python, fall through to the original denial.
        try:
            _ALLOW_VENV_PYTHON
        except NameError:
            _ALLOW_VENV_PYTHON = False
        if not _ALLOW_VENV_PYTHON:
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
    r = _run_argv(["playerctl", "-l"], timeout=30)
    if r.get("ok") and r.get("stdout"):
        players = [p.strip() for p in r["stdout"].splitlines() if p.strip()]
        for p in players:
            if "spotify" in p.lower():
                return p
    return "spotify"

def _spotify_launch():
    """
    Launch Spotify and VERIFY it actually stays running.
    """
    argv = shlex.split(SPOTIFY_CMD)
    if not argv:
        return {"ok": False, "error": "ELI_SPOTIFY_CMD is empty"}

    if not _allow_or_block(argv[0]):
        return {"ok": False, "error": f"command not allowed: {argv[0]} (ELI_ALLOWED_CMDS)"}

    # If using Flatpak, verify the app exists/installed first.
    appid = None
    if len(argv) >= 3 and argv[0] == "flatpak" and argv[1] == "run":
        appid = argv[2]
        chk = subprocess.run(
            ["flatpak", "info", appid],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if chk.returncode != 0:
            return {
                "ok": False,
                "error": f"Flatpak app not installed or not available: {appid}",
                "stderr": (chk.stderr or "")[-2000:],
            }

    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as e:
        return {"ok": False, "error": str(e), "cmd": argv}

    # Give it a moment, then verify it's actually running.
    time.sleep(1.8)

    running = False
    evidence = {}

    # Prefer flatpak ps if we're launching flatpak
    if appid:
        ps = subprocess.run(
            ["flatpak", "ps"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        evidence["flatpak_ps_rc"] = ps.returncode
        evidence["flatpak_ps_tail"] = (ps.stdout or "")[-4000:]
        if ps.returncode == 0 and appid in (ps.stdout or ""):
            running = True
    else:
        # Fallback: check playerctl list (best-effort)
        r = _run_argv(["playerctl", "-l"], timeout=30)
        evidence["playerctl"] = r
        if r.get("ok") and "spotify" in (r.get("stdout","").lower()):
            running = True

    return {
        "ok": bool(running),
        "launched": True,
        "running": bool(running),
        "pid": getattr(proc, "pid", None),
        "cmd": argv,
        "evidence": evidence,
    }


def _spotify_ctl(command: str, auto_launch: bool = True):
    """
    command: play|pause|stop|status|next|previous|play-pause
    """
    player = _spotify_player_name()
    r = _run_argv(["playerctl", "-p", player, command], timeout=30)

    # If play fails because spotify isn't running/registered, optionally launch and retry
    if (not r.get("ok")) and auto_launch and command in {"play", "play-pause"}:
        launch = _spotify_launch()
        time.sleep(2)
        player = _spotify_player_name()
        r2 = _run_argv(["playerctl", "-p", player, command], timeout=30)
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

# ---- BUILTIN: write_note (create a note file) ----
def _write_note_builtin(args: dict) -> dict:
    """Create a note file under ELI_DOC_DIR (default: ./eli_docs)."""
    try:
        title = (args.get("title") or "note").strip()
        content = (args.get("content") or "").strip()
        filename = (args.get("filename") or "").strip()
        open_after = bool(args.get("open_after", False))

        import os, re, time, subprocess
        from pathlib import Path

        root = Path(__file__).resolve().parent
        doc_dir = Path(os.environ.get("ELI_DOC_DIR", str(root / "eli_docs"))).expanduser()
        doc_dir.mkdir(parents=True, exist_ok=True)

        if not filename:
            safe_title = re.sub(r"[^a-zA-Z0-9_\-\.]+", "_", title).strip("_") or "note"
            filename = f"{safe_title}.md"
        if not filename.lower().endswith((".md", ".txt")):
            filename += ".md"

        if not content:
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            content = f"# {title}\n\nCreated: {ts}\n\n"

        path = (doc_dir / filename).resolve()
        doc_dir_resolved = doc_dir.resolve()
        if path != doc_dir_resolved and doc_dir_resolved not in path.parents:
            return {"ok": False, "error": "refusing to write outside ELI_DOC_DIR"}

        path.write_text(content, encoding="utf-8")

        if open_after:
            try:
                subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

        return {"ok": True, "path": str(path), "title": title}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---- BUILTIN: append_note (append to an existing note file) ----
def _append_note_builtin(args: dict) -> dict:
    """Append content to a note under ELI_DOC_DIR."""
    try:
        title = (args.get("title") or "").strip()
        content = (args.get("content") or "").strip()
        filename = (args.get("filename") or "").strip()
        open_after = bool(args.get("open_after", False))

        if not title and not filename:
            return {"ok": False, "error": "append_note: title or filename is required"}
        if not content:
            return {"ok": False, "error": "append_note: content is empty"}

        import os, re, time, subprocess
        from pathlib import Path

        root = Path(__file__).resolve().parent
        doc_dir = Path(os.environ.get("ELI_DOC_DIR", str(root / "eli_docs"))).expanduser()
        doc_dir.mkdir(parents=True, exist_ok=True)

        note_file = None
        if filename:
            note_file = (doc_dir / filename)
        else:
            if title.lower().endswith((".md", ".txt")):
                note_file = (doc_dir / title)
            else:
                for ext in (".md", ".txt"):
                    cand = doc_dir / f"{title}{ext}"
                    if cand.exists():
                        note_file = cand
                        break
                if note_file is None:
                    safe_title = re.sub(r"[^a-zA-Z0-9_\-\.]+", "_", title).strip("_") or "note"
                    note_file = doc_dir / f"{safe_title}.md"

        note_file = note_file.resolve()
        doc_dir_resolved = doc_dir.resolve()
        if note_file != doc_dir_resolved and doc_dir_resolved not in note_file.parents:
            return {"ok": False, "error": "refusing to write outside ELI_DOC_DIR"}

        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        blob = f"\n\n---\n\n{ts}\n\n{content.strip()}\n"

        if note_file.exists():
            prev = note_file.read_text(encoding="utf-8", errors="ignore")
        else:
            prev = f"# {title or note_file.stem}\n"

        note_file.write_text(prev.rstrip() + blob, encoding="utf-8")

        if open_after:
            try:
                subprocess.Popen(["xdg-open", str(note_file)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

        return {"ok": True, "path": str(note_file), "title": title or note_file.stem}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---- BUILTIN: calendar_event (create event via Google Calendar URL) ----
def _calendar_event_builtin(args: dict) -> dict:
    """Open a prefilled Google Calendar event in the browser (handles 'tomorrow', weekdays, 2pm, 16.40pm, etc.)."""
    try:
        import re, urllib.parse, subprocess, os
        from datetime import datetime, date, timedelta

        title = (args.get("title") or "ELI Event").strip()
        date_s = (args.get("date") or args.get("day") or "").strip()
        time_s = (args.get("time") or args.get("at") or "").strip()
        start_s = (args.get("start") or "").strip()
        location = (args.get("location") or "").strip()
        notes = (args.get("notes") or args.get("details") or "").strip()

        dur = args.get("duration_min", None)
        if dur is None:
            dur = args.get("duration", None)
        try:
            duration_min = int(dur) if dur is not None else 30
        except Exception:
            duration_min = 30

        def parse_time(ts: str) -> str:
            if not ts:
                return "09:00"
            t = ts.strip().lower().replace(" ", "")
            t = t.replace(".", ":")
            m = re.match(r'^(\d{1,2})(?::(\d{2}))?(am|pm)?$', t)
            if not m:
                return "09:00"
            hh = int(m.group(1))
            mm = int(m.group(2) or "0")
            ap = m.group(3)
            # If already 13-23, ignore am/pm even if user says nonsense like 16:40pm
            if ap and hh <= 12:
                if ap == "pm" and hh < 12: hh += 12
                if ap == "am" and hh == 12: hh = 0
            hh = max(0, min(23, hh))
            mm = max(0, min(59, mm))
            return f"{hh:02d}:{mm:02d}"

        def parse_date(ds: str) -> str:
            today = date.today()
            if not ds:
                return today.isoformat()
            d = ds.strip().lower()
            wmap = {"monday":0,"tuesday":1,"wednesday":2,"thursday":3,"friday":4,"saturday":5,"sunday":6}
            if d == "today":
                return today.isoformat()
            if d == "tomorrow":
                return (today + timedelta(days=1)).isoformat()
            if d in wmap:
                delta = (wmap[d] - today.weekday()) % 7
                delta = 7 if delta == 0 else delta
                return (today + timedelta(days=delta)).isoformat()
            # ISO date?
            if re.match(r'^\d{4}-\d{2}-\d{2}$', ds.strip()):
                return ds.strip()
            return today.isoformat()

        dt = None
        if start_s:
            # try iso-ish start string
            try:
                dt = datetime.fromisoformat(start_s.replace("Z",""))
            except Exception:
                # salvage "tomorrowT14:00" style
                if "T" in start_s:
                    left, right = start_s.split("T", 1)
                    date_s2 = parse_date(left)
                    time_s2 = parse_time(right)
                    dt = datetime.fromisoformat(f"{date_s2}T{time_s2}")

        if dt is None:
            d_iso = parse_date(date_s)
            t_hm = parse_time(time_s)
            dt = datetime.fromisoformat(f"{d_iso}T{t_hm}")

        end_dt = dt + timedelta(minutes=duration_min)

        def fmt(d: datetime) -> str:
            return d.strftime("%Y%m%dT%H%M%S")

        params = {
            "action": "TEMPLATE",
            "text": title,
            "dates": f"{fmt(dt)}/{fmt(end_dt)}",
        }
        if location:
            params["location"] = location
        if notes:
            params["details"] = notes

        # timezone offset (local)
        import time as _time
        tz_offset = _time.localtime().tm_gmtoff
        tz_sign = "+" if tz_offset >= 0 else "-"
        tz_hours = abs(tz_offset) // 3600
        tz_minutes = (abs(tz_offset) % 3600) // 60
        params["ctz"] = f"UTC{tz_sign}{tz_hours:02d}:{tz_minutes:02d}"

        base_url = "https://calendar.google.com/calendar/render"
        url = f"{base_url}?{urllib.parse.urlencode(params)}"
        subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        return {"ok": True, "title": title, "start": dt.isoformat(), "end": end_dt.isoformat(),
                "duration_min": duration_min, "url": url}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _recall_memory_builtin(args: dict) -> dict:
    """Read recent utterances from ./data/memory/utterances.jsonl (if present)."""
    try:
        import json
        from pathlib import Path

        limit = int(args.get("limit", 20))
        root = Path(__file__).resolve().parent
        memory_log = root / "data" / "memory" / "utterances.jsonl"

        if not memory_log.exists():
            return {"ok": True, "entries": [], "message": "No memory log found"}

        entries = []
        with open(memory_log, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        recent = entries[-limit:] if entries else []
        return {"ok": True, "entries": recent, "count": len(recent), "total": len(entries)}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# Builtin open_app (bypass executor allowlists)
# ----------------------------

_APP_ALIASES = {
    "mail": "thunderbird",
    "email": "thunderbird",
    "e-mail": "thunderbird",
    "thunderbird": "thunderbird",
    "thunderbirds": "thunderbird",
    "thunder birds": "thunderbird",
    "tundra bird": "thunderbird",
    "tundrabird": "thunderbird",
    "browser": "firefox",
    "mozilla": "firefox",
    "firefox": "firefox",
}

def _normalize_app(spoken: str) -> str:
    """Normalize application names using aliases."""
    s = (spoken or "").strip().lower()
    s = " ".join(s.split())
    return _APP_ALIASES.get(s, s)

def _normalize_task(task):
    """Normalize task dict to ensure it has action/args format."""
    if not task or not isinstance(task, dict):
        return task
    
    # If it already has 'action' field, it's already normalized
    if "action" in task:
        return task
    
    # Handle router output format (intent/args)
    if "intent" in task:
        intent = task.get("intent", "")
        args = task.get("args", {})
        if isinstance(intent, str):
            return {"action": intent, "args": args}
        elif isinstance(intent, dict):
            # Intent might already be an action dict
            action = intent.get("action", "")
            if action:
                intent_args = intent.get("args", {})
                return {"action": action, "args": {**intent_args, **args}}
            else:
                # Couldn't determine action, return as-is
                return task
    
    # Default: return as-is
    return task

def _normalize_app(spoken: str) -> str:
    """Normalize application names using aliases."""
    s = (spoken or "").strip().lower()
    s = " ".join(s.split())
    return _APP_ALIASES.get(s, s)


    
    # If it already has 'action' field, it's already normalized
    if "action" in task:
        return task
    
    # Handle router output format (intent/args)
    if "intent" in task:
        intent = task.get("intent", "")
        args = task.get("args", {})
        if isinstance(intent, str):
            return {"action": intent, "args": args}
        elif isinstance(intent, dict):
            # Intent might already be an action dict
            action = intent.get("action", "")
            if action:
                intent_args = intent.get("args", {})
                return {"action": action, "args": {**intent_args, **args}}
            else:
                # Couldn't determine action, return as-is
                return task
    
    # Default: return as-is
    return task
def _normalize_app(spoken: str) -> str:
    """Normalize application names using aliases."""
    s = (spoken or "").strip().lower()
    s = " ".join(s.split())
    return _APP_ALIASES.get(s, s)

def _normalize_task(task):
    """Normalize task dict to ensure it has action/args format."""
    if not task or not isinstance(task, dict):
        return task
    
    # If it already has 'action' field, it's already normalized
    if "action" in task:
        return task
    
    # Handle router output format (intent/args)
    if "intent" in task:
        intent = task.get("intent", "")
        args = task.get("args", {})
        if isinstance(intent, str):
            return {"action": intent, "args": args}
        elif isinstance(intent, dict):
            # Intent might already be an action dict
            action = intent.get("action", "")
            if action:
                intent_args = intent.get("args", {})
                return {"action": action, "args": {**intent_args, **args}}
            else:
                # Couldn't determine action, return as-is
                return task
    
    # Default: return as-is
    return task
def _allowed_apps_set():
    """Return set of allowed apps, or None for no restrictions."""
    import os
    
    # FULL CONTROL MODE: no app restrictions
    if os.environ.get("ELI_FULL_CONTROL", "0") == "1":
        return None
    
    raw = (os.environ.get("ELI_ALLOWED_APPS") or "").strip()
    if not raw:
        return None  # None => allow common safe apps
    return {x.strip().lower() for x in raw.split(",") if x.strip()}

def _open_app_with_timeout(argv, timeout=30):
    # ELI_OPEN_APP_SPAWN_PATCH_v3
    # GUI apps shouldn't be waited on. Spawn + return success unless it exits immediately with error.
    import subprocess
    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True
        )
        try:
            out, err = proc.communicate(timeout=0.7)
            return {"ok": (proc.returncode == 0), "returncode": proc.returncode, "stdout": out, "stderr": err, "argv": argv}
        except subprocess.TimeoutExpired:
            return {"ok": True, "spawned": True, "pid": proc.pid, "argv": argv}
    except Exception as e:
        return {"ok": False, "error": repr(e), "argv": argv}
def _open_app_builtin(app_name: str) -> dict:
    app = _normalize_app(app_name)
    if not app:
        return {"ok": False, "error": "empty app_name"}

    allowed = _allowed_apps_set()
    if allowed is not None and app not in allowed:
        return {"ok": False, "error": f"app not allowed: {app} (set ELI_ALLOWED_APPS)"}

    # Allow per-app override command
    env_key = "ELI_APP_CMD_" + re.sub(r"[^A-Z0-9]+", "_", app.upper())
    override = (os.environ.get(env_key) or "").strip()

    if override:
        argv = shlex.split(override)
    else:
        # sensible defaults
        if app == "thunderbird":
            argv = ["thunderbird"]
        elif app == "firefox":
            argv = ["firefox"]
        elif app == "spotify":
            argv = shlex.split(SPOTIFY_CMD) if SPOTIFY_CMD else ["spotify"]
        else:
            # last resort: try running by name
            argv = [app]

    try:
        return _open_app_with_timeout(argv)
        return {"ok": True, "app": app, "cmd": argv}
    except Exception as e:
        return {"ok": False, "error": str(e), "app": app, "cmd": argv}


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
            temperature: float = 0.0, num_predict: int = 256, num_ctx: int | None = None) -> str:
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
            "num_ctx": int(num_ctx if num_ctx is not None else os.environ.get("ELI_NUM_CTX","2048")),
            "top_p": float(os.environ.get("ELI_TOP_P", "0.9")),
        },
    }
    
    # --- DUMP_OLLAMA_PAYLOAD_V2 ---
    if os.environ.get("ELI_DUMP_OLLAMA_PAYLOAD"):
        try:
            from pathlib import Path as _Path
            import json as _json
            _d = DATA_DIR / "logs" / "ollama"
            _d.mkdir(parents=True, exist_ok=True)
            (_d / "last_payload.json").write_text(_json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    _t("OLLAMA chat start")
    r = HTTP.post(OLLAMA_CHAT, json=payload, timeout=HTTP_TIMEOUT)
    _t("OLLAMA chat end")
    if os.environ.get("ELI_DUMP_OLLAMA_PAYLOAD"):
        try:
            from pathlib import Path as _Path
            import json as _json
            _d = DATA_DIR / "logs" / "ollama"
            _d.mkdir(parents=True, exist_ok=True)
            _resp = {
                "status_code": getattr(r, "status_code", None),
                "text": getattr(r, "text", None),
            }
            (_d / "last_response.json").write_text(_json.dumps(_resp, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    r.raise_for_status()
    return r.json()["message"]["content"]


# ----------------------------
# Router system prompt (autofix)
# ----------------------------
DEFAULT_ROUTER_SYSTEM = r"""
You are a routing engine for a local PC assistant.
Return ONLY strict JSON. No markdown. No commentary. No extra keys.

Schema:
{"action": "<one of the allowed actions>", "args": { ... }}

Allowed actions (MUST match exactly):
append_note, arm_control, calendar_event, change_voice, chat, create_doc,
disarm_control, doc_about, list_dir, math, media, mute_toggle, noop, open_app,
open_path, open_url, paste_text, read_file, recall_memory, run, screen_read,
search, set_voice, spotify, summarize_pdfs, time, type_text, write_note,
timer, alarm, analyze_file, analyze_csv, analyze_vtk, analyze_image

Guidelines:
- If the user asks a question (not an action on the PC), use:
  {"action":"chat","args":{"prompt":"..."}}
- If unclear or nonsense, use {"action":"noop","args":{}}

Args hints (use what’s relevant):
- open_url: {"url":"https://..."}
- search: {"q":"..."}
- open_path: {"path":"/some/path"}
- list_dir: {"path":"...","depth":2}
- read_file: {"path":"...","max_bytes":20000}
- write_note: {"title":"...","content":"...","filename":null,"open_after":false}
- append_note: {"title":"...","content":"..."}
- time: {}
- timer: {"seconds":123,"message":"..."}
- alarm: {"at":"8am","message":"..."}
- calendar_event: {"title":"...","date":"tomorrow","time":"14:00","duration_min":30}
- paste_text: {"text":"...","mode":"paste"}
- type_text: {"text":"..."}   # types into active window
- spotify: {"command":"launch|play|pause|next|prev"}
- media: {"command":"play|pause|next|prev"}
- set_voice/change_voice: {"voice":"..."}  # if supported
- screen_read: {"save_screenshot":true}
- run: {"argv":["cmd","arg1",...]} or {"cmd":"..."} depending on your executor
- analyze_file: {"path":"..."}
- analyze_csv: {"path":"..."}
- analyze_vtk: {"path":"..."}
- analyze_image: {"path":"..."}
"""

# Only define ROUTER_SYSTEM if missing (prevents accidental overwrite)
if "ROUTER_SYSTEM" not in globals():
    ROUTER_SYSTEM = DEFAULT_ROUTER_SYSTEM

def _router_llm(text: str) -> dict:
    _sys = globals().get("ROUTER_SYSTEM", globals().get("DEFAULT_ROUTER_SYSTEM", ""))
    out = _ollama(ROUTER_MODEL, _sys, text, temperature=0.0, num_predict=160)
    return _extract_json(out)

def _chat_llm(text: str) -> str:
    # optional tone bias: drop a style file in eli_voice/style.txt
    style_path = ROOT / "eli_voice" / "style.txt"
    style = ""
    if style_path.exists():
        style = style_path.read_text(encoding="utf-8", errors="ignore").strip()

    owner = eli_config.user_name() or "the person who installed it"
    sysmsg = (
        "You are Eli (Entropic Logical Interpreter).\n"
        f"You are a LOCAL assistant set up by {owner} and running via Ollama on this machine.\n"
        "Never claim you were created by Alibaba Cloud, OpenAI, or any other company - you run on a local model.\n"
        f"If asked who created you: say you are ELI, configured by {owner}.\n"
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
    # ----------------------------
# Definitional vs Search intent guards
# ----------------------------

_DEF_PREFIXES = (
    "what is", "what are", "who is", "who was", "explain", "tell me", "tell me about",
    "teach me", "define", "describe", "give me an overview", "help me understand",
    "i would like to know", "i want to know",
)

_SEARCH_TRIGGERS = (
    "search", "look up", "lookup", "google", "find", "browse", "open web",
    "on the web", "online", "wikipedia", "source", "cite", "citations", "references",
    "latest", "current", "today", "this week", "news",
)

def _is_definitional(tl: str) -> bool:
    tl = (tl or "").strip().lower()
    if any(tl.startswith(p) for p in _DEF_PREFIXES):
        return True
    # spoken pattern: "tell me what X is"
    if ("tell me" in tl and "what" in tl and " is" in tl):
        return True
    # "tell me about X"
    if "tell me about" in tl:
        return True
    # "who is X", "what is X" even with filler words
    if re.match(r"^(what|who|how)\s+(is|are|was|were|do|does)\b", tl):
        return True
    return False

def _explicitly_requests_search(tl: str) -> bool:
    tl = (tl or "").strip().lower()
    return any(k in tl for k in _SEARCH_TRIGGERS)

def _should_search(user_text: str) -> bool:
    tl = (user_text or "").strip().lower()
    # Only search if explicitly requested.
    # Definitional questions default to chat.
    return _explicitly_requests_search(tl) and not _is_definitional(tl)


# ----------------------------
# Wake stripping (robust)
# ----------------------------

def _strip_wake(text: str) -> str:
    """
    Strip repeated leading wake words + trailing punctuation fragments:
    'Eli. Eli, tell me about Tesla' -> 'tell me about Tesla'
    """
    t = (text or "").strip()
    if not t:
        return ""
    for _ in range(3):
        changed = False
        for w in WAKE:
            m = re.match(rf"^{re.escape(w)}(?:[\s\W]+|$)", t, flags=re.IGNORECASE)
            if m:
                t = t[m.end():].strip()
                changed = True
        # strip leading punctuation left behind
        t2 = re.sub(r"^[\s\.,:;!\-]+", "", t).strip()
        if t2 != t:
            t = t2
            changed = True
        if not changed:
            break
    return t


def _local_intent(cmd: str):
    # --- LOCAL_ANALYZE_PDFS_V1 ---
    tl = (cmd or "").strip().lower()
    # Catch common mishears too ("pds", "ebf")
    if ("analy" in tl or "analyse" in tl) and any(k in tl for k in ("pdf", "pdfs", "pds", "ebf")):
        return {"action": "summarize_pdfs", "args": {"path": "data/input", "out": "artifacts/pdf_report_latest.md"}}

    c = (cmd or "").strip()
    if not c:
        return None
    cl = c.lower().strip()

    # --- POWER_VIEW_TO_PARAVIEW_V1 ---
    # Common STT mis-hear: "power view" -> ParaView
    cl = re.sub(r"\bpower\s*view\b", "paraview", cl)

    # Memory recall (quick local)
    if any(phrase in cl for phrase in [
        "what was our last conversation",
        "what did we talk about",
        "what did i say",
        "recall memory",
        "previous conversation"
    ]):
        return {"action": "recall_memory", "args": {"limit": 10}}

    # --- CL_PUNCT_NORMALIZE_V1 ---
    cl = (cl or '').replace("'", "")
    cl = re.sub(r"[.?!,]+", " ", cl)
    cl = re.sub(r"\s+", " ", cl).strip()



    # --- CONTROL_FASTPATH_V1 ---
    # Absolute priority: never let these fall through to fuzzy open/search/read rules or LLM routing.
    # ARM/DISARM (accept noisy STT like "arm conrolpc")
    if ("disarm" in cl) and ("control" in cl or cl.strip() == "disarm" or "autonomous mode off" in cl):
        return {"action": "disarm_control", "args": {}}

    if ("arm" in cl) and ("control" in cl or cl.strip() == "arm" or "autonomous mode on" in cl or "enable control" in cl):
        return {"action": "arm_control", "args": {}}

    # SCREEN READ: any phrase containing screen + (read/what/tell) wins
    if ("screen" in cl) and (("read" in cl) or ("what" in cl) or ("tell me" in cl)):
        return {"action": "screen_read", "args": {}}

    # TYPE TEXT: tolerate punctuation: "type. hello", "type: hello"
    m = re.match(r'^(type|write|enter)[ .,:;-]*\s*(.+)$', cl)
    if m:
        return {"action": "type_text", "args": {"text": m.group(2).strip()}}

    # PRESS KEY: tolerate punctuation: "press. enter"
    m = re.match(r'^press[ .,:;-]*\s*(.+)$', cl)
    if m:
        key = m.group(1).strip().lower()
        if key in {"enter", "return"}:
            key = "Return"
        return {"action": "key_press", "args": {"key": key}}

    # --- ROUTER_PRIORITY_CONTROL_V1 ---

    # --- CALENDAR_OPEN_V1 ---
    # Must beat calendar_event creation for bare "open calendar".
    if cl in {"open calendar", "show calendar", "my calendar", "calendar"}:
        return {"action": "open_url", "args": {"url": "https://calendar.google.com"}}

    # Robust parsing for noisy STT punctuation: "type. hello", "press: enter"
    m = re.match(r'^type[ .,:;-]*\s*(.+)$', cl)
    if m:
        return {"action":"type_text","args":{"text": m.group(1).strip()}}
    m = re.match(r'^press[ .,:;-]*\s*(.+)$', cl)
    if m:
        key = m.group(1).strip().lower()
        if key in {"enter","return"}:
            key = "Return"
        return {"action":"key_press","args":{"key": key}}

    # These must win before any fuzzy open/search/read rules.
    if cl in {"arm control","arm","enable control","autonomous mode on"}:
        return {"action":"arm_control","args":{}}
    if cl in {"disarm control","disarm","disable control","autonomous mode off"}:
        return {"action":"disarm_control","args":{}}

    if cl in {"read my screen","read screen","screen read","what is on my screen","whats on my screen","what's on my screen","tell me what is on my screen"}:
        return {"action":"screen_read","args":{}}

    m = re.match(r'^type\s+(.+)$', cl)
    if m:
        return {"action":"type_text","args":{"text": m.group(1).strip()}}

    m = re.match(r'^press\s+(.+)$', cl)
    if m:
        key = m.group(1).strip()
        if key in {"enter","return"}:
            key = "Return"
        return {"action":"key_press","args":{"key": key}}
    # ---- DEFINITIONS / EXPLANATIONS: default to chat (do NOT search) ----
    if _is_definitional(cl) and not _explicitly_requests_search(cl):
        return {"action": "chat", "args": {"prompt": c}}

    # ---- MAIL / THUNDERBIRD OPEN (local) ----
    # Handles: "mail", "thunderbirds", "open mail", "open application thunderbird", etc.
    if any(k in cl for k in ("mail", "email", "e-mail", "thunderbird", "thunderbirds", "tundra bird")):
        if cl in {"mail", "email", "e-mail", "thunderbird", "thunderbirds", "tundra bird"} or re.search(r"\b(open|launch|start)\b", cl):
            return {"action": "open_app", "args": {"app": "thunderbird"}}
    # ---- SOCIAL (local -> chat, avoid noop) ----
    if re.match(r'^\s*(thanks|thank\s+you|cheers|sound|nice\s+one)\b', cl):
        return {"action": "chat", "args": {"prompt": c}}

    # LOCAL_MATH_AND_TIME_FASTPATH

    # ---- TIME (catch short + salty variants; prevent router mislabeling as timer)
    if cl in {"time", "time?", "time."}:
        return {"action": "time", "args": {}}

    if (re.search(r"\btime\b", cl)
        and re.search(r"\b(what|tell|current|now|fucking|damn)\b", cl)
        and not re.search(r"\b(timer|alarm)\b", cl)):
        return {"action": "time", "args": {}}

    # ---- TYPE_TEXT (local; bypass router) ----
    m = re.match(r'^\s*(?:type|enter|write)\s+(?:the\s+following\s*[:\-]?\s*)?(.+?)\s*$', c, flags=re.IGNORECASE)
    if m:
        return {"action":"type_text","args":{"text": m.group(1)}}

    # ---- MATH (local; avoid browser + router weirdness)
    # multiply 28 by 19
    m = re.match(r'^\s*(?:what\s+is\s+)?multiply\s+(-?\d+(?:\.\d+)?)\s+by\s+(-?\d+(?:\.\d+)?)\s*\??\s*$', cl)
    if m:
        return {"action": "math", "args": {"kind": "binary", "a": m.group(1), "op": "*", "b": m.group(2)}}

    # 28 times 19 / 13 multiplied by 7 / 19 x 27
    m = re.match(r'^\s*(?:what\s+is\s+)?(-?\d+(?:\.\d+)?)\s*(times|x|\*|multiplied\s+by)\s*(-?\d+(?:\.\d+)?)\s*\??\s*$', cl)
    if m:
        return {"action": "math", "args": {"kind": "binary", "a": m.group(1), "op": "*", "b": m.group(3)}}

    # divide A by B
    m = re.match(r'^\s*(?:what\s+is\s+)?divide\s+(-?\d+(?:\.\d+)?)\s+by\s+(-?\d+(?:\.\d+)?)\s*\??\s*$', cl)
    if m:
        return {"action": "math", "args": {"kind": "binary", "a": m.group(1), "op": "/", "b": m.group(2)}}

    # A divided by B
    m = re.match(r'^\s*(?:what\s+is\s+)?(-?\d+(?:\.\d+)?)\s*(?:/|divided\s+by)\s*(-?\d+(?:\.\d+)?)\s*\??\s*$', cl)
    if m:
        return {"action": "math", "args": {"kind": "binary", "a": m.group(1), "op": "/", "b": m.group(2)}}

    # square root of pi / square root of 2
    m = re.match(r'^\s*(?:what\s+is\s+)?(?:the\s+)?square\s+root\s+of\s+([a-z0-9\.\-]+)\s*\??\s*$', cl)
    if m:
        return {"action": "math", "args": {"kind": "sqrt", "x": m.group(1)}}

    # ---- DOC ABOUT (local; keep router out of it)
    m = re.match(r'^\s*(?:create|make)\s+(?:a\s+)?(?:new\s+)?(?:document|doc)\s+about\s+(.+?)\s*[\.\?!]?\s*$', cl)
    if m:
        topic = m.group(1).strip()
        return {"action": "doc_about", "args": {"topic": topic, "doc_type": "md"}}



    # ---- OPEN HOME DIRECTORY (local, deterministic)
    # Handles: "open the home directory", "open home folder", etc.
    if re.search(r"\bopen\b.*\b(home|home directory|home folder)\b", cl):
        return {"action": "open_path", "args": {"path": "~"}}
    # ---- OPEN TERMINAL (deterministic)
    if re.search(r"\bopen\b.*\b(terminal|console)\b", cl):
        return {"action": "open_app", "args": {"name": "gnome-terminal"}}

    # ---- OPEN CALENDAR (deterministic)
    if re.search(r"\bopen\b.*\b(calendar)\b", cl):
        return {"action": "open_app", "args": {"name": "gnome-calendar"}}

    # ---- OPEN THUNDERBIRD / MAIL (deterministic)
    if re.search(r"\bopen\b.*\b(thunderbird|mail)\b", cl):
        return {"action": "open_app", "args": {"name": "thunderbird"}}

    # ---- OPEN PHYSICS FOLDER (project-relative, deterministic)
    if re.search(r"\bopen\b.*\bphysics\b.*\b(folder|directory)\b", cl) or re.fullmatch(r"open physics", cl.strip()):
        return {"action": "open_path", "args": {"path": "physics"}}

    # ---- WHAT COMMANDS ARE AVAILABLE (don’t list /usr/bin, just report allowed list)
    if re.search(r"\b(what commands are available|available commands|list commands)\b", cl):
        return {"action": "list_allowed_cmds", "args": {}}

    # ---- LIST NOTES FROM THIS WEEK (deterministic)
    if re.search(r"\blist\b.*\bnotes\b.*\b(this week|past week|last week)\b", cl):
        return {"action": "list_notes", "args": {"days": 7}}

    # ---- SEARCH (deterministic)
    m_q = re.search(r"\bsearch\s+(for\s+)?(.+)$", cl)
    if m_q:
        q = m_q.group(2).strip()
        if q:
            return {"action": "search", "args": {"q": q}}




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

    # ---- DOC ABOUT (local, bypass router)
    m = re.match(r'^(create|make)\s+(?:a\s+)?(?:document|doc)\s+about\s+(.+)$', cl)
    if m:
        topic = m.group(2).strip().strip("\"'").rstrip(" .!?")
        return {"action": "doc_about", "args": {"topic": topic, "doc_type": "md"}}

    # ---- SIMPLE MATH (local, bypass router/search)
    m = re.search(r'\b(-?\d+(?:\.\d+)?)\s*(times|multiplied\s+by|x)\s*(-?\d+(?:\.\d+)?)\b', cl)
    if m:
        return {"action": "math", "args": {"a": m.group(1), "op": "*", "b": m.group(3)}}

    m = re.search(r'\b(-?\d+(?:\.\d+)?)\s*(divided\s+by)\s*(-?\d+(?:\.\d+)?)\b', cl)
    if m:
        return {"action": "math", "args": {"a": m.group(1), "op": "/", "b": m.group(3)}}

    m = re.search(r'\b(-?\d+(?:\.\d+)?)\s*(plus|\+)\s*(-?\d+(?:\.\d+)?)\b', cl)
    if m:
        return {"action": "math", "args": {"a": m.group(1), "op": "+", "b": m.group(3)}}

    m = re.search(r'\b(-?\d+(?:\.\d+)?)\s*(minus|-)\s*(-?\d+(?:\.\d+)?)\b', cl)
    if m:
        return {"action": "math", "args": {"a": m.group(1), "op": "-", "b": m.group(3)}}

    # ---- SEARCH (supports "search for ...")
    m = re.match(r'^(search|google)\s+(?:for\s+)?(.+)$', cl)
    if m:
        q = m.group(2)
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
        # --- OPEN_DIR_SHORTCUTS_V1 ---
        # Handle common directory phrases without router hallucinating os.path.expanduser("~").
        k = re.sub(r"\b(directory|folder)\b", "", key).strip()
        k = re.sub(r"\s+", " ", k).strip()

        if k in {"downloads", "download"}:
            return {"action": "open_path", "args": {"path": os.path.expanduser("~/Downloads")}}
        if k in {"documents", "document"}:
            return {"action": "open_path", "args": {"path": os.path.expanduser("~/Documents")}}
        if k in {"desktop"}:
            return {"action": "open_path", "args": {"path": os.path.expanduser("~/Desktop")}}
        if k in {"home", "home directory", "my home"}:
            return {"action": "open_path", "args": {"path": os.path.expanduser("~")}}

        # Project shortcuts
        if k in {"eli", "ai_eli", "project", "project root", "ai eli"}:
            return {"action": "open_path", "args": {"path": str(ROOT)}}
        if k in {"data input", "input folder", "pdf input"}:
            return {"action": "open_path", "args": {"path": str(ROOT / "data" / "input")}}


        # common services
        if key in {"youtube", "youtube.com", "www.youtube.com"}:
            return {"action": "open_url", "args": {"url": "https://www.youtube.com"}}
        if key in {"spotify", "spotify.com", "open.spotify.com", "www.spotify.com"}:
            return {"action": "open_url", "args": {"url": "https://open.spotify.com"}}



        # common folders
        if key in {"downloads","download"}:
            return {"action": "open_path", "args": {"path": os.path.expanduser("~/Downloads")}}
        if key in {"documents","document"}:
            return {"action": "open_path", "args": {"path": os.path.expanduser("~/Documents")}}
        if key in {"desktop"}:
            return {"action": "open_path", "args": {"path": os.path.expanduser("~/Desktop")}}
        if key in {"home","home directory"}:
            return {"action": "open_path", "args": {"path": "~"}}
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
        raw = c.split(None, 1)[1].strip().strip("\"'").rstrip(" .!?,")
        k = raw.lower()
        k = re.sub(r"\b(the|my|a)\b\s+", "", k).strip()
        k = re.sub(r"\b(directory|folder)\b", "", k).strip()
        k = re.sub(r"\s+", " ", k).strip()

        if k in {"downloads","download"}:
            raw = os.path.expanduser("~/Downloads")
        elif k in {"documents","document"}:
            raw = os.path.expanduser("~/Documents")
        elif k in {"desktop"}:
            raw = os.path.expanduser("~/Desktop")
        elif k in {"home","home directory"}:
            raw = os.path.expanduser("~")
        elif k in {"data input","input","data input folder","input folder"}:
            raw = str(ROOT / "data" / "input")

        return {"action": "list_dir", "args": {"path": raw, "depth": 2}}
    

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


    # ----------------------------
    # NOTES / FILE READING
    # ----------------------------
    # "write a note about today's meeting"
    m = re.match(r'^(?:write|make)\s+(?:a\s+)?note(?:\s+about\s+(.+))?$', cl)
    if m:
        about = (m.group(1) or "note").strip()
        # create a stable-ish filename title
        title = about.lower()
        title = re.sub(r'\b(today|todays)\b', 'today', title)
        title = re.sub(r'[^a-z0-9]+', '_', title).strip('_')[:64] or "note"
        content = f"# {about}\n\n(Write details here.)\n\nRecorded: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        return {"action": "write_note", "args": {"title": title, "content": content}}

    # "append to my research notes: ..."
    m = re.match(r'^(?:append|add)\s+to\s+(?:my\s+)?(.+?)(?:\s*[:\-]\s*(.*))?$', cl)
    if m and ("note" in m.group(1) or "notes" in m.group(1)):
        target = (m.group(1) or "").strip()
        tail = (m.group(2) or "").strip()
        title = "research_notes" if "research" in target else "notes"
        content = tail or f"(Appended via voice) {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        return {"action": "append_note", "args": {"title": title, "content": content}}

    # "read the file executor.py"
    m = re.match(r'^(?:read|show|open)\s+(?:the\s+)?file\s+(.+)$', cl)
    if m:
        pth = (m.group(1) or "").strip()
        # STT often turns "executor.py" into "executor py"
        pth = re.sub(r'\b([a-zA-Z0-9_\-]+)\s+py\b', r'\1.py', pth)
        pth = pth.replace(" ", "")
        return {"action": "read_file", "args": {"path": pth}}

    # ----------------------------
    # DIRECTORY LISTING
    # ----------------------------
    if (cl.startswith("list files") or cl.startswith("list directory") or cl.startswith("list folder") or "list files in" in cl):
        p = "data" if "data" in cl else ("notes" if "notes" in cl else ("skills" if "skills" in cl else ""))
        if not p:
            # try "in X"
            mm = re.search(r'\bin\s+(.+)$', cl)
            if mm:
                p = mm.group(1).strip()
        if p:
            return {"action": "list_dir", "args": {"path": p}}

    # ----------------------------
    # TIMERS / ALARMS
    # ----------------------------
    # timer: "set a timer for 5 minutes"
    if "timer" in cl:
        mm = re.search(r'(\d+(?:\.\d+)?)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?)\b', cl)
        if mm:
            val = float(mm.group(1))
            unit = mm.group(2)
            seconds = val
            if unit.startswith("min"):
                seconds = val * 60
            elif unit.startswith("hour") or unit.startswith("hr"):
                seconds = val * 3600
            return {"action": "timer", "args": {"seconds": int(seconds)}}

    # alarm: "set an alarm for 11 a.m."
    if "alarm" in cl:
        mm = re.search(r'\b(?:for|at)\s+(.+)$', cl)
        if mm:
            t = mm.group(1).strip().lower()
            # normalize "a m" -> "am", "p m" -> "pm"
            t = re.sub(r'\b(a)\s*m\b', r'\1m', t)
            t = re.sub(r'\b(p)\s*m\b', r'\1m', t)
            # normalize "11 30" -> "11:30"
            t = re.sub(r'^(\d{1,2})\s+(\d{2})\b', r'\1:\2', t)
            t = t.replace(" ", "")
            return {"action": "alarm", "args": {"at": t}}

    # ----------------------------
    # CALENDAR EVENTS
    # ----------------------------
    if "calendar event" in cl or cl.startswith("add calendar") or cl.startswith("add a calendar"):
        date = "tomorrow" if "tomorrow" in cl else ("today" if "today" in cl else None)
        # time: "... at 14:00" / "... at 2pm"
        time_tok = None
        mm = re.search(r'\bat\s+(\S+)$', cl)
        if mm:
            time_tok = mm.group(1).strip().lower()
            time_tok = re.sub(r'\b(a)\s*m\b', r'\1m', time_tok)
            time_tok = re.sub(r'\b(p)\s*m\b', r'\1m', time_tok)
        # title: try "called X" or "named X"
        title = "ELI Event"
        mm = re.search(r'\b(?:called|named)\s+(.+)$', cl)
        if mm:
            title = mm.group(1).strip()
        return {"action": "calendar_event", "args": {"title": title, "date": date, "time": time_tok}}

    # ----------------------------
    # MEMORY RECALL
    # ----------------------------
    if ("what did i say" in cl) or ("what i said" in cl) or ("say earlier" in cl) or ("did i say earlier" in cl):
        return {"action": "recall_memory", "args": {"limit": 20}}

    # ----------------------------
    # VOICE / TTS CONTROL
    # ----------------------------
    if "list voices" in cl or "what voices" in cl:
        return {"action": "list_voices", "args": {}}
    if "change your voice" in cl or "change voice" in cl or "switch voice" in cl:
        return {"action": "change_voice", "args": {}}
    m = re.match(r'^set\s+voice\s+(.+)$', cl)
    if m:
        return {"action": "set_voice", "args": {"voice": m.group(1).strip()}}

    # ----------------------------
    # SKILLS
    # ----------------------------
    m = re.match(r'^save\s+(.+?)\s+as\s+(?:a\s+)?skill$', cl)
    if m:
        name = m.group(1).strip()
        return {"action": "save_skill", "args": {"name": name, "utterance": cmd}}



    # ---- PRESS KEY (robust)
    # Accept: "press enter", "press return", "press tab", "press ctrl+l"
    m = re.match(r'^press\s+(.+)$', cl)
    if m:
        key = m.group(1).strip()
        key = re.sub(r"[.?!,]+$", "", key).strip()
        if key in {"enter", "return"}:
            key = "Return"
        return {"action": "key_press", "args": {"key": key}}
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
    
def _type_text_builtin(text: str) -> dict:
    text = (text or "")
    if not text:
        return {"ok": False, "error": "empty text"}

    sess = (os.environ.get("XDG_SESSION_TYPE") or "").lower().strip()

    if sess == "wayland":
        # wtype types into the focused window on Wayland
        argv = ["wtype", "--", text]
        return _run_argv(argv, timeout=30)

    # X11 fallback
    argv = ["xdotool", "type", "--clearmodifiers", "--delay", "8", text]
    return _run_argv(argv, timeout=30)


# ----------------------------
# Document generation subsystem (long, complete Markdown docs)
# ----------------------------
def _doc_system_prompt() -> str:
    style_path = ROOT / "eli_voice" / "style.txt"
    style = ""
    if style_path.exists():
        style = style_path.read_text(encoding="utf-8", errors="ignore").strip()
    sysmsg = (
        "You are Eli.\n"
        "Write complete, well-structured Markdown documents.\n"
        "Never stop mid-sentence; finish sections cleanly.\n"
        "No URLs.\n"
    )
    if style:
        sysmsg += "\nUser tone preferences:\n" + style[:2000]
    return sysmsg

def _doc_llm(prompt: str) -> str:
    return _ollama(
        CHAT_MODEL,
        _doc_system_prompt(),
        prompt,
        temperature=float(os.environ.get("ELI_DOC_TEMP", "0.25")),
        num_predict=DOC_NUM_PREDICT,
        num_ctx=DOC_NUM_CTX,
    )

def _doc_looks_incomplete(md: str) -> bool:
    md = (md or "").strip()
    if not md:
        return True
    low = md.lower()
    # required structure for "doc about" output
    need = ("## overview", "## key ideas", "## timeline", "## further reading", "## conclusion")
    if any(h not in low for h in need):
        return True
    last = md.splitlines()[-1].strip()
    if last in {"-", "*"}:
        return True
    # crude cutoff detector: ends with alnum but not sentence-ish punctuation
    if re.search(r"[A-Za-z0-9]\s*$", md) and not re.search(r'[.!?\)\]"\'`]\s*$', md):
        return True
    return False

def _doc_complete(topic: str, md: str) -> str:
    md = (md or "").strip()
    for _ in range(max(0, DOC_CONTINUE_TRIES)):
        if len(md) >= DOC_MAX_CHARS:
            break
        if not _doc_looks_incomplete(md):
            break
        tail = md[-DOC_TAIL_CHARS:]
        cont_prompt = (
            f"Continue the Markdown document about {topic} from exactly where it cuts off.\n"
            "Do NOT repeat any text.\n"
            "Finish incomplete bullets and sentences.\n"
            "Ensure final sections end cleanly.\n"
            "No URLs.\n\n"
            f"LAST PART (do not repeat):\n{tail}\n"
        )
        add = (_doc_llm(cont_prompt) or "").strip()
        # if model reprints title header, strip it
        add = re.sub(r"^\s*#\s+.+\n+", "", add)
        if not add:
            break
        md = (md + "\n\n" + add).strip()
    return md[:DOC_MAX_CHARS]

# ----------------------------
# Worker: STT -> intent -> execute
# ----------------------------
def _handle_utterance(audio: np.ndarray, whisper: WhisperModel):
    global _BUSY_UNTIL, _LAST_INTENT, _LAST_DOC_ARGS
    if _STOP_REQUESTED:
        return

    global _MIC_IGNORE_UNTIL
    if time.monotonic() < _MIC_IGNORE_UNTIL:
        if DEBUG:
            print("[SKIP] mic ignored (TTS)")
        return
    t0 = time.perf_counter()
    import subprocess  # ELI_HOTFIX: keep subprocess bound (avoid UnboundLocalError)

    audio16 = _resample_to_16k(audio, SR_IN)
    # condition_on_previous_text=False avoids “bleed” between utterances
    _t("STT transcribe start")
    segments, info = whisper.transcribe(
        audio16,
        vad_filter=True,
        language=WHISPER_LANG,
        beam_size=1,
        temperature=0.0,
        initial_prompt=WHISPER_PROMPT,
        condition_on_previous_text=False,
    )
    _t("STT transcribe end")
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
    global _WAKE_UNTIL, _LISTEN_PAUSED
    now_w = time.monotonic()

    # Wake word opens/refreshes session window
    if has_wake:
        _WAKE_UNTIL = now_w + (WAKE_SESSION_MS / 1000.0)
        # --- MEDIA_DUCK_ON_WAKE_V1 ---
        try:
            if not ALWAYS_AWAKE:
                _duck_media_pause()
                _duck_schedule_resume(_WAKE_UNTIL)
        except Exception:
            pass
    # If paused: only accept wake+resume
    if _LISTEN_PAUSED:
        cmd_peek = _strip_wake(text) if has_wake else (text or "").strip()
        if has_wake and _is_resume_cmd(cmd_peek):
            _LISTEN_PAUSED = False
            _WAKE_UNTIL = now_w + (WAKE_SESSION_MS / 1000.0)
            # --- MEDIA_DUCK_ON_WAKE_V1 ---
            try:
                if not ALWAYS_AWAKE:
                    _duck_media_pause()
                    _duck_schedule_resume(_WAKE_UNTIL)
            except Exception:
                pass
            _speak("Back online.")
        return

    # If not AlwaysAwake: require wake OR active session window
    if (not ALWAYS_AWAKE) and (not has_wake) and (now_w > _WAKE_UNTIL):
        if DEBUG:
            print("[SKIP] no wake/session")
        return

    if DEBUG or ALWAYS_AWAKE or has_wake:
        print(f"[HEARD] {text}")
        ### ELI_SPOTIFY_FASTPATH_V2 ###
        try:
            import os as _os
            _low = str(text).lower().strip()
            # strip wake words and punctuation
            for _w in ("computer", "eli", "hey eli", "okay eli"):
                _low = _low.replace(_w, " ")
            _low = " ".join(_low.split())
            _low = _low.strip(" .,!?:;\"'\n\t")
        
            _map = {
                "next": ("next", "Next song."),
                "next song": ("next", "Next song."),
                "previous": ("previous", "Previous song."),
                "previous song": ("previous", "Previous song."),
                "prev": ("previous", "Previous song."),
                "pause": ("pause", "Paused."),
                "play": ("play", "Playing."),
                "resume": ("play", "Playing."),
                "stop": ("stop", "Stopped."),
            }
            if _low in _map:
                _cmd, _say = _map[_low]
                _spotify_ctl(_cmd, auto_launch=True)
                _speak(_say)
                return
        
            _open = {
                "open home": _os.path.expanduser("~"),
                "open home directory": _os.path.expanduser("~"),
                "open downloads": _os.path.expanduser("~/Downloads"),
                "open download": _os.path.expanduser("~/Downloads"),
                "open desktop": _os.path.expanduser("~/Desktop"),
                "open documents": _os.path.expanduser("~/Documents"),
                "open document": _os.path.expanduser("~/Documents"),
            }
            if _low in _open:
                _run_argv(["xdg-open", _open[_low]], timeout=30)
                _speak("Opened.")
                return
        except Exception:
            pass

        ### ELI_FASTFIX_BUNDLE_V1 ###
        # Fast-path media controls: skips router LLM entirely (cuts latency hard)
        try:
            _txt = str(text).strip().lower()
            _txt = re.sub(r"[^a-z0-9\s]+", " ", _txt)
            _txt = re.sub(r"\s+", " ", _txt).strip()
            if _txt.startswith("computer "):
                _txt = _txt[len("computer "):].strip()
        
            _MEDIA = {
                "next": "next",
                "next song": "next",
                "previous": "previous",
                "previous song": "previous",
                "prev": "previous",
                "pause": "pause",
                "play": "play",
                "resume": "play",
                "stop": "stop",
            }
            if _txt in _MEDIA:
                return {"action": "spotify", "args": {"command": _MEDIA[_txt]}}
        except Exception:
            pass
        # --- FASTDOC intercept: stop "create a document" turning into a 900-word manifesto ---
        try:
            if _fastdoc_should_handle(text):
                path = _fastdoc_create_blank("New Document", "md")
                _speak("Document created.")
                try:
                    # import subprocess  # ELI_HOTFIX: avoid local-shadowing
                    subprocess.Popen(["xdg-open", path])
                except Exception:
                    pass
                return
        except Exception:
            pass

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

    cmd = _strip_wake(text)

    # persist what you said (for 'what did I say earlier' recall)
    _memory_append({
        "ts": time.time(),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "text": text,
        "cmd": cmd,
    })


    # Stop word pauses listening until wake+resume
    if _is_stop_cmd(cmd):
        _LISTEN_PAUSED = True
        _WAKE_UNTIL = 0.0
        _speak("Going quiet.")
        return

    # Optional: auto-sleep after one command (default ON)
    if AUTO_SLEEP_AFTER_COMMAND and (not ALWAYS_AWAKE):
        _WAKE_UNTIL = 0.0

    # --- FULL_CONTROL_ARM_V1 ---
    # Phrase: "activate full control" (after wake word).
    # Arms the executor's allow-any window for 60 seconds and keeps the wake session open.
    if re.search(r"\bactivate\s+full\s+controls?\b", cmd.lower()):
        try:
            _WAKE_UNTIL = now_w + 60.0
            _task = {"action": "arm_control", "args": {"window_sec": 60}}
            print("[INTENT] arm_control {'window_sec': 60}")
            _task = _normalize_task(_task)

            result = execute(_task)
            if log_event:
                _ok = result.get('ok') if isinstance(result, dict) else None
                _err = result.get('error') if isinstance(result, dict) else None
                log_event({'type': 'result', 'action': action, 'ok': _ok, 'error': _err})
            print("[DONE]", result)
            _speak("Activated, full control activated for 60 seconds.")
        except Exception as e:
            print("[DONE] {'ok': False, 'error': %r}" % (str(e),))
            _speak("Error activating full control.")
        return


    # Small correction map for common STT mistakes

    fixes = {

        "nikla tessa": "nikola tesla",

        "nikla tesla": "nikola tesla",

        "tesa": "tesla",

    }

    cl_fix = cmd.lower().strip()

    if cl_fix in fixes:

        cmd = fixes[cl_fix]

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

    # --- DOC_REPAIR: make doc creation deterministic ---

    # If router emits create_doc for a doc request, force it to open and avoid 1-line garbage docs.

    if action == "create_doc" and isinstance(args, dict):

        # default: open created docs

        if args.get("open_after") is False:

            args["open_after"] = True

    

        title = (args.get("title") or "").strip()

        content = (args.get("content") or "").strip()

        # If content is too short, regenerate using the richer doc_about prompt

        if title and len(content) < 200:

            prompt = (

                f"Write a concise but informative document about {title}.\n"

                "Use Markdown with headings.\n"

                "Include: Overview, Key ideas (bullets), Timeline (5-10 bullets), and a short 'Further reading' section.\n"

                "No URLs.\n"

            )

            gen = _doc_llm(prompt)
            args["content"] = _doc_complete(title, gen)

    

        # keep intent consistent

        intent["args"] = args

    # normalize legacy builtin markers
    if action == 'noop' and isinstance(args, dict) and args.get('__builtin') == 'time':
        action, args = 'time', {}
    # ROUTER_CHAT_FORCE_VERBATIM_V3
    # Router can hallucinate an *answer* into args['prompt'].
    # For chat, ALWAYS pass the verbatim user utterance to the chat model.
    if str(action).strip().lower() in ('chat','ask','query'):
        if not isinstance(args, dict):
            args = {}
        args['prompt'] = cmd
    # --- APPLY_RULE_MEDIA_HOOK_V2 ---
    try:
        intent = _apply_rule_intent_media(intent, text)
    except Exception:
        pass
    # V3: deterministic intent fixups (router hallucinations -> corrected)
    intent = _intent_fixups(intent, cmd)
    action = intent.get("action", "noop")
    args   = intent.get("args", {}) or {}
    print(f"[INTENT] {action} {args}")
    if log_event:
        log_event({"type": "intent", "action": action, "args": args, "text": cmd})


    # --- INTENT_FIX_PDF_READFILE_TO_ANALYZER_V2 ---
    # Router sometimes tries read_file on PDFs (binary) or hallucinates placeholder paths.
    # Use the built-in summarize_pdfs on data/input instead.
    if action == "read_file":
        _p = ((_resolve_user_path(args.get("path") or ""))).strip()
        _lp = _p.lower()
        if (
            _lp.endswith('.pdf')
            or _lp in ('path/to/file.pdf', '/path/to/file.pdf')
            or 'os.path.expanduser("~")/' in _lp
        ):
            action = "summarize_pdfs"
            args = {"path": "data/input"}
            intent["action"] = action
            intent["args"] = args
            print(f"[INTENT-FIX] {action} {args}")

        # --- OPEN_APP_ARGS_NORMALIZE_V1 ---
    # Router sometimes emits open_app with {"cmd": "..."} instead of {"name": "..."}.
    if action == "open_app" and isinstance(args, dict):
        n = args.get("name")
        if not (isinstance(n, str) and n.strip()):
            for k in ("cmd", "app_name", "app", "application", "program"):
                v = args.get(k)
                if isinstance(v, str) and v.strip():
                    args["name"] = v.strip()
                    break

    # --- FULL_CONTROL_PHRASE_V1 ---
    # "computer activate full control" (punctuation ignored) arms control for 60s.
    try:
        _u_raw = (cmd or "") if isinstance(cmd, str) else ""
        _u_norm = re.sub(r"[^a-z0-9]+", " ", _u_raw.lower()).strip()
        if ("activate full control" in _u_norm) or ("full control activate" in _u_norm):
            action = "arm_control"
            args = {"window_sec": 60}
    except Exception:
        pass

    # --- INTENT_FIX_PDF_ANALYZE_V1 ---
    # If the user says "analyze PDFs" but the router chooses list_dir, upgrade it to a real analysis run.
    try:
        _u = (cmd or "").lower() if isinstance(cmd, str) else ""
        if action == "list_dir" and ("pdf" in _u) and ("analy" in _u or "scan" in _u or "read" in _u):
            action = "summarize_pdfs"
            args = {"path": "data/input"}
            print(f"[INTENT-FIX] {action} {args}")
    except Exception:
        pass

    
    # --- ELI_FORCE_OPEN_PARAVIEW_V1 ---
    # Router sometimes punts (noop) on "open the application ParaView".
    # If the utterance clearly requests ParaView, force open_app.
    try:
        if action == "noop" and re.search(r"\bopen\b.*\b(para\s*view|paraview)\b", cl):
            action = "open_app"
            args = {"name": "paraview"}
            intent = {"action": action, "args": args}
    except Exception:
        pass


    # ELI_FORCE_OPEN_PARAVIEW_V2: deterministic local fix (bypass LLM) for "open Paraview" utterances
    try:
        _u = (cmd or "").lower()
        if ("paraview" in _u) or ("para view" in _u):
            if ("open" in _u) or ("launch" in _u) or ("start" in _u):
                action = "open_app"
                args = {"name": "paraview"}
                print(f"[INTENT-FIX] {action} {args}  # ELI_FORCE_OPEN_PARAVIEW_V2")
    except Exception:
        pass

# ---- fallback_noop_to_chat: if router can't classify, treat as normal chat ----
    if action == "noop" and cmd.strip():
        action = "chat"
        args = {"prompt": cmd}
        # --- APPLY_RULE_MEDIA_HOOK_V2 ---
        try:
            intent = _apply_rule_intent_media(intent, text)
        except Exception:
            pass
        print(f"[INTENT] fallback->chat {args}")

    # BUILTIN_MATH_SPEAK

    # If router returns noop with a computed result, speak it instead of silently succeeding.
    if action == "noop" and isinstance(args, dict) and "result" in args and len(args) <= 2:
        res = args.get("result")
        _speak(str(res))
        print(f"[DONE] {{'ok': True, 'action': 'math', 'result': {res!r}}}")
        return

    # Local math action: compute + speak (bypass executor)
    if action == "math":
        try:
            from decimal import Decimal, InvalidOperation, getcontext
            import math as _math

            getcontext().prec = 50

            def _num(v: str) -> Decimal:
                return Decimal(str(v).strip())

            def _fmt_dec(d: Decimal) -> str:
                # integer?
                if d == d.to_integral_value():
                    return str(int(d))
                # 12-ish significant digits, no scientific notation if possible
                s = format(d.normalize(), "f")
                if "." in s:
                    s = s.rstrip("0").rstrip(".")
                # cap length to keep TTS sane
                return s[:32]

            kind = "binary"
            if isinstance(args, dict):
                kind = (args.get("kind") or "binary").strip().lower()

            if kind == "sqrt":
                x = (args.get("x") if isinstance(args, dict) else "") or ""
                xl = str(x).strip().lower()
                if xl == "pi":
                    val = _math.sqrt(_math.pi)
                    out = f"{val:.12f}".rstrip("0").rstrip(".")
                elif xl == "e":
                    val = _math.sqrt(_math.e)
                    out = f"{val:.12f}".rstrip("0").rstrip(".")
                else:
                    dx = _num(xl)
                    # Decimal sqrt (Newton) for better precision than float
                    if dx < 0:
                        raise ValueError("sqrt of negative")
                    guess = dx / 2 if dx != 0 else Decimal(0)
                    if guess == 0:
                        out = "0"
                    else:
                        for _ in range(40):
                            guess = (guess + dx / guess) / 2
                        out = _fmt_dec(guess)

                _speak(out)
                print(f"[DONE] {{'ok': True, 'action': 'math', 'result': {out!r}}}")
                return

            # binary ops
            if not isinstance(args, dict):
                raise ValueError("math args missing")

            a = _num(args.get("a", "0"))
            b = _num(args.get("b", "0"))
            op = (args.get("op") or "*").strip()

            if op == "*":
                r = a * b
            elif op == "/":
                if b == 0:
                    raise ZeroDivisionError("division by zero")
                r = a / b
            elif op == "+":
                r = a + b
            elif op == "-":
                r = a - b
            else:
                raise ValueError(f"unknown op: {op}")

            out = _fmt_dec(r)
            _speak(out)
            print(f"[DONE] {{'ok': True, 'action': 'math', 'result': {out!r}}}")
            return

        except Exception as e:
            print(f"[DONE] {{'ok': False, 'action': 'math', 'error': {str(e)!r}}}")
            _speak("Math error.")
            return


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
        intent["args"] = {"name": app, "app": app, "app_name": app}
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


    # ---- BUILTIN: write_note ----
    if action == "write_note":
        result = _write_note_builtin(args if isinstance(args, dict) else {})
        print(f"[DONE] {result}")
        _speak("Note written." if result.get("ok") else "There was an error writing the note.")
        return

    # ---- BUILTIN: append_note ----
    if action == "append_note":
        result = _append_note_builtin(args if isinstance(args, dict) else {})
        print(f"[DONE] {result}")
        _speak("Note appended." if result.get("ok") else "There was an error appending to the note.")
        return

    # ---- BUILTIN: calendar_event ----
    if action == "calendar_event":
        result = _calendar_event_builtin(args if isinstance(args, dict) else {})
        print(f"[DONE] {result}")
        _speak("Calendar event created." if result.get("ok") else "There was an error creating the calendar event.")
        return

    # ---- BUILTIN: recall_memory ----
    if action == "recall_memory":
        result = _recall_memory_builtin(args if isinstance(args, dict) else {})
        print(f"[DONE] {result}")
        # Speak the results
        if result.get("ok"):
            entries = result.get("entries", [])
            if not entries:
                _speak("I don't have any memory of previous conversations.")
            elif len(entries) == 1:
                entry = entries[0]
                text = entry.get("text", "").strip()
                if text:
                    _speak(f"You said: {text[:100]}{'...' if len(text) > 100 else ''}")
            else:
                _speak(f"Here are the last {len(entries)} things you said:")
                for i, entry in enumerate(entries[-3:], 1):
                    text = entry.get("text", "").strip()
                    if text:
                        short_text = text[:80] + "..." if len(text) > 80 else text
                        _speak(f"{i}. {short_text}")
        return

    # Built-in actions (bypass executor allowlist)
    if isinstance(args, dict) and args.get("__builtin") == "time":
        now = time.strftime("%H:%M:%S")
        _speak(f"It's {now}.")
        print(f"[DONE] {{'ok': True, 'action': 'time', 'time': now}}")
        return
        
            # ---- BUILTIN: spotify (bypass executor & NO SHELL) ----
    if action == "spotify":
        cmd0 = (args.get("command") or "").lower().strip()

        if cmd0 in {"launch", "open", "start"}:
            res = _spotify_launch()
            print(f"[DONE] {res}")
            _speak("Opening Spotify." if res.get("ok") else "Could not open Spotify.")
            return

        if cmd0 in {"play", "resume"}:
            res = _spotify_ctl("play", auto_launch=True)
            print(f"[DONE] {res}")
            _speak("Playing Spotify." if res.get("ok") else "Could not control Spotify.")
            return

        if cmd0 == "pause":
            res = _spotify_ctl("pause", auto_launch=False)
            print(f"[DONE] {res}")
            _speak("Paused Spotify." if res.get("ok") else "Could not pause Spotify.")
            return

        if cmd0 == "stop":
            res = _spotify_ctl("stop", auto_launch=False)
            print(f"[DONE] {res}")
            _speak("Stopped Spotify." if res.get("ok") else "Could not stop Spotify.")
            return

        if cmd0 in {"next", "skip"}:
            res = _spotify_ctl("next", auto_launch=False)
            print(f"[DONE] {res}")
            _speak("Next song." if res.get("ok") else "Could not skip.")
            return

        if cmd0 in {"previous", "prev", "back"}:
            res = _spotify_ctl("previous", auto_launch=False)
            print(f"[DONE] {res}")
            _speak("Previous song." if res.get("ok") else "Could not go back.")
            return

        res = {"ok": False, "error": f"unknown spotify command: {cmd0!r}"}
        print(f"[DONE] {res}")
        _speak("I didn't understand the Spotify command.")
        return
    # ---- end spotify ----





    # ---- BUILTIN: open_path (bypass executor path allowlist) ----
    if action == "open_path":
        try:
            path = "~"
            if isinstance(args, dict):
                path = (args.get("path") or "~").strip() or "~"

            expanded = os.path.expandvars(os.path.expanduser(path))
            # --- HOME_USER_FIX_V2 ---
            # Router sometimes hallucinates /home/user. Map it to the real $HOME.
            if expanded.startswith("/home/user/"):
                expanded = os.path.join(os.path.expanduser("~"), expanded[len("/home/user/"):])
            # --- HOME_ALIAS_FIX_V1 ---
            # Whisper/router sometimes invents os.path.expanduser("~"). Map it to the real home.
            expanded = re.sub(r'^os.path.expanduser("~")(?=/|$)', os.path.expanduser('~'), expanded)
            expanded = re.sub(r'^/home/USER(?=/|$)', os.path.expanduser('~'), expanded)
            target = expanded
            try:
                target = str(Path(expanded).resolve())
            except Exception:
                pass

            # --- OPEN_PATH_EXISTS_CHECK_V1 ---


            # Auto-reroute 'settings' or 'control center' phrases to GNOME Settings


            try:


                base = str(target).strip().lower()


            except Exception:


                base = ''


            if base in ('settings','setting','system settings','control center','control-centre','control_center','gnome-control-center','gnome-control-centre'):


                try:


                    import subprocess


                    subprocess.Popen(['gnome-control-center'])


                    res = {'ok': True, 'spawned': ['gnome-control-center']}


                    print(f"[DONE] {res}")


                    return res


                except Exception as e:


                    res = {'ok': False, 'error': f'open_settings failed: {e}'}


                    print(f"[DONE] {res}")


                    return res


            if not os.path.exists(target):


                res = {'ok': False, 'error': f'open_path: path does not exist: {target}'}


                print(f"[DONE] {res}")


                _speak("That path doesn't exist.")


                return



            subprocess.Popen(
                ["xdg-open", target],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            res = {"ok": True, "path": target}
            print(f"[DONE] {res}")
            _speak("Opened.")
        except Exception as e:
            res = {"ok": False, "error": str(e)}
            print(f"[DONE] {res}")
            _speak("Could not open that path.")
        return

    # ---- BUILTIN: doc_about (TEMP DISABLED: syntax repair) ----

    if action == "doc_about":

        return {"ok": False, "error": "doc_about disabled temporarily (syntax repair)"}


    # ---- BUILTIN: screen_read (screenshot -> OCR -> summarize/readout) ----
    if action == "screen_read":
        try:

            from shutil import which
            from pathlib import Path as _Path
            import time as _time

            mode = "full"
            out_rel = "artifacts/screen_read_latest.md"
            if isinstance(args, dict):
                mode = (args.get("mode") or mode).strip().lower() or mode
                out_rel = (args.get("out") or out_rel).strip() or out_rel

            screens_dir = (ROOT / "data" / "screens").resolve()
            screens_dir.mkdir(parents=True, exist_ok=True)

            ts = _time.strftime("%Y%m%d_%H%M%S")
            shot = screens_dir / f"screen_{ts}.png"
            base = screens_dir / f"screen_{ts}"   # no suffix; tesseract adds .txt
            out_p = (ROOT / out_rel).resolve() if not _Path(out_rel).is_absolute() else _Path(out_rel).resolve()

            art_root = (ROOT / "artifacts").resolve()
            if not str(out_p).startswith(str(art_root)):
                res = {"ok": False, "error": "screen_read: output must be under ./artifacts", "output": str(out_p)}
                print(f"[DONE] {res}")
                _speak("Output must be under artifacts.")
                return

            def have(cmd): return which(cmd) is not None

            # Screenshot (Wayland grim/slurp, else gnome-screenshot, else ImageMagick import)
            if mode == "region" and have("slurp") and have("grim"):
                reg = subprocess.check_output(["slurp"]).decode().strip()
                subprocess.check_call(['gnome-screenshot','-a','-f', str(shot)])
            elif have("grim"):
                subprocess.check_call(['gnome-screenshot','-f', str(shot)])
            elif have("gnome-screenshot"):
                subprocess.check_call(["gnome-screenshot", "-f", str(shot)])
            elif have("import"):
                subprocess.check_call(["import", "-window", "root", str(shot)])
            else:
                res = {"ok": False, "error": "screen_read: no screenshot tool found (need grim/gnome-screenshot/import)"}
                print(f"[DONE] {res}")
                _speak("No screenshot tool installed.")
                return

            if not have("tesseract"):
                res = {"ok": False, "error": "screen_read: tesseract not installed"}
                print(f"[DONE] {res}")
                _speak("Tesseract is not installed.")
                return

            subprocess.check_call(
                ["tesseract", str(shot), str(base), "-l", "eng"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )

            txt_path = _Path(str(base) + ".txt")
            ocr_text = txt_path.read_text(encoding="utf-8", errors="ignore").strip()

            if not ocr_text:
                res = {"ok": True, "note": "OCR produced empty text", "screenshot": str(shot)}
                print(f"[DONE] {res}")
                _speak("OCR got nothing readable.")
                return

            prompt = (
                "You are reading OCR text captured from the user's current screen.\n"
                "Do three things:\n"
                "1) Give a 5-10 bullet summary of what's on screen.\n"
                "2) Extract any actionable items (buttons/menus/forms) you can infer.\n"
                "3) Quote the most important 3-8 short lines verbatim (max 20 words each).\n\n"
                f"OCR TEXT:\n{ocr_text}"
            )
            summary = _chat_llm(prompt).strip()

            out_p.parent.mkdir(parents=True, exist_ok=True)
            out_p.write_text(summary + "\n", encoding="utf-8")

            res = {"ok": True, "output": str(out_p), "screenshot": str(shot)}
            print(f"[DONE] {res}")
            _speak("Screen summary written.")
        except Exception as e:
            res = {"ok": False, "error": str(e)}
            print(f"[DONE] {res}")
            _speak("There was an error reading the screen.")
        return

# ---- BUILTIN: summarize_pdfs (summarize PDFs via cache/extract, write artifact) ----
    if action == "summarize_pdfs":
        try:
            in_dir = "data/input"
            out_rel = "artifacts/pdf_summary_latest.md"
            if isinstance(args, dict):
                in_dir = (args.get("path") or in_dir).strip() or in_dir
                out_rel = (args.get("out") or out_rel).strip() or out_rel

            in_p = (ROOT / in_dir).resolve() if not Path(in_dir).is_absolute() else Path(in_dir).resolve()
            out_p = (ROOT / out_rel).resolve() if not Path(out_rel).is_absolute() else Path(out_rel).resolve()

            data_root = (ROOT / "data").resolve()
            art_root  = (ROOT / "artifacts").resolve()
            cache_dir = (ROOT / "data" / "cache").resolve()

            if not str(in_p).startswith(str(data_root)):
                res = {"ok": False, "error": "summarize_pdfs: input must be under ./data", "input": str(in_p)}
                print(f"[DONE] {res}")
                _speak("Input folder must be under data.")
                return
            if not str(out_p).startswith(str(art_root)):
                res = {"ok": False, "error": "summarize_pdfs: output must be under ./artifacts", "output": str(out_p)}
                print(f"[DONE] {res}")
                _speak("Output must be under artifacts.")
                return

            pdfs = sorted(in_p.rglob("*.pdf"))
            if not pdfs:
                res = {"ok": False, "error": "summarize_pdfs: no PDFs found", "input": str(in_p)}
                print(f"[DONE] {res}")
                _speak("No PDFs found.")
                return

            def load_text_for_pdf(fp: Path) -> str:
                cache_txt = cache_dir / (fp.stem + ".txt")
                if cache_txt.exists():
                    return cache_txt.read_text(encoding="utf-8", errors="ignore")
                try:
                    from pypdf import PdfReader
                    r = PdfReader(str(fp))
                    parts = []
                    for pg in r.pages:
                        try:
                            parts.append(pg.extract_text() or "")
                        except Exception:
                            parts.append("")
                    return "\n".join(parts)
                except Exception:
                    return ""

            def chunk_text(s: str, n: int = 9000):
                s = s or ""
                return [s[i:i+n] for i in range(0, len(s), n)] if s else [""]

            per_doc_summaries = []
            for fp in pdfs:
                raw = load_text_for_pdf(fp)
                chunks = chunk_text(raw, 9000)

                chunk_sums = []
                # cap chunks to prevent runaway LLM cost/time
                for idx, ch in enumerate(chunks[:10], 1):
                    prompt = (
                        f"Summarize this excerpt from '{fp.name}'.\n"
                        "Return bullet points only.\n"
                        "Focus on: key concepts and symbols, core equations or arguments, assumptions, claims/predictions, contradictions/placeholders.\n\n"
                        f"EXCERPT {idx}/{min(len(chunks),10)}:\n{ch}"
                    )
                    chunk_sums.append(_chat_llm(prompt).strip())

                prompt2 = (
                    f"Combine these bullets into ONE accurate structured summary of '{fp.name}'.\n"
                    "Format exactly:\n"
                    f"### {fp.name}\n"
                    "- Purpose: ...\n"
                    "- Key concepts/symbols: ...\n"
                    "- Core methods/equations: ...\n"
                    "- Claims/predictions: ...\n"
                    "- Open issues/ambiguities: ...\n\n"
                    + "\n\n".join(chunk_sums)
                )
                doc_sum = _chat_llm(prompt2).strip()
                per_doc_summaries.append(doc_sum)

            prompt3 = (
                "You are synthesizing the content of several PDFs.\n"
                "Using the per-document summaries below, produce a coherent global synthesis.\n\n"
                "Required sections:\n"
                "## One-paragraph overview\n"
                "## Key concepts and how they relate\n"
                "## Core methods, equations or arguments\n"
                "## Claims, results and testable predictions\n"
                "## Internal contradictions / unresolved placeholders / version conflicts\n"
                "## Next best 5 steps (minimal, concrete)\n\n"
                "Per-document summaries:\n"
                + "\n\n".join(per_doc_summaries)
            )
            global_sum = _chat_llm(prompt3).strip()

            out_p.parent.mkdir(parents=True, exist_ok=True)
            out_p.write_text(global_sum + "\n", encoding="utf-8")

            res = {"ok": True, "output": str(out_p), "pdfs": len(pdfs)}
            print(f"[DONE] {res}")
            _speak(f"PDF summary written to {out_p.name}.")
        except Exception as e:
            res = {"ok": False, "error": str(e)}
            print(f"[DONE] {res}")
            _speak("There was an error summarizing the PDFs.")
        return


# ---- BUILTIN: math (local compute) ----
    if action == "math":
        try:
            a = float(args.get("a"))
            b = float(args.get("b"))
            op = (args.get("op") or "*").strip()

            if op == "+": y = a + b
            elif op == "-": y = a - b
            elif op == "*": y = a * b
            elif op == "/": y = a / b
            else: raise ValueError(f"Unknown op: {op}")

            # pretty formatting: integers as ints
            if abs(y - round(y)) < 1e-12:
                out = str(int(round(y)))
            else:
                out = f"{y:.10g}"

            _speak(out)
            print(f"[DONE] {{'ok': True, 'action': 'math', 'result': {out!r}}}")
        except Exception as e:
            print(f"[DONE] {{'ok': False, 'error': {str(e)!r}}}")
            _speak("Math error.")
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
        ms = _env_int('ELI_ACTION_IGNORE_MS', 900)
    except Exception:
        ms = 900
    _BUSY_UNTIL = max(_BUSY_UNTIL, time.monotonic() + (ms/1000.0))
    # --- EXECUTE_USES_ACTION_ARGS_V1 ---
    # Always execute the post-fix action/args (router intent may be stale).
    _task = intent
    try:
        if isinstance(_task, dict):
            _task = dict(_task)
            _task["action"] = action
            if isinstance(args, dict):
                _task.update(args)          # flattened style
                _task["args"] = dict(args)  # nested style
        else:
            _task = {"action": action, **(args if isinstance(args, dict) else {})}
    except Exception:
        _task = {"action": action, **(args if isinstance(args, dict) else {})}
    # --- CONTROL_ARM_GATE_V1 ---
    global CONTROL_ARMED
    if action == "arm_control":
        CONTROL_ARMED = True
        try: _speak("Control armed.")
        except Exception: pass
        return {"ok": True, "action": "arm_control", "armed": True}
    if action == "disarm_control":
        CONTROL_ARMED = False
        try: _speak("Control disarmed.")
        except Exception: pass
        return {"ok": True, "action": "disarm_control", "armed": False}


    # VOICE / TTS controls are local (not routed through executor)
    if action in {"list_voices", "change_voice"}:
        try:
            info = _tts_list_voices()
            if action == "change_voice":
                voices = info.get("voices") or []
                cur = (os.environ.get("ELI_TTS_VOICE") or "").lower()
                if voices:
                    idx = 0
                    for i, v in enumerate(voices):
                        if cur and cur in (v.get("name","").lower()):
                            idx = (i + 1) % len(voices)
                            break
                    chosen = voices[idx].get("name") or voices[idx].get("id") or ""
                    if chosen:
                        _tts_set_voice(chosen)
                        try: _speak(f"Voice set to {chosen}.")
                        except Exception: pass
                        return {"ok": True, "voice": chosen, **info}
            # list_voices
            try:
                _speak(f"I have {int(info.get('count') or 0)} voices available.")
            except Exception:
                pass
            return {"ok": True, **info}
        except Exception as e:
            return {"ok": False, "error": str(e), "action": action}

    # ELI_DISPATCH_FIXPACK_20251231_v2

    # NOTE: This block assumes locals `action` (str) and `args` (dict) exist in this dispatcher.

    # It is intentionally placed at dispatcher scope (NOT in intent normalizers).


    import re as _re


    # Best-effort: recover last utterance text (current spoken_text if present; else tail MEMORY_LOG)

    _utt = ""

    try:

        _utt = str(spoken_text or "")

    except Exception:

        _utt = ""

    if not _utt:

        try:

            import os as _os, json as _json

            with open(MEMORY_LOG, "rb") as _f:

                _f.seek(0, _os.SEEK_END)

                _sz = _f.tell()

                _f.seek(max(0, _sz - 4096))

                _chunk = _f.read().decode("utf-8", "ignore")

            _last = _chunk.strip().splitlines()[-1]

            _utt = (_json.loads(_last).get("text","") or "")

        except Exception:

            _utt = ""


    _utt_low = _utt.lower()


    # Normalize args

    if not isinstance(args, dict):

        args = {}


    # ---- Cancel alarm/timer -> cancel_alarm action ----

    if _re.search(r"\b(cancel|stop|clear)\b.*\b(alarm|timer)s?\b", _utt_low):

        action = "cancel_alarm"

        args = {}


    # ---- Voice target salvage (change_voice -> set_voice; strip 'to') ----

    if action in ("set_voice", "change_voice"):

        v = str(args.get("voice") or args.get("name") or "").strip()

        if not v:

            mm = _re.search(r"\b(?:set|change)\s+voice\s+(?:to\s+)?([A-Za-z0-9_-]+)\b", _utt, flags=_re.I)

            if mm:

                v = mm.group(1)

        v = _re.sub(r"^\s*(?:to|voice)\s+", "", v, flags=_re.I).strip()

        if v:

            args["voice"] = v

        if action == "change_voice":

            action = "set_voice"


    # ---- Alarm time normalization: 7:30am / 8am / 7.30 a.m. -> HH:MM 24h ----

    if action == "alarm":

        at = str(args.get("at") or args.get("time") or "").strip()

        mm = _re.match(r"^\s*(\d{1,2})(?:[:\.](\d{2}))?\s*(a\.?m\.?|p\.?m\.?)\s*$", at, flags=_re.I)

        if mm:

            hh = int(mm.group(1))

            mi = int(mm.group(2) or "0")

            ampm = mm.group(3).lower()

            if hh == 12:

                hh = 0

            if "p" in ampm:

                hh += 12

            args["at"] = f"{hh:02d}:{mi:02d}"


    # ---- Calendar time inference if router dropped it ----

    if action == "calendar_event" and not str(args.get("time") or "").strip():

        mm = _re.search(r"\b(?:at|for)\s+(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)\b", _utt, flags=_re.I)

        if mm:

            hh = int(mm.group(1))

            mi = int(mm.group(2) or "0")

            ampm = mm.group(3).lower()

            if hh == 12:

                hh = 0

            if "p" in ampm:

                hh += 12

            args["time"] = f"{hh:02d}:{mi:02d}"


    # ---- run handler (argv/cmd) ----

    if action == "run":

        import os as _os

        argv = args.get("argv") or []

        cmd  = (args.get("cmd") or "").strip()

        tout = args.get("timeout")

        # strip common STT junk

        cmd = _re.sub(r"^(?:run\s+)?(?:the\s+)?command\b[ .,:;-]*", "", cmd, flags=_re.I).strip()

        try:

            timeout = float(tout) if tout not in (None,"") else float(_os.environ.get("ELI_RUN_TIMEOUT_SEC","120"))

        except Exception:

            timeout = float(_os.environ.get("ELI_RUN_TIMEOUT_SEC","120"))

        if argv:

            return _run_argv(argv, timeout=timeout)

        if cmd:

            return _run_argv(["bash","-lc", cmd], timeout=timeout)

        return {"ok": False, "error": "run: missing argv/cmd", "args": args}


    if action == "set_voice":
        try:
            target = str(args.get("voice") or args.get("name") or args.get("id") or "").strip()
            if not target:
                return {"ok": False, "error": "set_voice requires a voice name or id"}
            info = _tts_set_voice(target)
            try: _speak(f"Voice set to {info.get('voice', target)}.")
            except Exception: pass
            return {"ok": True, **info}
        except Exception as e:
            return {"ok": False, "error": str(e), "action": action}

    # Block UI-control actions unless armed (you can disable via ELI_REQUIRE_ARM=0)
    if REQUIRE_ARM and (not CONTROL_ARMED) and action in {"type_text","key_press","paste_text"}:
        return {"ok": False, "error": f"control not armed for action: {action}"}

    _task = _normalize_task(_task)


    result = execute(_task)

    _set_busy(_env_int('ELI_ACTION_IGNORE_MS', 900))
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
    if sd is None:
        raise SystemExit(f"Voice needs a working audio input (sounddevice + PortAudio): {_SD_ERROR}")
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
            except Exception as e:
                import traceback
                print("[UTT-ERR]", repr(e))
                traceback.print_exc()
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
                    x = audio_q.get(timeout=30.0)
                except queue.Empty:
                    continue

                now_m = time.monotonic()
                if now_m < _MIC_IGNORE_UNTIL or now_m < _BUSY_UNTIL:
                    continue
                now_m = time.monotonic()
                if now_m < _MIC_IGNORE_UNTIL or now_m < _BUSY_UNTIL:
                    continue
                r = _rms(x)
                if DEBUG and RMS_DEBUG:
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
        try:
            pool.shutdown(wait=True, cancel_futures=True)
        except KeyboardInterrupt:
            # Don't throw a traceback just because you hit Ctrl+C again.
            pool.shutdown(wait=False, cancel_futures=True)
            print('[ELI] stopped.')
            return

# === ELI_TTS_PATCH_V1 ===
# Force TTS to ALWAYS produce real audio via espeak-ng -> paplay.
# Routes to sink using PULSE_SINK = $ELI_OUTPUT_DEVICE when provided.

import tempfile
import subprocess
import os

def _eli_set_pulse_sink():
    sink = (os.environ.get("ELI_OUTPUT_DEVICE") or "").strip()
    if sink:
        os.environ["PULSE_SINK"] = sink

def _eli_tts_echo(_text: str) -> None:
    # Always show what ELI *tries* to say, even if audio routing is cursed.
    try:
        if os.environ.get("ELI_TTS_ECHO", "1") != "0":
            print(f"[ELI-SAY] {_text}", flush=True)
        if os.environ.get("ELI_TTS_LOG", "1") != "0":
            from pathlib import Path
            import json
            from datetime import datetime
            root = Path(__file__).resolve().parent
            logp = root / "data" / "logs" / "tts.jsonl"
            logp.parent.mkdir(parents=True, exist_ok=True)
            rec = {"ts": datetime.now().isoformat(timespec="seconds"), "text": _text}
            with open(logp, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass

### ELI_SPEAK_REPLACED_V1 ###
def _speak(text: str, *args, **kwargs):
    """Speak arbitrarily long text by chunking + sanitizing to avoid TTS silent failures."""
    import re as _re

    if text is None:
        return
    text = str(text)

    # Strip model junk tokens
    text = text.replace("<|end|>", "").replace("<|", "").replace("|>", "")

    # Remove/replace fenced code blocks (TTS engines often choke on them)
    text = _re.sub(r"```.*?```", " [code omitted] ", text, flags=_re.DOTALL)

    # Normalize whitespace
    text = _re.sub(r"[ \t]+", " ", text)
    text = _re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return

    # Chunk by sentence-ish boundaries, capped by char length
    MAX_CHARS = 350
    parts = _re.split(r"(?<=[.!?])\s+", text)
    buf = ""
    chunks = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if len(buf) + len(part) + 1 <= MAX_CHARS:
            buf = (buf + " " + part).strip()
        else:
            if buf:
                chunks.append(buf)
            # hard-split very long parts
            while len(part) > MAX_CHARS:
                chunks.append(part[:MAX_CHARS])
                part = part[MAX_CHARS:]
            buf = part
    if buf:
        chunks.append(buf)

    for c in chunks:
        _speak_raw(c, *args, **kwargs)


def _speak_raw(text: str) -> None:
    """Speak + ALWAYS echo transcript to terminal."""
    try:
        import os, subprocess, json
        from pathlib import Path
        from datetime import datetime
        t = ("" if text is None else str(text)).strip()
        if not t:
            return
        print(f"[ELI-SAY] {t}", flush=True)
        if os.environ.get("ELI_TTS_LOG", "1") != "0":
            try:
                root = Path(__file__).resolve().parent
                logp = root / "data" / "logs" / "tts.jsonl"
                logp.parent.mkdir(parents=True, exist_ok=True)
                rec = {"ts": datetime.now().isoformat(timespec="seconds"), "text": t}
                logp.open("a", encoding="utf-8").write(json.dumps(rec, ensure_ascii=False)+"\n")
            except Exception:
                pass
        if len(t.split()) > int(os.environ.get("ELI_TTS_MAX_WORDS", "80")):
            return
        if os.environ.get("ELI_MUTE", "0") == "1":
            return
        env = os.environ.copy()
        sink = env.get("ELI_OUTPUT_DEVICE", "").strip()
        if sink:
            env["PULSE_SINK"] = sink
        import tempfile
        tmpwav = Path(tempfile.gettempdir()) / "eli_tts.wav"
        engine = env.get("ELI_TTS_ENGINE", "espeak").strip().lower()
        if engine == "piper":
            model = os.path.expanduser(env.get("ELI_PIPER_MODEL", "").strip()
                                       or str(ROOT / "eli_tools" / "voices" / "en_US-amy-medium.onnx"))
            if Path(model).exists():
                piper_bin = os.environ.get("ELI_PIPER_BIN") or "piper"
                _t("TTS piper start")
                subprocess.run([piper_bin, "--model", model, "--output_file", str(tmpwav)], input=t, text=True, env=env)
                _t("TTS piper end")
                subprocess.Popen(["paplay",str(tmpwav)],env=env)
                return
        voice = env.get("ELI_ESPEAK_VOICE", "").strip()
        rate  = env.get("ELI_ESPEAK_RATE", "175").strip()
        cmd = ["espeak-ng","-s",rate]
        if voice: cmd += ["-v",voice]
        cmd += ["-w",str(tmpwav),t]
        subprocess.run(cmd,env=env)
        subprocess.Popen(["paplay",str(tmpwav)],env=env)
    except Exception:
        return
def _eli_norm_cmd0(cmd0: str) -> str:
    import os
    if not isinstance(cmd0, str):
        return ""
    cmd0 = cmd0.strip()
    if not cmd0:
        return ""
    cmd0 = os.path.expanduser(cmd0)

    # Dedup common hallucinated doubling
    cmd0 = cmd0.replace("./.venv/bin/./.venv/bin/python", "./.venv/bin/python")
    cmd0 = cmd0.replace("./.venv/bin/.venv/bin/python", "./.venv/bin/python")
    cmd0 = cmd0.replace(".venv/bin/./.venv/bin/python", ".venv/bin/python")
    cmd0 = cmd0.replace(".venv/bin/.venv/bin/python", ".venv/bin/python")

    # Normalize "./x" => "x"
    return os.path.normpath(cmd0)






if __name__ == "__main__":
    main()
