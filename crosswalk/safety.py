"""Safety analytics: surrogate safety measures used in traffic-conflict studies.

* TTC  (time-to-collision): online, constant-velocity prediction of every VRU-vehicle pair; a VRU is
  treated as a disc, the vehicle as an oriented rectangle (slab / ray-box test in the vehicle frame).
* PET  (post-encroachment time): offline per pair, once both have left the conflict area - time between the
  first road user leaving the conflict area and the second one entering it.
* Yield compliance: for every vehicle approaching while a pedestrian is waiting at / walking on the
  crosswalk - did it stop (art. 191 Codice della Strada) or not?
* Alerts: person motionless on the crosswalk (fall?), vehicle stopped on the crosswalk, red-light
  violations (when the node controls / knows the signal).
* Warning output for the active warning beacon / driver sign (driven by the MCU).
"""
from __future__ import annotations

import math
from collections import deque

from .classes import VRU_KINDS
from .approach import vehicle_eta
from .geometry import crossing_time


def ttc_box(vru, veh, horizon: float, vru_r: float):
    """Time until the VRU disc enters the vehicle rectangle (None if not within horizon)."""
    vx_, vy_ = veh.vel
    hd = veh.heading if veh.heading is not None else math.atan2(vy_, vx_)
    c, s = math.cos(hd), math.sin(hd)
    L, Wd, _ = veh.dims
    hx, hy = L / 2 + vru_r, Wd / 2 + vru_r
    px, py = vru.pos
    cx, cy = veh.pos
    dx, dy = px - cx, py - cy
    rx, ry = c * dx + s * dy, -s * dx + c * dy
    uvx, uvy = vru.vel
    dvx, dvy = uvx - vx_, uvy - vy_
    ux, uy = c * dvx + s * dvy, -s * dvx + c * dvy
    t_in, t_out = -math.inf, math.inf
    for p, u, h in ((rx, ux, hx), (ry, uy, hy)):
        if abs(u) < 1e-9:
            if abs(p) > h:
                return None
            continue
        t1, t2 = (-h - p) / u, (h - p) / u
        t_in = max(t_in, min(t1, t2))
        t_out = min(t_out, max(t1, t2))
    if t_in > t_out or t_out < 0 or t_in > horizon:
        return None
    return max(t_in, 0.0)


def drac(vru, veh, vru_r: float) -> float:
    """Deceleration Rate to Avoid Crash: braking (m/s^2) the vehicle needs to stop before the VRU.
    0 if the VRU is not ahead of the vehicle."""
    vx_, vy_ = veh.vel
    sp = math.hypot(vx_, vy_)
    if sp < 0.5:
        return 0.0
    hd = veh.heading if veh.heading is not None else math.atan2(vy_, vx_)
    c, s = math.cos(hd), math.sin(hd)
    dx, dy = vru.pos[0] - veh.pos[0], vru.pos[1] - veh.pos[1]
    rx = c * dx + s * dy
    if rx <= 0:
        return 0.0
    d = max(0.1, rx - veh.dims[0] / 2 - vru_r)
    uvx, uvy = vru.vel
    closing = sp - (c * uvx + s * uvy)
    if closing <= 0:
        return 0.0
    return closing * closing / (2 * d)


def _interval(ts, vals, lo, hi):
    """Time interval during which a sampled 1-D coordinate is within [lo, hi]."""
    if not ts:
        return None
    inside = [lo <= v <= hi for v in vals]
    if not any(inside):
        # maybe it jumped over the band between two samples
        a = crossing_time(ts, vals, lo)
        b = crossing_time(ts, vals, hi)
        if a is None or b is None:
            return None
        return (min(a, b), max(a, b))
    i0 = inside.index(True)
    i1 = len(inside) - 1 - inside[::-1].index(True)
    t0, t1 = ts[i0], ts[i1]
    if i0 > 0:  # refine entry
        lvl = lo if vals[i0 - 1] < lo else hi
        tc = crossing_time(ts[i0 - 1 : i0 + 1], vals[i0 - 1 : i0 + 1], lvl)
        t0 = tc if tc is not None else t0
    if i1 < len(ts) - 1:
        lvl = lo if vals[i1 + 1] < lo else hi
        tc = crossing_time(ts[i1 : i1 + 2], vals[i1 : i1 + 2], lvl)
        t1 = tc if tc is not None else t1
    return (t0, t1)


