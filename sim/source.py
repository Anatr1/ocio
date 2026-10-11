"""SimSource: a drop-in replacement for a camera. Renders a synthetic view of the simulated crosswalk from a
virtual camera and produces noisy detections (as a YOLO model would) so the whole pipeline - ground
projection, tracker, counting, safety, signal, MCU, dashboard - runs without hardware."""
from __future__ import annotations

import math
import random
import time

import cv2
import numpy as np

from crosswalk.detectors.base import Detection
from crosswalk.geometry import Camera

from .camera import camera_for_config
from .repro import file_hash
from .scenarios import load_scenario
from .world import DET_CLASS, World


def box_corners(a):
    L, W, H = a.dims
    c, s = math.cos(a.heading), math.sin(a.heading)
    pts = []
    for dz in (0.0, H):
        for dx, dy in ((L / 2, W / 2), (L / 2, -W / 2), (-L / 2, -W / 2), (-L / 2, W / 2)):
            pts.append((a.x + c * dx - s * dy, a.y + s * dx + c * dy, dz))
    return np.array(pts)


def stage(world, rng, name):
    """Dashboard demo buttons: add a scripted situation to a running World. Raises ValueError if it cannot be placed."""
    w = world
    if name == "near_miss":
        side = rng.choice((-1, 1))
        d = -side if rng.random() < 0.5 else side
        # pedestrian already at the curb, starts crossing now; a fast non-yielding car arrives
        p = w.spawn("pedestrian", side=side, x=0.5, y=side * (w.L / 2 + 0.35), cross_x=0.5, state="cross", v=1.15)
        p.meta["t_cross0"] = w.t
        lane_y = -d * w.L / 4
        dist_lane = abs(lane_y - p.y)
        t_ped_in_lane = dist_lane / 1.15
        # 9 m/s, 0.6 s behind the pedestrian: always a real conflict (TTC ~1 s), never a crash, and visible to the
        # camera long enough to be tracked (13 m/s from 48 m was flagged by the pipeline only half of the time)
        v = 9.0
        car_x0 = -d * (v * (t_ped_in_lane + 0.6) + 2.2)
        c = w.spawn("car", dir=d, x=car_x0, v=v, yields=False)
        c.meta["reaction"] = 1.4
        return True
    if name == "elderly":
        side = rng.choice((-1, 1))
        w.spawn("pedestrian", side=side, x=-0.5, y=side * (w.L / 2 + 0.6), cross_x=-0.5, v=0.55)
        return True
    if name == "group":
        side = rng.choice((-1, 1))
        for i in range(5):
            w.spawn("pedestrian", side=side, x=-1.2 + 0.6 * i, cross_x=-1.2 + 0.6 * i,
                    y=side * (w.L / 2 + 1.0 + 0.4 * (i % 2)))
        return True
    if name in ("car", "bicycle", "e-scooter", "pedestrian", "child"):
        w.spawn(name)
        return True
    return False


def apply_stage(world, rng, name):
    """stage() with rollback: a situation that cannot be placed leaves the World untouched."""
    agents, next_id, state = list(world.agents), world.next_id, world.rng.getstate()
    try:
        return stage(world, rng, name)
    except ValueError:
        world.agents, world.next_id = agents, next_id
        world.rng.setstate(state)
        return False


