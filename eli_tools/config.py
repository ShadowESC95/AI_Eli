# eli_tools/config.py
# Real config loader (replaces stub). Keeps compatibility constants.

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

# Back-compat: some code expects this name to exist.
MEMORY_FILE = "eli_memory.json"

DEFAULT_CONFIG_PATH = Path(os.path.expanduser("~/.eli_config"))
PROJECT_ROOT = Path(__file__).resolve().parents[1]

def _parse_kv(text: str) -> Dict[str, str]:
    """
    Parse KEY=VALUE lines, ignoring blanks/comments.
    Accepts 'export KEY=VALUE' (bash-style).
    Strips surrounding quotes on values.
    Expands ~ and environment vars like $HOME.
    """
    out: Dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        # allow bash style: export KEY=VALUE
        if line.startswith("export "):
            line = line[len("export "):].strip()

        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")

        if not k:
            continue

        # expand $HOME etc + ~
        v = os.path.expandvars(os.path.expanduser(v))
        out[k] = v
    return out
def load_eli_config(path: str | None = None) -> Dict[str, Any]:
    """
    Load ELI config and return as dict.

    Priority:
      1) explicit 'path' argument
      2) $ELI_CONFIG
      3) ~/.eli_config
      4) {} if none found / unreadable

    Values already in the environment win over the file.

    Supported file formats:
      - JSON object (starts with '{')
      - KEY=VALUE lines
    """
    candidates = []
    if path:
        candidates.append(Path(os.path.expanduser(path)))
    if os.environ.get("ELI_CONFIG"):
        candidates.append(Path(os.path.expanduser(os.environ["ELI_CONFIG"])))
    candidates.append(DEFAULT_CONFIG_PATH)

    for c in candidates:
        try:
            if not c.exists():
                continue
            txt = c.read_text(encoding="utf-8", errors="ignore").strip()
            if not txt:
                return {}
            if txt.lstrip().startswith("{"):
                cfg = json.loads(txt)
            else:
                cfg = _parse_kv(txt)
            # apply into process env (non-destructive)
            for kk, vv in cfg.items():
                if isinstance(kk, str) and isinstance(vv, str) and kk and vv and kk not in os.environ:
                    os.environ[kk] = vv
            return cfg
        except Exception:
            # Don't crash the assistant because config is weird
            continue

    return {}

def get_config(path: str | None = None, env: bool = True) -> Dict[str, Any]:
    """
    Merge config file + optional environment variables.

    Environment variables override file values.
    """
    cfg: Dict[str, Any] = load_eli_config(path)

    if env:
        # Pull in anything ELI_*/OLLAMA_* that might be used by the app
        for k, v in os.environ.items():
            if k.startswith("ELI_") or k.startswith("OLLAMA_"):
                cfg[k] = v
    return cfg


def chat_model() -> str:
    """The Ollama model ELI talks to: ELI_CHAT_MODEL, ELI_MODEL or OLLAMA_MODEL ("" when none is set)."""
    return (os.environ.get("ELI_CHAT_MODEL") or os.environ.get("ELI_MODEL")
            or os.environ.get("OLLAMA_MODEL") or "").strip()


def ollama_base() -> str:
    """Where Ollama answers. OLLAMA_HOST is often set for the server as "0.0.0.0" or "host:port"."""
    raw = (os.environ.get("ELI_OLLAMA_HOST") or os.environ.get("OLLAMA_BASE_URL")
           or os.environ.get("OLLAMA_HOST") or "127.0.0.1:11434").strip().rstrip("/")
    if "://" not in raw:
        raw = "http://" + raw
    return raw.replace("://0.0.0.0", "://127.0.0.1")


def artifacts_dir() -> Path:
    """Documents and other outputs: ELI_ARTIFACTS_DIR, else ./artifacts in the project."""
    return Path(os.environ.get("ELI_ARTIFACTS_DIR") or PROJECT_ROOT / "artifacts").expanduser()


def user_name() -> str:
    """What ELI calls its user (ELI_USER_NAME); empty until set."""
    return os.environ.get("ELI_USER_NAME", "").strip()


load_eli_config()
