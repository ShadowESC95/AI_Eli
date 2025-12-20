import re, json
from pathlib import Path

# --- LaTeX math ---
DISPLAY_PATS = [
    re.compile(r"\$\$(.+?)\$\$", re.S),
    re.compile(r"\\\[(.+?)\\\]", re.S),
    re.compile(r"\\begin\{equation\*?\}(.+?)\\end\{equation\*?\}", re.S),
    re.compile(r"\\begin\{align\*?\}(.+?)\\end\{align\*?\}", re.S),
    re.compile(r"\\begin\{gather\*?\}(.+?)\\end\{gather\*?\}", re.S),
]
INLINE_PATS = [
    re.compile(r"(?<!\$)\$(.+?)(?<!\$)\$", re.S),        # \(inline\)
    re.compile(r"\\\((.+?)\\\)", re.S),                  # \( ... \)
]

# --- Heuristic plain-text math lines ---
# contains "=" plus at least one "mathy" token (∇ ∂ ∑ ∫ greek subscripts etc.)
GREEK = "α-ωΑ-Ω"
MATH_CHARS = r"∇∂∑∫≈≃≅≡≤≥⊂⊃⊆⊇∈∉∪∩⋅·×∘→↦±⊕⊗"
SUBSUP = r"_\{[^}]+\}|\^[^\s=+*/)\]]+"
TOKEN = rf"[A-Za-z{GREEK}][A-Za-z0-9{GREEK}_]*({SUBSUP})?"
MATH_LINE = re.compile(
    rf"""
    ^                                     # whole line
    (?!\s*%)                              # not a TeX comment
    .{{0,8}}                              # small lead-in
    (?=.*=)                               # must contain equals
    (?:
        .*[{MATH_CHARS}]                  # or a math symbol
      | .*{TOKEN}.*{TOKEN}                # or at least two tokens
    )
    .*$                                   # rest of line
    """,
    re.X,
)

# Recognize lines that look like numbered equations: "(12)" at start or end
NUMBERED_LINE = re.compile(r"^\s*\(\s*\d+\s*\).+|.+\(\s*\d+\s*\)\s*$")

def _clean(s: str) -> str:
    return s.strip().strip("`")

def harvest_regex(txt_dir: str, out_json: str):
    items = []
    for txtf in sorted(Path(txt_dir).glob("*.txt")):
        text = Path(txtf).read_text(encoding="utf-8", errors="ignore")

        # 1) LaTeX display blocks
        for pat in DISPLAY_PATS:
            for m in pat.finditer(text):
                body = _clean(m.group(1))
                if body:
                    items.append({"file": txtf.name, "page_guess": None, "eq_label": None, "latex": body})

        # 2) LaTeX inline
        for pat in INLINE_PATS:
            for m in pat.finditer(text):
                body = _clean(m.group(1))
                if 3 <= len(body) <= 200:
                    items.append({"file": txtf.name, "page_guess": None, "eq_label": None, "latex": body})

        # 3) Heuristic plain-text equations (line-based)
        #    - Keep shortish lines to avoid scooping full paragraphs
        for ln in text.splitlines():
            s = ln.strip()
            if not s:
                continue
            if len(s) > 260:
                continue
            if MATH_LINE.search(s) or NUMBERED_LINE.search(s):
                # avoid double-catching already-LaTeX-delimited lines
                if not (s.startswith("$$") or s.startswith(r"\[") or "$" in s):
                    items.append({"file": txtf.name, "page_guess": None, "eq_label": None, "latex": s})

    Path(out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(out_json).write_text(json.dumps(items, indent=2), encoding="utf-8")
    print(f"[regex-harvest] {txt_dir} -> {out_json} : {len(items)} equations")

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-txt-dir", default="data/cache")
    ap.add_argument("--out", default="data/cache/equations_regex.json")
    a = ap.parse_args()
    harvest_regex(a.pdf_txt_dir, a.out)
