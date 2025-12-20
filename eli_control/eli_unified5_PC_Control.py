#!/usr/bin/env python3
import os, sys, json, re
from pathlib import Path

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

# Single-model by default (you can still set a dedicated router model if you want)
CHAT_MODEL   = os.environ.get("ELI_CHAT_MODEL")   or os.environ.get("ELI_MODEL") or os.environ.get("OLLAMA_MODEL")
ROUTER_MODEL = os.environ.get("ELI_ROUTER_MODEL") or CHAT_MODEL

if not CHAT_MODEL:
    raise RuntimeError("No model configured. Set ELI_MODEL (or OLLAMA_MODEL).")

# ----------------------------
# Voice config
# ----------------------------
WAKE = tuple(x.strip().lower() for x in os.environ.get("ELI_WAKE", "eli,hey eli,okay eli").split(",") if x.strip())
ALWAYS_AWAKE = os.environ.get("ELI_ALWAYS_AWAKE", "1") == "1"

SR_TARGET = 16000
SR_IN = int(os.environ.get("ELI_SR", "44100"))
CHUNK_MS = int(os.environ.get("ELI_CHUNK_MS", "200"))
MAX_UTTER_SEC = float(os.environ.get("ELI_MAX_UTTER_SEC", "12"))
SILENCE_END_MS = int(os.environ.get("ELI_SILENCE_END_MS", "700"))

DEVICE = os.environ.get("ELI_AUDIO_IN", "").strip()
DEVICE = int(DEVICE) if DEVICE else None

DEBUG = os.environ.get("ELI_VOICE_DEBUG", "0") == "1"

# Whisper config
WHISPER_SIZE = os.environ.get("ELI_WHISPER", "base")
WHISPER_DEVICE = os.environ.get("ELI_WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE = os.environ.get("ELI_WHISPER_COMPUTE", "int8")
WHISPER_LANG = os.environ.get("ELI_WHISPER_LANG", "en")

# ----------------------------
# Router system prompt (LLM returns strict JSON intent)
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
    """Best-effort notification; never crash voice loop."""
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

def _ollama(model: str, system: str, user: str, temperature: float = 0.0, num_predict: int = 256) -> str:
    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "options": {
            "temperature": float(temperature),
            "num_predict": int(num_predict),
            "num_ctx": int(os.environ.get("ELI_NUM_CTX", "2048")),
            "top_p": float(os.environ.get("ELI_TOP_P", "0.9")),
        },
    }
    r = requests.post(OLLAMA_CHAT, json=payload, timeout=120)
    r.raise_for_status()
    return r.json()["message"]["content"]

def _router(text: str) -> dict:
    out = _ollama(ROUTER_MODEL, ROUTER_SYSTEM, text, temperature=0.0, num_predict=220)
    return _extract_json(out)

def _chat(text: str) -> str:
    sysmsg = (
        "You are Eli. Be concise, practical, and honest.\n"
        "If the user asks to DO something on this PC, propose a concrete command/action."
    )
    return _ollama(CHAT_MODEL, sysmsg, text, temperature=float(os.environ.get("ELI_CHAT_TEMP", "0.4")), num_predict=320)

def _has_wake(text: str) -> bool:
    t = (text or "").lower().strip()
    return any(t.startswith(w + " ") or t == w for w in WAKE)

def _strip_wake(text: str) -> str:
    t = (text or "").strip()
    tl = t.lower()
    for w in WAKE:
        if tl.startswith(w + " "):
            return t[len(w) + 1 :].strip()
        if tl == w:
            return ""
    return t

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
    start_thr = max(0.02, noise * 1.8)
    stop_thr  = max(0.015, noise * 1.2)

    # --- env overrides for thresholds ---
    _st = os.environ.get("ELI_START_THR", "").strip()
    _sp = os.environ.get("ELI_STOP_THR", "").strip()
    if _st:
        start_thr = float(_st)
    if _sp:
        stop_thr = float(_sp)
    if stop_thr >= start_thr:
        stop_thr = max(0.0, start_thr * 0.75)

    if DEBUG:
        print(f"[CAL] noise_rms={noise:.6f} start_thr={start_thr:.6f} stop_thr={stop_thr:.6f}")

    SILENCE_CHUNKS_TO_END = max(1, int(np.ceil(SILENCE_END_MS / CHUNK_MS)))
    MIN_UTTER_CHUNKS = max(2, int(np.ceil(350 / CHUNK_MS)))  # 350ms min

    # --- ONE source of truth for max utterance length ---
    # If ELI_MAX_UTTER_MS is set, it overrides ELI_MAX_UTTER_SEC.
    _ms = os.environ.get("ELI_MAX_UTTER_MS", "").strip()
    if _ms:
        max_chunks = max(3, int(np.ceil(int(_ms) / CHUNK_MS)))
    else:
        max_chunks = max(3, int(np.ceil(MAX_UTTER_SEC * 1000 / CHUNK_MS)))

    if DEBUG:
        print(f"[CAL] silence_chunks={SILENCE_CHUNKS_TO_END} min_chunks={MIN_UTTER_CHUNKS} max_chunks={max_chunks}")

    started = False
    silent = 0
    buf = []

    frames_per_chunk = int(SR_IN * CHUNK_MS / 1000)

    try:
        while True:
            x = sd.rec(frames_per_chunk, samplerate=SR_IN, channels=1, dtype="float32", device=DEVICE)
            sd.wait()
            x = x.reshape(-1)

            r = _rms(x)
            if DEBUG:
                print(f"[RMS] {r:.5f} started={started} silent={silent} len={len(buf)}")

            if not started:
                if r >= start_thr:
                    started = True
                    silent = 0
                    buf = [x]
                continue

            buf.append(x)

            if r < stop_thr:
                silent += 1
            else:
                silent = 0

            # keep recording until enough silence OR max duration
            if silent < SILENCE_CHUNKS_TO_END and len(buf) < max_chunks:
                continue

            audio = np.concatenate(buf, axis=0).astype(np.float32, copy=False)
            started = False
            silent = 0
            buf = []

            # too short → ignore
            if len(audio) < int(MIN_UTTER_CHUNKS * frames_per_chunk):
                if DEBUG:
                    print("[SKIP] too short")
                continue

            # ---- transcribe utterance ----
            audio16 = _resample_to_16k(audio, SR_IN)
            segments, info = whisper.transcribe(audio16, vad_filter=True, language=WHISPER_LANG, beam_size=1)
            text = " ".join(s.text.strip() for s in segments).strip()
            if not text:
                continue

            print(f"[HEARD] {text}")

            if not ALWAYS_AWAKE and not _has_wake(text):
                if DEBUG:
                    print("[SKIP] no wake word")
                continue

            cmd = _strip_wake(text)
            if not cmd:
                continue

            intent = _router(cmd)
            action = intent.get("action", "noop")
            args = intent.get("args", {}) or {}
            print(f"[INTENT] {action} {args}")

            if action == "chat":
                reply = _chat(args.get("prompt") or cmd)
                print(reply)
                continue

            result = execute(intent)
            print(f"[DONE] {result}")

            if not result.get("ok", True):
                _notify("ELI error", result.get("error", ""))
            else:
                if action in {"timer", "alarm", "calendar_event", "write_note"}:
                    _notify("ELI", f"{action} set")

    except KeyboardInterrupt:
        print("\n[ELI] stopped.")
        return

if __name__ == "__main__":
    main()
