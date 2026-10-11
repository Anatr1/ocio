"""Check sustained intersection flow and sample all road-user footprints once per second."""
from pathlib import Path
import argparse
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sim.behaviour import overlaps
from sim.intersection.world import IntersectionWorld, SCENARIOS


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=SCENARIOS, nargs="+", default=["commute", "saturated", "pedestrian"])
    parser.add_argument("--minutes", type=int, default=15)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--policy", choices=["fixed", "adaptive"], default="adaptive")
    parser.add_argument("--out", default="runs/intersection/soak.json")
    args = parser.parse_args(argv)
    if not 1 <= args.minutes <= 240:
        parser.error("minutes must be in 1–240")
    reports = []
    for scenario in args.scenario:
        world = IntersectionWorld(scenario, args.policy, args.seed)
        minute_counts, samples = [], 0
        for _ in range(args.minutes):
            previous = world.metrics["vehicles_completed"]
            for tick in range(600):
                world.step()
                if tick % 10 == 0:
                    samples += 1
                    for i, a in enumerate(world.users):
                        for b in world.users[i+1:]:
                            if overlaps(a, b):
                                raise AssertionError(f"{scenario}: footprint overlap at {world.t}s, IDs {a.id}/{b.id}")
            minute_counts.append(world.metrics["vehicles_completed"]-previous)
        if scenario != "empty" and any(count < 5 for count in minute_counts[1:]):
            raise AssertionError(f"{scenario}: traffic ceased flowing: {minute_counts}")
        report = {"scenario":scenario, "footprint_samples":samples, "footprint_overlaps":0,
                  "road_passages_per_minute":minute_counts, "run":world.report()}
        reports.append(report)
        print(json.dumps({k:v for k,v in report.items() if k!="run"}),flush=True)
    result = {"source_sha256":{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
                              ("sim/intersection/world.py","sim/intersection/controller.py","sim/intersection/geometry.py")},
              "policy":args.policy, "seed":args.seed, "minutes":args.minutes, "reports":reports,
              "note":"Footprints sampled once per simulated second; this is a laptop simulation soak, not a board/camera soak."}
    output = Path(args.out)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,indent=2),encoding="utf-8")


if __name__ == "__main__":
    main()
