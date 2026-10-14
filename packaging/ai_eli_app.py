"""AI_Eli as one program (the entry point of the packaged app).

    AI_Eli                the desktop window
    AI_Eli --voice        the hands-free voice assistant (say "Eli" first)
    AI_Eli --documents    the PDF and memory window
    AI_Eli --terminal     chat in the terminal
    AI_Eli --selftest     check that everything in the package loads, then exit
"""

import os
import sys
from pathlib import Path


def _prepare() -> None:
    # Programs AI_Eli starts (espeak, paplay, xdg-open, playerctl, ...) must load this system's
    # libraries, not the ones packed inside the app.
    original = os.environ.pop("LD_LIBRARY_PATH_ORIG", None)
    if original:
        os.environ["LD_LIBRARY_PATH"] = original
    else:
        os.environ.pop("LD_LIBRARY_PATH", None)

    bundle = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    whisper = bundle / "whisper-base"
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
    """Load every part of the package. ELI_SELFTEST_WAV: a recording whose words must come back.
    ELI_SELFTEST_CHAT=1: also ask the Ollama model one question."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if os.environ.get("ELI_SELFTEST_CHAT") != "1":
        # the voice assistant will not start without a model name; no model is asked anything here
        os.environ.setdefault("ELI_MODEL", "selftest")
    failed = []

    def check(name, run):
        try:
            detail = run()
            print(f"ok    {name}" + (f": {detail}" if detail else ""), flush=True)
        except BaseException as e:  # SystemExit from a module counts as a failure here
            failed.append(name)
            print(f"FAIL  {name}: {e!r}", flush=True)

    def windows():
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        import eli_pro_audio_gui_MKI as gui1
        import eli_pro_audio_gui_MKII as gui2
        titles = [gui1.ELIEntropicGUI().windowTitle(), gui2.ELIWindow().windowTitle()]
        app.processEvents()
        return " / ".join(titles)

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

    def chat():
        from eli_tools.compat import execute
        reply = execute("CHAT", {"message": "Reply with one word: hello"})
        if not reply.get("ok"):
            raise RuntimeError(reply.get("content"))
        return f"{reply.get('model')}: {reply.get('content', '')[:60]!r}"

    check("windows", windows)
    check("voice assistant", voice_assistant)
    check("speech recognition (local Whisper)", speech_recognition)
    check("microphone capture", microphone)
    check("speech output", speech_output)
    check("documents", documents)
    if os.environ.get("ELI_SELFTEST_CHAT") == "1":
        check("chat through Ollama", chat)
    print("selftest OK" if not failed else f"selftest FAILED: {', '.join(failed)}", flush=True)
    return 1 if failed else 0


def main() -> int:
    _prepare()
    args = sys.argv[1:]
    mode = args[0] if args else ""
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