class SimSource:
    live = False

    def __init__(self, cfg, scenario="mixed", seed=0, realtime=True, fps=15.0, speed=1.0, signal=None,
                 noise=None, render=True):
        scfg = cfg.scene
        self.cfg = cfg
        self.width = int(cfg.source.get("width", 640))
        self.height = int(cfg.source.get("height", 480))
        sim = cfg.get("sim", {}) or {}
        cw = scfg["crosswalk"]
        W, L, D = float(cw["width"]), float(cw["length"]), float(scfg.get("curb_depth", 2.5))
        self.camera, self.scene = camera_for_config(cfg, self.width, self.height)
        sc = load_scenario(scenario)
        self.scenario_name = sc["name"]
        self.conditions = sc["conditions"]
        if not math.isfinite(fps) or fps <= 0 or not math.isfinite(speed) or speed <= 0:
            raise ValueError("fps and playback speed must be positive and finite")
        if sim.get("presentation_mode") or sc.get("presentation_mode"):
            raise ValueError("L1 evaluation refuses presentation_mode")
        self.world = World(scfg, sc, seed=seed, signal=signal, cfg=cfg)
        self.rng = random.Random(seed + 1)
        self._pending = []  # dashboard demo buttons, applied in the simulation thread
        self.np_rng = np.random.default_rng(seed + 2)
        self.fps = fps
        self.realtime = realtime
        self.speed = speed
        self.dt = 1.0 / fps
        self.seq = 0
        self.t_wall0 = None
        self.render_enabled = render
        profile = sim.get("noise", {})
        if isinstance(profile, str):
            import yaml

            with open(profile, encoding="utf-8") as f:
                profile = yaml.safe_load(f)
        self.noise = {"miss": 0.03, "jitter": 0.03, "fp_rate": 0.02, "class_flip": 0.02, **profile, **(noise or {})}
        self.unfitted_bins = set()
        self._last_detection_t = 0.0
        if self.noise.get("fitted") and file_hash(cfg.detector.model) != self.noise["model_hash"]:
            raise ValueError("the fitted noise profile belongs to a different detector model")
        if self.noise.get("fitted"):
            recorded = self.noise["detector_config"]
            for key in ("imgsz", "conf", "conf_low", "iou", "roi", "class_names"):
                if recorded.get(key) != cfg.detector.get(key):
                    raise ValueError(f"fitted noise detector configuration differs at {key}")
        self._bg = self._render_background() if render else np.zeros((self.height, self.width, 3), np.uint8)
        self.t0 = time.monotonic()

    # ------------------------------------------------------------------ calibration helpers
    def calibration(self):
        """Image points of the crosswalk corners as seen by the virtual camera (as a human would click)."""
        W, L = self.world.W, self.world.L
        corners = [(-W / 2, -L / 2, 0), (W / 2, -L / 2, 0), (W / 2, L / 2, 0), (-W / 2, L / 2, 0)]
        uv, _ = self.camera.project(corners)
        return {"H": self.camera.H_i2w.tolist(), "image_points": uv.tolist(),
                "image_size": [self.width, self.height], "focal_px": float(self.camera.K[0, 0])}

    # ------------------------------------------------------------------ rendering
    def _poly(self, img, pts3, color):
        uv, z = self.camera.project(pts3)
        if (z <= 0.2).any():
            return
        cv2.fillPoly(img, [np.round(uv).astype(np.int32)], color, cv2.LINE_AA)

    def _render_background(self):
        w = self.world
        img = np.zeros((self.height, self.width, 3), np.uint8)
        img[:] = (95, 105, 110)  # far field / buildings
        far = 80.0
        Wd, L, D, sw, A = w.W, w.L, w.D, w.sw, w.A
        rng = np.random.default_rng(3)

        def quad(x0, y0, x1, y1):
            return [(x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y1, 0)]

        # sidewalks and road (split into chunks so the near-plane clipping never discards everything)
        for xs in np.arange(-far, far, 5.0):
            self._poly(img, quad(xs, -L / 2 - D - sw - 6, xs + 5.0, -L / 2), (150, 150, 145))
            self._poly(img, quad(xs, L / 2, xs + 5.0, L / 2 + D + sw + 6), (150, 150, 145))
            self._poly(img, quad(xs, -L / 2, xs + 5.0, L / 2), (70, 72, 74))
        # curbs
        for xs in np.arange(-far, far, 5.0):
            for y in (-L / 2, L / 2):
                self._poly(img, quad(xs, y - 0.15, xs + 5.0, y + 0.15), (185, 185, 180))
        # zebra stripes (parallel to the road axis, 0.5 m wide)
        stripe, gap = 0.5, 0.5
        y = -L / 2 + 0.25
        while y + stripe <= L / 2 - 0.1:
            self._poly(img, quad(-Wd / 2, y, Wd / 2, y + stripe), (232, 232, 228))
            y += stripe + gap
        # lane line + stop lines
        for xs in np.arange(-far, far, 6.0):
            if abs(xs) > Wd / 2 + 2:
                self._poly(img, quad(xs, -0.06, xs + 3.0, 0.06), (220, 220, 220))
        for d in (-1, 1):
            x = -d * (Wd / 2 + 1.5)
            yl = -d * L / 4
            self._poly(img, quad(x - 0.25, yl - L / 4 + 0.2, x + 0.25, yl + L / 4 - 0.2), (225, 225, 225))
        # texture noise
        noise = rng.normal(0, 4, img.shape).astype(np.int16)
        img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        return img

    def render(self):
        img = self._bg.copy()
        C = self.camera.center
        agents = sorted(self.world.agents, key=lambda a: -math.hypot(a.x - C[0], a.y - C[1]))
        for a in agents:
            pts = box_corners(a)
            uv, z = self.camera.project(pts)
            if (z <= 0.3).any():
                continue
            uv = np.round(uv).astype(np.int32)
            col = tuple(int(c) for c in a.color)
            dark = tuple(int(c * 0.6) for c in col)
            light = tuple(min(255, int(c * 1.25 + 20)) for c in col)
            if a.kind == "vehicle":
                faces = [[0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]
                for f in faces:
                    cv2.fillConvexPoly(img, uv[f], dark, cv2.LINE_AA)
                cv2.fillConvexPoly(img, uv[[4, 5, 6, 7]], light, cv2.LINE_AA)
                # windscreen band
                top = uv[[4, 5, 6, 7]].mean(axis=0)
                cv2.circle(img, tuple(int(v) for v in top), max(2, int(abs(uv[4, 1] - uv[0, 1]) * 0.15)), (40, 40, 50), -1)
            else:
                foot = uv[:4].mean(axis=0)
                head = uv[4:].mean(axis=0)
                hgt = max(4.0, float(np.linalg.norm(head - foot)))
                wpx = max(2, int(hgt * 0.16))
                p0 = tuple(int(v) for v in foot)
                p1 = tuple(int(v) for v in head + (foot - head) * 0.15)
                cv2.line(img, p0, p1, col, wpx * 2, cv2.LINE_AA)
                cv2.circle(img, tuple(int(v) for v in head + (foot - head) * 0.08), max(2, int(wpx * 0.9)), (170, 190, 220), -1, cv2.LINE_AA)
                if a.cls in ("bicycle", "e-scooter"):
                    cv2.line(img, tuple(uv[0]), tuple(uv[2]), (30, 30, 30), max(1, wpx // 2), cv2.LINE_AA)
        return img

    # ------------------------------------------------------------------ detections
    # ------------------------------------------------------------------ ground truth (sim only, never fed to the pipeline)
    def in_view(self, a) -> float:
        """Fraction of the agent's projected 3D box inside the image (0 = not visible)."""
        uv, z = self.camera.project(box_corners(a))
        if (z <= 0.3).any():
            return 0.0
        x1, y1 = uv.min(axis=0)
        x2, y2 = uv.max(axis=0)
        full = max(1.0, (x2 - x1) * (y2 - y1))
        cx1, cy1, cx2, cy2 = max(0, x1), max(0, y1), min(self.width - 1, x2), min(self.height - 1, y2)
        if cx2 - cx1 < 3 or cy2 - cy1 < 3:
            return 0.0
        return float((cx2 - cx1) * (cy2 - cy1) / full)

    GT_RANGE_M = 90.0  # the dashboard twin's street ends here (dashboard/js/twin.js `far`)

    def ground_truth(self) -> list[dict]:
        """True state of every agent on the modelled street (saturated queues can extend far beyond it).
        Adapter point: if World's agent fields change, update only this method."""
        out = []
        for a in self.world.agents:
            if abs(a.x) > self.GT_RANGE_M:
                continue
            L, W, H = a.dims
            out.append({"id": a.id, "kind": a.kind, "cls": a.cls, "x": round(a.x, 3), "y": round(a.y, 3),
                        "vx": round(a.vx, 3), "vy": round(a.vy, 3), "heading": round(a.heading, 3),
                        "dims": [L, W, H], "visible": round(self.in_view(a), 2), "state": a.state})
        return out

    def detections(self, t=None) -> list[Detection]:
        cam = self.camera
        C = cam.center
        W, H = self.width, self.height
        items = []
        for a in self.world.agents:
            pts = box_corners(a)
            uv, z = cam.project(pts)
            if (z <= 0.3).any():
                continue
            x1, y1 = uv.min(axis=0)
            x2, y2 = uv.max(axis=0)
            full = max(1.0, (x2 - x1) * (y2 - y1))
            cx1, cy1, cx2, cy2 = max(0, x1), max(0, y1), min(W - 1, x2), min(H - 1, y2)
            if cx2 - cx1 < 3 or cy2 - cy1 < 3:
                continue
            vis = (cx2 - cx1) * (cy2 - cy1) / full
            if vis < 0.35:
                continue
            dist = math.hypot(a.x - C[0], a.y - C[1])
            items.append((dist, a, (cx1, cy1, cx2, cy2), vis, (x1, y1, x2, y2)))
        items.sort(key=lambda it: it[0])
        dets = []
        placed = []
        n = self.noise
        for dist, a, (x1, y1, x2, y2), vis, _ in items:
            area = (x2 - x1) * (y2 - y1)
            occ = 0.0
            for (px1, py1, px2, py2) in placed:
                ix = max(0, min(x2, px2) - max(x1, px1))
                iy = max(0, min(y2, py2) - max(y1, py1))
                occ += ix * iy / max(area, 1)
            occ = min(1.0, occ)
            placed.append((x1, y1, x2, y2))
            hpx = y2 - y1
            condition = self.conditions.get("time_of_day", "day") + ":" + self.conditions.get("weather", "clear")
            bins = n.get("bins", {})
            size_bin = "small" if hpx < 30 else "medium" if hpx < 80 else "large"
            fine_class = "person" if a.kind == "pedestrian" else DET_CLASS[a.cls]
            key = f"{fine_class}:{size_bin}:{condition}"
            fitted = bins.get(key, {})
            if n.get("fitted") and not fitted:
                self.unfitted_bins.add(key)
                if not self.cfg.get("sim", {}).get("allow_unfitted_bins", False):
                    raise ValueError(f"no fitted observations for {key}; supply matching site labels")
            base_miss = fitted.get("miss", n["miss"])
            p_miss = base_miss if fitted else base_miss + 0.55 * max(0.0, occ - 0.2) + (0.35 if hpx < 18 else 0.0) + (1 - vis) * 0.3
            if self.rng.random() < p_miss or occ > (0.95 if fitted else 0.75):
                continue
            jw, jh = n["jitter"] * (x2 - x1), n["jitter"] * hpx
            g = self.rng.gauss
            bx1, bx2 = x1 + g(0, jw), x2 + g(0, jw)
            by1, by2 = y1 + g(0, jh), y2 + g(0, jh * 0.6)
            score = max(0.08, min(0.97, 0.86 - 0.35 * occ - (0.2 if hpx < 30 else 0.0) + g(0, 0.06)))
            if fitted.get("edge_errors_rel"):
                error = self.rng.choice(fitted["edge_errors_rel"])
                bx1, by1, bx2, by2 = np.array([x1, y1, x2, y2]) + np.array(error) * [x2 - x1, hpx, x2 - x1, hpx]
            if fitted.get("scores"):
                score = self.rng.choice(fitted["scores"])
            if bx2 <= bx1 or by2 <= by1:
                continue
            cls = DET_CLASS[a.cls]
            if a.cls in ("bicycle", "motorcycle"):
                # detectors return the bike AND the rider - exercises rider fusion
                hb = by2 - by1
                dets.append(Detection(bx1, by1 + 0.4 * hb, bx2, by2, score, cls, extra={"gt": a.id}))
                if self.rng.random() > 0.15:
                    pw = (bx2 - bx1) * 0.55
                    pcx = (bx1 + bx2) / 2 + g(0, pw * 0.1)
                    dets.append(Detection(pcx - pw / 2, by1, pcx + pw / 2, by1 + 0.82 * hb, score * 0.95, "person",
                                          extra={"gt": a.id}))
                continue
            if self.rng.random() < n["class_flip"]:
                cls = {"person": "bicycle", "car": "truck", "truck": "car", "bus": "truck"}.get(cls, cls)
                score *= 0.7
            dets.append(Detection(bx1, by1, bx2, by2, score, cls, extra={"gt": a.id}))
        # false positives
        condition = self.conditions.get("time_of_day", "day") + ":" + self.conditions.get("weather", "clear")
        fp = n.get("false_positives", {}).get(condition, {})
        now = self.world.t if t is None else t
        elapsed = max(0, now - self._last_detection_t)
        self._last_detection_t = now
        if fp.get("samples"):
            for _ in range(self.np_rng.poisson(fp["per_minute"] * elapsed / 60)):
                sample = self.rng.choice(fp["samples"])
                bounds = np.array(sample["box_rel"]) * [W, H, W, H]
                dets.append(Detection(*bounds, sample["score"], sample["cls"], extra={"fp": True}))
        if not n.get("fitted") and self.rng.random() < n["fp_rate"]:
            u = self.rng.uniform(0.1, 0.9) * W
            v = self.rng.uniform(0.45, 0.95) * H
            s = self.rng.uniform(15, 50)
            dets.append(Detection(u, v - 2.2 * s, u + s, v, self.rng.uniform(0.18, 0.42), "person", extra={"fp": True}))
        return dets

    # ------------------------------------------------------------------ source API
    def read(self, last_seq=-1, timeout=1.0):
        if self.realtime:
            if self.t_wall0 is None:
                self.t_wall0 = time.monotonic()
            t_target = (self.seq + 1) * self.dt / self.speed
            wait = t_target - (time.monotonic() - self.t_wall0)
            if wait > 0:
                time.sleep(wait)
        self._apply_pending()
        self.world.step(self.dt)
        self.seq += 1
        frame = self.render() if self.render_enabled else self._bg
        return frame, self.world.t, self.seq

    def inject(self, name):
        """Queue a demo situation; applied by the simulation thread before its next step (no race with step)."""
        self._pending.append(name)
        return True

    def _apply_pending(self):
        while self._pending:
            apply_stage(self.world, self.rng, self._pending.pop(0))

    def stats(self):
        el = max(1e-6, time.monotonic() - self.t0)
        return {"camera_fps": round(self.seq / el, 1), "width": self.width, "height": self.height,
                "sim_t": round(self.world.t, 1), "sim_agents": len(self.world.agents), "scenario": self.scenario_name,
                "fidelity": "L1", "noise_fitted": bool(self.noise.get("fitted")), "unfitted_bins": sorted(self.unfitted_bins),
                "noise_model_hash": self.noise.get("model_hash")}

    def close(self):
        pass
