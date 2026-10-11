"""Counting accuracy on real footage vs. manual ground truth (tools/count_gt.py).

    python tools/eval_counts.py --video data/recordings/rec_X.mp4 --gt data/recordings/rec_X.gt.csv --config configs/site.yaml
    python tools/eval_counts.py --events runs/<run>/events.jsonl --gt rec_X.gt.csv      # evaluate an existing run

Matches pipeline passages to GT marks of the same kind within +-tolerance seconds (greedy by time) and reports
per-class precision / recall / count error -> markdown table for the pitch ("validated on N minutes of real
traffic: 97% counting accuracy").
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

KINDS = ("pedestrian", "bicycle", "micromobility", "vehicle")


def run_pipeline(video, config, overrides):
    from crosswalk.config import load_config
    from crosswalk.pipeline import Node

    cfg = load_config(config, overrides)
    cfg.server.enabled = False
    cfg.source.type = "video"
    cfg.source.path = video
    cfg.source.realtime = False   # every frame, deterministic
    cfg.source.loop = False
    cfg.log.dir = ""
    events = []
    node = Node(cfg)
    node.bus.subscribe(lambda m: events.append(m["event"]) if m["type"] == "event" else None)
    t0 = time.time()
    node.run()
    print(f"processed {node.frames} frames in {time.time() - t0:.1f}s, detector runs {node.det_runs}")
    return events


def load_events(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def final_passages(events):
    """Passages after reclassification corrections."""
    by_track = {}
    for e in events:
        if e["type"] == "passage":
            if e.get("corrected"):  # reclassification: replaces one earlier passage of this track
                prior = by_track.get(e["track"], [])
                if prior:
                    prior.pop()
            by_track.setdefault(e["track"], []).append(e)  # a track may cross several times (back and forth)
        elif e["type"] == "count_corrected" and e.get("reason") == "merged_duplicate":
            by_track.pop(e["track"], None)
    return sorted((e for ps in by_track.values() for e in ps), key=lambda e: e["t"])


def match(gt, pred, tol):
    used = set()
    tp = {k: 0 for k in KINDS}
    for g in gt:
        best, bd = None, tol + 1
        for i, p in enumerate(pred):
            if i in used or p["kind"] != g["kind"]:
                continue
            d = abs(p["t"] - g["t"])
            if d <= tol and d < bd:
                best, bd = i, d
        if best is not None:
            used.add(best)
            tp[g["kind"]] += 1
    return tp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", default=None)
    ap.add_argument("--events", default=None)
    ap.add_argument("--gt", required=True)
    ap.add_argument("--config", default=os.path.join(ROOT, "configs", "board.yaml"))
    ap.add_argument("--set", action="append", default=[])
    ap.add_argument("--tol", type=float, default=3.0, help="time tolerance (s) for matching")
    ap.add_argument("--offset", type=float, default=0.0, help="add to GT times (sync)")
    args = ap.parse_args()
    with open(args.gt) as f:
        gt = [{"t": float(r["t"]) + args.offset, "kind": r["kind"], "cls": r["cls"]} for r in csv.DictReader(f)]
    events = load_events(args.events) if args.events else run_pipeline(args.video, args.config, args.set)
    pred = final_passages(events)
    tp = match(gt, pred, args.tol)
    lines = ["| class | ground truth | counted | matched | precision | recall | count error |", "|---|---|---|---|---|---|---|"]
    tot_g = tot_p = tot_tp = tot_err = 0
    for k in KINDS:
        g = sum(1 for x in gt if x["kind"] == k)
        p = sum(1 for x in pred if x["kind"] == k)
        if g == 0 and p == 0:
            continue
        prec = tp[k] / p if p else 0.0
        rec = tp[k] / g if g else 0.0
        lines.append(f"| {k} | {g} | {p} | {tp[k]} | {prec:.0%} | {rec:.0%} | {p - g:+d} |")
        tot_g += g
        tot_p += p
        tot_tp += tp[k]
        tot_err += abs(p - g)
    acc = 1 - tot_err / max(1, tot_g)
    lines.append(f"| **total** | {tot_g} | {tot_p} | {tot_tp} | {tot_tp / max(1, tot_p):.0%} | {tot_tp / max(1, tot_g):.0%} | "
                 f"accuracy {acc:.1%} |")
    report = "\n".join(lines)
    print(report)
    out = os.path.join(ROOT, "runs", f"eval_counts_{time.strftime('%Y%m%d-%H%M%S')}.md")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        f.write(f"# Counting accuracy - {os.path.basename(args.video or args.events)}\n\n{report}\n")
    print("report:", out)


if __name__ == "__main__":
    main()
