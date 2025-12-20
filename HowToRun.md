# Terminal 1
cd ~/Desktop/AI_Eli
source ./.env && source .venv/bin/activate
python eli_voice/eli_unified.py

# Terminal 2 (optional)
source ./.env && source .venv/bin/activate
python eli_control/eli_agent.py

# Terminal 3 (clipboard, after patch)
source ./.env && source .venv/bin/activate
python eli_clipboard_agent.py
