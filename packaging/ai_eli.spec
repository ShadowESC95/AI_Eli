# PyInstaller recipe for the AI_Eli app. From the repo root: pyinstaller packaging/ai_eli.spec
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT))  # the collect_* helpers below must be able to import eli_tools

datas, binaries, hiddenimports = [], [], []
for package in ("faster_whisper", "ctranslate2", "onnxruntime", "av", "tokenizers", "speech_recognition", "pyttsx3"):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h

# scripts in eli_tools that run on import (listeners, agents) are not part of the app
scripts = {"eli_tools.eli_listen", "eli_tools.eli_agent", "eli_tools.eli_clipboard_agent"}
hiddenimports += collect_submodules("eli_tools", filter=lambda name: name not in scripts)
if "eli_tools.proactive_daemon" not in hiddenimports:
    raise SystemExit("AI_Eli's modules (eli_tools) were not collected into the bundle")
hiddenimports += ["Eli_PC_Control2_Working", "eli_pro_audio_gui_MKI", "eli_pro_audio_gui_MKII",
                  "pyaudio", "pypdf", "sounddevice", "soundfile", "numpy", "requests", "ollama", "pandas"]

datas += [(str(ROOT / "modelfiles"), "modelfiles"), (str(ROOT / "LICENSE"), ".")]
whisper = ROOT / "build" / "whisper-base"  # the speech model, so voice works offline
if whisper.is_dir():
    datas.append((str(whisper), "whisper-base"))

a = Analysis(
    [str(ROOT / "packaging" / "ai_eli_app.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "PyQt5", "PySide6", "matplotlib", "IPython", "torch", "mitmproxy"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="AI_Eli", console=True, strip=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="AI_Eli")
