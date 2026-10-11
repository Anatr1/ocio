"""Compare the optional intersection controller against its fixed-cycle baseline."""
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sim.intersection.evaluation import compare, write_report
from sim.intersection.world import SCENARIOS


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=SCENARIOS, default="commute")
    parser.add_argument("--minutes", type=float, default=5.)
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    parser.add_argument("--out", default="runs/intersection/comparison")
    args = parser.parse_args(argv)
    result = compare(args.scenario, args.minutes * 60, args.seeds)
    write_report(result, args.out)
    print(json.dumps({k: v for k, v in result.items() if k != "runs"}, indent=2))


if __name__ == "__main__":
    main()
