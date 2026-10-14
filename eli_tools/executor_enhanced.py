# eli_tools/executor_enhanced.py
from __future__ import annotations

from typing import Any, Dict, Optional, List, Tuple
from pathlib import Path
import os
import re
import json

# Document generator
from eli_tools import config as eli_config
from eli_tools.advanced_doc_generator import AdvancedDocumentGenerator
import time
import hashlib
import subprocess

import requests


import sys
import signal
import datetime
# -------------------- OLLAMA WARM LOAD HELPERS --------------------
def _ollama_http_post_json(url: str, payload: dict, timeout_s: int = 30):
    """
    Minimal JSON POST helper using stdlib only.
    Returns: (ok: bool, status_code: int|None, data: dict|str|None, err: str|None)
    """
    try:
        import json
        import urllib.request
        import urllib.error
    except Exception as e:
        return (False, None, None, f"stdlib_import_error: {e!r}")

    body = None
    try:
        body = json.dumps(payload).encode("utf-8")
    except Exception as e:
        return (False, None, None, f"json_encode_error: {e!r}")

    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            status = getattr(resp, "status", None) or 200
            raw = resp.read()
            try:
                txt = raw.decode("utf-8", errors="ignore")
            except Exception:
                txt = ""
            try:
                data = json.loads(txt) if txt else {}
            except Exception:
                data = txt
            return (True, status, data, None)
    except urllib.error.HTTPError as e:
        try:
            raw = e.read()
            txt = raw.decode("utf-8", errors="ignore")
        except Exception:
            txt = ""
        return (False, getattr(e, "code", None), txt, f"HTTPError: {e!r}")
    except Exception as e:
        return (False, None, None, f"urlopen_error: {e!r}")


def _ollama_warm_load(model: str, ollama_host: str) -> bool:
    """
    Best-effort warm-load so /api/ps can report digest for lockdown verification.
    Uses /api/chat (non-stream) with a tiny prompt.
    Returns True if the request likely caused the model to load (or is already loadable),
    False otherwise.
    """
    try:
        model = (model or "").strip()
        if not model:
            return False
        host = (ollama_host or "http://localhost:11434").rstrip("/")
        url = host + "/api/chat"

        payload = {
            "model": model,
            "stream": False,
            "messages": [{"role": "user", "content": "ping"}],
            "options": {"num_predict": 1},
        }

        ok, status, data, err = _ollama_http_post_json(url, payload, timeout_s=30)
        if not ok:
            return False

        # If we got a response object at all, the model was at least resolvable.
        # Ollama typically loads the model to answer, so this is a decent warm-load signal.
        if isinstance(data, dict):
            if "message" in data or "done" in data or "created_at" in data:
                return True
        return True
    except Exception:
        return False
# ------------------ END OLLAMA WARM LOAD HELPERS ------------------
# ----------------------------
# Core normalization utilities
# ----------------------------

def _ollama_warm_load(model: str, ollama_host: str) -> bool:
    """
    Best-effort warm load so /api/ps can report digest for lockdown verification.
    Uses /api/chat (non-stream) with a tiny prompt.
    """
    try:
        import requests
    except Exception:
        return False
    try:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "."}],
            "stream": False,
        }
        r = requests.post(f"{ollama_host.rstrip('/')}/api/chat", json=payload, timeout=60)
        return r.status_code == 200
    except Exception:
        return False

def _normalize_result(res: object) -> Dict[str, Any]:
    """
    Guarantee GUI/voice always has:
      - res['ok'] (bool)
      - res['content'] (str)
      - res['response'] (str)
    """
    if not isinstance(res, dict):
        txt = "" if res is None else str(res)
        return {"ok": False, "error": "handler_returned_non_dict", "content": txt, "response": txt}

    if "ok" not in res:
        res["ok"] = False

    if "response" in res and "content" not in res:
        res["content"] = res.get("response")
    if "content" in res and "response" not in res:
        res["response"] = res.get("content")

    if "content" not in res or res.get("content") is None:
        fallback = res.get("message") or res.get("error") or ""
        res["content"] = str(fallback)
    if "response" not in res or res.get("response") is None:
        res["response"] = str(res.get("content") or "")

    res["content"] = "" if res["content"] is None else str(res["content"])
    res["response"] = "" if res["response"] is None else str(res["response"])
    return res


def _strip_ollama_artifacts(s: str) -> str:
    s = (s or "")
    s = s.replace("<|\nend\n", "").replace("<|end|>", "").replace("<|end|", "")
    s = re.sub(r"\s+$", "", s)
    return s.strip()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _run(argv: List[str], timeout: int = 15) -> Dict[str, Any]:
    try:
        p = subprocess.run(argv, timeout=timeout, capture_output=True, text=True, check=False)
        ok = (p.returncode == 0)
        msg = "OK" if ok else "Command failed"
        return {
            "ok": ok,
            "returncode": p.returncode,
            "stdout": p.stdout,
            "stderr": p.stderr,
            "cmd": argv,
            "content": msg,
            "response": msg,
        }
    except Exception as e:
        msg = "Command error"
        return {
            "ok": False,
            "returncode": 1,
            "stdout": "",
            "stderr": repr(e),
            "cmd": argv,
            "content": msg,
            "response": msg,
            "error": repr(e),
        }


# ----------------------------
# Config / state
# ----------------------------

OLLAMA_HOST = eli_config.ollama_base()
DEFAULT_CHAT_MODEL = eli_config.chat_model()
ARTIFACTS_DIR = eli_config.artifacts_dir()

# Enumerated actions for capability_registry bootstrap
SUPPORTED_ACTIONS = ['CHAT', 'CHECK_CHRONAL_ALIGNMENT', 'CREATE_DOCUMENT', 'DATA_FABRICATOR', 'DOC_GENERATE', 'HELP', 'LIST_CAPABILITIES', 'MEMORY_RECALL', 'MEMORY_STORE', 'OPEN_APP', 'OPEN_AUDIO_SETTINGS', 'OPEN_BROWSER', 'OPEN_COMMUNICATION_HUB', 'OPEN_FILE_SYSTEM', 'OPEN_MEDIA_HUB', 'OPEN_NETWORK_BROWSER', 'OPEN_URL', 'PERSONA_LOCK_CLEAR', 'PERSONA_LOCK_SET', 'PERSONA_LOCK_STATUS', 'PROACTIVE_START', 'PROACTIVE_STATUS', 'PROACTIVE_STOP', 'READ_FILE', 'RUN_CMD', 'TIME', 'WRITE_NOTE']


