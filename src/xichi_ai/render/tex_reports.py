# src/xichi_ai/render/tex_reports.py
import json
import re
import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

# --------------------------
# LaTeX document scaffolding
# --------------------------

PREAMBLE = r"""
\documentclass[11pt]{article}
\usepackage{fontspec,unicode-math}
\setmainfont{Latin Modern Roman}
\setmathfont{Latin Modern Math}

% ---- AMS symbol shims (avoid amssymb clash with unicode-math) ----
\makeatletter
\AtBeginDocument{%
  \providecommand{\Box}{\square}%
  \providecommand{\qed}{\blacksquare}%
  \providecommand{\smallsetminus}{\setminus}%
}
\makeatother

% Math & utilities
\usepackage{amsmath,mathtools,physics,siunitx}
\sisetup{detect-all}

% Tables & refs
\usepackage{longtable,booktabs,array}
\usepackage[hidelinks]{hyperref}
\usepackage[a4paper,margin=1in]{geometry}
"""

CONTRACT_TOP = r"""
\begin{document}
\maketitle

\section*{Consistency Gate (pre-answer notes)}
% (Optional) Ambiguities, Conflicts, Sanity Checks, Questions.

\section*{Equation Audit Table}
\begin{longtable}{@{}l l l l p{0.55\textwidth}@{}}
\toprule
\textbf{ID} & \textbf{Eq (inline)} & \textbf{Source} & \textbf{Status} & \textbf{Notes/Conflicts}\\
\midrule
\endfirsthead
\toprule
\textbf{ID} & \textbf{Eq (inline)} & \textbf{Source} & \textbf{Status} & \textbf{Notes/Conflicts}\\
\midrule
\endhead
"""

CONTRACT_BOTTOM = r"""
\bottomrule
\end{longtable}

\section{Derivations (Detailed)}
% Add derivations D1..Dn here later if desired.

\section{Weak Forms (Simulation-Ready)}
% Test/trial functions, spaces, BC/IC, jump terms, units.

\section{Recovery Limits and Sanity Checks}
% Dimensional checks, limiting cases (Maxwell/GR/SR), sign conventions.

\section{Proposals \& Connected Dots}
% Independent proposals and testable predictions.

\appendix
\section{Appendix: Numbered Equations (Display)}
% Each equation from the audit, re-shown clearly.
"""

# --------------------------
# Helpers (escaping & detect)
# --------------------------

LATEX_HEUR = re.compile(
    r"(\\begin\{|\\end\{|(?<!\$)\$[^$].*?[^$]\$(?!\$)|\\\[|\\\]|\\frac|\\sum|\\int|\\nabla|\\partial|"
    r"\\alpha|\\beta|\\gamma|\\mathrm\{|\\mathbb\{|\\mathbf\{|\\vec\{|\\dot\{|\\hat\{)"
)

def looks_latex(s: str) -> bool:
    return isinstance(s, str) and bool(LATEX_HEUR.search(s))

def _tex_escape_text(s: str) -> str:
    if not isinstance(s, str):
        s = str(s)
    repl = {
        '\\': r'\textbackslash{}',
        '&': r'\&',
        '%': r'\%',
        '$': r'\$',
        '#': r'\#',
        '_': r'\_',
        '{': r'\{',
        '}': r'\}',
        '~': r'\textasciitilde{}',
        '^': r'\textasciicircum{}',
    }
    return ''.join(repl.get(ch, ch) for ch in s)

def _tex_escape_title(s: str) -> str:
    return _tex_escape_text(s)

def _inline_safe(s: str) -> str:
    s2 = re.sub(r"\s+", " ", (s or "").strip())
    return (s2[:86] + r"\ldots") if len(s2) > 90 else s2

def _index_cell(mid: str) -> str:
    # keep tables bulletproof: show only an ID in monospace
    return r"\\texttt{" + mid.replace("_", r"\\_") + "}"

    s2 = re.sub(r"\s+", " ", (s or "").strip())
    return (s2[:86] + r"\ldots") if len(s2) > 90 else s2

def _dollars_balanced(s: str) -> bool:
    if not isinstance(s, str):
        return True
    singles = s.count("$") - 2 * s.count("$$")
    return singles % 2 == 0

def _tt(s: str) -> str:
    """Monospace-safe wrapper for text columns (handles _, %, etc.)."""
    return r"\texttt{\detokenize{" + (s or "") + "}}"

# --------------------------
# Symbols table (optional)
# --------------------------

