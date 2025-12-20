import os, time, re, tempfile, subprocess
import numpy as np
import sounddevice as sd
import soundfile as sf
from faster_whisper import WhisperModel

HOST = os.uname().nodename.lower()

def clip_set(text):
    sess = os.environ.get("XDG_SESSION_TYPE","").lower()
    if sess == "x11":
        p = subprocess.Popen(["xclip","-selection","clipboard"], stdin=subprocess.PIPE, text=True)
        p.communicate(text); return
    p = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE, text=True)
    p.communicate(text)

def record_utterance(sr=16000, chunk=0.05, start_rms=0.02, end_silence=0.8, max_s=12):
    frames=[]
    block = int(sr*chunk)
    silence=0.0
    started=False
    t0=time.time()
    with sd.InputStream(samplerate=sr, channels=1, blocksize=block, dtype="float32") as s:
        while True:
            data,_ = s.read(block)
            x = data[:,0]
            rms = float(np.sqrt(np.mean(x*x)) + 1e-12)
            if not started and rms >= start_rms:
                started=True
            if started:
                frames.append(x.copy())
                silence = silence + chunk if rms < start_rms else 0.0
            if started and silence >= end_silence:
                break
            if time.time()-t0 > max_s:
                break
    if not frames:
        return None, sr
    return np.concatenate(frames), sr

model = WhisperModel("small", device="cpu", compute_type="int8")

print("ELI listen running.")
print("Say: 'rig open firefox' / 'ghost mute' / 'both volume up'. Ctrl+C to stop.")

while True:
    audio, sr = record_utterance()
    if audio is None or len(audio) < sr*0.2:
        continue

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as f:
        sf.write(f.name, audio, sr)
        segments, _ = model.transcribe(f.name, vad_filter=True)
        text = " ".join(seg.text.strip() for seg in segments).strip()

    if not text:
        continue

    m = re.match(r'^(ghost|rig|both)\s+(.*)$', text.lower())
    if m:
        tgt, cmd = m.group(1), m.group(2)
        out = f"eli@{tgt}: {cmd}"
    else:
        out = f"eli@{HOST}: {text}"

    print("->", out)
    clip_set(out)