def pet_pair(veh, vru, vru_r=0.35, W=4.0):
    """Post-encroachment time between a vehicle and a VRU (None if their paths don't conflict)."""
    vh = list(veh.history)
    uh = list(vru.history)
    if len(vh) < 2 or len(uh) < 2:
        return None
    near = [h for h in vh if abs(h[1]) < W / 2 + 6]
    if not near:
        return None
    ys = sorted(h[2] for h in near)
    y_c = ys[len(ys) // 2]  # vehicle lane (lateral position)
    L, Wd, _ = veh.dims
    hw = Wd / 2 + vru_r
    # VRU occupancy of the vehicle's lane band (only near the crosswalk)
    u_ts = [h[0] for h in uh if abs(h[1]) < W / 2 + 3]
    u_ys = [h[2] for h in uh if abs(h[1]) < W / 2 + 3]
    iv = _interval(u_ts, u_ys, y_c - hw, y_c + hw)
    if iv is None:
        return None
    # where along the road the VRU crossed the lane
    xs_in = [h[1] for h in uh if iv[0] - 0.3 <= h[0] <= iv[1] + 0.3] or [uh[len(uh) // 2][1]]
    x_v = sum(xs_in) / len(xs_in)
    hl = L / 2 + vru_r
    ic = _interval([h[0] for h in vh], [h[1] for h in vh], x_v - hl, x_v + hl)
    if ic is None:
        return None
    if ic[1] < iv[0]:
        return {"pet": iv[0] - ic[1], "first": "vehicle", "x": x_v, "y": y_c, "t": iv[0]}
    if iv[1] < ic[0]:
        return {"pet": ic[0] - iv[1], "first": "vru", "x": x_v, "y": y_c, "t": ic[0]}
    return {"pet": 0.0, "first": "overlap", "x": x_v, "y": y_c, "t": max(iv[0], ic[0])}


def level_of(value, levels):
    names = ("critical", "serious", "potential")
    for n, lv in zip(names, levels):
        if value <= lv:
            return n
    return None


class SafetyMonitor:
    def __init__(self, scene, cfg, emit, signal_mode="beacon"):
        self.scene = scene
        self.cfg = cfg
        self.emit = emit
        self.signal_mode = signal_mode
        self.horizon = float(cfg.get("ttc_horizon_s", 4.0))
        self.ttc_levels = list(cfg.get("ttc_levels_s", [1.0, 2.0, 3.0]))
        self.pet_levels = list(cfg.get("pet_levels_s", [1.0, 2.0, 3.0]))
        self.vru_r = float(cfg.get("vru_radius_m", 0.35))
        self.conflicts = {}       # (vru, veh) -> state
        self.pending_pet = deque()  # (t_due, veh_track)
        self.pet_done = set()
        self.yield_state = {}
        self.alerted = set()
        self.near_miss = {"critical": 0, "serious": 0, "potential": 0}
        self.pets = deque(maxlen=500)
        self.yields = {"yielded": 0, "not_yielded": 0}
        self.violations = {"ped_red": 0, "veh_red": 0}
        self.alerts = 0
        self.warning_until = -1.0
        self.warning_level = 0
        self.beacon_rule = {"id": "B0", "why": "no person at the crossing with a vehicle arriving", "t": 0.0}
        self.beacon_history = deque(maxlen=20)
        self.active = []          # current conflicts for the dashboard

    # ------------------------------------------------------------------ helpers
    def _vru_state(self, tr, t):
        """Update and return 'crossing' | 'waiting' | 'approaching' | None for a VRU."""
        m = tr.meta.setdefault("safety", {"wait": 0.0, "t_prev": t, "still": 0.0})
        dt = max(0.0, t - m["t_prev"])
        m["t_prev"] = t
        x, y = tr.pos
        sc = self.scene
        z = sc.zone_of(x, y, 0.5)
        st = None
        if z == "crosswalk":
            st = "crossing"
            m["wait"] = 0.0
        elif z in ("curb_a", "curb_b"):
            if tr.speed < float(self.cfg.get("waiting_speed", 0.6)):
                m["wait"] += dt
                if m["wait"] >= float(self.cfg.get("waiting_min_s", 0.8)):
                    st = "waiting"
            else:
                m["wait"] = 0.0
                vy = tr.vel[1]
                toward = (z == "curb_a" and vy > 0.3) or (z == "curb_b" and vy < -0.3)
                if toward:
                    st = "approaching"
        else:
            m["wait"] = 0.0
        # motionless on the crosswalk
        if z == "crosswalk" and tr.speed < 0.25:
            m["still"] += dt
        else:
            m["still"] = 0.0
        return st

    @staticmethod
    def _approach(veh, sc, lookahead):
        """Distance (m) to the crosswalk edge if the vehicle is approaching it, else None (shared definition)."""
        r = vehicle_eta(veh.pos, veh.vel, sc, lookahead)
        return None if r is None else r[0]

    # ------------------------------------------------------------------ main update
    def update(self, t, tracks, ended, signal=None, dead=()):
        sc = self.scene
        conf = [tr for tr in tracks if tr.state == "confirmed"]
        vrus = [tr for tr in conf if tr.kind in VRU_KINDS]
        vehs = [tr for tr in conf if tr.kind == "vehicle"]
        vstate = {tr.id: self._vru_state(tr, t) for tr in vrus}
        demand_cross = [tr for tr in vrus if vstate[tr.id] == "crossing"]
        demand_wait = [tr for tr in vrus if vstate[tr.id] in ("waiting", "approaching")]

        # ---------------- TTC conflicts
        self.active = []
        live_pairs = set()
        for u in vrus:
            st = vstate[u.id]
            ux, uy = u.vel
            in_road = abs(u.pos[1]) <= sc.L / 2 and abs(u.pos[0]) <= sc.W / 2 + 8.0
            crossing_motion = abs(uy) >= 0.5 * abs(ux) and u.speed < 8.0
            # Only road users actually crossing the carriageway: people waiting / walking up to the curb are
            # not predicted to walk into traffic, cyclists riding along the road are a different conflict type.
            if not (st == "crossing" or (in_road and crossing_motion)):
                continue
            for c in vehs:
                if c.speed < 1.0:
                    continue
                ttc = ttc_box(u, c, self.horizon, self.vru_r)
                if ttc is None:
                    continue
                lvl = level_of(ttc, self.ttc_levels)
                if lvl is None:
                    continue
                # conflict = imminent (TTC) AND needs more than comfortable braking to avoid (DRAC);
                # a car calmly slowing down for a pedestrian 25 m ahead is not a conflict
                need = drac(u, c, self.vru_r)
                if need < float(self.cfg.get("drac_min", 3.0)):
                    continue
                key = (u.id, c.id)
                live_pairs.add(key)
                st = self.conflicts.get(key)
                rank = {"potential": 1, "serious": 2, "critical": 3}[lvl]
                self.active.append({"vru": u.id, "veh": c.id, "ttc": round(ttc, 2), "level": lvl,
                                    "x": round(u.pos[0], 2), "y": round(u.pos[1], 2)})
                if st is None:
                    st = {"t_first": t, "ttc_min": ttc, "rank": 0, "hits": 0}
                    self.conflicts[key] = st
                st["hits"] += 1
                st["ttc_min"] = min(st["ttc_min"], ttc)
                if rank > st["rank"] and st["hits"] >= 2:
                    if st["rank"] > 0:
                        prev = {1: "potential", 2: "serious", 3: "critical"}[st["rank"]]
                        self.near_miss[prev] = max(0, self.near_miss[prev] - 1)
                    st["rank"] = rank
                    self.near_miss[lvl] += 1
                    self.emit({"type": "conflict", "t": t, "episode_t": st["t_first"], "level": lvl, "ttc": round(ttc, 2),
                               "drac": round(need, 1), "vru": u.id, "vru_kind": u.kind, "veh": c.id,
                               "veh_cls": c.subclass, "veh_speed_kmh": round(c.speed * 3.6, 1),
                               "x": round(u.pos[0], 2), "y": round(u.pos[1], 2), "replay": True})
        for key in list(self.conflicts):
            if key not in live_pairs and t - self.conflicts[key].get("t_seen", t) > 5:
                self.conflicts.pop(key, None)
            elif key in live_pairs:
                self.conflicts[key]["t_seen"] = t

        # ---------------- yield behaviour (unsignalised zebra, or crossing peds in any mode)
        look = float(self.cfg.get("yield_lookahead_m", 20.0))
        stop_v = float(self.cfg.get("yield_stop_speed", 1.5))
        signalised = self.signal_mode in ("adaptive", "fixed")
        def relevant(c):
            """VRUs this vehicle must yield to: crossing near its lane, or (unsignalised) waiting on its side."""
            cy = c.pos[1]
            out = [u for u in demand_cross if abs(u.pos[1] - cy) < 3.0]
            if not signalised:
                out += [u for u in demand_wait if (u.pos[1] < 0) == (cy < 0)]
            return out

        for c in vehs:
            ys = self.yield_state.setdefault(c.id, {"opp": False, "min_v": 1e9, "done": False, "who": None})
            if ys["done"]:
                continue
            d = self._approach(c, sc, look)
            rel = relevant(c)
            if d is not None and rel and d > 0.3:
                if not ys["opp"]:
                    ys["opp"] = True
                    ys["t_opp"] = t
                    ys["who"] = rel[0].id
                    ys["v_opp"] = c.speed
                ys["min_v"] = min(ys["min_v"], c.speed)
                if c.speed <= stop_v:
                    ys["done"] = True
                    if ys["v_opp"] > stop_v:  # it actually slowed down for the VRU (not queued from before)
                        self.yields["yielded"] += 1
                        self.emit({"type": "yield", "t": t, "outcome": "yielded", "veh": c.id, "vru": ys["who"],
                                   "dist_m": round(d, 1)})
            elif ys["opp"] and sc.in_crosswalk(*c.pos, 0.2):
                ys["done"] = True
                if rel and ys["min_v"] > stop_v:
                    self.yields["not_yielded"] += 1
                    self.emit({"type": "yield", "t": t, "outcome": "not_yielded", "veh": c.id, "vru": ys["who"],
                               "speed_kmh": round(c.speed * 3.6, 1), "replay": True,
                               "x": round(c.pos[0], 2), "y": round(c.pos[1], 2)})

        # ---------------- PET scheduling: when a vehicle has driven over the crosswalk
        for c in vehs:
            m = c.meta.get("count", {})
            if m.get("passed") and not c.meta.get("pet_sched"):
                c.meta["pet_sched"] = True
                self.pending_pet.append((t + 4.0, c))
        for tr in ended:
            if tr.kind == "vehicle" and tr.meta.get("count", {}).get("t_in") is not None and not tr.meta.get("pet_sched"):
                tr.meta["pet_sched"] = True
                self.pending_pet.append((t + 3.0, tr))
        while self.pending_pet and self.pending_pet[0][0] <= t:
            _, c = self.pending_pet.popleft()
            pool = {tr.id: tr for tr in list(dead) + vrus if tr.kind in VRU_KINDS}
            for u in pool.values():
                if (u.id, c.id) in self.pet_done:
                    continue
                if not u.history or not c.history:
                    continue
                if abs(u.history[-1][0] - c.history[-1][0]) > 30:
                    continue
                r = pet_pair(c, u, self.vru_r, sc.W)
                if r is None or r["pet"] > 10:
                    continue
                self.pet_done.add((u.id, c.id))
                self.pets.append((t, r["pet"], r["first"]))
                lvl = level_of(r["pet"], self.pet_levels)
                if lvl:
                    self.emit({"type": "pet", "t": r["t"], "level": lvl, "pet": round(r["pet"], 2),
                               "first": r["first"], "vru": u.id, "vru_kind": u.kind, "veh": c.id,
                               "veh_cls": c.subclass, "x": round(r["x"], 2), "y": round(r["y"], 2), "replay": True})

        # ---------------- alerts
        for u in vrus:
            m = u.meta.get("safety", {})
            if m.get("still", 0) >= float(self.cfg.get("stationary_alert_s", 12.0)) and ("still", u.id) not in self.alerted:
                self.alerted.add(("still", u.id))
                self.alerts += 1
                self.emit({"type": "alert", "t": t, "alert": "person_motionless_on_crosswalk", "vru": u.id,
                           "x": round(u.pos[0], 2), "y": round(u.pos[1], 2), "replay": True})
        for c in vehs:
            m = c.meta.setdefault("safety", {"block": 0.0, "t_prev": t})
            dt = max(0.0, t - m.get("t_prev", t))
            m["t_prev"] = t
            if sc.in_crosswalk(*c.pos, 0.0) and c.speed < 0.4:
                m["block"] = m.get("block", 0.0) + dt
            else:
                m["block"] = 0.0
            if m["block"] >= float(self.cfg.get("blocking_alert_s", 6.0)) and ("block", c.id) not in self.alerted:
                self.alerted.add(("block", c.id))
                self.alerts += 1
                self.emit({"type": "alert", "t": t, "alert": "vehicle_blocking_crosswalk", "veh": c.id,
                           "x": round(c.pos[0], 2), "y": round(c.pos[1], 2)})

        # ---------------- red-light violations (when a signal is present)
        if signal is not None and signalised:
            for u in vrus:
                if vstate[u.id] == "crossing" and not u.meta.get("red_checked"):
                    u.meta["red_checked"] = True
                    if signal.ped_state() == "red" and signal.time_in_state() > 1.0:
                        self.violations["ped_red"] += 1
                        self.emit({"type": "violation", "t": t, "violation": "pedestrian_on_red", "vru": u.id})
            for c in vehs:
                if sc.in_crosswalk(*c.pos, 0.0) and not c.meta.get("red_checked"):
                    c.meta["red_checked"] = True
                    if signal.veh_state() == "red" and signal.time_in_state() > 0.8 and c.speed > 1.5:
                        self.violations["veh_red"] += 1
                        self.emit({"type": "violation", "t": t, "violation": "vehicle_on_red", "veh": c.id,
                                   "speed_kmh": round(c.speed * 3.6, 1), "replay": True})

        # ---------------- warning beacon: explicit rules B0 / B1 / B2 (crosswalk/rules.py)
        level, why = 0, ""
        tta_max = float(self.cfg.get("beacon_tta_s", 6.0))
        people = demand_cross + demand_wait
        if people:
            best = None
            for c in vehs:
                r = vehicle_eta(c.pos, c.vel, sc, 40.0)
                if r is None or c.speed <= 1.0:
                    continue
                if r[1] < tta_max and (best is None or r[1] < best[1]):
                    best = (c, r[1])
            if best:
                u = people[0]
                c, tta = best
                level = 1
                why = (f"{u.subclass} #{u.id} {vstate[u.id]}; {c.subclass} #{c.id} arrives in {tta:.1f} s "
                       f"at {c.speed * 3.6:.0f} km/h")
        danger = [a for a in self.active if a["level"] in ("critical", "serious")]
        if danger:
            a = min(danger, key=lambda a: a["ttc"])
            level = 2
            why = f"vehicle #{a['veh']} -> person #{a['vru']}: TTC {a['ttc']:.1f} s ({a['level']})"
        hold = float(self.cfg.get("warning_hold_s", 1.5))
        if level > 0:
            self.warning_until = t + hold
            new_level = level
        elif t > self.warning_until:
            new_level, why = 0, "no person at the crossing with a vehicle arriving"
        else:
            new_level = self.warning_level  # hold
        if new_level != self.warning_level or (new_level > 0 and why and self.beacon_rule.get("why") != why
                                               and t - self.beacon_rule.get("t", 0) > 1.0):
            rid = f"B{new_level}"
            changed = new_level != self.warning_level
            self.beacon_rule = {"id": rid, "why": why, "t": round(t, 2)}
            if changed:
                self.beacon_history.appendleft(dict(self.beacon_rule))
                self.emit({"type": "beacon", "t": t, "rule": rid, "level": new_level, "why": why, "log_only": True})
        self.warning_level = new_level
        self.vru_waiting = len(demand_wait)
        self.vru_crossing = len(demand_cross)
        self.slowest_crossing = min((u.speed for u in demand_cross), default=None)
        # crossing pedestrians' remaining distance to the far curb (for signal extension)
        rem = []
        for u in demand_cross:
            y, vy = u.pos[1], u.vel[1]
            target = sc.L / 2 if vy >= 0 else -sc.L / 2
            rem.append(abs(target - y) / max(abs(vy), 0.5))
        self.max_time_to_clear = max(rem) if rem else 0.0

    def stats(self) -> dict:
        y, n = self.yields["yielded"], self.yields["not_yielded"]
        pets = [p for _, p, _ in self.pets]
        crit = self.near_miss["critical"] + sum(1 for p in pets if p <= self.pet_levels[0])
        # conflict rate normalised by exposure (vehicle passages), like conflict studies report it
        exposure = max(20, getattr(self, "exposure", 0))
        weighted = 3.0 * crit + 1.5 * self.near_miss["serious"] + 0.5 * self.near_miss["potential"] + 1.0 * n
        score = 100.0 * math.exp(-4.0 * weighted / exposure)
        return {
            "near_miss": dict(self.near_miss),
            "pet_count": len(pets),
            "pet_min": None if not pets else round(min(pets), 2),
            "pet_serious": sum(1 for p in pets if p <= self.pet_levels[1]),
            "yield": dict(self.yields),
            "yield_rate": None if (y + n) == 0 else round(y / (y + n), 3),
            "violations": dict(self.violations),
            "alerts": self.alerts,
            "warning_level": self.warning_level,
            "beacon_rule": self.beacon_rule,
            "beacon_history": list(self.beacon_history)[:8],
            "active_conflicts": self.active,
            "vru_waiting": getattr(self, "vru_waiting", 0),
            "vru_crossing": getattr(self, "vru_crossing", 0),
            "safety_score": round(max(0.0, score), 1),
        }