def _symbols_note_from_yaml(sym_path: Path) -> Optional[str]:
    try:
        import yaml
    except Exception:
        return None
    try:
        if sym_path.exists():
            data = yaml.safe_load(sym_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data:
                lines = [
                    r"\begin{longtable}{@{}l l@{}}",
                    r"\toprule \textbf{Alias} & \textbf{Canonical} \\ \midrule",
                ]
                for k, v in sorted(data.items()):
                    canon = v.get("canonical") if isinstance(v, dict) else str(v)
                    lines.append(f"{_tex_escape_text(k)} & {_tex_escape_text(str(canon))} \\\\")
                lines.append(r"\bottomrule \end{longtable}")
                return "\n".join(lines)
    except Exception:
        return None
    return None

# --------------------------
# Core rendering
# --------------------------

def group_by_file(items: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    g: Dict[str, List[Dict[str, Any]]] = {}
    for it in items:
        fn = it.get("file", "unknown.txt")
        g.setdefault(fn, []).append(it)
    return g

def _build_eq_cell(eq_raw: str) -> str:
    if (
        looks_latex(eq_raw)
        and "$$" not in eq_raw
        and _dollars_balanced(eq_raw)
        and not re.search(r"\\begin\{", eq_raw)
    ):
        return r"\(" + _inline_safe(eq_raw) + r"\)"
    return r"\texttt{" + _tex_escape_text(_inline_safe(eq_raw)) + "}"

def _appendix_block(eq_id: str, eq_raw: str) -> str:
    if looks_latex(eq_raw):
        return f"\n\\subsection*{{{_tex_escape_title(eq_id)}}}\n\\begin{{align}}\n{eq_raw}\n\\end{{align}}\n"
    return f"\n\\subsection*{{{_tex_escape_title(eq_id)}}}\n\\[\n\\text{{{_tex_escape_text(eq_raw)}}}\n\\]\n"

def _tex_doc(title: str,
             rows_latex: List[str],
             appendix_blocks: List[str],
             symbols_note: Optional[str] = None) -> str:
    head = PREAMBLE + f"\n\\title{{{_tex_escape_title(title)}}}\n" + CONTRACT_TOP
    body = ""
    body += "\n".join(rows_latex) + "\n" + CONTRACT_BOTTOM
    appendix = "\n".join(appendix_blocks) + "\n\\end{document}"
    return head + body + appendix

def make_reports(equations_json: str,
                 out_dir: str = "out/tex",
                 master_name: str = "master_equations.tex",
                 symbols_yaml: Optional[str] = None) -> None:
    eq_path = Path(equations_json)
    items = json.loads(eq_path.read_text(encoding="utf-8"))
    if not isinstance(items, list):
        raise ValueError("equations_json must contain a JSON list")

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    sym_note = _symbols_note_from_yaml(Path(symbols_yaml)) if symbols_yaml else None

    by_file = group_by_file(items)
    all_rows_master: List[str] = []
    appendix_master: List[str] = []

    # Per-file documents
    for fn, rows in sorted(by_file.items()):
        file_rows: List[str] = []
        appendix_blocks: List[str] = []
        stem = Path(fn).stem

        for i, it in enumerate(rows, 1):
            eq_raw = it.get("latex", "") or ""
            eq_id = f"E{i:03d}"

            # source text (raw, not escaped since we wrap with detokenize)
            src_text = fn
            pg = it.get("page_guess", None)
            if isinstance(pg, int):
                src_text += f" p.{pg}"

            # inline equation cell
            eq_cell = _build_eq_cell(eq_raw)

            # table row (wrap ID & Source)
            file_rows.append(f"{_tt(eq_id)} & {eq_cell} & {_tt(src_text)} & Pending & \\\\")

            # appendix block
            appendix_blocks.append(_appendix_block(eq_id, eq_raw))

        # write per-file
        title = f"Equation Audit — {fn}"
        tex = _tex_doc(title, file_rows, appendix_blocks, symbols_note=sym_note)
        (out / f"{stem}.tex").write_text(tex, encoding="utf-8")

        # also append to master
        for i, it in enumerate(rows, 1):
            eq_raw = it.get("latex", "") or ""
            mid = f"{stem}:{i:03d}"

            src_text = fn
            pg = it.get("page_guess", None)
            if isinstance(pg, int):
                src_text += f" p.{pg}"

            eq_cell = _build_eq_cell(eq_raw)

            all_rows_master.append(f"{_tt(mid)} & {eq_cell} & {_tt(src_text)} & Pending & \\\\")
            appendix_master.append(_appendix_block(mid, eq_raw))

    # Master document
    master_title = "Ξ–χ Framework — Master Equation Audit"
    master_tex = _tex_doc(master_title, all_rows_master, appendix_master, symbols_note=sym_note)
    (out / master_name).write_text(master_tex, encoding="utf-8")

    manifest = {
        "created_at": datetime.datetime.now().isoformat(),
        "count_files": len(by_file),
        "files": sorted([f"{Path(k).stem}.tex" for k in by_file.keys()]),
        "master": master_name,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"[tex-reports] wrote {manifest['count_files']} per-file .tex and {master_name} in {out_dir}")

