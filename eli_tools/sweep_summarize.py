from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import matplotlib.pyplot as plt

from eli_tools import config as eli_config

ROOT = eli_config.home()

RE_MD_PATH = re.compile(r"(artifacts/[^\s]+/summary\.md)")

def _read_json(p: Path) -> Dict[str, Any]:
    return json.loads(p.read_text(encoding="utf-8", errors="ignore"))

def _parse_metrics_from_md(md: Path) -> Dict[str, Any]:
    s = md.read_text(encoding="utf-8", errors="ignore")
    def grab(key: str) -> Optional[float]:
        m = re.search(rf"^- {re.escape(key)}:\s*([0-9eE\.\+\-]+)\s*$", s, flags=re.M)
        return float(m.group(1)) if m else None

    out = {
        "freq_Hz": grab("freq_Hz"),
        "N": grab("N"),
        "k": grab("k"),
        "mean_u2": grab("mean(u^2)"),
        "mean_grad2": grab("mean(|grad u|^2)"),
    }
    return out

def _solution_paths_from_summary(md: Path) -> Tuple[Path, Path]:
    # toy_helmholtz writes solution.npy next to summary.md
    out_dir = md.parent
    return out_dir / "solution.npy", out_dir / "solution.png"

def _extract_md_from_stdout(stdout_txt: Path) -> Optional[Path]:
    if not stdout_txt.exists():
        return None
    t = stdout_txt.read_text(encoding="utf-8", errors="ignore")
    m = RE_MD_PATH.search(t)
    if not m:
        # fallback: last non-empty line might be the md path
        lines = [x.strip() for x in t.splitlines() if x.strip()]
        if lines:
            cand = lines[-1]
            if cand.endswith("summary.md"):
                return (ROOT / cand).resolve() if cand.startswith("artifacts/") else Path(cand).expanduser().resolve()
        return None
    rel = m.group(1)
    return (ROOT / rel).resolve()

def summarize(sweep_summary_json: Path) -> Dict[str, Any]:
    sweep = _read_json(sweep_summary_json)
    out_dir = Path(sweep["out_dir"]).resolve()

    rows: List[Dict[str, Any]] = []
    for run in sweep.get("runs", []):
        run_dir = out_dir / f"run_{int(run['i']):04d}_freq_{run['freq']:.6g}_mesh_{run['mesh']}"
        stdout_txt = run_dir / "stdout.txt"
        md = _extract_md_from_stdout(stdout_txt)

        row: Dict[str, Any] = {
            "i": run.get("i"),
            "freq_Hz": run.get("freq"),
            "mesh": run.get("mesh"),
            "ok": bool(run.get("ok")),
            "run_dir": str(run_dir),
            "md": str(md) if md else None,
            "max_abs_u": None,
            "mean_u2": None,
            "mean_grad2": None,
            "k": None,
            "N": None,
            "png": None,
            "npy": None,
        }

        if md and md.exists():
            met = _parse_metrics_from_md(md)
            row.update({k: met.get(k) for k in ("mean_u2","mean_grad2","k","N")})

            npy, png = _solution_paths_from_summary(md)
            row["npy"] = str(npy) if npy.exists() else None
            row["png"] = str(png) if png.exists() else None

            if npy.exists():
                arr = np.load(npy)
                # columns: x, u
                u = arr[:, 1]
                row["max_abs_u"] = float(np.max(np.abs(u)))

        rows.append(row)

    # rank by peak amplitude (resonance-ish proxy)
    ok_rows = [r for r in rows if r.get("ok") and r.get("max_abs_u") is not None]
    ok_rows_sorted = sorted(ok_rows, key=lambda r: float(r["max_abs_u"]), reverse=True)

    # build response curve plot
    curve_png = out_dir / "response_curve.png"
    try:
        xs = [r["freq_Hz"] for r in ok_rows_sorted][::-1]
        ys = [r["max_abs_u"] for r in ok_rows_sorted][::-1]
        if xs and ys:
            fig = plt.figure()
            plt.plot(xs, ys)
            plt.title("Sweep response: max(|u|) vs frequency")
            plt.xlabel("frequency (Hz)")
            plt.ylabel("max |u|")
            fig.savefig(curve_png, dpi=170)
            plt.close(fig)
    except Exception as e:
        # don't hard-fail
        curve_png = None

    report = {
        "sweep_summary_json": str(sweep_summary_json),
        "out_dir": str(out_dir),
        "n_runs": len(rows),
        "n_ok_with_metrics": len(ok_rows),
        "top5": ok_rows_sorted[:5],
        "rows": rows,
        "response_curve_png": str(curve_png) if curve_png else None,
    }
    return report

def write_report(report: Dict[str, Any]) -> Path:
    out_dir = Path(report["out_dir"]).resolve()
    md = out_dir / "report.md"
    top5 = report.get("top5", [])

    lines = []
    lines.append("# Sweep Report")
    lines.append("")
    lines.append(f"- Sweep: `{report['sweep_summary_json']}`")
    lines.append(f"- Runs: {report['n_runs']}")
    lines.append(f"- OK runs with metrics: {report['n_ok_with_metrics']}")
    if report.get("response_curve_png"):
        lines.append(f"- Response curve: `response_curve.png`")
    lines.append("")
    lines.append("## Top 5 (by max |u|)")
    lines.append("")
    if not top5:
        lines.append("(No successful runs with metrics found.)")
    else:
        for r in top5:
            lines.append(f"- run {r['i']}: freq={r['freq_Hz']} Hz, max|u|={r['max_abs_u']:.6g}, mean(u^2)={r.get('mean_u2')}, mesh={r.get('mesh')}")
            if r.get("png"):
                lines.append(f"  - plot: `{Path(r['png']).name}` (stored in toy_helmholtz artifact dir)")
            if r.get("md"):
                lines.append(f"  - summary: `{r['md']}`")
    lines.append("")
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return md

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", required=True, help="path to sweep summary.json")
    args = ap.parse_args()

    p = Path(args.summary).expanduser().resolve()
    rep = summarize(p)
    out_md = write_report(rep)
    print(str(out_md))

if __name__ == "__main__":
    main()
