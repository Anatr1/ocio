"""Time-overlap lamp metrics and approach recall/lead time, in simulation time."""
from __future__ import annotations

import bisect
import math

import numpy as np

from crosswalk.approach import CATEGORY, CATEGORIES, classify


def distribution(values):
    return {"n": len(values), "values": values, "median": float(np.median(values)) if values else None,
            "p95": float(np.percentile(values, 95)) if values else None}


class TemporalEvaluator:
    def __init__(self, scene, safety_cfg):
        self.scene, self.cfg = scene, safety_cfg
        self.frames = []
        self.commands = []
        self.last_signal_state = "veh_green"

    def observe(self, t, tracks, safety, identity, signal=None):
        users = []
        for tr in tracks:
            if tr.state != "confirmed":
                continue
            users.append({"id": identity.get(tr.id, f"unmatched-{tr.id}"), "kind": tr.kind,
                          **classify(tr, self.scene, float(self.cfg.get("waiting_min_s", 0.8)))})
        self.frames.append({"t": t, "rules": {"B1": safety.warning_level >= 1, "B2": safety.warning_level == 2},
                            "users": users})
        if signal:
            if signal.mode == "adaptive" and self.last_signal_state == "veh_green" and signal.state == "veh_yellow":
                self.commands.append(t)
            self.last_signal_state = signal.state

    def evaluate(self, ground_frames, duration):
        times = [f["t"] for f in ground_frames]
        scores = {r: {"tp_s": 0.0, "fp_s": 0.0, "fn_s": 0.0, "hold_adjusted_fp_s": 0.0,
                      "onsets": 0, "missed_onsets": 0, "latencies": [], "latency_frames": []} for r in ("B1", "B2")}
        # Track GT onsets at the physics rate, not at the detector rate.
        intervals = {r: [] for r in scores}
        for rule in scores:
            start = None
            for g in ground_frames:
                active = g["rules"][rule]
                if active and start is None:
                    start = g["t"]
                elif not active and start is not None:
                    intervals[rule].append((start, g["t"]))
                    start = None
            if start is not None:
                intervals[rule].append((start, duration))
        for rule, windows in intervals.items():
            row = scores[rule]
            row["onsets"] = len(windows)
            for start, end in windows:
                hits = [(i, f) for i, f in enumerate(self.frames) if start <= f["t"] <= end and f["rules"][rule]]
                if hits:
                    i, f = hits[0]
                    row["latencies"].append(max(0.0, f["t"] - start))
                    onset_frame = bisect.bisect_left([p["t"] for p in self.frames], start)
                    row["latency_frames"].append(i - onset_frame)
                else:
                    row["missed_onsets"] += 1
        previous = 0.0
        last_true = {r: -math.inf for r in scores}
        gt_seen = {c: set() for c in CATEGORIES}
        pred_seen = {c: set() for c in CATEGORIES}
        arrivals, first, eta_samples = {}, {}, []
        for g in ground_frames:
            for u in g["users"]:
                cat = CATEGORY[u["kind"]]
                if u["status"] == "approaching":
                    gt_seen[cat].add(u["id"])
                if u["status"] in ("crossing", "on_crosswalk"):
                    arrivals.setdefault(u["id"], g["t"])
        for frame in self.frames:
            t = frame["t"]
            dt = max(0.0, t - previous)
            previous = t
            if not times:
                continue
            gt = ground_frames[max(0, bisect.bisect_right(times, t + 1e-8) - 1)]
            for rule, row in scores.items():
                actual, pred = gt["rules"][rule], frame["rules"][rule]
                if actual:
                    last_true[rule] = t
                if actual and pred:
                    row["tp_s"] += dt
                elif actual:
                    row["fn_s"] += dt
                elif pred:
                    row["fp_s"] += dt
                    if t - last_true[rule] > float(self.cfg.get("warning_hold_s", 1.5)):
                        row["hold_adjusted_fp_s"] += dt
            for u in frame["users"]:
                if u["status"] != "approaching":
                    continue
                cat = CATEGORY[u["kind"]]
                pred_seen[cat].add(u["id"])
                first.setdefault(u["id"], (t, cat))
                if u["eta"] is not None:
                    eta_samples.append((u["id"], t, u["eta"], cat))
        for row in scores.values():
            row["precision"] = row["tp_s"] / (row["tp_s"] + row["fp_s"]) if row["tp_s"] + row["fp_s"] else None
            row["recall"] = row["tp_s"] / (row["tp_s"] + row["fn_s"]) if row["tp_s"] + row["fn_s"] else None
            row["false_on_s_per_hour"] = row["fp_s"] * 3600 / max(duration, 1e-6)
            row["hold_adjusted_false_on_s_per_hour"] = row["hold_adjusted_fp_s"] * 3600 / max(duration, 1e-6)
            row["onset_latency_s"] = distribution(row.pop("latencies"))
        onsets, windows, start = [], [], None
        for g in ground_frames:
            if g["rules"].get("S1", False) and start is None:
                start = g["t"]
            elif not g["rules"].get("S1", False) and start is not None:
                windows.append((start, g["t"]))
                start = None
        if start is not None:
            windows.append((start, duration))
        command_matches = set()
        frame_times = [f["t"] for f in self.frames]
        latency_frames = []
        for start, end in windows:
            candidates = [(i, t) for i, t in enumerate(self.commands) if start - 1e-8 <= t <= end + 1e-8]
            if candidates:
                i, t = candidates[0]
                command_matches.add(i)
                onsets.append(max(0, t - start))
                latency_frames.append(bisect.bisect_left(frame_times, t) - bisect.bisect_left(frame_times, start))
        scores["S1"] = {"onsets": len(windows), "missed_onsets": len(windows) - len(onsets),
                        "commands": len(self.commands), "premature_commands": len(self.commands) - len(command_matches),
                        "onset_latency_s": distribution(onsets), "latency_frames": latency_frames,
                        "evaluation": "command onset after true waiting, minimum green and traffic-gap eligibility"}
        approach = {}
        for cat in CATEGORIES:
            lead = [arrivals[aid] - t for aid, (t, c) in first.items() if c == cat and aid in arrivals and arrivals[aid] >= t]
            errors = [eta - (arrivals[aid] - t) for aid, t, eta, c in eta_samples if c == cat and aid in arrivals and t <= arrivals[aid]]
            approach[cat] = {"gt_users": len(gt_seen[cat]), "flagged_users": len(pred_seen[cat]),
                             "recall": len(gt_seen[cat] & pred_seen[cat]) / len(gt_seen[cat]) if gt_seen[cat] else None,
                             "precision": len(gt_seen[cat] & pred_seen[cat]) / len(pred_seen[cat]) if pred_seen[cat] else None,
                             "lead_time_s": distribution(lead), "eta_error_s": distribution(errors),
                             "eta_mae_s": float(np.mean(np.abs(errors))) if errors else None}
        return {"rules": scores, "approach": approach,
                "time_resolution_s": max((b["t"] - a["t"] for a, b in zip(self.frames, self.frames[1:])), default=None),
                "F1": "unassessed: requires the real MCU at L3"}