STATE_PATH = eli_config.state_file()

# Short-term conversation continuity
MAX_HISTORY_MESSAGES = int(os.environ.get("ELI_MAX_HISTORY_MESSAGES", "32"))

# Long-term memory store (simple deterministic archive, no embeddings)
MEMORY_PATH = eli_config.memory_file()

# Lock behavior: if true, refuse CHAT when verification fails
LOCK_ENFORCED = os.environ.get("ELI_LOCK_ENFORCED", "1").strip() not in ("0", "false", "False", "no", "NO")


def _load_state() -> Dict[str, Any]:
    try:
        if STATE_PATH.exists():
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_state(st: Dict[str, Any]) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(st, indent=2), encoding="utf-8")
    except Exception:
        pass


def _state_get_history(st: Dict[str, Any]) -> List[Dict[str, str]]:
    h = st.get("chat_history")
    if not isinstance(h, list):
        return []
    out: List[Dict[str, str]] = []
    for m in h:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = m.get("content")
        if role in ("user", "assistant") and isinstance(content, str):
            out.append({"role": role, "content": content})
    return out


def _state_append_history(st: Dict[str, Any], user_msg: str, assistant_msg: str) -> None:
    h = _state_get_history(st)
    h.append({"role": "user", "content": user_msg})
    h.append({"role": "assistant", "content": assistant_msg})
    if len(h) > MAX_HISTORY_MESSAGES:
        h = h[-MAX_HISTORY_MESSAGES:]
    st["chat_history"] = h
    st["updated_at"] = time.time()


# ----------------------------
# Persona lock + checksum verification
# ----------------------------

def _ollama_ps() -> Dict[str, Any]:
    try:
        return requests.get(f"{OLLAMA_HOST}/api/ps", timeout=10).json()
    except Exception:
        return {"models": []}


def _ollama_model_digest_from_ps(ps: Dict[str, Any], model_name: str) -> Optional[str]:
    for m in ps.get("models", []) or []:
        if (m.get("name") == model_name) or (m.get("model") == model_name):
            return m.get("digest") or None
    return None


def _verify_persona_lock(st: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Returns (ok, reason, details). If ok==False and LOCK_ENFORCED, CHAT should refuse to run.
    We verify:
      - model name matches expected (optional)
      - Modelfile checksum matches expected (optional)
      - Ollama digest matches expected (optional)
    """
    details: Dict[str, Any] = {}
    expected_model = (st.get("persona_lock") or {}).get("model") or None
    expected_modelfile = (st.get("persona_lock") or {}).get("modelfile_path") or None
    expected_modelfile_sha = (st.get("persona_lock") or {}).get("modelfile_sha256") or None
    expected_digest = (st.get("persona_lock") or {}).get("ollama_digest") or None
    current_model = DEFAULT_CHAT_MODEL.strip()
    details["current_model"] = current_model
    details["expected_model"] = expected_model

    # 1) Model name check
    if expected_model and current_model != expected_model:
        return (False, "model_name_mismatch", {**details, "msg": f"Expected {expected_model}, got {current_model}."})

    # 2) Modelfile checksum check
    if expected_modelfile and expected_modelfile_sha:
        p = Path(os.path.expanduser(expected_modelfile))
        if not p.exists():
            return (False, "modelfile_missing", {**details, "msg": f"Locked Modelfile not found: {p}"})
        sha = _sha256_file(p)
        details["current_modelfile_sha256"] = sha
        if sha != expected_modelfile_sha:
            return (False, "modelfile_sha256_mismatch", {**details, "msg": "Modelfile checksum changed."})

    # 3) Ollama digest check (from /api/ps)
    # Resolve Ollama host once (no implicit globals)
    ollama_host = OLLAMA_HOST
    ps = _ollama_ps()
    dig = _ollama_model_digest_from_ps(ps, current_model)
    details["current_ollama_digest"] = dig
    details["expected_ollama_digest"] = expected_digest
    if expected_digest and dig and dig != expected_digest:
        return (False, "ollama_digest_mismatch", {**details, "msg": "Loaded model digest differs."})
    if expected_digest and dig is None:
        # Model may not be loaded yet; attempt a warm-load then re-check /api/ps.
        warmed = False
        try:
            warmed = _ollama_warm_load(current_model, ollama_host)
        except Exception as e:
            details["warm_load_error"] = repr(e)

        if warmed:
            ps2 = _ollama_ps()
            dig2 = _ollama_model_digest_from_ps(ps2, current_model)
            details["current_ollama_digest"] = dig2
            if dig2 and dig2 != expected_digest:
                return (False, "ollama_digest_mismatch", {**details, "msg": "Loaded model digest differs after warm-load."})
            if dig2:
                return (True, "ok", details)

        return (True, "ok_unverified", {**details, "warn": "Model not yet loaded; digest cannot be verified until first use."})
    # FINAL SUCCESS PATH — if nothing failed above, the lock is valid
    return (True, "ok", details)


def persona_lock_set(model: Optional[str] = None, modelfile_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Sets the lock baseline. This is the "make it unbreakable" button.
    - model defaults to DEFAULT_CHAT_MODEL
    - modelfile_path can be None (then only model + digest are locked)
    """
    st = _load_state()
    model = (model or DEFAULT_CHAT_MODEL).strip()

    lock: Dict[str, Any] = {"model": model, "set_at": time.time()}

    if modelfile_path:
        p = Path(os.path.expanduser(modelfile_path))
        if not p.exists():
            msg = f"Modelfile not found: {p}"
            return {"ok": False, "action": "PERSONA_LOCK_SET", "error": msg, "content": msg, "response": msg}
        lock["modelfile_path"] = str(p)
        lock["modelfile_sha256"] = _sha256_file(p)

    # Capture current digest (best effort)
    ps = _ollama_ps()
    dig = _ollama_model_digest_from_ps(ps, model)
    if dig:
        lock["ollama_digest"] = dig

    st["persona_lock"] = lock
    _save_state(st)

    msg = f"Persona lock set for model={model}."
    return {"ok": True, "action": "PERSONA_LOCK_SET", "lock": lock, "content": msg, "response": msg}


def persona_lock_status() -> Dict[str, Any]:
    st = _load_state()
    ok, reason, details = _verify_persona_lock(st)
    lock = st.get("persona_lock") or {}
    msg = "Persona lock OK." if ok else f"Persona lock FAIL: {reason}"
    return {"ok": ok, "action": "PERSONA_LOCK_STATUS", "reason": reason, "details": details, "lock": lock, "content": msg, "response": msg}


def persona_lock_clear() -> Dict[str, Any]:
    st = _load_state()
    st.pop("persona_lock", None)
    _save_state(st)
    msg = "Persona lock cleared."
    return {"ok": True, "action": "PERSONA_LOCK_CLEAR", "content": msg, "response": msg}


# ----------------------------
# Persistent long-term memory (deterministic archive)
# ----------------------------

def memory_store(text: str, tags: Optional[List[str]] = None) -> Dict[str, Any]:
    text = (text or "").strip()
    if not text:
        msg = "Empty memory text."
        return {"ok": False, "action": "MEMORY_STORE", "error": "empty_text", "content": msg, "response": msg}

    rec = {
        "ts": time.time(),
        "text": text,
        "tags": [t.strip() for t in (tags or []) if isinstance(t, str) and t.strip()],
    }
    try:
        MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with MEMORY_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        msg = "Memory stored."
        return {"ok": True, "action": "MEMORY_STORE", "record": rec, "content": msg, "response": msg}
    except Exception as e:
        msg = "Failed to store memory."
        return {"ok": False, "action": "MEMORY_STORE", "error": repr(e), "content": msg, "response": msg}


def memory_recall(query: str, limit: int = 5) -> Dict[str, Any]:
    q = (query or "").strip().lower()
    if not q:
        msg = "Empty recall query."
        return {"ok": False, "action": "MEMORY_RECALL", "error": "empty_query", "content": msg, "response": msg}

    hits: List[Dict[str, Any]] = []
    try:
        if not MEMORY_PATH.exists():
            msg = "No memory archive yet."
            return {"ok": True, "action": "MEMORY_RECALL", "hits": [], "content": msg, "response": msg}

        with MEMORY_PATH.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                text = str(rec.get("text", "")).lower()
                tags = " ".join(rec.get("tags") or []).lower()
                if q in text or q in tags:
                    hits.append(rec)

        hits = hits[-max(1, int(limit)):]  # most recent matches
        # Human readable summary
        summary_lines = []
        for r in reversed(hits):
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r.get("ts", 0)))
            t = str(r.get("text", "")).strip()
            t = t if len(t) <= 180 else t[:177] + "..."
            summary_lines.append(f"- [{ts}] {t}")
        content = "Memory recall:\n" + ("\n".join(summary_lines) if summary_lines else "(no matches)")
        return {"ok": True, "action": "MEMORY_RECALL", "hits": hits, "content": content, "response": content}
    except Exception as e:
        msg = "Memory recall failed."
        return {"ok": False, "action": "MEMORY_RECALL", "error": repr(e), "content": msg, "response": msg}


