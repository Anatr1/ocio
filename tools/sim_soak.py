"""Long continuous-traffic soak of the simulated World (no perception): does traffic keep flowing for
minutes, and are all collisions caused by deliberately careless road users rather than by the simulator?

    python tools/sim_soak.py                                  # 4 scenarios x beacon/adaptive x seeds 0-2, 10 min
    python tools/sim_soak.py --scenarios rush_hour --modes adaptive --seeds 1 --minutes 30

Per run: passages per 2-minute window (a gridlock shows as a collapse to ~0), agents alive, collisions
(and how many involved a cautious, unhurried crosser: should be 0), aborted crossings, dropped arrivals,
local physics rewinds and global physics_guard resets (should be 0). Exit status 1 if any run fails.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def soak(scenario, mode, seed, minutes):
    from crosswalk.config import load_config
    from crosswalk.scene import Scene
    from crosswalk.signal import SignalController
    from sim.world import World

    cfg = load_config(None, [f"signal.mode={mode}"])
    world = World(cfg.scene, scenario, seed, cfg=cfg)
    signal = SignalController(cfg.signal, Scene(cfg.scene, tracker_cfg=cfg.tracker), lambda e: None)
    world.signal = signal
    careful = 0
    for _ in range(int(minutes * 60 * 15)):
        n = len(world.gt_events)
        world.step(1 / 15)
        signal.update(world.t, waiting=sum(a.state == "wait" for a in world.agents),
                      crossing=sum(a.state == "cross" for a in world.agents), time_to_clear=3.0)
        for e in world.gt_events[n:]:
            if e["type"] == "collision" and any(
                    a.id in e["agents"] and "side" in a.meta and a.meta.get("cautious") and not a.meta.get("hurry")
                    for a in world.agents):
                careful += 1
    events = Counter(e["type"] for e in world.gt_events)
    times = [e["t"] for e in world.gt_events if e["type"] == "passage"]
    windows = [sum(1 for t in times if 120 * k <= t < 120 * (k + 1)) for k in range(max(1, int(minutes // 2)))]
    ok = min(windows[1:] or windows) >= 5 and careful == 0 and events["physics_guard"] == 0
    return {"scenario": scenario, "mode": mode, "seed": seed, "windows": windows, "alive": len(world.agents),
            "collisions": events["collision"], "careful": careful, "aborted": events["crossing_aborted"],
            "dropped": events["arrival_dropped"], "rewinds": events["physics_rewind"],
            "guard": events["physics_guard"], "ok": ok}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenarios", nargs="+", default=["count_test", "mixed", "rush_hour", "dangerous"])
    ap.add_argument("--modes", nargs="+", default=["beacon", "adaptive"])
    ap.add_argument("--seeds", nargs="+", type=int, default=[0, 1, 2])
    ap.add_argument("--minutes", type=float, default=10.0)
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    args = ap.parse_args()
    runs = [(s, m, seed, args.minutes) for s in args.scenarios for m in args.modes for seed in args.seeds]
    with ProcessPoolExecutor(max_workers=min(args.jobs, len(runs))) as pool:
        results = list(pool.map(soak, *zip(*runs)))
    print(f"{'scenario':11s} {'mode':8s} seed  passages/2min{'':18s} alive coll careful abort drop rewind guard")
    for r in results:
        print(f"{r['scenario']:11s} {r['mode']:8s} {r['seed']:4d}  {str(r['windows']):30s} {r['alive']:5d} "
              f"{r['collisions']:4d} {r['careful']:7d} {r['aborted']:5d} {r['dropped']:4d} {r['rewinds']:6d} "
              f"{r['guard']:5d}  {'ok' if r['ok'] else 'FAIL'}")
    failed = [r for r in results if not r["ok"]]
    print(f"{len(results) - len(failed)}/{len(results)} runs flowed without simulator-made crashes")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
