The first release of AI_Eli, the earliest version of ELI: a local voice assistant for Linux that runs on Ollama.

## Get started

1. Install [Ollama](https://ollama.com) and pull any chat model:
   ```bash
   curl -fsSL https://ollama.com/install.sh | sh
   ollama pull qwen2.5:1.5b
   ```
2. Download `AI_Eli-0.1.0-x86_64.AppImage`, make it executable and open it:
   ```bash
   chmod +x AI_Eli-0.1.0-x86_64.AppImage
   ./AI_Eli-0.1.0-x86_64.AppImage
   ```

Everything else is inside the AppImage: Python and all its libraries, the desktop windows, the voice assistant and the Whisper speech model, so speech recognition works offline. AI_Eli talks to the newest chat model in your Ollama unless `ELI_MODEL` names another.

| Command | |
|---|---|
| `./AI_Eli-0.1.0-x86_64.AppImage` | the desktop window |
| `./AI_Eli-0.1.0-x86_64.AppImage --voice` | the hands-free voice assistant (say "Eli" first) |
| `./AI_Eli-0.1.0-x86_64.AppImage --documents` | the PDF and memory window |
| `./AI_Eli-0.1.0-x86_64.AppImage --terminal` | chat in the terminal |

AI_Eli keeps its files in `~/.local/share/AI_Eli`. Settings go in `~/.eli_config` as `KEY=VALUE` lines; the README lists them.

## Needs

- Linux on x86_64 with glibc 2.35 or newer (Ubuntu 22.04, Debian 12, Fedora 36 or later)
- PulseAudio or PipeWire, and `espeak-ng` for the spoken replies
- If your system will not open AppImages, run it with `--appimage-extract-and-run`

`SHA256SUMS.txt` holds the file's checksum. Apache 2.0.
