"""Counting logic: who passes through the crosswalk, in which direction, how fast.

Counting uses virtual counting lines on the ground (the industry-standard approach), evaluated on each
track's full history (including the samples from before the track was confirmed), so fast cars that are
confirmed mid-crosswalk are still counted, and position jitter of stationary objects never counts.

* passage (VRU)      - the track crosses the crosswalk mid-line (y = 0) within the crosswalk (|x| <= W/2+margin)
* passage (vehicle)  - the track crosses the road cross-line x = 0 within the carriageway (|y| <= L/2 + 0.5)
* crossing           - a VRU that covers >= complete_fraction of the curb-to-curb length: direction, time, speed
* vehicle_pass       - direction and speed (km/h) of every vehicle passage
* jaywalk            - a VRU crossing the road mid-line away from the crosswalk (desire-line analytics)
Each track is counted at most once; tracks that lose their detections are re-identified by the tracker
(same id), and class flicker is reconciled when the track ends (voted class).
"""
from __future__ import annotations

import math
from collections import defaultdict, deque

from .classes import KINDS, VRU_KINDS


def _speed_around(hist, t_c, window=0.8):
    pts = [h for h in hist if abs(h[0] - t_c) <= window]
    if len(pts) >= 2 and pts[-1][0] - pts[0][0] >= 0.2:
        (t0, x0, y0, *_), (t1, x1, y1, *_) = pts[0], pts[-1]
        return math.hypot(x1 - x0, y1 - y0) / (t1 - t0)
    if hist:
        _, _, _, vx, vy = hist[-1]
        return math.hypot(vx, vy)
    return 0.0


