import os
import sys
from pathlib import Path

from fastapi import FastAPI, Request
import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from eli_tools import config as eli_config

OLLAMA_URL = f"{eli_config.ollama_base()}/api/chat"
MODEL = eli_config.chat_model()
PORT = int(os.environ.get("ELI_PROXY_PORT", "18080"))

ELI_SYSTEM = (HERE / "eli_system.txt").read_text(encoding="utf-8").strip()

app = FastAPI()

@app.post("/chat")
async def chat(req: Request):
    data = await req.json()

    user_msg = ""
    if "messages" in data and isinstance(data["messages"], list):
        for m in data["messages"]:
            if m.get("role") == "user":
                user_msg = m.get("content", "")
    elif "prompt" in data:
        user_msg = data["prompt"]

    payload = {
        "model": MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": ELI_SYSTEM},
            {"role": "user", "content": user_msg}
        ]
    }

    r = requests.post(OLLAMA_URL, json=payload, timeout=180)
    r.raise_for_status()
    out = r.json()
    content = out.get("message", {}).get("content", "")

    return {"reply": content, "status": "ok"}

if __name__ == "__main__":
    import uvicorn
    if not MODEL:
        raise SystemExit("Set ELI_MODEL to an Ollama model you have pulled (see `ollama list`).")
    uvicorn.run(app, host=os.environ.get("ELI_PROXY_HOST", "127.0.0.1"), port=PORT)
