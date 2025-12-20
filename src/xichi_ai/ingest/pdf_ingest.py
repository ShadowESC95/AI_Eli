import os
from pathlib import Path
from pdfminer.high_level import extract_text

def ingest_pdfs(pdf_dir: str):
    pdf_dir = Path(pdf_dir)
    out_dir = Path("data/cache")
    out_dir.mkdir(parents=True, exist_ok=True)
    for pdf in pdf_dir.glob("*.pdf"):
        try:
            txt = extract_text(str(pdf))
        except Exception as e:
            print(f"[ingest] failed {pdf}: {e}")
            continue
        out_path = out_dir / (pdf.stem + ".txt")
        out_path.write_text(txt, encoding="utf-8")
        print(f"[ingest] {pdf.name} -> {out_path}")
