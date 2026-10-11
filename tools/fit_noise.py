"""Fit an L1 profile from tools/detector_eval.py's reviewed, representative real report."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml
from sim.noise import fit_noise


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=ROOT / "sim/noise_site.yaml")
    args = ap.parse_args()
    profile = fit_noise(json.loads(args.report.read_text(encoding="utf-8")))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    print("fitted profile:", args.out, "(not a G3 pass; compare L1 against L2 and held-out real data)")


if __name__ == "__main__":
    main()
