# AI_Eli

An early version of ELI (Entropic Logical Interpreter), a local voice assistant for Linux that runs on Ollama. It listens for a wake word, works out what you asked, and either answers or does it on the PC: opening apps, folders and websites, media and volume, reading and writing files, making documents, and summarising PDFs.

Everything runs on your own machine: the model through your local Ollama, and speech recognition through Whisper (faster-whisper). The first time you speak to it, the Whisper model is downloaded once from Hugging Face.

## Download

The [releases page](https://github.com/ShadowESC95/AI_Eli/releases) has a ready-to-run Linux AppImage. The rest of this page is for running it from source.

## What you need

- Linux with PulseAudio or PipeWire
- Python 3.10 or newer
- [Ollama](https://ollama.com) with any chat model pulled
- A few system tools: `espeak-ng`, `pulseaudio-utils` (for `paplay`), `libportaudio2`, `xdg-utils`, `playerctl`, and `wl-clipboard` or `xclip`

On Ubuntu or Debian:

```bash
sudo apt install espeak-ng pulseaudio-utils libportaudio2 xdg-utils playerctl wl-clipboard
```

## Setup

```bash
git clone https://github.com/ShadowESC95/AI_Eli.git
cd AI_Eli
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
ollama pull <any-model>
```

Then tell ELI which model to use. Put settings in `~/.eli_config` as `KEY=VALUE` lines, or export them:

```
ELI_MODEL=<any-model>
ELI_USER_NAME=<your name>
```

## Run

| What | Command |
|---|---|
| Voice assistant | `python Eli_PC_Control2_Working.py` |
| List microphones | `python Eli_PC_Control2_Working.py --list-devices`, then set `ELI_AUDIO_IN` |
| Desktop window | `python eli_pro_audio_gui_MKI.py` |
| PDF and memory window | `python eli_pro_audio_gui_MKII.py` |
| Terminal chat | `python -m eli_tools.eli_terminal` |

Say "Eli" or "hey Eli" (or "computer") before a request. Typing, key presses and pasting into other windows stay off until you say "activate full control", which lasts a minute. `ELI_REQUIRE_ARM=0` turns that check off.

To summarise PDFs, put them in `data/input` and say "analyse my PDFs". The summary lands in `artifacts/`.

## Optional

- **Persona.** `scripts/build_persona_model.sh <any-model>` builds an `eli-persona` model from `modelfiles/eli-persona.Modelfile` on top of the model you choose. Then set `ELI_MODEL=eli-persona`.
- **Better voice.** `scripts/get_piper_voice.sh` downloads a Piper voice into `eli_tools/voices`. Install [Piper](https://github.com/rhasspy/piper) and set `ELI_TTS_ENGINE=piper`.
- **Mic button in the desktop window** needs PyAudio (`sudo apt install portaudio19-dev && pip install pyaudio`).
- **Two machines with a shared clipboard.** `eli_tools/eli_listen.py` turns speech into `eli@<hostname>: ...` on the clipboard, and `eli_tools/eli_agent.py`, running on each machine, carries out the ones meant for it. Set `ELI_ALIAS_A` and `ELI_ALIAS_B` to the two hostnames.

## Settings

| Setting | Default | |
|---|---|---|
| `ELI_MODEL` | none | Ollama model for chat (also read from `ELI_CHAT_MODEL` or `OLLAMA_MODEL`) |
| `ELI_ROUTER_MODEL` | `ELI_MODEL` | a smaller model for working out commands |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | where Ollama is |
| `ELI_USER_NAME` | none | what ELI calls you |
| `ELI_WAKE` | `computer,eli,hey eli,okay eli` | wake words |
| `ELI_ALWAYS_AWAKE` | `0` | `1` answers without a wake word |
| `ELI_AUDIO_IN` | system default | microphone, by number or name |
| `ELI_SR` | the mic's own rate | microphone sample rate |
| `ELI_OUTPUT_DEVICE` | system default | PulseAudio sink to speak through |
| `ELI_WHISPER` | `base` | Whisper model size |
| `ELI_WHISPER_DEVICE` | `cpu` | `cuda` for an NVIDIA card |
| `ELI_TTS_ENGINE` | `espeak` | or `piper` |
| `ELI_PIPER_MODEL` | `eli_tools/voices/en_US-amy-medium.onnx` | Piper voice file |
| `ELI_ARTIFACTS_DIR` | `./artifacts` | where documents and summaries go |
| `ELI_CONFIG` | `~/.eli_config` | another settings file |

What ELI remembers is kept in `data/`, `artifacts/`, `~/.eli_state.json` and `~/.eli_memory.jsonl`, none of which go into git.

## Licence

Apache 2.0, see [LICENSE](LICENSE).
