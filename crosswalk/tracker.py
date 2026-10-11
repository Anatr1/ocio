"""Multi-object tracker in bird's-eye-view (ground plane, metres).

* constant-velocity Kalman filter per track, time-based (detections arrive at a variable rate because the
  detector is motion-gated / rate-adapted)
* measurement noise propagated from pixel noise through the homography Jacobian -> far objects are
  automatically trusted less
* ByteTrack-style two-stage association: confident detections first, then low-confidence detections may
  only extend existing tracks
* class voting over the whole track life (no class flicker in counts)
"""
from __future__ import annotations

import math
from collections import defaultdict, deque

import numpy as np

from .classes import DIMS, VRU_KINDS, kind_of, subclass_of

try:
    from scipy.optimize import linear_sum_assignment as _lsa
except Exception:  # noqa: BLE001 - scipy is optional on the board
    _lsa = None

INF = 1e6
CHI2_GATE = 13.8  # 2 dof, 99.9 %
TYPICAL_SPEED = {"pedestrian": 1.4, "bicycle": 5.0, "micromobility": 5.0, "vehicle": 10.0}


def assign(cost: np.ndarray):
    """Min-cost assignment; returns list of (row, col) with cost < INF."""
    if cost.size == 0:
        return []
    if _lsa is not None:
        r, c = _lsa(cost)
        return [(i, j) for i, j in zip(r, c) if cost[i, j] < INF]
    # greedy fallback
    pairs = []
    used_r, used_c = set(), set()
    for idx in np.argsort(cost, axis=None):
        i, j = divmod(int(idx), cost.shape[1])
        if cost[i, j] >= INF:
            break
        if i in used_r or j in used_c:
            continue
        pairs.append((i, j))
        used_r.add(i)
        used_c.add(j)
    return pairs


def kind_penalty(tk: str, dk: str, tcls: str = "", dcls: str = "") -> float:
    if tk == dk:
        return 0.0
    if tk in VRU_KINDS and dk in VRU_KINDS:
        return 2.0
    two_wheel = {"bicycle", "motorcycle", "e-scooter", "scooter"}
    if tcls in two_wheel and dcls in two_wheel:
        return 3.0
    return INF


