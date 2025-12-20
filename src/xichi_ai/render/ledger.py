import json
from pathlib import Path

HEADER = r"""\
\documentclass[11pt,a4paper]{article}
\usepackage{amsmath,amssymb,mathtools}
\usepackage{geometry}
\geometry{margin=1in}
\title{Master Equation Ledger (Ξ–χ–φ–A_E–A_B–G)}
\author{Automated Builder}
\begin{document}
\maketitle
\tableofcontents
\newpage
"""
FOOTER = r"""\
\end{document}
"""

def build_master_ledger(out_path: str):
    eqf = Path("data/cache/equations.json")
    out = Path(out_path)
    if not eqf.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(HEADER + "No equations harvested.\n" + FOOTER, encoding="utf-8")
        print("[ledger] no equations harvested; wrote empty ledger.")
        return

    eqs = json.loads(eqf.read_text(encoding="utf-8"))
    sections = {}
    for e in eqs:
        sections.setdefault(e["file"], []).append(e)

    body = []
    for fname, items in sections.items():
        body.append(f"\\section*{{{fname}}}\n")
        for e in items:
            body.append(f"\\subsection*{{{e['local_id']}}}\n")
            # Wrap as display math verbatim
            body.append("\\begin{align}\n")
            body.append(e["latex"].replace("\\[","").replace("\\]","").replace("$$","") + "\n")
            body.append("\\end{align}\n\n")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(HEADER + "".join(body) + FOOTER, encoding="utf-8")
    print(f"[ledger] wrote {out}")