# ----------------------------
# Self-consistency tests + healthcheck
# ----------------------------

def self_test() -> Dict[str, Any]:
    """
    Runs a deterministic suite:
      - persona lock status
      - minimal chat handshake
      - consistency probe (temperature=0 twice) and compare
    """
    st = _load_state()
    ok_lock, reason, details = _verify_persona_lock(st)

    results: Dict[str, Any] = {
        "persona_lock": {"ok": ok_lock, "reason": reason, "details": details},
        "tests": []
    }

    # 1) Handshake: "Reply with exactly: persona_ok"
    handshake_prompt = "Reply with exactly these 2 words: persona ok"
    h1 = _ollama_chat_raw(handshake_prompt, temperature=0.0, num_predict=16)
    results["tests"].append({"name": "handshake", **h1})

    # 2) Consistency probe: same prompt twice with temp=0
    probe = "Reply with exactly 4 words: consistency test passed."
    p1 = _ollama_chat_raw(probe, temperature=0.0, num_predict=16)
    p2 = _ollama_chat_raw(probe, temperature=0.0, num_predict=16)
    same = (p1.get("content") == p2.get("content")) and p1.get("ok") and p2.get("ok")
    results["tests"].append({"name": "consistency_probe_1", **p1})
    results["tests"].append({"name": "consistency_probe_2", **p2})
    results["tests"].append({"name": "consistency_equal", "ok": same, "content": str(same), "response": str(same)})

    # overall ok
    overall_ok = bool(ok_lock) and bool(h1.get("ok")) and bool(p1.get("ok")) and bool(p2.get("ok"))
    msg = "SELF_TEST OK" if overall_ok else "SELF_TEST FAIL"
    return {"ok": overall_ok, "action": "SELF_TEST", "results": results, "content": msg, "response": msg}


def _ollama_chat_raw(user_text: str, temperature: float = 0.7, num_predict: int = 80) -> Dict[str, Any]:
    model = DEFAULT_CHAT_MODEL
    payload = {
        "model": model,
        "stream": False,
        "messages": [{"role": "user", "content": user_text}],
        "options": {"temperature": float(temperature), "num_predict": int(num_predict)},
    }
    try:
        r = requests.post(f"{OLLAMA_HOST}/api/chat", json=payload, timeout=(10, 3600))
        r.raise_for_status()
        j = r.json()
        content = _strip_ollama_artifacts(((j.get("message") or {}).get("content") or "").strip())
        return {"ok": True, "model": model, "content": content, "response": content}
    except Exception as e:
        msg = "raw chat failed"
        return {"ok": False, "model": model, "error": repr(e), "content": msg, "response": msg}


# ----------------------------
# Origin / identity (NO prompt hijack)
# ----------------------------

def _is_origin_question(msg: str) -> bool:
    low = (msg or "").lower()
    triggers = [
        "who created you", "who made you", "who built you",
        "who are you", "your creator", "your origin",
        "who developed you"
    ]
    return any(t in low for t in triggers)


def _origin_facts(st: Dict[str, Any]) -> str:
    name = (st.get("user_name") or eli_config.user_name()).strip() or "The user"
    return (
        f"Factual note: {name} assembled/configured ELI; ELI runs locally via Ollama using base model weights. "
        f"Don’t claim any company 'created ELI' as a shipped product."
    )


