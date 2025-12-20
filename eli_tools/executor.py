from pathlib import Path
import os, re, shlex, subprocess, pathlib, datetime, time
from typing import Any, Dict, Optional

DOC_DIR = Path(os.path.expanduser(os.environ.get('ELI_DOC_DIR','~/Desktop/AI_Eli/eli_docs'))).resolve()
DOC_DIR.mkdir(parents=True, exist_ok=True)
def _expand(p: str) -> pathlib.Path:
    return pathlib.Path(os.path.expanduser(p)).resolve()

def _allowed_roots():
    roots = os.environ.get("ELI_ALLOWED_ROOTS", "").strip()
    if not roots:
        roots = str(_expand("~/Desktop/AI_Eli"))
    return [_expand(r.strip()) for r in roots.split(",") if r.strip()]

def _is_under_allowed(path: pathlib.Path) -> bool:
    path = path.resolve()
    for root in _allowed_roots():
        try:
            path.relative_to(root)
            return True
        except Exception:
            pass
    return False

def _notes_dir() -> pathlib.Path:
    return _expand(os.environ.get("ELI_NOTES_DIR", "~/Desktop/AI_Eli/notes"))

def _cal_dir() -> pathlib.Path:
    return _expand(os.environ.get("ELI_CAL_DIR", "~/Desktop/AI_Eli/calendar"))

def _allowed_cmds():
    s = os.environ.get("ELI_ALLOWED_CMDS", "python,python3,make,cmake,ninja,rg,ls,cat,grep,find,tree").strip()
    return {c.strip() for c in s.split(",") if c.strip()}

def _allowed_apps():
    s = os.environ.get("ELI_ALLOWED_APPS", "nautilus,org.gnome.Calendar,gnome-calendar,libreoffice,libreoffice-writer,libreoffice-calc,gedit,code").strip()
    return {a.strip() for a in s.split(",") if a.strip()}

def _run(args, timeout=30, cwd: Optional[str]=None):
    return subprocess.run(args, text=True, capture_output=True, timeout=timeout, cwd=cwd)

def _notify(title: str, body: str=""):
    try:
        subprocess.Popen(["notify-send", title, body])
    except Exception:
        pass

def _safe_name(s: str):
    s = (s or "").strip()
    s = re.sub(r"[^\w\-\.]+", "_", s)
    return s[:80] if s else "note"

def _open_path(p: str):
    path = _expand(p)
    if not _is_under_allowed(path):
        return {"ok": False, "error": f"path not allowed: {path}"}
    subprocess.Popen(["xdg-open", str(path)])
    return {"ok": True, "opened": str(path)}

def _open_url(url: str):
    if not re.match(r"^https?://", url or ""):
        return {"ok": False, "error": "url must start with http(s)://"}
    subprocess.Popen(["xdg-open", url])
    return {"ok": True, "opened": url}

def _search(q: str):
    q = (q or "").strip()
    if not q:
        return {"ok": False, "error": "empty query"}
    url = "https://www.google.com/search?q=" + q.replace(" ", "+")
    subprocess.Popen(["xdg-open", url])
    return {"ok": True, "opened": url}

def _get_default_sink():
    p = _run(["wpctl", "status"], timeout=5)
    if p.returncode != 0:
        return None
    txt = p.stdout
    if "Sinks:" not in txt:
        return None
    sinks = txt.split("Sinks:", 1)[1]
    for line in sinks.splitlines():
        if "*" in line:
            m = re.search(r"\*\s*(\d+)\.", line)
            if m:
                return m.group(1)
    m = re.search(r"\n\s*(\d+)\.", sinks)
    return m.group(1) if m else None

def _volume(delta_percent: int = 0, set_percent: Optional[int] = None):
    sink = _get_default_sink()
    if not sink:
        return {"ok": False, "error": "no sink found (wpctl status)"}
    if set_percent is not None:
        v = max(0, min(150, int(set_percent)))
        _run(["wpctl", "set-volume", sink, f"{v}%"], timeout=5)
        return {"ok": True, "sink": sink, "set_percent": v}
    d = int(delta_percent or 0)
    n = abs(d) if abs(d) > 0 else 5
    arg = f"{n}%+" if d >= 0 else f"{n}%-"
    _run(["wpctl", "set-volume", sink, arg], timeout=5)
    return {"ok": True, "sink": sink, "delta_percent": d}

def _mute_toggle():
    sink = _get_default_sink()
    if not sink:
        return {"ok": False, "error": "no sink found"}
    _run(["wpctl", "set-mute", sink, "toggle"], timeout=5)
    return {"ok": True, "sink": sink}

def _media(cmd: str):
    cmd = (cmd or "play-pause").strip()
    if cmd not in {"play-pause", "next", "previous", "stop"}:
        return {"ok": False, "error": "media cmd must be play-pause|next|previous|stop"}
    subprocess.Popen(["playerctl", cmd])
    return {"ok": True, "cmd": cmd}

