"""Paired fixed/adaptive experiments, using identical exogenous arrival streams."""
from __future__ import annotations

import json
from pathlib import Path

from .world import IntersectionWorld


def compare(scenario="commute", seconds=300., seeds=(0, 1, 2), progress=None):
    if not 10 <= seconds <= 3600 or not seeds or len(seeds) > 20:
        raise ValueError("comparison needs 10–3600 seconds and 1–20 seeds")
    rows = []
    total = len(seeds) * 2
    for seed in seeds:
        worlds = {}
        for policy in ("fixed", "adaptive"):
            world = IntersectionWorld(scenario, policy, seed)
            world.run(seconds)
            worlds[policy] = world
            rows.append(world.report())
            if progress:
                progress(len(rows) / total)
        if worlds["fixed"].arrival_log != worlds["adaptive"].arrival_log:
            raise AssertionError("policies received different generated traffic")
    totals = {}
    for policy in ("fixed", "adaptive"):
        reports = [r for r in rows if r["policy"] == policy]
        totals[policy] = {
            "vehicle_delay_s": round(sum(r["metrics"].get("vehicle_delay_s", 0.) for r in reports), 2),
            "pedestrian_wait_s": round(sum(r["metrics"].get("pedestrian_wait_s", 0.) for r in reports), 2),
            "vehicles_completed": sum(r["metrics"].get("vehicles_completed", 0) for r in reports),
            "pedestrians_completed": sum(r["metrics"].get("pedestrians_completed", 0) for r in reports),
            "residual_vehicles": sum(r["residual"]["vehicles"] for r in reports),
            "residual_pedestrians": sum(r["residual"]["pedestrians"] for r in reports),
            "dropped_vehicles": sum(r["metrics"].get("dropped_vehicles", 0) for r in reports),
            "possible_conflicts": sum(r["metrics"].get("possible_conflicts", 0) for r in reports),
        }
    changes = {k: round(100 * (totals["adaptive"][k] / totals["fixed"][k] - 1), 1)
               if totals["fixed"][k] else None for k in ("vehicle_delay_s", "pedestrian_wait_s")}
    return {"scenario": scenario, "seconds_per_seed": seconds, "seeds": list(seeds),
            "observation_mode": "perfect simulator ground truth", "arrivals_identical": True,
            "totals": totals, "change_percent": changes, "runs": rows,
            "notes": ["Signed changes: negative delay/wait means less accumulated delay.",
                      "No warm-up: includes start-up queues and residual waiting in the stated finite window.",
                      "Dropped arrivals are reported; compare them alongside delay and throughput.",
                      "These intersection results do not replace single-crosswalk validation or measure detector performance."]}


def write_report(result, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.with_suffix(".json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = ["# Intersection policy comparison", "", f"Scenario: {result['scenario']}; {result['seconds_per_seed']:g} s per seed; seeds {result['seeds']}.",
             "", "Perfect ground-truth observations; identical generated arrivals.", "",
             "| Metric | Fixed | Adaptive |", "|---|---:|---:|"]
    for metric in result["totals"]["fixed"]:
        lines.append(f"| {metric} | {result['totals']['fixed'][metric]} | {result['totals']['adaptive'][metric]} |")
    lines += ["", *[f"- {note}" for note in result["notes"]]]
    path.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
