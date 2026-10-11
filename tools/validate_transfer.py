"""Evaluate G2 from matched detector reports, or G6 from paired configuration scores."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sim.validation import compare_detection, decision_transfer


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", type=Path)
    ap.add_argument("--real", type=Path)
    ap.add_argument("--ranks", type=Path, help="JSON rows: config_hash, sim_accuracy, real_accuracy")
    ap.add_argument("--min-observations", type=int, default=30)
    ap.add_argument("--out", type=Path, default=ROOT / "runs/transfer.json")
    args = ap.parse_args()
    if args.ranks:
        result = decision_transfer(json.loads(args.ranks.read_text(encoding="utf-8")))
    elif args.sim and args.real:
        result = compare_detection(json.loads(args.sim.read_text(encoding="utf-8")),
                                   json.loads(args.real.read_text(encoding="utf-8")), args.min_observations)
    else:
        ap.error("supply --sim and --real, or --ranks")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"{result['gate']}: {result['status']}; report: {args.out}")
    return int(result["status"] != "PASS")


if __name__ == "__main__":
    raise SystemExit(main())
