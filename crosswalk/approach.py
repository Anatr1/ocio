"""Who is approaching the crossing, and when will they get there.

Single definition used by the beacon rule (B1), the dashboard "Approaching" panel and the evaluation. Categories
follow the challenge: pedestrians, cyclists (bicycles + e-scooters), vehicles.

Status per road user:
  vehicles : approaching (on the carriageway, <= lookahead m, moving towards the zebra) | on_crosswalk | None
  people   : crossing | waiting (curb, slow, >= waiting_min_s) | approaching (curb area / sidewalk near the zebra,
             moving towards it) | None
  cyclists riding along the road are treated like vehicles.
"""
from __future__ import annotations

import math

CATEGORY = {"pedestrian": "pedestrian", "bicycle": "cyclist", "micromobility": "cyclist", "vehicle": "vehicle"}
CATEGORIES = ("pedestrian", "cyclist", "vehicle")


def vehicle_eta(pos, vel, sc, lookahead=40.0):
    """(distance to the zebra edge, time-to-arrival) for a road user moving along the road, else None."""
    x, y = pos
    vx = vel[0]
    if abs(y) > sc.L / 2 + 1.0:
        return None
    d = abs(x) - sc.W / 2
    if d < -0.5 or d > lookahead:
        return None
    if d > 0 and x * vx > 0 and abs(vx) > 0.5:  # moving away (stopped vehicles still count)
        return None
    d = max(d, 0.0)
    return d, d / max(abs(vx), 0.5)


def classify(tr, sc, waiting_min=0.8, near_m=8.0, lookahead=40.0):
    """-> {"status": str|None, "eta": float|None, "dist": float|None}"""
    x, y = tr.pos
    vx, vy = tr.vel
    kind = tr.kind
    along_road = abs(y) <= sc.L / 2 + 0.5 and abs(vx) > 1.5 * abs(vy) and math.hypot(vx, vy) > 1.0
    if kind == "vehicle" or (kind in ("bicycle", "micromobility") and along_road):
        if sc.in_crosswalk(x, y, 0.0):
            return {"status": "on_crosswalk", "eta": 0.0, "dist": 0.0}
        r = vehicle_eta((x, y), (vx, vy), sc, lookahead)
        if r is None:
            return {"status": None, "eta": None, "dist": None}
        return {"status": "approaching", "eta": round(r[1], 1), "dist": round(r[0], 1)}
    # people (and cyclists using the zebra)
    if sc.in_crosswalk(x, y, 0.5):
        return {"status": "crossing", "eta": 0.0, "dist": 0.0}
    wait = tr.meta.get("safety", {}).get("wait", 0.0)
    zone = sc.zone_of(x, y, 0.5)
    if zone in ("curb_a", "curb_b") and wait >= waiting_min:
        return {"status": "waiting", "eta": 0.0, "dist": round(abs(abs(y) - sc.L / 2), 1)}
    # target: nearest point of the zebra's curb edge on this side
    side = -1 if y < 0 else 1
    tx = max(-sc.W / 2, min(sc.W / 2, x))
    ty = side * sc.L / 2
    dx, dy = tx - x, ty - y
    dist = math.hypot(dx, dy)
    if dist > near_m or abs(y) < sc.L / 2:  # too far, or on the road away from the zebra
        return {"status": None, "eta": None, "dist": None}
    sp = math.hypot(vx, vy)
    toward = (vx * dx + vy * dy) / max(dist, 1e-6)  # speed component towards the zebra
    if dist < 0.3 or (sp > 0.3 and toward > 0.6 * sp):
        return {"status": "approaching", "eta": round(dist / max(toward, 0.3), 1), "dist": round(dist, 1)}
    return {"status": None, "eta": None, "dist": None}


class ApproachMonitor:
    """Live per-category summary + unique road users seen approaching (for counts and evaluation)."""

    def __init__(self, scene, cfg):
        self.scene = scene
        self.cfg = cfg
        self.seen = {c: set() for c in CATEGORIES}

    def update(self, tracks):
        summary = {c: {"approaching": 0, "waiting": 0, "crossing": 0, "next_eta": None, "seen": 0} for c in CATEGORIES}
        per_track = {}
        wm = float(self.cfg.get("waiting_min_s", 0.8))
        for tr in tracks:
            if tr.state != "confirmed":
                continue
            cat = CATEGORY.get(tr.kind)
            if cat is None:
                continue
            a = classify(tr, self.scene, wm)
            per_track[tr.id] = a
            st = a["status"]
            if st in ("approaching", "waiting"):
                self.seen[cat].add(tr.id)
                summary[cat][st] += 1
                if a["eta"] is not None and st == "approaching":
                    ne = summary[cat]["next_eta"]
                    summary[cat]["next_eta"] = a["eta"] if ne is None else min(ne, a["eta"])
            elif st in ("crossing", "on_crosswalk"):
                summary[cat]["crossing"] += 1
        for c in CATEGORIES:
            summary[c]["seen"] = len(self.seen[c])
        self.summary = summary
        self.per_track = per_track
        return summary