def _list_dir(path: str, depth: int = 2, max_lines: int = 250):
    p = _expand(path)
    if not _is_under_allowed(p):
        return {"ok": False, "error": f"path not allowed: {p}"}
    depth = max(1, min(8, int(depth)))
    if subprocess.call(["bash", "-lc", "command -v tree >/dev/null 2>&1"]) == 0:
        r = _run(["tree", "-L", str(depth), "-a", str(p)], timeout=20)
        out = r.stdout.splitlines()[:max_lines]
        return {"ok": r.returncode == 0, "path": str(p), "output": "\n".join(out)}
    r = _run(["find", str(p), "-maxdepth", str(depth), "-print"], timeout=20)
    out = r.stdout.splitlines()[:max_lines]
    return {"ok": r.returncode == 0, "path": str(p), "output": "\n".join(out)}

def _read_file(path: str, max_bytes: int = 12000):
    p = _expand(path)
    if not _is_under_allowed(p):
        return {"ok": False, "error": f"path not allowed: {p}"}
    if not p.exists() or not p.is_file():
        return {"ok": False, "error": f"not a file: {p}"}
    data = p.read_bytes()[:max_bytes]
    text = data.decode("utf-8", errors="replace")
    return {"ok": True, "path": str(p), "content": text, "truncated": p.stat().st_size > max_bytes}

def _lo_convert(src: pathlib.Path, to: str, outdir: pathlib.Path):
    if to not in {"pdf", "odt"}:
        return {"ok": False, "error": "convert_to must be pdf or odt"}
    outdir.mkdir(parents=True, exist_ok=True)
    if to == "odt":
        fmt = 'odt:writer8'
    else:
        fmt = 'pdf'
    cmd = [
        "libreoffice", "--headless", "--nologo", "--nolockcheck", "--nodefault", "--norestore",
        "--convert-to", fmt, "--outdir", str(outdir), str(src)
    ]
    r = _run(cmd, timeout=180)
    out = (r.stdout or "") + (("\n"+r.stderr) if r.stderr else "")
    expected = outdir / (src.stem + f".{to}")
    ok = (r.returncode == 0) and expected.exists()
    return {"ok": ok, "cmd": " ".join(shlex.quote(x) for x in cmd), "output": out[-5000:], "out": str(expected) if expected.exists() else None}

def _create_doc(doc_type: str, title: str, content: str, filename: Optional[str]=None,
                convert_to: Optional[str]=None, open_after: bool=True):
    dt = (doc_type or "md").strip().lower()
    if dt not in {"md","txt","tex"}:
        return {"ok": False, "error": "doc_type must be md|txt|tex"}
    nd = _notes_dir()
    nd.mkdir(parents=True, exist_ok=True)

    if filename:
        fn = _safe_name(filename)
        if not fn.endswith(f".{dt}"):
            fn += f".{dt}"
    else:
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fn = f"{stamp}_{_safe_name(title)}.{dt}"

    path = nd / fn
    if dt == "md":
        body = f"# {title}\n\n{content}\n"
    elif dt == "tex":
        body = content if "\\documentclass" in (content or "") else (
            "\\documentclass[11pt]{article}\n"
            "\\usepackage[a4paper,margin=1in]{geometry}\n"
            "\\usepackage{lmodern}\n"
            "\\begin{document}\n"
            f"\\section*{{{title}}}\n"
            f"{content}\n"
            "\\end{document}\n"
        )
    else:
        body = f"{title}\n\n{content}\n"

    path.write_text(body, encoding="utf-8")

    converted = None
    if convert_to:
        # LibreOffice converts txt/md nicely; it will NOT convert .tex meaningfully.
        if dt == "tex":
            return {"ok": True, "doc": str(path), "warning": "Saved .tex. LibreOffice headless does not convert .tex to PDF/ODT. Use LaTeX toolchain for PDF.", "converted": None}
        converted = _lo_convert(path, convert_to, nd)

    to_open = None
    if converted and converted.get("ok") and converted.get("out"):
        to_open = converted["out"]
    else:
        to_open = str(path)

    if open_after:
        subprocess.Popen(["xdg-open", to_open])

    return {"ok": True, "doc": str(path), "converted": converted, "opened": to_open}

def _systemd_notify_in(seconds: int, message: str):
    seconds = int(max(1, seconds))
    message = (message or "Alarm").strip()
    cmd = ["systemd-run", "--user", f"--on-active={seconds}s", "--unit=eli_alarm_" + str(int(time.time())), "notify-send", "ELI", message]
    r = _run(cmd, timeout=8)
    if r.returncode != 0:
        subprocess.Popen(["bash", "-lc", f"(sleep {seconds}; notify-send 'ELI' {shlex.quote(message)}) >/dev/null 2>&1 &"])
    return {"ok": True, "in_seconds": seconds, "message": message}

