AI_Eli, the earliest version of ELI: a local voice assistant for Linux that runs on Ollama.

## Get started

1. Install [Ollama](https://ollama.com) and pull any chat model:
   ```bash
   curl -fsSL https://ollama.com/install.sh | sh
   ollama pull qwen2.5:1.5b
   ```
2. Download `AI_Eli-0.1.1-x86_64.AppImage`, make it executable and open it:
   ```bash
   chmod +x AI_Eli-0.1.1-x86_64.AppImage
   ./AI_Eli-0.1.1-x86_64.AppImage
   ```

Everything else is inside the AppImage: Python and all its libraries, the desktop windows, the voice assistant and the Whisper speech model, so speech recognition works offline. AI_Eli talks to the newest chat model in your Ollama unless you name another.

| Command | |
|---|---|
| `./AI_Eli-0.1.1-x86_64.AppImage` | the desktop window |
| `./AI_Eli-0.1.1-x86_64.AppImage --voice` | the hands-free voice assistant (say "Eli" first) |
| `./AI_Eli-0.1.1-x86_64.AppImage --documents` | the PDF and memory window |
| `./AI_Eli-0.1.1-x86_64.AppImage --terminal` | chat in the terminal |

## Its own folders and settings

AI_Eli keeps everything in its own folders, apart from any other ELI version: what it remembers in `~/.local/share/AI_Eli`, settings in `~/.config/AI_Eli/config` as `KEY=VALUE` lines (the README lists them), for example `ELI_MODEL=llama3.2`. A variable named with `AI_ELI_` in place of `ELI_` works too: `AI_ELI_MODEL=llama3.2 ./AI_Eli-0.1.1-x86_64.AppImage`. Plain `ELI_` variables belong to other ELI versions and are ignored.

## Fixed since 0.1.0

- 0.1.0 kept its settings and chat state in `~/.eli_config`, `~/.eli_state.json` and `~/.eli_memory.jsonl`, names other ELI versions could share. They are in AI_Eli's own folders now.
- The window saved conversations to whatever folder it was started from; they go to AI_Eli's folder now.
- Settings exported for another ELI version (such as `ELI_FULL_CONTROL`) no longer reach AI_Eli.
- The speech model's onnxruntime queued usage telemetry for Microsoft. That is switched off.

## Needs

- Linux on x86_64 with glibc 2.35 or newer (Ubuntu 22.04, Debian 12, Fedora 36 or later)
- PulseAudio or PipeWire, and `espeak-ng` for the spoken replies
- If your system will not open AppImages, run it with `--appimage-extract-and-run`

`SHA256SUMS.txt` holds the file's checksum. Apache 2.0.
