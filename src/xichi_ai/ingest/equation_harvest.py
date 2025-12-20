import re, json
from pathlib import Path

# naive LaTeX-ish display math sniffing in text; improve for your PDFs
EQN_PATTERNS = [
    r"\$\$.*?\$\$",
    r"\\\[.*?\\\]",
    r"\\begin\{equation\}.*?\\end\{equation\}",
    r"\\begin\{align\}.*?\\end\{align\}",
]

def harvest_equations():
    cache = Path("data/cache")
    equations = []
    for txtf in cache.glob("*.txt"):
        text = txtf.read_text(encoding="utf-8", errors="ignore")
        hits = []
        for pat in EQN_PATTERNS:
            hits += re.findall(pat, text, flags=re.DOTALL)
        for i, h in enumerate(hits, 1):
            equations.append({
                "file": txtf.name.replace(".txt",""),
                "local_id": f"{txtf.stem}:eq{i:03d}",
                "latex": h.strip()
            })
    out = cache / "equations.json"
    out.write_text(json.dumps(equations, indent=2), encoding="utf-8")
    print(f"[harvest] wrote {out} with {len(equations)} eqs.")
