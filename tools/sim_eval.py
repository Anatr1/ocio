"""Validate the pipeline against simulator ground truth (counting accuracy, near-miss detection,
fixed vs adaptive signal). Runs headless and fast.

    python tools/sim_eval.py --scenario count_test --minutes 10 --seeds 0 1 2
    python tools/sim_eval.py --scenario dangerous --minutes 10
    python tools/sim_eval.py --compare-signal --minutes 15        # adaptive vs fixed pedestrian waiting time
    python tools/sim_eval.py --sweep-hz 3 5 8 15                   # counting accuracy vs detector rate
Writes a markdown report to runs/sim_eval_<timestamp>.md
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from collections import Counter as C

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crosswalk.config import load_config  # noqa: E402
from crosswalk.pipeline import Node  # noqa: E402
from sim.source import SimSource  # noqa: E402

KINDS = ("pedestrian", "bicycle", "micromobility", "vehicle")


def run_once(scenario, seed, minutes, overrides=(), fps=15.0, verbose=False):
    cfg = load_config(None, list(overrides))
    cfg.server.enabled = False
    cfg.log.dir = ""
    cfg.detector.backend = "sim"
    sim = SimSource(cfg, scenario=scenario, seed=seed, realtime=False, fps=fps, render=False)
    cfg.scene.calibration.update(sim.calibration())
    events = []
    node = Node(cfg, source=sim)
    sim.world.signal = node.signal
    node.bus.subscribe(lambda m: events.append(m["event"]) if m["type"] == "event" else None)
    tracks = {}

    def hook(n, f, d):
        for tr in n.tracker.tracks:
            tracks[tr.id] = tr

    node.on_step = hook
    n_frames = int(minutes * 60 * fps)
    node.run(max_frames=n_frames)
    gt = C(e["kind"] for e in sim.world.gt_events if e["type"] == "passage")
    got = dict(node.counter.counts)
    gt_dir = C((e["kind"], e.get("dir")) for e in sim.world.gt_events if e["type"] == "passage")
    got_dir = {(k, d): v for k, dd in node.counter.dir_counts.items() for d, v in dd.items() if v}
    ttc_pairs = sim.world.pairs_min_ttc
    gt_nm = {lvl: sum(1 for v in ttc_pairs.values() if v <= th) for lvl, th in (("critical", 1.0), ("serious", 2.0), ("potential", 3.0))}
    # near-miss detection quality: map pipeline conflict pairs to ground-truth agent pairs
    det_pairs = set()
    for e in events:
        if e["type"] == "conflict":
            u, c = tracks.get(e["vru"]), tracks.get(e["veh"])
            if u is not None and c is not None and u.gt_id is not None and c.gt_id is not None:
                det_pairs.add((u.gt_id, c.gt_id))
            else:
                det_pairs.add(("?", e["id"]))
    tp = sum(1 for p in det_pairs if ttc_pairs.get(p, 99) <= 3.0)
    fp = len(det_pairs) - tp
    gt_serious = {p for p, v in ttc_pairs.items() if v <= 2.0}
    fn = sum(1 for p in gt_serious if p not in det_pairs)
    res = {
        "scenario": scenario, "seed": seed, "minutes": minutes,
        "gt": {k: gt.get(k, 0) for k in KINDS}, "got": {k: got.get(k, 0) for k in KINDS},
        "near_miss": dict(node.safety.near_miss), "gt_near_miss_ttc": gt_nm,
        "gt_dir": dict(gt_dir), "got_dir": got_dir,
        "nm_tp": tp, "nm_fp": fp, "nm_fn": fn, "nm_gt_serious": len(gt_serious),
        "pets": len(node.safety.pets), "yield": dict(node.safety.yields),
        "signal": node.signal.to_dict(), "events": events,
        "det_runs": node.det_runs, "frames": node.frames,
    }
    return res


def fmt_counts(rows):
    lines = ["| scenario | seed | kind | ground truth | counted | error |", "|---|---|---|---|---|---|"]
    tot_gt = tot_err = 0
    for r in rows:
        for k in KINDS:
            g, c = r["gt"][k], r["got"][k]
            if g == 0 and c == 0:
                continue
            tot_gt += g
            tot_err += abs(g - c)
            lines.append(f"| {r['scenario']} | {r['seed']} | {k} | {g} | {c} | {c - g:+d} |")
    acc = 100.0 * (1 - tot_err / max(1, tot_gt))
    lines.append(f"\n**Overall counting accuracy: {acc:.1f}%** (1 - sum|error| / sum(ground truth), {tot_gt} passages)")
    return "\n".join(lines), acc


def fmt_dirs(rows):
    keys = sorted({k for r in rows for k in list(r["gt_dir"]) + list(r["got_dir"])}, key=str)
    lines = ["| kind | direction | ground truth | counted | error |", "|---|---|---|---|---|"]
    tg = te = 0
    for k in keys:
        g = sum(r["gt_dir"].get(k, 0) for r in rows)
        c = sum(r["got_dir"].get(k, 0) for r in rows)
        tg += g
        te += abs(c - g)
        lines.append(f"| {k[0]} | {k[1]} | {g} | {c} | {c - g:+d} |")
    acc = 100.0 * (1 - te / max(1, tg))
    lines.append(f"\n**Direction-resolved counting accuracy: {acc:.1f}%** (all seeds pooled)")
    return "\n".join(lines), acc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="count_test")
    ap.add_argument("--seeds", nargs="*", type=int, default=[0, 1, 2])
    ap.add_argument("--minutes", type=float, default=5.0)
    ap.add_argument("--set", action="append", default=[])
    ap.add_argument("--compare-signal", action="store_true")
    ap.add_argument("--sweep-hz", nargs="*", type=float, default=None)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    report = [f"# Simulator validation - {time.strftime('%Y-%m-%d %H:%M')}\n"]
    if args.sweep_hz:
        report.append("## Counting accuracy vs detector rate\n")
        report.append("| detector Hz | accuracy |\n|---|---|")
        for hz in args.sweep_hz:
            rows = [run_once(args.scenario, s, args.minutes, args.set + [f"detector.max_hz={hz}"]) for s in args.seeds]
            _, acc = fmt_counts(rows)
            report.append(f"| {hz:g} | {acc:.1f}% |")
            print(f"hz={hz}: {acc:.1f}%")
    elif args.compare_signal:
        report.append("## Fixed-time vs vision-adaptive pedestrian signal\n")
        report.append("| mode | ped. cycles | mean ped wait (s) | Green Man+ extensions |\n|---|---|---|---|")
        for mode in ("fixed", "adaptive"):
            waits, cyc, ext = [], 0, 0
            for s in args.seeds:
                r = run_once("mixed", s, args.minutes, args.set + [f"signal.mode={mode}"])
                sg = r["signal"]
                if sg["mean_ped_wait_s"] is not None:
                    waits.append(sg["mean_ped_wait_s"])
                cyc += sg["cycles"]
                ext += sg["extensions"]
            mw = sum(waits) / len(waits) if waits else float("nan")
            report.append(f"| {mode} | {cyc} | {mw:.1f} | {ext} |")
            print(mode, "cycles", cyc, "mean wait", mw, "ext", ext)
    else:
        rows = []
        for s in args.seeds:
            r = run_once(args.scenario, s, args.minutes, args.set, verbose=args.verbose)
            rows.append(r)
            print(f"seed {s}: gt={r['gt']} got={r['got']} near_miss={r['near_miss']} gt_ttc={r['gt_near_miss_ttc']} "
                  f"pets={r['pets']} yield={r['yield']} det_runs={r['det_runs']}/{r['frames']}")
        table, acc = fmt_counts(rows)
        report.append(f"## Counting ({args.scenario}, {args.minutes:g} min x {len(args.seeds)} seeds)\n")
        report.append(table)
        dtable, dacc = fmt_dirs(rows)
        report.append("\n## Counting by direction\n")
        report.append(dtable)
        report.append("\n## Near-miss detection (TTC with DRAC gating)\n")
        tp = sum(r["nm_tp"] for r in rows)
        fp = sum(r["nm_fp"] for r in rows)
        fn = sum(r["nm_fn"] for r in rows)
        gs = sum(r["nm_gt_serious"] for r in rows)
        prec = tp / max(1, tp + fp)
        rec = (gs - fn) / max(1, gs)
        report.append(f"- precision {prec:.0%} ({tp} of {tp + fp} flagged pairs are real conflicts, TTC <= 3 s)")
        report.append(f"- recall {rec:.0%} ({gs - fn} of {gs} serious/critical ground-truth conflicts flagged)")
        for r in rows:
            report.append(f"- seed {r['seed']}: detected {r['near_miss']}, ground truth {r['gt_near_miss_ttc']}, "
                          f"PET measurements {r['pets']}, yield {r['yield']}")
        print(f"counting accuracy {acc:.1f}%   by direction {dacc:.1f}%   near-miss precision {prec:.0%} recall {rec:.0%}")
    os.makedirs(os.path.join(ROOT, "runs"), exist_ok=True)
    path = os.path.join(ROOT, "runs", f"sim_eval_{time.strftime('%Y%m%d-%H%M%S')}.md")
    with open(path, "w") as f:
        f.write("\n".join(report) + "\n")
    print("report:", path)


if __name__ == "__main__":
    main()
