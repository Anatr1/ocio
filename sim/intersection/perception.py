"""Four-camera RGB observations -> fused metric tracks, demand and digital twin.

This module has no simulator-user input. Geometry and calibrated cameras are
known infrastructure; identities, motion, queues and passages come from the NN.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import replace
import math
import numpy as np

from crosswalk.classes import kind_of
from crosswalk.config import load_config
from crosswalk.tracker import Tracker
from .geometry import ARMS, FORWARD, right


def fuse_observations(observations):
    """Associate only across cameras, then conservatively combine measurements.

    A cluster contains at most one detection per camera. Covariance intersection
    avoids assuming that camera calibration/footpoint errors are independent.
    Spatial gating is deliberately tight; uncertain associations stay separate.
    """
    clusters = []
    for camera, detections in observations.items():
        for det in sorted(detections, key=lambda d: -d.score):
            if det.world is None or not np.isfinite(det.world).all():
                continue
            kind = det.kind or kind_of(det.cls)
            if kind == "other":
                continue
            best, distance = None, math.inf
            gate = 2.2 if kind == "vehicle" else .75
            for cluster in clusters:
                if camera in cluster["cameras"] or cluster["kind"] != kind:
                    continue
                # Complete-link gating prevents a chain joining two close users.
                gap = max(math.dist(det.world, d.world) for d in cluster["detections"])
                if gap < gate and gap < distance:
                    best, distance = cluster, gap
            if best is None:
                clusters.append({"kind": kind, "cameras": {camera}, "detections": [det]})
            else:
                best["cameras"].add(camera)
                best["detections"].append(det)
    fused = []
    for cluster in clusters:
        rows = cluster["detections"]
        weights = np.asarray([max(.05, d.score) for d in rows]); weights /= weights.sum()
        precision = [np.linalg.pinv(d.cov if d.cov is not None else np.eye(2)*.25) for d in rows]
        covariance = np.linalg.pinv(sum(w*p for w,p in zip(weights,precision)))
        position = covariance @ sum(w*p@np.asarray(d.world) for w,p,d in zip(weights,precision,rows))
        exemplar = max(rows, key=lambda d: d.score)
        fused.append(replace(exemplar, world=tuple(position), cov=covariance,
                             extra={"cameras": sorted(cluster["cameras"])}))
    return fused


class IntersectionPerception:
    def __init__(self, geometry, tracker_cfg=None, max_frame_age=1.5):
        if not math.isfinite(max_frame_age) or max_frame_age <= 0:
            raise ValueError("max_frame_age must be finite and positive")
        self.geometry = geometry
        self.max_frame_age = max_frame_age
        self.tracker = Tracker(tracker_cfg or load_config(None, []).tracker)
        self.frame_t = None
        self.batches = 0
        self.raw_count = self.fused_count = 0
        self.movements = Counter()
        self.crossings = {a: Counter() for a in ARMS}
        self.counts = Counter()
        self.class_counts = Counter()
        self.wait_sum, self.wait_n = Counter(), Counter()
        self.speed_samples = []

    def update(self, t, observations):
        if self.frame_t is not None and t <= self.frame_t:
            return
        fused = fuse_observations(observations)
        self.raw_count = sum(len(rows) for rows in observations.values())
        self.fused_count = len(fused)
        self.tracker.update(t, fused)
        self.frame_t, self.batches = t, self.batches + 1
        for tr in self.tracker.confirmed():
            self._describe(tr, t)

    def _axes(self, pos, arm):
        f = FORWARD[arm]; lateral = right(f)
        return -sum(p*v for p,v in zip(pos,f)), sum(p*v for p,v in zip(pos,lateral))

    def _describe(self, tr, t):
        meta = tr.meta
        if tr.speed < .8 and t-tr.t_last < .3:
            meta.setdefault("wait_started", t)
        else:
            if "wait_started" in meta:
                meta["observed_wait"] = meta.get("observed_wait", 0.) + t-meta.pop("wait_started")
        meta["movement"], meta["crosswalk"] = None, None
        if tr.kind == "vehicle" or tr.kind in ("bicycle", "micromobility"):
            for arm in ARMS:
                radius, lateral = self._axes(tr.pos, arm)
                if 14 < radius < self.geometry.approach and .2 < lateral < 7.7:
                    meta.setdefault("origin", arm)
                    meta["movement"] = f"{arm}_{'left' if lateral < 3.5 else 'straight'}"
                    meta["turn_uncertain"] = lateral >= 3.5
                    break
            origin = meta.get("origin")
            if origin:
                for arm in ARMS:
                    radius, lateral = self._axes(tr.pos, arm)
                    f = FORWARD[arm]
                    outward = -sum(v*w for v,w in zip(tr.vel,f))
                    if arm != origin and radius > 16 and -7.7 < lateral < -.2 and outward > .5:
                        route = next((r for r in self.geometry.routes.values() if r.origin == origin and r.destination == arm), None)
                        if route:
                            meta["movement"], meta["turn_uncertain"] = route.id, False
                            if not meta.get("passage_counted"):
                                meta["passage_counted"] = True
                                self.movements[route.id] += 1
                                self.counts["vehicles_completed"] += 1
                                self.class_counts[tr.kind] += 1
                                self._record_wait("vehicle", meta)
                                self.speed_samples.append(tr.speed*3.6)
                                self.speed_samples = self.speed_samples[-10000:]
            if origin:
                return
        # Zebra association is geometric and independent of simulator admission.
        for arm in ARMS:
            radius, lateral = self._axes(tr.pos, arm)
            if abs(radius-self.geometry.crossing_radius) < 2.5 and abs(lateral) < 11:
                meta["crosswalk"] = arm
                if abs(lateral) > 7.3:
                    side = 1 if lateral > 0 else -1
                    key = "crossing_start"
                    if key not in meta:
                        meta[key] = (arm, side)
                    elif meta[key] == (arm, -side) and not meta.get("passage_counted"):
                        meta["passage_counted"] = True
                        self.crossings[arm][tr.kind] += 1
                        self.counts["pedestrians_completed"] += 1
                        self.class_counts[tr.kind] += 1
                        self._record_wait("pedestrian", meta)
                break

    def _record_wait(self, kind, meta):
        self.wait_sum[kind] += meta.get("observed_wait", 0.)
        self.wait_n[kind] += 1

    def demands(self, t):
        vehicles = {rid: {"count": 0, "queued": 0, "oldest_s": 0.} for rid in self.geometry.routes}
        pedestrians = {arm: {"count": 0, "oldest_s": 0.} for arm in ARMS}
        occupied = False
        # Recently lost tracks still block clearance while occluded.
        track_age = max(2.,self.max_frame_age)
        tracks = self.tracker.confirmed() + [tr for tr in self.tracker.lost if t-tr.t_last <= track_age]
        for tr in tracks:
            if t-tr.t_last > track_age:
                continue
            x,y = tr.pos
            occupied |= abs(x) < self.geometry.half_road and abs(y) < self.geometry.half_road
            for crossing_arm in ARMS:
                radius,lateral = self._axes(tr.pos, crossing_arm)
                occupied |= (abs(radius-self.geometry.crossing_radius) < self.geometry.crosswalk_width/2+1
                             and abs(lateral) < self.geometry.half_road)
            meta = tr.meta
            age = t-meta.get("wait_started", t)
            movement = meta.get("movement")
            if movement and not meta.get("passage_counted"):
                radius,lateral = self._axes(tr.pos, movement[0])
                if radius > self.geometry.stop_radius-1 and .2 < lateral < 7.7:
                    row = vehicles[movement]
                    row["count"] += 1; row["queued"] += int(tr.speed < 1)
                    row["oldest_s"] = max(row["oldest_s"], round(age,2))
            arm = meta.get("crosswalk")
            if arm:
                radius,lateral = self._axes(tr.pos, arm)
                if abs(lateral) >= 7 and not meta.get("passage_counted"):
                    row = pedestrians[arm]; row["count"] += 1
                    row["oldest_s"] = max(row["oldest_s"], round(age,2))
        return vehicles, pedestrians, occupied

    def control_observations(self, t):
        vehicles,pedestrians,occupied = self.demands(t)
        fresh = self.frame_t is not None and t-self.frame_t <= self.max_frame_age
        return vehicles,pedestrians,occupied,fresh

    def report(self):
        speeds = sorted(self.speed_samples)
        return {"observation_mode": "four-camera NN perception", "frames": self.batches,
                "counts": {kind:self.class_counts[kind] for kind in ("vehicle","pedestrian","bicycle","micromobility")},
                "metrics": dict(self.counts),
                "mean_completed_wait_s": {k: round(self.wait_sum[k]/self.wait_n[k],2) if self.wait_n[k] else None for k in ("vehicle","pedestrian")},
                "movement_counts": {rid: self.movements[rid] for rid in self.geometry.routes},
                "crosswalk_counts": {a: dict(self.crossings[a]) for a in ARMS},
                "vehicle_speed_kmh": {"sample_count": len(speeds), "mean": round(sum(speeds)/len(speeds),2) if speeds else None,
                                      "v85": round(speeds[int(.85*(len(speeds)-1))],2) if speeds else None},
                "notes": ["Counts require an observed approach and exit on the same model track; missed/reidentified users can affect counts.",
                          "Wait is observed stationary time, not a full journey delay. Through/right intent is unknown until the exit is observed.",
                          "Camera footpoints use a ground-plane assumption; vehicle localization and multi-camera association remain approximate.",
                          "Clearance uses perceived occupancy. Missed objects are not silently replaced with simulator truth."]}

    def snapshot(self, t):
        vehicles,pedestrians,occupied = self.demands(t)
        agents = []
        for tr in self.tracker.confirmed():
            if t-tr.t_last > self.max_frame_age:
                continue
            row = tr.to_dict(t)
            row.update({"heading": tr.heading if tr.heading is not None else 0.,
                        "movement": tr.meta.get("movement"), "crosswalk": tr.meta.get("crosswalk"),
                        "turn_uncertain": tr.meta.get("turn_uncertain", True),
                        "wait_s": round(t-tr.meta.get("wait_started", t),1)})
            agents.append(row)
        conflicts = []
        for i,a in enumerate(agents):
            for b in agents[i+1:]:
                if "vehicle" not in (a["kind"],b["kind"]):
                    continue
                separation = np.array([b["x"]-a["x"],b["y"]-a["y"]])
                relative = np.array([b["vx"]-a["vx"],b["vy"]-a["vy"]])
                closing = float(relative@relative)
                if closing < .25:
                    continue
                ttc = -float(separation@relative)/closing
                if 0 < ttc < 3 and np.linalg.norm(separation+relative*ttc) < 2:
                    conflicts.append({"t":round(t,1),"agents":[a["id"],b["id"]],"ttc":round(ttc,2)})
        return {"agents": agents, "demands": {"vehicles": vehicles,"pedestrians": pedestrians},
                "statistics": self.report(), "events": [], "conflicts": conflicts,
                "perception": {"frame_t": self.frame_t, "batches": self.batches, "raw_detections": self.raw_count,
                               "fused_detections": self.fused_count, "tracks": len(agents), "occupied": occupied,
                               "fresh": self.control_observations(t)[3]}}
