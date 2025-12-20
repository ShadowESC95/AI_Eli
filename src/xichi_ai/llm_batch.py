import argparse
import json
import re
from pathlib import Path
from .llm.ollama_client import OllamaClient
from .validation.validator import validate_equations_json

PROMPT = """SYSTEM: Return ONLY a JSON ARRAY (even if 1 item). No prose, no markdown.
Each item MUST be an object with fields:
- "file": string (we will overwrite)
- "page_guess": integer or null
- "eq_label": string or null
- "latex": string containing LaTeX MATH ONLY (no English sentences).
Valid examples for "latex": expressions with =, \\frac, \\nabla, \\partial, \\int, \\sum, F_{\\mu\\nu}, g_{\\mu\\nu}, etc.
INVALID: descriptive sentences or variable definitions written in English.
Return: JSON array ONLY."""

MATH_RE = re.compile(r"(=|\\\\frac|\\\\nabla|\\\\partial|\\\\int|\\\\sum|_\\{|\\^\\{|F_\\{|g_\\\\{|\\\\cdot|\\\\times)")

def _is_math(s: str) -> bool:
    if not isinstance(s, str):
        return False
    t = s.strip()
    if not t:
        return False
    # reject obvious sentences without math tokens
    if t.endswith(".") and not MATH_RE.search(t):
        return False
    return bool(MATH_RE.search(t))

def chunk_text(s: str, max_chars: int):
    paras = s.split("\n\n")
    chunks = []
    cur = ""
    for p in paras:
        if len(cur) + len(p) + 2 <= max_chars:
            cur += (("\n\n" if cur else "") + p)
        else:
            if cur:
                chunks.append(cur)
                cur = ""
            while len(p) > max_chars:
                chunks.append(p[:max_chars])
                p = p[max_chars:]
            cur = p
    if cur:
        chunks.append(cur)
    return chunks

def _try_parse_json(raw: str):
    """Best effort to parse a JSON array out of model output."""
    if not isinstance(raw, str):
        return None
    s = raw.strip()

    # Strip ``` fences if present
    if s.startswith("```"):
        s = re.sub(r"^```[^\n]*\n", "", s, flags=re.S)
        s = re.sub(r"\n```$", "", s)

    s = s.strip("` \n\t\r")

    # Try to find first [...] block
    i = s.find('[')
    j = s.rfind(']')
    if i != -1 and j != -1 and j > i:
        cand = s[i:j+1]
        try:
            parsed = json.loads(cand)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass

    # Fallback: parse entire string
    try:
        parsed = json.loads(s)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]  # accept single-object replies
    except Exception:
        return None

def harvest_batched(pdf_txt_dir, model, out_json, max_chars):
    client = OllamaClient(model=model)
    all_items = []

    txt_files = sorted(Path(pdf_txt_dir).glob("*.txt"))
    print(f"[harvest-batched] scanning {len(txt_files)} files; model={model}")

    for txtf in txt_files:
        text = txtf.read_text(encoding="utf-8", errors="ignore")
        for idx, chunk in enumerate(chunk_text(text, max_chars), 1):
            messages = [
                {"role": "system", "content": PROMPT},
                {"role": "user", "content": f"# FILE: {txtf.name}\n# CHUNK: {idx}\n\n{chunk}"}
            ]
            raw = client.chat(messages, stream=False, options={"temperature": 0})
            parsed = _try_parse_json(raw)
            if not parsed:
                Path("out").mkdir(exist_ok=True, parents=True)
                dbg = f"out/harvest_batch_error_{txtf.stem}_{idx}.txt"
                Path(dbg).write_text(raw if isinstance(raw, str) else str(raw), encoding="utf-8")
                print(f"[warn] batch {txtf.name} #{idx} not valid JSON; saved debug -> {dbg}")
                continue

            for it in parsed:
                if isinstance(it, dict):
                    # keep only plausible math
                    if not _is_math(it.get("latex", "")):
                        continue
                    it["file"] = txtf.name
                    all_items.append(it)

    if not all_items:
        print("[harvest-batched] no valid items collected; writing empty array.")
        Path(out_json).parent.mkdir(parents=True, exist_ok=True)
        Path(out_json).write_text("[]", encoding="utf-8")
        return

    # Validate and persist
    validated = validate_equations_json(all_items)
    Path(out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(out_json).write_text(json.dumps(validated, indent=2), encoding="utf-8")
    print(f"[harvest-batched] wrote {out_json} with {len(validated)} equations.")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("task", choices=["harvest-batched"])
    ap.add_argument("--model", required=True)
    ap.add_argument("--pdf-txt-dir", default="data/cache")
    ap.add_argument("--out", default="data/cache/equations_llm.json")
    ap.add_argument("--max-chars", type=int, default=12000)
    a = ap.parse_args()
    if a.task == "harvest-batched":
        harvest_batched(a.pdf_txt_dir, a.model, a.out, a.max_chars)

if __name__ == "__main__":
    main()

