import os, sqlite3, json, math, subprocess, textwrap
from pathlib import Path
from typing import List, Tuple
import requests

ROOT = Path(__file__).resolve().parents[2]  # project root
DATA_IN = ROOT / "data" / "input"
DATA_TXT = ROOT / "data" / "cache"
DB = ROOT / "data" / "cache" / "xichi_rag.sqlite"

EMBED_MODEL = os.environ.get("XICHI_EMBED_MODEL", "mxbai-embed-large")
GEN_MODEL   = os.environ.get("XICHI_GEN_MODEL") or os.environ.get("ELI_MODEL") or "xichi-analyst-qwen32:2025-12-09a"

MAX_CHARS = 1800
OVERLAP   = 200
TOP_K     = 12
NUM_CTX   = int(os.environ.get("XICHI_NUM_CTX", "16384"))

def pdftotext(pdf: Path) -> str:
    # robust for Unicode filenames and spaces
    r = subprocess.run(
        ["pdftotext", "-layout", str(pdf), "-"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True
    )
    return r.stdout.decode("utf-8", errors="ignore")

def chunk_text(s: str, size=MAX_CHARS, overlap=OVERLAP) -> List[str]:
    s = s.replace("\0","")
    out=[]
    i=0; n=len(s)
    while i < n:
        j=min(i+size, n)
        out.append(s[i:j])
        i = max(0, j - overlap)
        if i >= n: break
    return out

def ensure_db():
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS chunks(
        id INTEGER PRIMARY KEY,
        doc TEXT,
        idx INTEGER,
        text TEXT,
        vec TEXT  -- JSON list for simplicity/portability
    )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_doc ON chunks(doc)")
    con.commit(); con.close()

def _embed_batch(payload) -> List[List[float]]:
    r = requests.post("http://localhost:11434/api/embeddings", json=payload, timeout=120)
    r.raise_for_status()
    data = r.json()
    if "embeddings" in data: return data["embeddings"]
    if "embedding"  in data: return [data["embedding"]]
    raise RuntimeError(f"Unexpected embeddings response: {data}")

def embed_texts(texts: List[str]) -> List[List[float]]:
    # batch to keep payloads small
    B=8; out=[]
    for i in range(0, len(texts), B):
        out.extend(_embed_batch({"model": EMBED_MODEL, "prompt": texts[i:i+B]}))
    return out

def index_pdfs():
    ensure_db()
    con = sqlite3.connect(DB); cur = con.cursor()

    indexed = {row[0] for row in cur.execute("SELECT DISTINCT doc FROM chunks")}
    pdfs = sorted(p for p in DATA_IN.glob("*.pdf"))
    to_index = [p for p in pdfs if p.name not in indexed]

    if not to_index:
        print("Index is up to date (PDFs)."); con.close(); return

    for pdf in to_index:
        print(f"[index] {pdf.name}")
        txt = pdftotext(pdf)
        pieces = chunk_text(txt)
        vecs = embed_texts(pieces)
        for i,(t,v) in enumerate(zip(pieces,vecs)):
            cur.execute("INSERT INTO chunks(doc,idx,text,vec) VALUES(?,?,?,?)",
                        (pdf.name, i, t, json.dumps(v)))
        con.commit()
    con.close()
    print("Done.")

def index_txt():
    ensure_db()
    con = sqlite3.connect(DB); cur = con.cursor()

    indexed = {row[0] for row in cur.execute("SELECT DISTINCT doc FROM chunks")}
    txts = sorted(DATA_TXT.glob("*.txt"))
    to_index = [p for p in txts if p.name not in indexed]

    if not to_index:
        print("Index is up to date (TXT)."); con.close(); return

    for txtp in to_index:
        print(f"[index] {txtp.name}")
        txt = txtp.read_text(encoding="utf-8", errors="ignore")
        pieces = chunk_text(txt)
        vecs = embed_texts(pieces)
        for i,(t,v) in enumerate(zip(pieces,vecs)):
            cur.execute("INSERT INTO chunks(doc,idx,text,vec) VALUES(?,?,?,?)",
                        (txtp.name, i, t, json.dumps(v)))
        con.commit()
    con.close()
    print("Done.")

def cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x*y for x,y in zip(a,b))
    na = math.sqrt(sum(x*x for x in a)) or 1e-9
    nb = math.sqrt(sum(y*y for y in b)) or 1e-9
    return dot/(na*nb)

def retrieve(query: str, k=TOP_K):
    qv = embed_texts([query])[0]
    con = sqlite3.connect(DB); cur = con.cursor()
    rows = list(cur.execute("SELECT doc, idx, text, vec FROM chunks"))
    scored=[]
    for doc, idx, text, vecj in rows:
        v = json.loads(vecj)
        s = cosine(qv, v)
        scored.append((s, doc, idx, text))
    scored.sort(reverse=True, key=lambda x: x[0])
    con.close()
    return scored[:k]

def generate(prompt: str) -> str:
    r = requests.post("http://localhost:11434/api/generate", json={
        "model": GEN_MODEL,
        "prompt": prompt,
        "options": {"num_ctx": NUM_CTX}
    }, stream=True, timeout=600)
    r.raise_for_status()
    out=[]
    for line in r.iter_lines():
        if not line: continue
        j = json.loads(line.decode())
        if "response" in j: out.append(j["response"])
    return "".join(out)

def ask(query: str):
    hits = retrieve(query)
    blocks=[]
    for i,(score, doc, idx, text) in enumerate(hits,1):
        head=f"[{i}] {doc} :: chunk {idx} :: score {score:.3f}"
        body=textwrap.shorten(text.replace("\n","\n"), 2000, placeholder=" […] ")
        blocks.append(head+"\n"+body)
    context="\n\n".join(blocks)
    prompt=f"""You are XiChi-Analyst. Use ONLY the Context.

Context:
{context}

Task:
{query}

Rules:
- Cite chunks like [1], [2] inline where evidence came from.
- If a needed detail is missing from Context, say so explicitly.
- Prefer equations with labels; output LaTeX tables when mapping equations.
"""
    print(generate(prompt))

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m xichi_ai.rag [index-pdf|index-txt|ask 'question']")
        raise SystemExit(1)
    cmd = sys.argv[1]
    if cmd == "index-pdf":
        index_pdfs()
    elif cmd == "index-txt":
        index_txt()
    elif cmd == "ask":
        q = " ".join(sys.argv[2:])
        ask(q)
    else:
        print("Unknown command")

