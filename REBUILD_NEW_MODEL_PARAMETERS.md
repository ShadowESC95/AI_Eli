# stay in the folder with your Modelfile
sed -i 's/\r$//' Modelfile.qwen32                      # strip CRLF just in case
grep -o '"""' Modelfile.qwen32 | wc -l                 # must be even (2, 4, …)

ollama rm xichi-analyst-qwen32 2>/dev/null || true
ollama create xichi-analyst-qwen32 -f Modelfile.qwen32

# verify the baked-in system text includes your name & tone
ollama show xichi-analyst-qwen32 --system | sed -n '1,120p'

# quick test — the reply should address you as Jay and carry the tone
printf 'who are you?\n' | ollama run xichi-analyst-qwen32
