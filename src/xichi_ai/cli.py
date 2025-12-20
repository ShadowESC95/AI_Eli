import argparse, sys
from .ingest.pdf_ingest import ingest_pdfs
from .render.ledger import build_master_ledger
from .cas.el import smoke_el
from .cas.verify import derive_and_check

def main():
    ap = argparse.ArgumentParser(prog="xichi_ai")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_ing = sub.add_parser("ingest")
    p_ing.add_argument("--pdf-dir", default="data/input")

    p_led = sub.add_parser("build-ledger")
    p_led.add_argument("--out", default="out/master_ledger.tex")

    p_c1 = sub.add_parser("cas-check")
    p_c1.add_argument("--report", default="out/cas_report.md")

    p_c2 = sub.add_parser("cas-verify")
    p_c2.add_argument("--report", default="out/cas_verify.md")

    args = ap.parse_args()

    if args.cmd == "ingest":
        ingest_pdfs(args.pdf_dir)
    elif args.cmd == "build-ledger":
        build_master_ledger(args.out)
    elif args.cmd == "cas-check":
        smoke_el(args.report)
    elif args.cmd == "cas-verify":
        derive_and_check(args.report)
    else:
        print("unknown command", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
