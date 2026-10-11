"""Exact trajectories and safety oracle, independent of detector/tracker errors.

Counting uses interpolated ground-line intersections. Safety reuses the production
TTC/DRAC/PET/yield definitions on perfect ground trajectories, without the detector.
"""
from __future__ import annotations

import math
from collections import deque

from crosswalk.approach import classify, vehicle_eta
from crosswalk.safety import SafetyMonitor, drac, ttc_box


def line_passage(previous, current, kind, width, length, margin=0.75):
    t0, x0, y0 = previous
    t1, x1, y1 = current
    vru = kind in ("pedestrian", "bicycle", "micromobility")
    if vru and (y0 < 0) != (y1 < 0) and y1 != y0:
        f = -y0 / (y1 - y0)
        x = x0 + f * (x1 - x0)
        if abs(x) <= width / 2 + margin:
            return {"t": t0 + f * (t1 - t0), "x": x, "y": 0.0,
                    "dir": "A>B" if y1 > y0 else "B>A"}
    cross_y = y0 + (-x0 / (x1 - x0)) * (y1 - y0) if x1 != x0 else y1
    along_road = (kind in ("bicycle", "micromobility") and abs(cross_y) <= length / 2 and
                  abs(x1 - x0) > 1.5 * abs(y1 - y0) and
                  math.hypot(x1 - x0, y1 - y0) / max(t1 - t0, 1e-9) > 2.0)
    if (kind == "vehicle" or along_road) and (x0 < 0) != (x1 < 0) and x1 != x0:
        f = -x0 / (x1 - x0)
        y = y0 + f * (y1 - y0)
        if abs(y) <= length / 2 + 0.5:
            return {"t": t0 + f * (t1 - t0), "x": 0.0, "y": y,
                    "dir": "+X" if x1 > x0 else "-X"}
    return None


class GroundTrack:
    def __init__(self, agent, t):
        self.id = agent.id
        self.kind = agent.kind
        self.subclass = agent.subclass
        self.dims = agent.dims
        self.height = agent.dims[2]
        self.state = "confirmed"
        self.meta = {}
        self.history = deque()
        self.update(agent, t)

    def update(self, agent, t):
        self.pos, self.vel, self.heading = (agent.x, agent.y), (agent.vx, agent.vy), agent.heading
        self.history.append((t, agent.x, agent.y, agent.vx, agent.vy))
        while self.history and t - self.history[0][0] > 20:
            self.history.popleft()

    @property
    def speed(self):
        return math.hypot(*self.vel)


class GroundTruth:
    def __init__(self, scene, safety_cfg, counting_cfg, signal=None):
        self.scene, self.signal = scene, signal
        self.margin = float(counting_cfg.get("crosswalk_margin_m", 0.75))
        self.tracks = {}
        self.dead = deque(maxlen=200)
        self.events = []
        self.counted = set()
        self.pairs_min_ttc = {}
        self.frames = []
        self.safety_cfg = safety_cfg
        self.safety = SafetyMonitor(scene, safety_cfg, self.events.append,
                                    signal.mode if signal else "beacon")

    def update(self, t, agents):
        live = []
        ids = {a.id for a in agents if a.alive}
        ended = []
        for aid in list(self.tracks):
            if aid not in ids:
                tr = self.tracks.pop(aid)
                tr.state = "ended"
                self.dead.append(tr)
                ended.append(tr)
        for a in agents:
            if not a.alive:
                continue
            tr = self.tracks.get(a.id)
            if tr is None:
                tr = self.tracks[a.id] = GroundTrack(a, t)
            else:
                prev = tr.history[-1][:3]
                tr.update(a, t)
                if a.id not in self.counted:
                    hit = line_passage(prev, (t, a.x, a.y), a.kind, self.scene.W, self.scene.L, self.margin)
                    if hit:
                        self.counted.add(a.id)
                        self.events.append({"type": "passage", "agent": a.id, "track": a.id,
                                            "kind": a.kind, "cls": a.subclass, **hit})
                        tr.meta.setdefault("count", {}).update({"passed": True, "t_in": hit["t"]})
            live.append(tr)
        self.safety.update(t, live, ended, self.signal, self.dead)
        for conflict in self.safety.active:
            key = (conflict["vru"], conflict["veh"])
            self.pairs_min_ttc[key] = min(self.pairs_min_ttc.get(key, math.inf), conflict["ttc"])
        self.frames.append(self.snapshot(t, live))

    def snapshot(self, t, live):
        """Raw GT conditions, before debounce/hold, using production geometry and approach APIs."""
        states = {tr.id: classify(tr, self.scene, float(self.safety_cfg.get("waiting_min_s", 0.8)))
                  for tr in live}
        vrus = [tr for tr in live if tr.kind in ("pedestrian", "bicycle", "micromobility")]
        vehicles = [tr for tr in live if tr.kind == "vehicle"]
        demand = any(states[u.id]["status"] in ("approaching", "waiting", "crossing") for u in vrus)
        arrivals = [vehicle_eta(c.pos, c.vel, self.scene) for c in vehicles if c.speed > 1]
        caution = demand and any(r and r[1] < float(self.safety_cfg.get("beacon_tta_s", 6)) for r in arrivals)
        danger = False
        for u in vrus:
            in_road = abs(u.pos[1]) <= self.scene.L / 2 and abs(u.pos[0]) <= self.scene.W / 2 + 8
            crossing = abs(u.vel[1]) >= 0.5 * abs(u.vel[0]) and u.speed < 8
            if not (states[u.id]["status"] == "crossing" or in_road and crossing):
                continue
            for c in vehicles:
                if c.speed < 1:
                    continue
                ttc = ttc_box(u, c, self.safety.horizon, self.safety.vru_r)
                if ttc is not None and ttc <= self.safety.ttc_levels[1] and drac(u, c, self.safety.vru_r) >= float(self.safety_cfg.get("drac_min", 3)):
                    danger = True
        eligible = False
        if self.signal and self.signal.mode == "adaptive" and self.signal.state == "veh_green":
            elapsed = t - (self.signal.t_state if self.signal.t_state is not None else t)
            waiting = any(states[u.id]["status"] == "waiting" for u in vrus)
            close = any(c.speed > 1.5 and 0 < abs(c.pos[0]) - self.scene.W / 2 < 3 * c.speed and
                        c.pos[0] * c.vel[0] < 0 for c in vehicles)
            eligible = (waiting and elapsed >= self.signal.cfg["veh_min_green_s"] and
                        (not close or elapsed >= self.signal.cfg["veh_max_green_s"]))
        return {"t": t, "rules": {"B1": bool(caution), "B2": danger, "S1": bool(eligible)},
                "users": [{"id": tr.id, "kind": tr.kind, **states[tr.id]} for tr in live]}