def _needs_origin_anchor(ans: str) -> bool:
    """
    If origin question answer drifts into corporate-creator claims,
    we append a short factual anchor (we do NOT rewrite the answer).
    """
    a = (ans or "").lower()
    bad = [
        "created by alibaba", "developed by alibaba", "created by openai", "developed by openai",
        "created by qwen", "developed by qwen", "alibaba cloud created", "openai created"
    ]
    return any(x in a for x in bad)


# ----------------------------
# CHAT with persistent conversation + lock enforcement
# ----------------------------

def chat(message: str, *, model: Optional[str] = None) -> Dict[str, Any]:
    msg = (message or "").strip()
    if not msg:
        return {"ok": False, "action": "CHAT", "error": "empty_message", "content": "", "response": ""}

    st = _load_state()

    # Enforce lock BEFORE chatting (prevents silent personality drift)
    ok_lock, reason, details = _verify_persona_lock(st)
    if LOCK_ENFORCED and not ok_lock and (st.get("persona_lock") is not None):
        content = (
            f"ELI LOCKDOWN: persona verification failed ({reason}).\n"
            f"Details: {details}\n"
            f"Fix: rebuild/reload your locked model/Modelfile or clear the lock."
        )
        return {"ok": False, "action": "CHAT", "error": f"lockdown:{reason}", "content": content, "response": content}

    model = (model or DEFAULT_CHAT_MODEL or eli_config.chat_model()).strip()
    if not model:
        content = ("No model found. Install Ollama from https://ollama.com, then pull a chat model with "
                   "`ollama pull <name>` (or set ELI_MODEL to one you have).")
        return {"ok": False, "action": "CHAT", "error": "no_model", "content": content, "response": content}

    # Build messages with history for continuity (NO extra system prompt; Modelfile persona stays in charge)
    messages: List[Dict[str, str]] = []
    messages.extend(_state_get_history(st))
    messages.append({"role": "user", "content": msg})

    payload = {
        "model": model,
        "stream": False,
        "messages": messages,
        "options": {
            "temperature": float(os.environ.get("ELI_TEMPERATURE", "0.7")),
        },
    }

    try:
        r = requests.post(f"{OLLAMA_HOST}/api/chat", json=payload, timeout=(10, 3600))
        r.raise_for_status()
        j = r.json()
        content = _strip_ollama_artifacts(((j.get("message") or {}).get("content") or "").strip())

        # If origin question drifts, append a factual anchor (without prompt hijack)
        if _is_origin_question(msg) and _needs_origin_anchor(content):
            content = f"{content}\n\n{_origin_facts(st)}"

        _state_append_history(st, msg, content)
        _save_state(st)

        return {"ok": True, "action": "CHAT", "model": model, "content": content, "response": content}
    except requests.exceptions.ConnectionError as e:
        msg2 = (f"Ollama is not running at {OLLAMA_HOST}. Install it from https://ollama.com, start it, "
                "and pull a chat model with `ollama pull <name>`.")
        return {"ok": False, "action": "CHAT", "model": model, "error": repr(e), "content": msg2, "response": msg2}
    except requests.exceptions.HTTPError as e:
        msg2 = (f"Ollama could not run {model}: {e.response.text[:200] if e.response is not None else e}. "
                f"If it is not pulled yet: `ollama pull {model}`.")
        return {"ok": False, "action": "CHAT", "model": model, "error": repr(e), "content": msg2, "response": msg2}
    except Exception as e:
        msg2 = "Chat failed."
        return {"ok": False, "action": "CHAT", "model": model, "error": repr(e), "content": msg2, "response": msg2}


# ----------------------------
# Deterministic quick actions
# ----------------------------

def open_audio_settings() -> Dict[str, Any]:
    for cmd in (["pavucontrol"], ["gnome-control-center", "sound"]):
        r = _run(cmd, timeout=5)
        if r.get("ok"):
            msg = "Audio settings opened."
            return {"ok": True, "action": "OPEN_AUDIO_SETTINGS", "cmd": cmd, "content": msg, "response": msg}
    msg = "No audio settings app found (pavucontrol / gnome-control-center)."
    return {"ok": False, "action": "OPEN_AUDIO_SETTINGS", "error": msg, "content": msg, "response": msg}


