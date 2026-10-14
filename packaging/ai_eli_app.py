"""AI_Eli as one program (the entry point of the packaged app).

    AI_Eli                the desktop window
    AI_Eli --voice        the hands-free voice assistant (say "Eli" first)
    AI_Eli --documents    the PDF and memory window
    AI_Eli --terminal     chat in the terminal
    AI_Eli --selftest     check that everything in the package works, then exit
    AI_Eli -m <module>    run one of AI_Eli's modules, as `python -m` does (AI_Eli uses this itself)

AI_Eli keeps its files in ~/.local/share/AI_Eli and its settings in ~/.config/AI_Eli/config
(KEY=VALUE lines, e.g. ELI_MODEL=llama3.2). A variable named AI_ELI_ instead of ELI_
(AI_ELI_MODEL=llama3.2) also works. Other ELI_ variables belong to other ELI versions and are ignored.
"""

import os
import sys
from pathlib import Path

BUNDLE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))


OWN_PREFIX = "AI_ELI_"  # AI_ELI_MODEL=... sets ELI_MODEL for this app only


def own_settings() -> None:
    """Keep only this app's own settings. Every ELI version reads ELI_... variables, so ones exported
    for another version (in a shell profile, say) are dropped; this app's come from its settings file
    (~/.config/AI_Eli/config, read by eli_tools.config) and from AI_ELI_... variables, which win."""
    own = {"ELI_" + k[len(OWN_PREFIX):]: v for k, v in os.environ.items()
           if k.startswith(OWN_PREFIX) and len(k) > len(OWN_PREFIX)}
    for k in [k for k in os.environ if k.startswith("ELI_")]:
        del os.environ[k]
    os.environ.update(own)


def _prepare() -> None:
    own_settings()
    # Programs AI_Eli starts (espeak, paplay, xdg-open, playerctl, ...) must load this system's
    # libraries, not the ones packed inside the app.
    original = os.environ.pop("LD_LIBRARY_PATH_ORIG", None)
    if original:
        os.environ["LD_LIBRARY_PATH"] = original
    else:
        os.environ.pop("LD_LIBRARY_PATH", None)
    # The Qt inside the app has its own styles only; a desktop's style name (adwaita, breeze...) cannot load
    os.environ.pop("QT_STYLE_OVERRIDE", None)

    whisper = BUNDLE / "whisper-base"
    if whisper.is_dir():
        os.environ.setdefault("ELI_WHISPER", str(whisper))

    # The app itself is read-only; AI_Eli's files go here.
    data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    home = Path(os.environ.get("ELI_HOME") or data_home / "AI_Eli").expanduser()
    home.mkdir(parents=True, exist_ok=True)
    os.environ["ELI_HOME"] = str(home)
    os.environ.setdefault("ELI_ROOT", str(home))
    os.environ.setdefault("ELI_MEMORY_DB", str(home / "eli_memory.sqlite3"))
    os.chdir(home)