def _alarm_at(hhmm: str, message: str):
    now = datetime.datetime.now()
    m = re.match(r"^(\d{1,2}):(\d{2})$", (hhmm or "").strip())
    if not m:
        return {"ok": False, "error": "time must be HH:MM (24h)"}
    hh, mm = int(m.group(1)), int(m.group(2))
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    delta = int((target - now).total_seconds())
    return _systemd_notify_in(delta, message or f"Alarm {hhmm}")

def _calendar_event(title: str, start_iso: str, duration_min: int = 30, location: str = "", notes: str = ""):
    try:
        dt = datetime.datetime.fromisoformat(start_iso)
    except Exception:
        return {"ok": False, "error": "start must be ISO like 2025-12-09T19:30 (local time)"}
    dur = max(5, min(24*60, int(duration_min)))
    end = dt + datetime.timedelta(minutes=dur)

    cald = _cal_dir()
    cald.mkdir(parents=True, exist_ok=True)
    uid = f"eli-{int(time.time())}@local"

    def fmt(d): return d.strftime("%Y%m%dT%H%M%S")

    ics = "\n".join([
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//ELI//LOCAL//EN",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{fmt(datetime.datetime.utcnow())}Z",
        f"DTSTART:{fmt(dt)}",
        f"DTEND:{fmt(end)}",
        f"SUMMARY:{title}",
        f"LOCATION:{location}",
        "DESCRIPTION:" + (notes or "").replace("\n", "\\n"),
        "END:VEVENT",
        "END:VCALENDAR",
        ""
    ])
    path = cald / f"{fmt(dt)}_{_safe_name(title)}.ics"
    path.write_text(ics, encoding="utf-8")
    subprocess.Popen(["xdg-open", str(path)])
    return {"ok": True, "ics": str(path)}

def _open_app(app: str):
    app = (app or "").strip()
    if not app:
        return {"ok": False, "error": "empty app"}
    if app not in _allowed_apps():
        return {"ok": False, "error": f"app not allowed: {app} (set ELI_ALLOWED_APPS)"}
    if "." in app:
        r = _run(["gtk-launch", app], timeout=4)
        if r.returncode == 0:
            return {"ok": True, "app": app}
    subprocess.Popen([app])
    return {"ok": True, "app": app}

def _run_cmd(cmd: str, cwd: Optional[str] = None, timeout: int = 60):
    parts = shlex.split(cmd or "")
    if not parts:
        return {"ok": False, "error": "empty cmd"}
    exe = parts[0]
    if exe not in _allowed_cmds():
        return {"ok": False, "error": f"command not allowed: {exe} (ELI_ALLOWED_CMDS)"}
    if cwd:
        c = _expand(cwd)
        if not _is_under_allowed(c):
            return {"ok": False, "error": f"cwd not allowed: {c}"}
        cwd = str(c)
    r = _run(parts, timeout=int(max(1, min(600, timeout))), cwd=cwd)
    out = (r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")
    return {"ok": r.returncode == 0, "returncode": r.returncode, "output": out[:20000]}

def execute(intent: Dict[str, Any]) -> Dict[str, Any]:
    action = (intent.get("action") or "noop").strip()
    args = intent.get("args") or {}

    try:
        if action == "open_url":
            return _open_url(args.get("url", ""))
        if action == "search":
            return _search(args.get("q", "") or args.get("query", ""))
        if action == "open_path":
            return _open_path(args.get("path", ""))
        if action == "list_dir":
            return _list_dir(args.get("path", ""), args.get("depth", 2), args.get("max_lines", 250))
        if action == "read_file":
            return _read_file(args.get("path", ""), args.get("max_bytes", 12000))
        if action == "create_doc":
            return _create_doc(
                args.get("doc_type","md"),
                args.get("title","Document"),
                args.get("content",""),
                args.get("filename"),
                args.get("convert_to"),
                bool(args.get("open_after", True)),
            )
        if action == "volume":
            return _volume(args.get("delta_percent", 0), args.get("set_percent", None))
        if action == "mute_toggle":
            return _mute_toggle()
        if action == "media":
            return _media(args.get("cmd", "play-pause"))
        if action == "timer":
            return _systemd_notify_in(int(args.get("seconds", 60)), args.get("message", "Timer"))
        if action == "alarm":
            return _alarm_at(args.get("time", ""), args.get("message", "Alarm"))
        if action == "calendar_event":
            return _calendar_event(args.get("title", "Event"), args.get("start", ""), int(args.get("duration_min", 30)), args.get("location", ""), args.get("notes", ""))
        if action == "open_app":
            return _open_app(args.get("app", ""))
        if action == "run":
            return _run_cmd(args.get("cmd", ""), args.get("cwd", None), int(args.get("timeout", 60)))
        return {"ok": True, "action": "noop"}
    except Exception as e:
        return {"ok": False, "error": f"EXEC_ERR: {e}"}
