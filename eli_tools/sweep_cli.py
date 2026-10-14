from __future__ import annotations

import argparse, json, shlex, subprocess
from itertools import product
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

ROOT = Path(__file__).resolve().parent.parent
ART = ROOT / "artifacts"

TEMPLATES = {
    "helmholtz": "python3 -m eli_tools.toy_helmholtz --freq {freq} --mesh {mesh}",
}

def parse_range(spec: str) -> List[float]:
    # "800:1000:10" -> 10 points inclusive
    import numpy as np
    a, b, n = spec.split(":")
    a = float(a); b = float(b); n = int(n)
    if n <= 1:
        return [a]
    return [float(x) for x in np.linspace(a, b, n)]

def run_one(argv: List[str], cwd: Path, timeout: int) -> Dict[str, Any]:
    r = subprocess.run(argv, cwd=str(cwd), text=True, capture_output=True, timeout=timeout)
    return {"returncode": r.returncode, "stdout": r.stdout, "stderr": r.stderr}

def main() -> None:
    ap = argparse.ArgumentParser(description="Parameter sweep runner (writes artifacts)")
    ap.add_argument("--template", required=True, choices=sorted(TEMPLATES.keys()))
    ap.add_argument("--freq", required=True, help="start:stop:steps (e.g. 800:1000:10)")
    ap.add_argument("--mesh", default="medium")
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--workdir", default=".", help="working directory")
    args = ap.parse_args()

    workdir = Path(args.workdir).expanduser().resolve()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = ART / "sweeps" / f"{args.template}_{ts}"
    out.mkdir(parents=True, exist_ok=True)

    freqs = parse_range(args.freq)
    meshes = [args.mesh]

    runs: List[Dict[str, Any]] = []
    i = 0
    for freq, mesh in product(freqs, meshes):
        i += 1
        cmd = TEMPLATES[args.template].format(freq=freq, mesh=mesh)
        argv = shlex.split(cmd)

        run_dir = out / f"run_{i:04d}_freq_{freq:.6g}_mesh_{mesh}"
        run_dir.mkdir(parents=True, exist_ok=True)

        meta: Dict[str, Any] = {"i": i, "freq": freq, "mesh": mesh, "cmd": cmd}
        try:
            rr = run_one(argv, cwd=workdir, timeout=args.timeout)
            meta["ok"] = (rr["returncode"] == 0)
            (run_dir / "stdout.txt").write_text(rr["stdout"], encoding="utf-8", errors="ignore")
            (run_dir / "stderr.txt").write_text(rr["stderr"], encoding="utf-8", errors="ignore")
        except Exception as e:
            meta["ok"] = False
            meta["error"] = str(e)

        (run_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        runs.append(meta)

    summary = {
        "template": args.template,
        "freq_spec": args.freq,
        "mesh": args.mesh,
        "workdir": str(workdir),
        "out_dir": str(out),
        "n_runs": len(runs),
        "ok_runs": sum(1 for r in runs if r.get("ok")),
        "runs": runs,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(str(out / "summary.json"))

if __name__ == "__main__":
    main()