class Counter:
    def __init__(self, scene, cfg, emit):
        self.scene = scene
        self.cfg = cfg
        self.emit = emit
        self.counts = {k: 0 for k in KINDS}
        self.sub_counts = defaultdict(int)
        self.dir_counts = {"pedestrian": {"A>B": 0, "B>A": 0}, "bicycle": {"A>B": 0, "B>A": 0, "+X": 0, "-X": 0},
                           "micromobility": {"A>B": 0, "B>A": 0}, "vehicle": {"+X": 0, "-X": 0}}
        self.crossings = deque(maxlen=1000)       # (t, kind, duration, speed)
        self.vehicle_speeds = deque(maxlen=1000)  # (t, cls, kmh)
        self.jaywalks = deque(maxlen=500)         # (t, x)
        self.timeline = deque(maxlen=24 * 60)     # per-minute buckets
        self.margin = float(cfg.get("crosswalk_margin_m", 0.75))
        self.complete_frac = float(cfg.get("complete_fraction", 0.7))
        names = (getattr(scene, "cfg", None) or {}).get("direction_names") or {}
        self.dir_names = {"A>B": "A → B", "B>A": "B → A", "+X": "→ (+X)", "-X": "← (−X)", **dict(names)}

    # ------------------------------------------------------------------ helpers
    def _bucket(self, t, kind, delta=1):
        minute = int(t // 60)
        if not self.timeline or self.timeline[-1]["m"] != minute:
            self.timeline.append({"m": minute, **{k: 0 for k in KINDS}})
        self.timeline[-1][kind] = max(0, self.timeline[-1][kind] + delta)

    def _dir_add(self, kind, d, delta):
        if d:
            dk = self.dir_counts.setdefault(kind, {})
            dk[d] = max(0, dk.get(d, 0) + delta)

    def _count(self, tr, t, x, y, how, d=None):
        kind, sub = tr.kind, tr.subclass
        self.counts[kind] += 1
        self.sub_counts[sub] += 1
        self._bucket(t, kind)
        self._dir_add(kind, d, +1)
        m = tr.meta["count"]
        m["counted"] = (kind, sub, d)
        m.setdefault("counted_all", []).append((kind, sub, d))
        m["rearmed"] = False
        self.emit({"type": "passage", "t": t, "track": tr.id, "kind": kind, "cls": sub, "how": how, "dir": d,
                   "dir_name": self.dir_names.get(d, d), "x": round(x, 2), "y": round(y, 2),
                   "speed": round(tr.speed, 2), "total": self.counts[kind]})

    def _uncount(self, tr, t, kind, sub, reason, d=None):
        self.counts[kind] = max(0, self.counts[kind] - 1)
        self.sub_counts[sub] = max(0, self.sub_counts[sub] - 1)
        self._bucket(t, kind, -1)
        self._dir_add(kind, d, -1)
        self.emit({"type": "count_corrected", "t": t, "track": tr.id, "kind": kind, "cls": sub, "dir": d, "reason": reason})

    # ------------------------------------------------------------------ main update
    def update(self, t, tracks, ended):
        for tr in tracks:
            if tr.state == "confirmed":
                self._process(tr, t)
        # reconcile ended / merged tracks
        for tr in ended:
            m = tr.meta.get("count")
            if not m or not m.get("counted"):
                continue
            for kind, sub, d in m.get("counted_all", [m["counted"]]):  # a track can cross several times
                if tr.state == "merged":
                    self._uncount(tr, t, kind, sub, "merged_duplicate", d)
                    continue
                fk, fs = tr.kind, tr.subclass
                if fk != kind:
                    self._uncount(tr, t, kind, sub, f"reclassified_as_{fs}", d)
                    self.counts[fk] += 1
                    self.sub_counts[fs] += 1
                    self._bucket(t, fk)
                    self._dir_add(fk, d, +1)
                    self.emit({"type": "passage", "t": t, "track": tr.id, "kind": fk, "cls": fs, "x": None, "y": None,
                               "dir": d, "dir_name": self.dir_names.get(d, d),
                               "speed": None, "total": self.counts[fk], "corrected": True})
                elif fs != sub:
                    self.sub_counts[sub] = max(0, self.sub_counts[sub] - 1)
                    self.sub_counts[fs] += 1

    def _process(self, tr, t):
        sc = self.scene
        L, W = sc.L, sc.W
        m = tr.meta.setdefault("count", {
            "t_proc": -1e9, "prev": None, "counted": None, "crossed": False, "jaywalk": False,
            "y_min": None, "y_max": None, "t_in": None, "first_inside_x": None, "x_in0": None,
        })
        kind = tr.kind
        vru = kind in VRU_KINDS
        for (ts, x, y, vx, vy) in list(tr.history):
            if ts <= m["t_proc"]:
                continue
            m["t_proc"] = ts
            prev = m["prev"]
            m["prev"] = (ts, x, y)
            in_cw = abs(x) <= W / 2 + self.margin and abs(y) <= L / 2
            if in_cw:
                m["t_in"] = m["t_in"] if m["t_in"] is not None else ts
                m["y_min"] = y if m["y_min"] is None else min(m["y_min"], y)
                m["y_max"] = y if m["y_max"] is None else max(m["y_max"], y)
                if m["x_in0"] is None:
                    m["x_in0"] = x
            if prev is None:
                continue
            t0, x0, y0 = prev
            if vru and m["counted"] is not None and not m.get("rearmed"):
                # Somebody who reached the far side and comes back (or crosses again) is a new passage. Re-arm only
                # once they got near the far edge, so hesitating in the middle and stepping back is not counted twice.
                far = 0.8 * L / 2
                if (m["counted"][2] == "A>B" and y >= far) or (m["counted"][2] == "B>A" and y <= -far):
                    m["rearmed"] = True
                    m.update(crossed=False, y_min=y, y_max=y, t_in=ts)
            if vru:
                # crossing the crosswalk mid-line y = 0
                if (y0 < 0) != (y < 0) and y != y0:
                    a = -y0 / (y - y0)
                    xc, tc = x0 + a * (x - x0), t0 + a * (ts - t0)
                    if abs(xc) <= W / 2 + self.margin:
                        if m["counted"] is None or m.get("rearmed"):
                            self._count(tr, tc, xc, 0.0, "midline", "A>B" if y > y0 else "B>A")
                    elif abs(xc) <= sc.A and not m["jaywalk"] and m["counted"] is None:
                        m["jaywalk"] = True
                        self.jaywalks.append((tc, xc))
                        self.emit({"type": "jaywalk", "t": tc, "track": tr.id, "kind": kind,
                                   "x": round(xc, 2), "offset_m": round(abs(xc) - W / 2, 2)})
            # vehicles (and cyclists riding along the road) crossing the road cross-line x = 0
            if (x0 < 0) != (x < 0) and x != x0:
                a = -x0 / (x - x0)
                yc, tc = y0 + a * (y - y0), t0 + a * (ts - t0)
                # vehicles, and cyclists/e-scooters riding ALONG the carriageway; pedestrians are only ever counted
                # on the crossing mid-line (people walking along the curb edge must not count)
                riding = (kind != "pedestrian" and abs(yc) <= L / 2 and abs(vx) > 1.5 * abs(vy)
                          and math.hypot(vx, vy) > 2.0)
                if abs(yc) <= L / 2 + 0.5 and (not vru or riding):
                    d = "+X" if x > x0 else "-X"
                    if m["counted"] is None:
                        self._count(tr, tc, 0.0, yc, "crossline", d)
                    if not m.get("passed"):
                        m["passed"] = True
                        kmh = _speed_around(tr.history, tc) * 3.6
                        if kind == "vehicle":
                            self.vehicle_speeds.append((tc, tr.subclass, kmh))
                            self.emit({"type": "vehicle_pass", "t": tc, "track": tr.id, "cls": tr.subclass, "dir": d,
                                       "speed_kmh": round(kmh, 1),
                                       "speeding": bool(kmh > sc.speed_limit * 3.6 + 5)})

        # fallback for tracks born after the line (e.g. confirmed late): sufficient coverage inside
        if m["counted"] is None and m["y_min"] is not None:
            if vru and m["y_max"] - m["y_min"] >= 0.5 * L:
                self._count(tr, t, tr.pos[0], tr.pos[1], "coverage", "A>B" if tr.vel[1] >= 0 else "B>A")
            elif not vru and m["x_in0"] is not None and abs(tr.pos[0] - m["x_in0"]) >= W / 2 + 0.5 \
                    and abs(tr.pos[1]) <= L / 2 + 0.5:
                self._count(tr, t, tr.pos[0], tr.pos[1], "coverage", "+X" if tr.pos[0] > m["x_in0"] else "-X")

        # full crossing (VRU): direction, duration, walking speed
        if vru and not m["crossed"] and m["y_min"] is not None and m["y_max"] - m["y_min"] >= self.complete_frac * L:
            m["crossed"] = True
            dur = max(0.1, t - m["t_in"])
            cov = m["y_max"] - m["y_min"]
            spd = cov / dur
            d = (m["counted"][2] if m["counted"] else None) or ("A>B" if tr.vel[1] > 0 else "B>A")
            self.crossings.append((t, kind, dur, spd))
            self.emit({"type": "crossing", "t": t, "track": tr.id, "kind": kind, "cls": tr.subclass,
                       "dir": d, "duration": round(dur, 2), "speed": round(spd, 2), "height": tr.height})

    # ------------------------------------------------------------------ stats
    def stats(self) -> dict:
        speeds = sorted(k for _, _, k in self.vehicle_speeds)
        v85 = speeds[int(0.85 * (len(speeds) - 1))] if speeds else None
        walk = [s for _, k, _, s in self.crossings if k == "pedestrian"]
        durs = [d for _, k, d, _ in self.crossings if k == "pedestrian"]
        return {
            "counts": dict(self.counts),
            "sub_counts": dict(self.sub_counts),
            "directions": self.dir_counts,
            "direction_names": self.dir_names,
            "vehicle_v85_kmh": None if v85 is None else round(v85, 1),
            "vehicle_mean_kmh": None if not speeds else round(sum(speeds) / len(speeds), 1),
            "ped_mean_speed": None if not walk else round(sum(walk) / len(walk), 2),
            "ped_mean_crossing_s": None if not durs else round(sum(durs) / len(durs), 1),
            "crossings": len(self.crossings),
            "jaywalks": len(self.jaywalks),
            "timeline": list(self.timeline)[-60:],
        }

    def reset(self):
        self.__init__(self.scene, self.cfg, self.emit)
