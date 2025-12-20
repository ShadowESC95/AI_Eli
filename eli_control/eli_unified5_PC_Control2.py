#!/usr/bin/env python3
import os, sys, json, re, time, queue, threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

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

DEVICE = os.environ.get("ELI_AUDIO_IN", "").strip()
DEVICE = int(DEVICE) if DEVICE else None

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

# ----------------------------
# TTS (pyttsx3)
# ----------------------------
_TTS_ENGINE = None

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
    text = (text or "").strip()
    if not text:
        return
    # always print transcript
    print(f"[ELI-VOICE] {text}")
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
    out = _ollama(ROUTER_MODEL, ROUTER_SYSTEM, text, temperature=0.0, num_predict=220)
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
    t = (text or "").lower().strip()
    return any(t.startswith(w + " ") or t == w for w in WAKE)

def _strip_wake(text: str) -> str:
    t  = (text or "").strip()
    tl = t.lower()
    for w in WAKE:
        if tl.startswith(w + " "):
            return t[len(w) + 1 :].strip()
        if tl == w:
            return ""
    return t

# ----------------------------
# Local fast-path parser
# ----------------------------
def _local_intent(cmd: str):
    c  = (cmd or "").strip()
    cl = c.lower().strip()

    # search ...
    m = re.match(r'^(search|google)\s+(.+)$', cl)
    if m:
        return {"action": "search", "args": {"q": c.split(None, 1)[1]}}

    # open path ...
    m = re.match(r'^(open|open\s+path)\s+(.+)$', cl)
    if m:
        return {"action": "open_path", "args": {"path": c.split(None, 1)[1]}}

    # list dir ...
    m = re.match(r'^(list|ls|dir)\s+(.+)$', cl)
    if m:
        return {"action": "list_dir", "args": {"path": c.split(None, 1)[1], "depth": 2}}

    # read file ...
    m = re.match(r'^(read|cat)\s+(.+)$', cl)
    if m:
        return {"action": "read_file", "args": {"path": c.split(None, 1)[1]}}

    # run command ...
    m = re.match(r'^(run)\s+(.+)$', cl)
    if m:
        return {"action": "run", "args": {"cmd": c.split(None, 1)[1], "cwd": str(ROOT), "timeout": 120}}

    # timer N seconds/minutes
    m = re.match(r'^timer\s+(\d+)\s*(s|sec|secs|seconds|m|min|mins|minutes)?\s*(.*)$', cl)
    if m:
        n    = int(m.group(1))
        unit = (m.group(2) or "seconds")
        msg  = (m.group(3) or "").strip() or "timer"
        if unit.startswith("m"):
            n *= 60
        return {"action": "timer", "args": {"seconds": n, "message": msg}}

    return None

# ----------------------------
# Audio IO
# ----------------------------
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

    print(f"[HEARD] {text}")

    if not ALWAYS_AWAKE and not _has_wake(text):
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
    print(f"[INTENT] {action} {args}")

    if action == "chat":
        reply = _chat_llm(args.get("prompt") or cmd)
        _speak(reply)
        t3 = time.perf_counter()
        if DEBUG:
            print(f"[LAT] stt={t1-t0:.2f}s parse={t2-t1:.2f}s llm+chat={t3-t2:.2f}s total={t3-t0:.2f}s")
        return

    t_llm = time.perf_counter()
    result = execute(intent)
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
        summary = "Command executed."

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
        print("\n[ELI] stopped.")
    finally:
        pool.shutdown(wait=False)

if __name__ == "__main__":
    main()