class Track:
    _next_id = 1

    def __init__(self, det, t: float, cfg):
        self.id = Track._next_id
        Track._next_id += 1
        self.cfg = cfg
        self.t_first = t
        self.t_last = t          # last measurement update
        self.t_pred = t          # time the state was last predicted to
        self.hits = 1
        self.state = "tentative"
        self.cls_votes = defaultdict(float)
        self.ridden_votes = 0.0
        kind = det.kind or kind_of(det.cls)
        x, y = det.world
        v0 = TYPICAL_SPEED.get(kind, 2.0)
        self.x = np.array([x, y, 0.0, 0.0])
        c = det.cov if det.cov is not None else np.eye(2) * 0.25
        self.P = np.zeros((4, 4))
        self.P[:2, :2] = c
        self.P[2, 2] = self.P[3, 3] = v0 * v0
        self.history = deque()
        self.bbox = (det.x1, det.y1, det.x2, det.y2)
        self.score = det.score
        self.heights = deque(maxlen=15)
        self.heading = None
        self.fast_time = 0.0
        self.meta = {}           # used by counting / safety modules
        self._vote(det)
        self._push_history(t)

    # ------------------------------------------------------------------ class handling
    def _vote(self, det):
        self.cls_votes[det.cls] += max(det.score, 0.05)
        gt = det.extra.get("gt") if det.extra else None
        if gt is not None:  # simulator ground truth (diagnostics only)
            self.gt_votes = getattr(self, "gt_votes", defaultdict(int))
            self.gt_votes[gt] += 1
        if det.ridden:
            self.ridden_votes += det.score
        if det.height_m:
            self.heights.append(det.height_m)
        self.score = 0.7 * self.score + 0.3 * det.score

    @property
    def cls(self) -> str:
        return max(self.cls_votes.items(), key=lambda kv: kv[1])[0]

    @property
    def subclass(self) -> str:
        if kind_of(self.cls) == "pedestrian" and self.kind != "pedestrian":  # reclassified by speed
            return "bicycle" if self.kind == "bicycle" else "e-scooter"
        return subclass_of(self.cls)

    @property
    def kind(self) -> str:
        k = kind_of(self.cls)
        if k == "pedestrian" and self.fast_time >= 1.0:
            # A "person" this fast is riding something the detector missed (bikes are thin and small at
            # 320 px). Bicycles are what the task counts, so they are the default guess (e-scooters too).
            return self.cfg.get("fast_person_kind", "bicycle")
        return k

    @property
    def ridden(self) -> bool:
        return self.ridden_votes > 0.3 * sum(self.cls_votes.values())

    @property
    def height(self):
        if not self.heights:
            return None
        return float(np.median(self.heights))

    @property
    def dims(self):
        return DIMS.get(self.subclass, DIMS.get(self.kind, (0.5, 0.5, 1.7)))

    # ------------------------------------------------------------------ kinematics
    @property
    def pos(self):
        return float(self.x[0]), float(self.x[1])

    @property
    def vel(self):
        return float(self.x[2]), float(self.x[3])

    @property
    def speed(self) -> float:
        return float(math.hypot(self.x[2], self.x[3]))

    def accel_long(self, window=0.8) -> float:
        """Longitudinal acceleration (m/s^2, negative = braking) over the last ``window`` seconds."""
        if len(self.history) < 3:
            return 0.0
        t1, _, _, vx1, vy1 = self.history[-1]
        old = None
        for h in reversed(self.history):
            if t1 - h[0] >= window:
                old = h
                break
        if old is None:
            old = self.history[0]
        t0, _, _, vx0, vy0 = old
        if t1 - t0 < 0.25:
            return 0.0
        return (math.hypot(vx1, vy1) - math.hypot(vx0, vy0)) / (t1 - t0)

    @property
    def gt_id(self):
        v = getattr(self, "gt_votes", None)
        return max(v.items(), key=lambda kv: kv[1])[0] if v else None

    def accel_noise(self):
        return float(self.cfg["accel_noise"].get(self.kind, 2.0))

    def predict(self, t: float):
        dt = t - self.t_pred
        if dt <= 0:
            return
        q = self.accel_noise() ** 2
        F = np.eye(4)
        F[0, 2] = F[1, 3] = dt
        G = np.array([[0.5 * dt * dt, 0], [0, 0.5 * dt * dt], [dt, 0], [0, dt]])
        Q = G @ G.T * q
        self.x = F @ self.x
        self.P = F @ self.P @ F.T + Q
        self.t_pred = t

    def innovation(self, z, R):
        S = self.P[:2, :2] + R
        nu = np.asarray(z) - self.x[:2]
        return nu, S

    def mahalanobis2(self, z, R) -> float:
        nu, S = self.innovation(z, R)
        try:
            return float(nu @ np.linalg.solve(S, nu))
        except np.linalg.LinAlgError:
            return INF

    def update(self, det, t: float):
        z = np.asarray(det.world)
        R = det.cov if det.cov is not None else np.eye(2) * 0.25
        nu, S = self.innovation(z, R)
        K = self.P[:, :2] @ np.linalg.inv(S)
        self.x = self.x + K @ nu
        I_KH = np.eye(4)
        I_KH[:, :2] -= K
        self.P = I_KH @ self.P
        self.P = 0.5 * (self.P + self.P.T)
        dt = t - self.t_last
        self.t_last = t
        self.hits += 1
        self.bbox = (det.x1, det.y1, det.x2, det.y2)
        self._vote(det)
        sp = self.speed
        if sp > 0.4:
            hd = math.atan2(self.x[3], self.x[2])
            self.heading = hd if self.heading is None else _blend_angle(self.heading, hd, 0.3)
        thr = float(self.cfg.get("micromobility_speed", 3.6))
        if kind_of(self.cls) == "pedestrian":
            self.fast_time = self.fast_time + dt if sp > thr else max(0.0, self.fast_time - dt)
        self._push_history(t)

    def _push_history(self, t):
        self.history.append((t, float(self.x[0]), float(self.x[1]), float(self.x[2]), float(self.x[3])))
        horizon = float(self.cfg.get("history_s", 20.0))
        while self.history and t - self.history[0][0] > horizon:
            self.history.popleft()

    def to_dict(self, t=None, zone=None) -> dict:
        x, y = self.pos
        vx, vy = self.vel
        L, W, Hh = self.dims
        h = self.height
        return {
            "id": self.id,
            "kind": self.kind,
            "cls": self.subclass,
            "x": round(x, 3),
            "y": round(y, 3),
            "vx": round(vx, 3),
            "vy": round(vy, 3),
            "speed": round(self.speed, 2),
            "heading": None if self.heading is None else round(self.heading, 3),
            "state": self.state,
            "age": round((t or self.t_last) - self.t_first, 2),
            "since_update": round((t or self.t_last) - self.t_last, 2),
            "conf": round(self.score, 2),
            "zone": zone,
            "height": None if h is None else round(h, 2),
            "dims": [L, W, Hh if not h else round(h, 2)],
            "ridden": self.ridden,
            "bbox": [round(v, 1) for v in self.bbox],
        }


