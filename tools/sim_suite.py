"""Scenario regression suite: python tools/sim_suite.py --level L0 --out runs/suite."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sim.evaluation import write_html
from sim.runner import run_scenario
from sim.scenarios import catalogue


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", choices=["L0", "L1", "L2"], default="L1")
    ap.add_argument("--scenarios", nargs="+")
    ap.add_argument("--seeds", nargs="+", type=int, default=[0])
    ap.add_argument("--config", default=str(ROOT / "configs/board.yaml"))
    ap.add_argument("--set", action="append", default=[])
    ap.add_argument("--fps", type=float, default=15)
    ap.add_argument("--out", type=Path, default=ROOT / "runs" / "suite")
    args = ap.parse_args()
    results = []
    for name in args.scenarios or catalogue():
        for seed in args.seeds:
            try:
                r = run_scenario(name, args.level, seed, args.config, args.set, args.fps)
                ok = bool(r["checks"]) and all(c["passed"] for c in r["checks"])
                print(f"{'PASS' if ok else 'FAIL'} {name} seed={seed} {r['metrics']['count_accuracy']:.1%}", flush=True)
            except Exception as e:
                r = {"scenario": name, "level": args.level, "seed": seed, "error": str(e)}
                ok = False
                print(f"ERROR {name}: {e}", flush=True)
            results.append(r)
            args.out.mkdir(parents=True, exist_ok=True)
            (args.out / "results.json").write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
            write_html(args.out / "report.html", results)
    failures = sum(bool(r.get("error")) or not r.get("checks") or not all(c["passed"] for c in r["checks"]) for r in results)
    print(f"{len(results) - failures}/{len(results)} passed; report: {args.out / 'report.html'}")
    return int(failures > 0)


if __name__ == "__main__":
    raise SystemExit(main())
