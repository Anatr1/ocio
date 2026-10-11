"""Live matching of perceived tracks against simulator ground truth (for the dashboard 'Ground truth' layer).

Reusable by the evaluator: same gates and kind rules. Never imported by crosswalk/ (the pipeline must not see GT).
"""
from __future__ import annotations

import math

import numpy as np

from crosswalk.tracker import INF, assign

VRU = {"pedestrian", "bicycle", "micromobility"}
GATE = {"vehicle": 5.0, "vru": 2.5}  # metres


def _group(kind):
    return "vehicle" if kind == "vehicle" else "vru"


def match(tracks, gt, min_visible=0.35):
    """tracks: state track dicts (id, kind, x, y); gt: SimSource.ground_truth() dicts.
    Only GT agents visible in the camera (>= min_visible of their box in frame) count as misses."""
    vis = [g for g in gt if g["visible"] >= min_visible]
    C = np.full((len(vis), len(tracks)), INF)
    for i, g in enumerate(vis):
        for j, t in enumerate(tracks):
            if _group(g["kind"]) != _group(t["kind"]):
                continue
            d = math.hypot(g["x"] - t["x"], g["y"] - t["y"])
            if d <= GATE[_group(g["kind"])]:
                C[i, j] = d
    pairs = assign(C)
    matched_g = {i for i, _ in pairs}
    matched_t = {j for _, j in pairs}
    links = [{"gt": vis[i]["id"], "track": tracks[j]["id"], "err": round(float(C[i, j]), 2),
              "class_ok": vis[i]["kind"] == tracks[j]["kind"]} for i, j in pairs]
    misses = [vis[i]["id"] for i in range(len(vis)) if i not in matched_g]
    false_pos = [tracks[j]["id"] for j in range(len(tracks)) if j not in matched_t]
    errs = [lk["err"] for lk in links]
    return {
        "links": links, "missed": misses, "false_pos": false_pos,
        "stats": {"visible": len(vis), "matched": len(links), "missed": len(misses), "false_pos": len(false_pos),
                  "mean_err_m": round(sum(errs) / len(errs), 2) if errs else None,
                  "class_ok": sum(1 for lk in links if lk["class_ok"]),
                  "recall": round(len(links) / len(vis), 3) if vis else None},
    }