def _blend_angle(a, b, w):
    d = (b - a + math.pi) % (2 * math.pi) - math.pi
    return a + w * d


class Tracker:
    def __init__(self, cfg, scene=None, conf_high=0.35):
        if cfg.get("fast_person_kind", "bicycle") not in ("bicycle", "micromobility"):
            raise ValueError("tracker.fast_person_kind must be bicycle or micromobility")
        self.cfg = cfg
        self.scene = scene
        self.conf_high = conf_high
        self.tracks: list[Track] = []
        self.dead: deque = deque(maxlen=200)   # recently ended tracks (for PET / replays)
        self._dup = defaultdict(int)
        self.t = 0.0
        self.ended_now: list[Track] = []
        self.lost: list[Track] = []            # confirmed tracks that lost their detections (re-identifiable)
        self.revived = 0

    def max_age(self, tr: Track) -> float:
        if tr.state == "tentative":
            return float(self.cfg.get("tentative_max_age_s", 0.6))
        return float(self.cfg["max_age_s"].get(tr.kind, 1.2))

    def min_hits(self, tr: Track) -> int:
        n = int(self.cfg.get("min_hits", 3))
        return max(2, n - 1) if tr.kind == "vehicle" else n

    def predict(self, t):
        for tr in self.tracks:
            tr.predict(t)
        self.t = t

    def _cost(self, tracks, dets, extra_penalty=0.0):
        C = np.full((len(tracks), len(dets)), INF)
        for i, tr in enumerate(tracks):
            gate = float(self.cfg["gate_m"].get(tr.kind, 2.0)) + 0.3 * tr.speed
            tx, ty = tr.pos
            for j, d in enumerate(dets):
                pen = kind_penalty(tr.kind, d.kind or kind_of(d.cls), tr.cls, d.cls)
                if pen >= INF:
                    continue
                dx, dy = d.world[0] - tx, d.world[1] - ty
                if dx * dx + dy * dy > gate * gate:
                    continue
                m2 = tr.mahalanobis2(d.world, d.cov if d.cov is not None else np.eye(2) * 0.25)
                if m2 > CHI2_GATE:
                    continue
                C[i, j] = m2 + pen + extra_penalty
        return C

    def update(self, t: float, dets) -> list[Track]:
        """dets: localized Detection objects (with .world). Returns live tracks.
        Tracks that ended during this call are in ``self.ended_now``."""
        self.ended_now = []
        self.predict(t)
        dets = [d for d in dets if d.world is not None and (d.kind or kind_of(d.cls)) != "other"]
        if self.scene is not None:
            dets = [d for d in dets if self.scene.in_bounds(*d.world)]
        high = [d for d in dets if d.score >= self.conf_high]
        low = [d for d in dets if d.score < self.conf_high]

        # stage 1: all tracks vs confident detections (confirmed tracks preferred)
        order = sorted(self.tracks, key=lambda tr: 0 if tr.state == "confirmed" else 1)
        C = self._cost(order, high)
        for i, tr in enumerate(order):
            if tr.state != "confirmed":
                C[i][C[i] < INF] += 0.5
        matched_t, matched_d = set(), set()
        for i, j in assign(C):
            order[i].update(high[j], t)
            matched_t.add(order[i].id)
            matched_d.add(j)

        # stage 2: remaining confirmed tracks vs low-confidence detections
        rem = [tr for tr in self.tracks if tr.id not in matched_t and tr.state == "confirmed"]
        if rem and low:
            C2 = self._cost(rem, low, extra_penalty=1.0)
            for i, j in assign(C2):
                rem[i].update(low[j], t)
                matched_t.add(rem[i].id)

        # stage 3: re-identify lost tracks (occlusion behind a bus, missed detections) with unmatched
        # confident detections - same id, counting state preserved, no double count
        unmatched = [j for j in range(len(high)) if j not in matched_d]
        if self.lost and unmatched:
            for tr in self.lost:
                tr.predict(t)
            cand = [high[j] for j in unmatched]
            C3 = np.full((len(self.lost), len(cand)), INF)
            for i, tr in enumerate(self.lost):
                gap_t = t - tr.t_last
                gate = float(self.cfg["gate_m"].get(tr.kind, 2.0)) + 0.6 * tr.speed * gap_t + 0.5
                for j, d in enumerate(cand):
                    pen = kind_penalty(tr.kind, d.kind or kind_of(d.cls), tr.cls, d.cls)
                    if pen >= INF:
                        continue
                    dist = math.hypot(d.world[0] - tr.pos[0], d.world[1] - tr.pos[1])
                    if dist <= gate:
                        C3[i, j] = dist / gate + pen
            for i, j in assign(C3):
                tr = self.lost[i]
                tr.update(cand[j], t)
                tr.state = "confirmed"
                self.revived += 1
                self.tracks.append(tr)
                matched_d.add(unmatched[j])
                matched_t.add(tr.id)
            self.lost = [tr for tr in self.lost if tr.state == "lost"]

        # new tracks from unmatched confident detections
        for j, d in enumerate(high):
            if j in matched_d:
                continue
            # don't spawn on top of an existing track (duplicate box / bad measurement of the same object)
            dk = d.kind or kind_of(d.cls)
            r_sup = 2.5 if dk == "vehicle" else 0.5
            if any(math.hypot(d.world[0] - tr.pos[0], d.world[1] - tr.pos[1]) < (2.5 if "vehicle" in (dk, tr.kind) else r_sup)
                   and kind_penalty(tr.kind, dk, tr.cls, d.cls) < INF for tr in self.tracks):
                continue
            self.tracks.append(Track(d, t, self.cfg))

        # lifecycle
        alive = []
        for tr in self.tracks:
            if tr.state == "tentative" and tr.hits >= self.min_hits(tr):
                tr.state = "confirmed"
            age = t - tr.t_last
            out_of_scene = self.scene is not None and not self.scene.in_bounds(*tr.pos)
            if age > self.max_age(tr) or out_of_scene:
                if tr.state == "confirmed":
                    if out_of_scene:
                        self._end(tr, t)
                    else:
                        tr.state = "lost"
                        self.lost.append(tr)
                continue
            alive.append(tr)
        self.tracks = alive
        ttl = float(self.cfg.get("lost_ttl_s", 3.0))
        keep = []
        for tr in self.lost:
            if t - tr.t_last > ttl or (self.scene is not None and not self.scene.in_bounds(*tr.pos)):
                self._end(tr, t)
            else:
                keep.append(tr)
        self.lost = keep
        self._dedup(t)
        return self.tracks

    def _end(self, tr, t):
        tr.state = "ended"
        tr.t_end = t
        self.dead.append(tr)
        self.ended_now.append(tr)

    def _dedup(self, t):
        conf = [tr for tr in self.tracks if tr.state == "confirmed"]
        seen = set()
        for i in range(len(conf)):
            for j in range(i + 1, len(conf)):
                a, b = conf[i], conf[j]
                if kind_penalty(a.kind, b.kind, a.cls, b.cls) >= INF:
                    continue
                lim = 1.2 if "vehicle" in (a.kind, b.kind) else 0.35
                d = math.hypot(a.pos[0] - b.pos[0], a.pos[1] - b.pos[1])
                key = (min(a.id, b.id), max(a.id, b.id))
                seen.add(key)
                if d < lim:
                    self._dup[key] += 1
                    if self._dup[key] >= 4:
                        young = a if a.t_first > b.t_first else b
                        old = b if young is a else a
                        for k, v in young.cls_votes.items():
                            old.cls_votes[k] += v
                        young.state = "merged"
                        young.merged_into = old.id
                        young.t_end = t
                        self.ended_now.append(young)
                        self.tracks = [tr for tr in self.tracks if tr is not young]
                        return
                else:
                    self._dup.pop(key, None)
        for k in list(self._dup):
            if k not in seen:
                self._dup.pop(k, None)

    def confirmed(self):
        return [tr for tr in self.tracks if tr.state == "confirmed"]
