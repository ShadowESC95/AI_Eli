import argparse, json
from pathlib import Path
from .llm.ollama_client import OllamaClient

PROMPTS_DIR = Path(__file__).parent / "promptpacks"

def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")

def _write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")

def run_llm(task: str, system_prompt_file: str, user_input: str, out_path: str, model: str | None):
    client = OllamaClient(model=model)
    system = _read(PROMPTS_DIR / system_prompt_file)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_input},
    ]
    text = client.chat(messages, stream=False, options={"temperature": 0.1})
    _write(Path(out_path), text)
    print(f"[llm:{task}] wrote {out_path}")

def cmd_harvest(args):
    cache = Path("data/cache")
    # Concatenate page texts for each file
    texts = []
    for txtf in cache.glob("*.txt"):
        texts.append(f"# FILE: {txtf.name}\n" + _read(txtf))
    user = "Extract **only** equations in LaTeX from the following sources. For each equation, return a JSON array of objects with fields: {file, page_guess, eq_label, latex}. Keep LaTeX verbatim.\n\n" + "\n\n".join(texts)
    run_llm("harvest", "harvest.md", user, "data/cache/equations_llm.json", args.model)

def cmd_normalize(args):
    eq = Path("data/cache/equations_llm.json").read_text(encoding="utf-8") if Path("data/cache/equations_llm.json").exists() else "[]"
    user = "Given these extracted equations (JSON below), build a YAML symbol alias registry mapping aliases → canonical (Ξ, χ, φ, A_E, A_B, g_{μν}, F_E, F_B, ε(Ξ,χ), μ^{-1}(Ξ,χ), κ(Ξ,χ), θ(Ξ,χ)). Include notes and SI units when applicable.\n\n" + eq
    run_llm("normalize", "normalize.md", user, "data/cache/symbols.yaml", args.model)

def cmd_derive_el(args):
    symbols = Path("data/cache/symbols.yaml").read_text(encoding="utf-8") if Path("data/cache/symbols.yaml").exists() else ""
    user = "Using the canonical symbols (YAML below), produce the covariant Euler–Lagrange equations for the Ξ–χ–φ–A_E–A_B–G framework, then a 3+1 split. Output **LaTeX only** with labeled equations.\n\n" + symbols
    run_llm("derive_el", "derive_el.md", user, "out/derived_el.tex", args.model)

def cmd_recovery(args):
    el = Path("out/derived_el.tex").read_text(encoding="utf-8") if Path("out/derived_el.tex").exists() else ""
    user = "Given the derived equations (LaTeX below), show explicit substitutions to recover Maxwell, GR, and SR limits. Provide step-by-step substitutions and the resulting simplified equations.\n\n" + el
    run_llm("recovery", "recovery.md", user, "out/recovery_notes.md", args.model)

def cmd_weak(args):
    el = Path("out/derived_el.tex").read_text(encoding="utf-8") if Path("out/derived_el.tex").exists() else ""
    user = "Convert the Euler–Lagrange equations (LaTeX below) into weak forms suitable for FEniCSx and deal.II. Include test/trial functions, integrals, and boundary jump conditions. Output clear, commented code blocks.\n\n" + el
    run_llm("weak", "weak_forms.md", user, "out/weak_forms.md", args.model)

def main():
    ap = argparse.ArgumentParser(prog="xichi_ai_llm")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("harvest"); p1.add_argument("--model", default=None)
    p2 = sub.add_parser("normalize"); p2.add_argument("--model", default=None)
    p3 = sub.add_parser("derive-el"); p3.add_argument("--model", default=None)
    p4 = sub.add_parser("recovery"); p4.add_argument("--model", default=None)
    p5 = sub.add_parser("weak"); p5.add_argument("--model", default=None)
    args = ap.parse_args()
    if args.cmd == "harvest": cmd_harvest(args)
    elif args.cmd == "normalize": cmd_normalize(args)
    elif args.cmd == "derive-el": cmd_derive_el(args)
    elif args.cmd == "recovery": cmd_recovery(args)
    elif args.cmd == "weak": cmd_weak(args)
    else:
        ap.error("unknown command")

if __name__ == "__main__":
    main()