def open_file_system(path: str = "~") -> Dict[str, Any]:
    try:
        target = os.path.expanduser(path)
        subprocess.Popen(["xdg-open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        msg = "File system opened."
        return {"ok": True, "action": "OPEN_FILE_SYSTEM", "path": target, "content": msg, "response": msg}
    except Exception as e:
        msg = "Failed to open file system."
        return {"ok": False, "action": "OPEN_FILE_SYSTEM", "error": repr(e), "content": msg, "response": msg}




def fabricate_document(args: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a real on-disk document (DOCX; optionally ODT) under artifacts/."""
    topic = (args.get('topic') or args.get('title') or 'Untitled Document').strip()
    content = (args.get('content') or '').strip()
    fmt = (args.get('format') or 'docx').lower().strip()

    # If content wasn't supplied, generate it via the chat model, but keep it deterministic-ish.
    if not content:
        prompt = (
            "Write a clean, factual document in Markdown about: " + topic + "\n"
            "Structure: title, short biography/overview, key contributions, timeline, references placeholder. "
            "No made-up citations. If unsure, say so."
        )
        gen = chat_ollama(prompt, temperature=0.3)
        if not gen.get('ok'):
            return {"ok": False, "error": gen.get('error') or 'document_content_generation_failed'}
        content = gen.get('content', '')

    want_docx = fmt in ('docx', 'both', 'docx+odt', 'odt', 'odt+docx')
    want_odt = fmt in ('odt', 'both', 'docx+odt', 'odt+docx')

    genr = AdvancedDocumentGenerator(base_dir=str(ARTIFACTS_DIR))
    res = genr.generate(topic=topic, content=content, want_docx=want_docx, want_odt=want_odt, also_txt=True)
    if not res.ok:
        return {"ok": False, "error": res.error or 'document_generation_failed', "topic": topic, "out_dir": res.out_dir}

    # Return paths so GUI can show / open.
    return {
        "ok": True,
        "topic": topic,
        "out_dir": res.out_dir,
        "txt_path": res.txt_path,
        "docx_path": res.docx_path,
        "odt_path": res.odt_path,
        "content": (
            f"Document generated.\n"
            f"- out_dir: {res.out_dir}\n"
            + (f"- docx: {res.docx_path}\n" if res.docx_path else "")
            + (f"- odt: {res.odt_path}\n" if res.odt_path else "")
            + (f"- text: {res.txt_path}\n" if res.txt_path else "")
        ),
    }
def open_browser(url: str = "https://duckduckgo.com") -> Dict[str, Any]:
    try:
        subprocess.Popen(["xdg-open", str(url)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        msg = "Network browser opened."
        return {"ok": True, "action": "OPEN_BROWSER", "url": str(url), "content": msg, "response": msg}
    except Exception as e:
        msg = "Failed to open browser."
        return {"ok": False, "action": "OPEN_BROWSER", "error": repr(e), "content": msg, "response": msg}


def set_user_name(name: str) -> Dict[str, Any]:
    n = (name or "").strip()
    if not n:
        msg = "Empty name."
        return {"ok": False, "action": "SET_USER_NAME", "error": "empty_name", "content": msg, "response": msg}
    st = _load_state()
    st["user_name"] = n
    st["updated_at"] = time.time()
    _save_state(st)
    msg = f"Name set to {n}."
    return {"ok": True, "action": "SET_USER_NAME", "user_name": n, "content": msg, "response": msg}


def get_status() -> Dict[str, Any]:
    st = _load_state()
    ps = _ollama_ps()
    msg = "Status OK."
    return {
        "ok": True,
        "action": "GET_STATUS",
        "user_name": st.get("user_name", ""),
        "chat_model_default": DEFAULT_CHAT_MODEL,
        "persona_lock": st.get("persona_lock") or None,
        "ollama_ps": ps,
        "content": msg,
        "response": msg,
    }


def clear_chat_history() -> Dict[str, Any]:
    st = _load_state()
    st["chat_history"] = []
    st["updated_at"] = time.time()
    _save_state(st)
    msg = "Chat history cleared."
    return {"ok": True, "action": "CLEAR_CHAT_HISTORY", "content": msg, "response": msg}


# ----------------------------
# Dispatcher
# ----------------------------

def _execute_impl(action: str, args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    args = args or {}
    # Normalize action for dispatch (accept open_app, OPEN_APP, open-app, etc.)
    a = (str(action) if action is not None else "").strip()
    a = re.sub(r"[\s\-]+", "_", a)
    a = a.upper()

    if a == "CHAT":
        msg = args.get("message") or args.get("prompt") or args.get("text") or ""
        model = args.get("model") or None
        return chat(str(msg), model=model)

    # Persistent memory
    # Persistent memory
    if a == "MEMORY_STORE":
        txt = str(args.get("text") or args.get("message") or "")
        tags = args.get("tags")

        # Normalize tags: allow "tag1, tag2" or ["tag1","tag2"]
        if isinstance(tags, str):
            tags = [t.strip() for t in re.split(r"[,\s]+", tags) if t.strip()]
        elif tags is None:
            tags = []
        elif not isinstance(tags, (list, tuple)):
            tags = [str(tags)]

        try:
            # Prefer eli_tools.memory_db if present; fall back to state/memory helpers if your codebase differs
            from eli_tools import memory_db as _memory_db  # type: ignore
            if hasattr(_memory_db, "store"):
                _memory_db.store(txt, tags=tags)
                return {"ok": True, "action": a, "content": "stored", "response": "stored"}
            if hasattr(_memory_db, "memory_store"):
                _memory_db.memory_store(txt, tags=tags)
                return {"ok": True, "action": a, "content": "stored", "response": "stored"}
            # last-resort: if module exists but no known method
            return {"ok": False, "action": a, "error": "memory_db has no store() / memory_store()", "content": "memory store not wired", "response": "memory store not wired"}
        except Exception as e:
            return {"ok": False, "action": a, "error": f"memory_store_error: {e}", "content": f"memory store error: {e}", "response": f"memory store error: {e}"}

    # --- DISPATCH PATCH: CORE + PROACTIVE ACTIONS ---
    # NOTE: Capabilities can be "registered" without being "implemented".
    # This block ensures the common actions actually route to real code.

    # ---- TIME ----
    if a == "TIME":
        from datetime import datetime
        return {"ok": True, "action": a, "content": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "response": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

    # ---- HELP / LIST_CAPABILITIES ----
    if a in ("HELP", "LIST_CAPABILITIES"):
        try:
            from eli_tools.capability_registry import list_capabilities, render_detailed
            if a == "HELP":
                txt = render_detailed()
                return {"ok": True, "action": a, "content": txt, "response": txt}
            caps = list_capabilities()
            return {"ok": True, "action": a, "capabilities": caps, "content": str(len(caps)), "response": str(len(caps))}
        except Exception as e:
            return {"ok": False, "action": a, "error": f"capabilities error: {e}", "content": f"capabilities error: {e}", "response": f"capabilities error: {e}"}

    # ---- READ_FILE ----
    if a == "READ_FILE":
        try:
            from pathlib import Path as _Path
            path = (args or {}).get("path") or (args or {}).get("file") or ""
            path = str(path).strip()
            if not path:
                return {"ok": False, "action": a, "error": "Missing path", "content": "Missing path", "response": "Missing path"}
            pp = _Path(path).expanduser()
            if not pp.is_absolute():
                pp = (_Path.cwd() / pp).resolve()
            data = pp.read_text(encoding="utf-8", errors="replace")
            return {"ok": True, "action": a, "path": str(pp), "content": data, "response": data}
        except Exception as e:
            return {"ok": False, "action": a, "error": str(e), "content": str(e), "response": str(e)}

    # ---- WRITE_NOTE ----
    if a == "WRITE_NOTE":
        try:
            from pathlib import Path as _Path
            import time as _time
            txt = (args or {}).get("text") or (args or {}).get("content") or ""
            txt = str(txt)
            root = _Path((args or {}).get("root") or _Path.cwd())
            nb = root / "eli_notebook"
            nb.mkdir(parents=True, exist_ok=True)
            fn = nb / f"{_time.strftime('%Y-%m-%d')}.md"
            fn.write_text(txt, encoding="utf-8")
            msg = f"Wrote note: {fn}"
            return {"ok": True, "action": a, "path": str(fn), "content": msg, "response": msg}
        except Exception as e:
            return {"ok": False, "action": a, "error": str(e), "content": str(e), "response": str(e)}

    # ---- OPEN_URL ----
    if a == "OPEN_URL":
        try:
            url = (args or {}).get("url") or ""
            url = str(url).strip()
            if not url:
                return {"ok": False, "action": a, "error": "Missing url", "content": "Missing url", "response": "Missing url"}
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            msg = f"Opened URL: {url}"
            return {"ok": True, "action": a, "content": msg, "response": msg}
        except Exception as e:
            return {"ok": False, "action": a, "error": str(e), "content": str(e), "response": str(e)}

    # ---- OPEN_APP ----
    if a == "OPEN_APP":
        try:
            name = (args or {}).get("name") or (args or {}).get("app") or ""
            name = str(name).strip()
            if not name:
                return {"ok": False, "action": a, "error": "Missing app name", "content": "Missing app name", "response": "Missing app name"}
            # simple mapping (extend in your own config if you want)
            app = name
            subprocess.Popen([app], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            msg = f"Opened app: {app}"
            return {"ok": True, "action": a, "content": msg, "response": msg}
        except Exception as e:
            return {"ok": False, "action": a, "error": str(e), "content": str(e), "response": str(e)}

    # ---- RUN_CMD ----
    if a == "RUN_CMD":
        try:
            cmd = (args or {}).get("cmd") or ""
            cmd = str(cmd).strip()
            if not cmd:
                return {"ok": False, "action": a, "error": "Missing cmd", "content": "Missing cmd", "response": "Missing cmd"}
            out = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT, text=True)
            return {"ok": True, "action": a, "content": out, "response": out}
        except subprocess.CalledProcessError as e:
            return {"ok": False, "action": a, "error": e.output, "content": e.output, "response": e.output}
        except Exception as e:
            return {"ok": False, "action": a, "error": str(e), "content": str(e), "response": str(e)}

    # ---- PROACTIVE (start/stop/status) ----
    if a == "PROACTIVE_STATUS":
        try:
            st = proactive_status()
            return {"ok": True, "action": a, **st, "content": str(st), "response": str(st)}
        except Exception as e:
            return {"ok": False, "action": a, "error": str(e), "content": str(e), "response": str(e)}

    if a == "PROACTIVE_START":
        try:
            st = proactive_start()
            return {"ok": True, "action": a, **st, "content": "proactive started", "response": "proactive started"}
        except Exception as e:
            return {"ok": False, "action": a, "error": str(e), "content": str(e), "response": str(e)}

    if a == "PROACTIVE_STOP":
        try:
            st = proactive_stop()
            return {"ok": True, "action": a, **st, "content": "proactive stopped", "response": "proactive stopped"}
        except Exception as e:
            return {"ok": False, "action": a, "error": str(e), "content": str(e), "response": str(e)}
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    # ---- MEMORY_STORE ----
    if a == "MEMORY_STORE":
        # --- tags normalization ---
        tags = (args or {}).get("tags", [])
        if tags is None:
            tags = []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        if not isinstance(tags, list):
            tags = []

        # --- txt normalization ---
        txt = (args or {}).get("text")
        if txt is None:
            txt = (args or {}).get("content")
        if txt is None:
            txt = (args or {}).get("message")
        if txt is None:
            txt = ""
        txt = str(txt)

        return memory_store(txt, tags=tags)


    if a == "MEMORY_RECALL":
        # voice command "access neural archive" maps here
        q = str(args.get("q") or args.get("query") or args.get("text") or args.get("message") or "archive")
        lim = int(args.get("limit") or 5)
        # If user just says "access neural archive" with no query, don't error; explain.
        if q.strip().lower() in ("archive", "neural archive", "memory", "recall"):
            content = "Neural archive is available. Say: 'access neural archive about <topic>'"
            return {"ok": True, "action": "MEMORY_RECALL", "hits": [], "content": content, "response": content}
        return memory_recall(q, limit=lim)

    # Quick commands
    if a == "CHECK_CHRONAL_ALIGNMENT":
        msg = f"Chronal alignment nominal. Local time: {time.strftime('%H:%M:%S')}."
        return {"ok": True, "action": a, "content": msg, "response": msg}

    if a == "OPEN_FILE_SYSTEM":
        path = str(args.get("path") or "~")
        return open_file_system(path)
    if a == "OPEN_COMMUNICATION_HUB":
        try:
            # Prefer local mail clients; fall back to Gmail in browser.
            candidates = [
                ["thunderbird"],
                ["evolution"],
                ["geary"],
            ]
            for cmd in candidates:
                try:
                    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    msg = f"Opened Communication Hub: {' '.join(cmd)}"
                    return {"ok": True, "action": a, "content": msg, "response": msg}
                except FileNotFoundError:
                    continue
            url = "https://mail.google.com"
            open_browser(url)
            msg = f"Opened Communication Hub: {url}"
            return {"ok": True, "action": a, "content": msg, "response": msg}
        except Exception as e:
            return {"ok": False, "action": a, "error": str(e), "content": str(e), "response": str(e)}
    if a == "DATA_FABRICATOR":
        try:
            # If a topic/prompt is provided, generate a document first then open it.
            topic = str((args or {}).get("topic") or (args or {}).get("query") or (args or {}).get("text") or (args or {}).get("message") or "").strip()
            if topic:
                r = _execute_impl(action="DOC_GENERATE", args={"topic": topic, "format": (args or {}).get("format") or "md"})
                # If generation succeeded, also open in an editor if available
                if r.get("ok") and r.get("path"):
                    path = r.get("path")
                    editors = [
                        ["code", path],
                        ["codium", path],
                        ["gedit", path],
                        ["kate", path],
                        ["nano", path],
                    ]
                    for cmd in editors:
                        try:
                            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            break
                        except FileNotFoundError:
                            continue
                return r

            # Otherwise just open an editor for a new blank file.
            out_dir = ARTIFACTS_DIR.resolve()
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"data_construct_{int(time.time())}.md"
            if not out_path.exists():
                out_path.write_text("# Data Construct\n\n", encoding="utf-8")

            editors = [
                ["code", str(out_path)],
                ["codium", str(out_path)],
                ["gedit", str(out_path)],
                ["libreoffice", "--writer", str(out_path)],
            ]
            for cmd in editors:
                try:
                    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    msg = f"Opened editor: {' '.join(cmd)}"
                    return {"ok": True, "action": a, "path": str(out_path), "content": msg, "response": msg}
                except FileNotFoundError:
                    continue

            # Fallback: open with default system handler
            subprocess.Popen(["xdg-open", str(out_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            msg = f"Opened file: {out_path}"
            return {"ok": True, "action": a, "path": str(out_path), "content": msg, "response": msg}
        except Exception as e:
            return {"ok": False, "action": a, "error": str(e), "content": str(e), "response": str(e)}

    if a == "OPEN_AUDIO_SETTINGS":
        try:
            # Try common Linux audio mixers/settings panels.
            candidates = [
                ["pavucontrol"],
                ["gnome-control-center", "sound"],
                ["gnome-control-center"],
                ["systemsettings5", "kcm_pulseaudio"],
                ["systemsettings5"],
                ["kcmshell5", "kcm_pulseaudio"],
                ["mate-volume-control"],
                ["xfce4-mixer"],
            ]
            for cmd in candidates:
                try:
                    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    msg = f"Opened audio settings: {' '.join(cmd)}"
                    return {"ok": True, "action": a, "content": msg, "response": msg}
                except FileNotFoundError:
                    continue
            raise FileNotFoundError("No audio settings app found (pavucontrol / gnome-control-center / systemsettings5 / etc).")
        except Exception as e:
            return {"ok": False, "action": a, "error": str(e), "content": str(e), "response": str(e)}


    if a == "OPEN_BROWSER":
        url = str(args.get("url") or args.get("link") or "https://duckduckgo.com")
        return open_browser(url)

    # Persona lock / verification


    if a == "OPEN_NETWORK_BROWSER":
        try:
            url = str((args or {}).get("url") or "https://duckduckgo.com").strip()
            open_browser(url)
            msg = f"Opened Network Browser: {url}"
            return {"ok": True, "action": a, "content": msg, "response": msg}
        except Exception as e:
            return {"ok": False, "action": a, "error": str(e), "content": str(e), "response": str(e)}

    if a == "OPEN_MEDIA_HUB":
        try:
            # Try Spotify client first; otherwise open YouTube Music; otherwise open local Music folder.
            opened = False
            # Optional: also open audio settings (requested by voice phrase "initiate audio interface")
            if (args or {}).get("open_settings"):
                try:
                    _ = _execute_impl(action="OPEN_AUDIO_SETTINGS", args={})
                except Exception:
                    pass

            candidates = [
                ["spotify"],
                ["flatpak", "run", "com.spotify.Client"],
            ]
            for cmd in candidates:
                try:
                    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    opened = True
                    msg = f"Opened media: {' '.join(cmd)}"
                    return {"ok": True, "action": a, "content": msg, "response": msg}
                except FileNotFoundError:
                    continue

            # Browser fallbacks
            try:
                url = "https://music.youtube.com"
                open_browser(url)
                msg = f"Opened media: {url}"
                return {"ok": True, "action": a, "content": msg, "response": msg}
            except Exception:
                pass

            # Local folder fallback
            try:
                music_dir = os.path.expanduser("~/Music")
                open_file_system(music_dir)
                msg = f"Opened media folder: {music_dir}"
                return {"ok": True, "action": a, "content": msg, "response": msg}
            except Exception as e:
                raise e
        except Exception as e:
            return {"ok": False, "action": a, "error": str(e), "content": str(e), "response": str(e)}

    if a in ("DOC_GENERATE", "CREATE_DOCUMENT"):
        try:
            topic = str((args or {}).get("topic") or (args or {}).get("query") or (args or {}).get("text") or (args or {}).get("message") or "").strip()
            if not topic:
                return {"ok": False, "action": a, "error": "missing_topic", "content": "Missing topic.", "response": "Missing topic."}

            fmt = str((args or {}).get("format") or "md").strip().lower()
            if fmt in ("markdown", "md"):
                ext = "md"
            elif fmt in ("txt", "text"):
                ext = "txt"
            elif fmt in ("html",):
                ext = "html"
            else:
                ext = "md"

            out_dir = Path(os.path.expanduser((args or {}).get("out_dir") or str(ARTIFACTS_DIR))).resolve()
            out_dir.mkdir(parents=True, exist_ok=True)
            safe = re.sub(r"[^a-zA-Z0-9_\-]+", "_", topic.strip())[:60] or "document"
            out_path = out_dir / f"{safe}_{int(time.time())}.{ext}"

            # Ask the chat model to write the document content (local Ollama) if available.
            prompt = (
                "Write a clean, structured document for a general intelligent reader.\n"
                f"Topic: {topic}\n\n"
                "Requirements:\n"
                "- Use headings and short paragraphs\n"
                "- Include key facts, definitions, and examples\n"
                "- End with a short 'Further Questions' section\n"
                "- No fluff.\n"
            )

            content = None
            try:
                # chat_ollama signature varies across versions; we try both.
                if "chat_ollama" in globals():
                    try:
                        r = chat_ollama(prompt)
                    except TypeError:
                        r = chat_ollama(message=prompt)
                    # Expect dict with 'content' or string
                    if isinstance(r, dict):
                        content = r.get("content") or r.get("response") or r.get("text")
                    elif isinstance(r, str):
                        content = r
            except Exception:
                content = None

            if not content:
                # Fallback: minimal stub-free local document scaffold
                content = f"# {topic}\n\n(LLM content unavailable. This is a placeholder scaffold.)\n\n## Summary\n\n## Key Points\n\n## Examples\n\n## Further Questions\n"

            if ext == "html":
                body = content
                if not body.lstrip().lower().startswith("<"):
                    body = "<pre>" + (content.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")) + "</pre>"
                content_to_write = "<!doctype html><html><head><meta charset='utf-8'><title>" + topic + "</title></head><body>" + body + "</body></html>"
            else:
                content_to_write = content

            out_path.write_text(content_to_write, encoding="utf-8")
            # Open with default app
            try:
                subprocess.Popen(["xdg-open", str(out_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

            msg = f"Document created: {out_path}"
            return {"ok": True, "action": a, "path": str(out_path), "content": msg, "response": msg}
        except Exception as e:
            return {"ok": False, "action": a, "error": str(e), "content": str(e), "response": str(e)}

    if a == "PERSONA_LOCK_SET":
        model = args.get("model") or None
        modelfile = args.get("modelfile_path") or args.get("modelfile") or None
        return persona_lock_set(model=model, modelfile_path=modelfile)

    if a == "PERSONA_LOCK_STATUS":
        return persona_lock_status()

    if a == "PERSONA_LOCK_CLEAR":
        return persona_lock_clear()

    if a == "SELF_TEST":
        return self_test()

    if a == "SET_USER_NAME":
        return set_user_name(str(args.get("name", "")))

    if a == "GET_STATUS":
        return get_status()

    if a == "CLEAR_CHAT_HISTORY":
        return clear_chat_history()

    # --- OPEN_APP_INSERTED_V1 ---
    # Generic Linux app launcher using args dict.
    if a in ("OPEN_APP", "open_app", "openapp", "LAUNCH_APP", "launch_app"):
        name = ""
        if isinstance(args, dict):
            name = (args.get("name") or args.get("app") or args.get("title") or "").strip()

        if not name:
            return {"ok": False, "action": "OPEN_APP", "error": "missing_name",
                    "content": "Missing app name.", "response": "Missing app name."}

        tries = []

        def try_run(cmd):
            tries.append(cmd)
            try:
                import subprocess
                p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return {"ok": True, "pid": p.pid, "cmd": cmd}
            except Exception as e:
                return {"ok": False, "error": repr(e)}

        # gtk-launch desktop id
        for t in (name, name.lower(), name + ".desktop"):
            r = try_run(["gtk-launch", t])
            if r.get("ok"):
                return {"ok": True, "action": "OPEN_APP",
                        "content": f"Opened {name}.", "response": f"Opened {name}.",
                        "result": {"tries": tries, **r}}

        # gio launch desktop file
        for t in (name, name + ".desktop"):
            r = try_run(["gio", "launch", t])
            if r.get("ok"):
                return {"ok": True, "action": "OPEN_APP",
                        "content": f"Opened {name}.", "response": f"Opened {name}.",
                        "result": {"tries": tries, **r}}

        # direct command (supports "cmd --flags")
        try:
            import shlex
            r = try_run(shlex.split(name))
            if r.get("ok"):
                return {"ok": True, "action": "OPEN_APP",
                        "content": f"Opened {name}.", "response": f"Opened {name}.",
                        "result": {"tries": tries, **r}}
        except Exception:
            pass

        return {"ok": False, "action": "OPEN_APP", "error": "launch_failed",
                "content": f"Could not open {name}.", "response": f"Could not open {name}.",
                "result": {"tries": tries}}

    return {"ok": False, "action": a, "error": f"Unknown action: {a}", "content": f"Unknown action: {a}", "response": f"Unknown action: {a}"}


def execute(action: str, args: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    if isinstance(args, dict):
        merged.update(args)
    merged.update(kwargs or {})
    res = _execute_impl(action=str(action), args=merged)
    return _normalize_result(res)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("action")
    ap.add_argument("--args", default="{}")
    ns = ap.parse_args()
    print(json.dumps(execute(ns.action, json.loads(ns.args)), indent=2))

# --- AUTO-REGISTER CAPABILITIES (ON IMPORT) ---

# --- AUTO-REGISTER CAPABILITIES (ON IMPORT) ---
try:
    from eli_tools.capability_registry import register as _cap_register
    _SUPPORTED = [
        "CHAT",
        "HELP",
        "LIST_CAPABILITIES",
        "TIME",
        "READ_FILE",
        "WRITE_NOTE",
        "RUN_CMD",
        "OPEN_URL",
        "OPEN_APP",
        "MEMORY_STORE",
        "MEMORY_RECALL",
        "MEMORY_STATS",
        "PROACTIVE_START",
        "PROACTIVE_STOP",
        "PROACTIVE_STATUS",
        "SELF_TEST",
        "PERSONA_LOCK_SET",
        "PERSONA_LOCK_STATUS",
        "PERSONA_LOCK_CLEAR",
    ]
    for _a in _SUPPORTED:
        _cap_register(_a, description=f"Executor action: {_a}")
except Exception:
    pass



# ----------------------------
# Proactive daemon control (real PID management)
# ----------------------------
def _proactive_paths():
    base = ARTIFACTS_DIR / "proactive"
    base.mkdir(parents=True, exist_ok=True)
    return base, base / "daemon.pid", base / "daemon.log"

def proactive_status() -> Dict[str, Any]:
    base, pidf, logf = _proactive_paths()
    pid = None
    if pidf.exists():
        try:
            pid = int(pidf.read_text().strip())
        except Exception:
            pid = None
    alive = False
    if pid:
        try:
            os.kill(pid, 0)
            alive = True
        except Exception:
            alive = False
    msg = f"Proactive daemon is {'RUNNING' if alive else 'STOPPED'}."
    return {"ok": True, "action": "PROACTIVE_STATUS", "pid": pid, "running": alive, "log": str(logf), "content": msg, "response": msg}

def proactive_start() -> Dict[str, Any]:
    base, pidf, logf = _proactive_paths()
    st = proactive_status()
    if st.get("running"):
        return st
    try:
        py = sys.executable if "sys" in globals() else "python3"
    except Exception:
        py = "python3"
    # run as module so imports work
    argv = [py, "-m", "eli_tools.proactive_daemon"]
    try:
        lf = open(logf, "a", encoding="utf-8")
        p = subprocess.Popen(argv, stdout=lf, stderr=lf, cwd=str(Path.cwd()))
        pidf.write_text(str(p.pid), encoding="utf-8")
        msg = "Proactive daemon started."
        return {"ok": True, "action": "PROACTIVE_START", "pid": p.pid, "cmd": argv, "log": str(logf), "content": msg, "response": msg}
    except Exception as e:
        msg = "Failed to start proactive daemon."
        return {"ok": False, "action": "PROACTIVE_START", "error": repr(e), "content": msg, "response": msg}

def proactive_stop() -> Dict[str, Any]:
    base, pidf, logf = _proactive_paths()
    pid = None
    if pidf.exists():
        try:
            pid = int(pidf.read_text().strip())
        except Exception:
            pid = None
    if not pid:
        msg = "Proactive daemon not running (no PID)."
        return {"ok": True, "action": "PROACTIVE_STOP", "content": msg, "response": msg}
    try:
        os.kill(pid, 15)
    except Exception:
        pass
    try:
        pidf.unlink(missing_ok=True)  # py3.8+: if not available it will throw
    except Exception:
        try:
            pidf.unlink()
        except Exception:
            pass
    msg = "Proactive daemon stopped."
    return {"ok": True, "action": "PROACTIVE_STOP", "pid": pid, "content": msg, "response": msg}
