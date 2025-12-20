from __future__ import annotations
import os, sys, json, platform, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def sh(cmd):
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=10)
        return {"cmd": cmd, "rc": r.returncode, "out": r.stdout[-4000:], "err": r.stderr[-4000:]}
    except Exception as e:
        return {"cmd": cmd, "error": str(e)}

def main():
    report = {}
    report["python"] = {
        "executable": sys.executable,
        "version": sys.version,
        "platform": platform.platform(),
        "cwd": str(Path.cwd()),
        "root": str(ROOT),
        "sys_path_head": sys.path[:5],
    }

    # Detect stdlib-shadowing files (your earlier actions/types.py incident)
    bad_names = {"types.py","enum.py","re.py","json.py","subprocess.py","queue.py","typing.py"}
    shadows = []
    for p in ROOT.rglob("*.py"):
        if p.name in bad_names:
            shadows.append(str(p.relative_to(ROOT)))
    report["stdlib_shadow_candidates"] = shadows

    # Package trees
    pkgs = []
    for p in ROOT.rglob("__init__.py"):
        pkgs.append(str(p.parent.relative_to(ROOT)))
    report["packages_found"] = sorted(pkgs)

    # Key imports
    imports = {}
    for mod in ["eli_full", "dotenv", "sounddevice", "webrtcvad", "numpy"]:
        try:
            __import__(mod)
            imports[mod] = "OK"
        except Exception as e:
            imports[mod] = f"FAIL: {e}"
    report["imports"] = imports

    # Audio devices snapshot
    try:
        import sounddevice as sd
        devs = []
        for i,d in enumerate(sd.query_devices()):
            mi = int(d.get("max_input_channels") or 0)
            mo = int(d.get("max_output_channels") or 0)
            if mi or mo:
                devs.append({
                    "i": i, "name": d.get("name",""),
                    "in": mi, "out": mo,
                    "default_sr": int(d.get("default_samplerate") or 0),
                })
        report["sounddevice"] = {
            "default_device": sd.default.device,
            "devices": devs,
        }
    except Exception as e:
        report["sounddevice"] = {"error": str(e)}

    # PipeWire / Pulse / ALSA snapshots (best-effort)
    report["cmd_wpctl_status"] = sh(["bash","-lc","wpctl status | head -n 120"])
    report["cmd_pactl_sources"] = sh(["bash","-lc","pactl list short sources || true"])
    report["cmd_arecord_l"] = sh(["bash","-lc","arecord -l || true"])

    print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()