def selftest() -> int:
    """Check every part, as a user would meet it: a message sent through the window and the window
    closed, with every write into AI_Eli's own (read-only when packaged) code folder reported.
    ELI_SELFTEST_WAV: a recording whose words must come back. ELI_SELFTEST_CHAT=1: the reply must
    come from a model (Ollama running with one pulled)."""
    import threading
    import time

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    real_chat = os.environ.get("ELI_SELFTEST_CHAT") == "1"
    if not real_chat:
        # the voice assistant will not start without a model name; no model is asked anything here
        os.environ.setdefault("ELI_MODEL", "selftest")
    failed, errors, code_writes = [], [], []
    code_dirs = [str(BUNDLE.resolve())]

    def in_code(path) -> bool:
        try:
            p = os.path.realpath(os.fsdecode(path))
        except (TypeError, ValueError):
            return False
        return "__pycache__" not in p and any(p == d or p.startswith(d + os.sep) for d in code_dirs)

    write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC

    def audit(event, args):
        if event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
            mode, flags = (args[1] if len(args) > 1 else None), (args[2] if len(args) > 2 else 0)
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or bool((flags or 0) & write_flags)
            if writing and in_code(args[0]):
                code_writes.append(f"open {os.fsdecode(args[0])}")
        elif event in ("os.mkdir", "os.rename", "os.remove", "shutil.copyfile") and args and in_code(args[0]):
            code_writes.append(f"{event} {os.fsdecode(args[0])}")
        elif event == "sqlite3.connect" and args and str(args[0]) not in (":memory:", "") and in_code(args[0]):
            code_writes.append(f"sqlite {args[0]}")

    # onnxruntime keeps its telemetry device ID and upload queue here; it must never appear
    telemetry_queue = Path.home() / ".cache" / "Microsoft" / "DeveloperTools" / ".onnxruntime"
    queue_existed = telemetry_queue.exists()

    sys.addaudithook(audit)
    sys.excepthook = lambda t, e, tb: errors.append(f"{t.__name__}: {e}")
    threading.excepthook = lambda a: errors.append(f"{a.exc_type.__name__}: {a.exc_value}")

    def check(name, run):
        try:
            detail = run()
            print(f"ok    {name}" + (f": {detail}" if detail else ""), flush=True)
        except BaseException as e:  # SystemExit from a module counts as a failure here
            failed.append(name)
            print(f"FAIL  {name}: {e!r}", flush=True)

    def window_turn():
        from PyQt6.QtWidgets import QApplication
        from eli_tools import config as eli_config
        app = QApplication.instance() or QApplication([])
        import eli_pro_audio_gui_MKI as gui
        conversations = eli_config.artifacts_dir() / "conversations"
        before = set(conversations.glob("*.json")) if conversations.is_dir() else set()
        w = gui.ELIEntropicGUI()
        w.show()
        settle = time.time() + 5  # the start-up messages appear over the first seconds
        while time.time() < settle:
            app.processEvents()
            time.sleep(0.05)
        sent = len(w.conversation_log)
        w.input_field.setText("Reply with one word: hello")
        w.process_input_stream()
        deadline = time.time() + 600
        while time.time() < deadline:
            app.processEvents()
            worker = getattr(w, "worker", None)
            if worker is not None and worker.isFinished():
                break
            time.sleep(0.05)
        else:
            raise RuntimeError("no reply within 10 minutes")
        for _ in range(40):
            app.processEvents()
            time.sleep(0.02)
        replies = [e.get("message", "") for e in w.conversation_log[sent:] if e.get("source") in ("ELI", "ERROR")]
        w.close()
        app.processEvents()
        if not replies:
            raise RuntimeError("the window showed no reply")
        reply = replies[-1]
        if real_chat and any(m in reply for m in ("Ollama is not running", "No model found", "Chat failed", "could not run")):
            raise RuntimeError(f"no model answered: {reply!r}")
        saved = (set(conversations.glob("*.json")) if conversations.is_dir() else set()) - before
        if not saved:
            raise RuntimeError(f"closing the window saved no conversation in {conversations}")
        return f"{w.windowTitle()}; reply {reply[:60]!r}; conversation saved to {sorted(saved)[-1]}"

    def documents_window():
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        import eli_pro_audio_gui_MKII as gui2
        w = gui2.ELIWindow()
        w.show()
        app.processEvents()
        title = w.windowTitle()
        w.close()
        app.processEvents()
        return title

    def voice_assistant():
        import Eli_PC_Control2_Working as voice
        return f"wake words {', '.join(voice.WAKE)}"

    def speech_recognition():
        import speech_recognition as sr
        from eli_tools.audio_stt import transcribe
        wav = os.environ.get("ELI_SELFTEST_WAV")
        if wav:
            with sr.AudioFile(wav) as source:
                audio = sr.Recognizer().record(source)
            text = transcribe(audio)
            if not text:
                raise RuntimeError("no words came back")
            return repr(text)
        try:
            transcribe(sr.AudioData(b"\0\0" * 16000, 16000, 2))
        except sr.UnknownValueError:
            return "model loads (silence gives no words)"
        return "model loads"

    def microphone():
        import pyaudio
        return f"PortAudio {pyaudio.get_portaudio_version_text()}"

    def speech_output():
        import pyttsx3  # noqa: F401
        return ""

    def documents():
        import pypdf  # noqa: F401
        from eli_tools.advanced_doc_generator import AdvancedDocumentGenerator  # noqa: F401
        return ""

    check("window: a message sent and the window closed", window_turn)
    check("documents window", documents_window)
    check("voice assistant", voice_assistant)
    check("speech recognition (local Whisper)", speech_recognition)
    check("microphone capture", microphone)
    check("speech output", speech_output)
    check("documents", documents)
    if telemetry_queue.exists() and not queue_existed:
        failed.append("telemetry")
        print(f"FAIL  telemetry: onnxruntime created its upload queue in {telemetry_queue}", flush=True)
    else:
        print(f"ok    no telemetry (ORT_DISABLE_TELEMETRY={os.environ.get('ORT_DISABLE_TELEMETRY')})", flush=True)
    if errors:
        failed.append("errors raised inside the app")
        print("FAIL  errors raised inside the app (window events, threads):", flush=True)
        for e in errors[:10]:
            print(f"        {e}", flush=True)
    if code_writes:
        failed.append("writes into AI_Eli's own folder")
        print("FAIL  writes into AI_Eli's own folder (read-only when packaged):", flush=True)
        for w in sorted(set(code_writes))[:20]:
            print(f"        {w}", flush=True)
    print("selftest OK" if not failed else f"selftest FAILED: {', '.join(failed)}", flush=True)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(1 if failed else 0)  # background threads must not hold the exit


def main() -> int:
    _prepare()
    args = sys.argv[1:]
    mode = args[0] if args else ""
    if mode == "-m" and len(args) > 1:
        import runpy
        sys.argv = [args[1]] + args[2:]
        runpy.run_module(args[1], run_name="__main__", alter_sys=True)
        return 0
    if mode.endswith(".py") and os.path.isfile(mode):
        import runpy
        sys.argv = args
        runpy.run_path(mode, run_name="__main__")
        return 0
    sys.argv = [sys.argv[0]] + args[1:]
    if mode == "--selftest":
        return selftest()
    if mode == "--voice":
        import Eli_PC_Control2_Working as voice
        return voice.main() or 0
    if mode == "--documents":
        import eli_pro_audio_gui_MKII as gui
        return gui.main() or 0
    if mode == "--terminal":
        from eli_tools import eli_terminal
        return eli_terminal.main() or 0
    if mode in ("-h", "--help"):
        print(__doc__)
        return 0
    if mode:
        sys.argv.insert(1, mode)
    import eli_pro_audio_gui_MKI as gui
    return gui.main() or 0


if __name__ == "__main__":
    sys.exit(main())
