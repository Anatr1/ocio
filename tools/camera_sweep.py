"""Measure camera first-visibility and approach lead time using actual L2 pixels."""
import argparse
import json
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from crosswalk.config import load_config
from sim.evaluation import write_html
from sim.runner import run_scenario


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--poses", type=Path, default=ROOT / "configs/sim-camera-poses.yaml")
    ap.add_argument("--config", default=str(ROOT / "configs/board.yaml"))
    ap.add_argument("--scenario", default="car_positive")
    ap.add_argument("--set", action="append", default=[])
    ap.add_argument("--fps", type=float, default=5)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=Path, default=ROOT / "runs/camera-sweep")
    args = ap.parse_args()
    cfg = load_config(args.config, args.set)
    if cfg.scene.calibration.get("H") or cfg.scene.calibration.get("image_points"):
        ap.error("a calibrated site camera cannot be replaced silently; use an explicitly uncalibrated virtual configuration")
    results = []
    for pose in yaml.safe_load(args.poses.read_text(encoding="utf-8"))["poses"]:
        overrides = [*args.set, "sim.camera_pos=" + json.dumps(pose["position"]), "sim.camera_target=" + json.dumps(pose["target"])]
        result = run_scenario(args.scenario, "L2", args.seed, args.config, overrides, args.fps)
        result["camera_pose_name"] = pose["name"]
        result["scenario"] += "-" + pose["name"]
        result["camera_visibility"] = result["source"]["first_visible_vehicles"]
        results.append(result)
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        write_html(args.out / "report.html", results)
        print(pose["name"], result["camera_visibility"], flush=True)
    print(f"What-if report: {args.out / 'report.html'}; not real-site G0/G2 certification")


if __name__ == "__main__":
    main()
