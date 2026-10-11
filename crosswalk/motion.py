"""Motion gate + adaptive detector scheduling.

The neural detector is the only expensive stage. With a fixed camera most frames of a crosswalk are
empty, so we run a ~1 ms background-difference check on a 160 px thumbnail and only call the detector
when something moves, when tracks are alive, or as a slow heartbeat. Compute follows traffic.
"""
from __future__ import annotations

import cv2
import numpy as np


class MotionGate:
    def __init__(self, cfg, roi=None, width=160):
        self.threshold = float(cfg.get("motion_threshold", 0.004))
        self.roi = roi
        self.width = width
        self.bg = None
        self.motion = 0.0
        self.mask = None

    def check(self, frame) -> float:
        img = frame
        if self.roi:
            x, y, w, h = [int(v) for v in self.roi]
            img = frame[y : y + h, x : x + w]
        h, w = img.shape[:2]
        sw = self.width
        sh = max(1, int(h * sw / w))
        small = cv2.resize(img, (sw, sh), interpolation=cv2.INTER_AREA)
        g = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32)
        g = cv2.GaussianBlur(g, (5, 5), 0)
        if self.bg is None or self.bg.shape != g.shape:
            self.bg = g.copy()
            self.motion = 1.0
            return self.motion
        diff = cv2.absdiff(g, self.bg)
        self.mask = diff > 18.0
        self.motion = float(self.mask.mean())
        cv2.accumulateWeighted(g, self.bg, 0.05)
        return self.motion

    @property
    def moving(self) -> bool:
        return self.motion >= self.threshold


class Scheduler:
    """Decides when to run the detector."""

    def __init__(self, cfg):
        self.max_hz = float(cfg.get("max_hz", 15.0))
        self.idle_hz = float(cfg.get("idle_hz", 1.0))
        self.use_gate = bool(cfg.get("motion_gate", True))
        self.t_last = -1e9
        self.reason = "init"
        self.runs = 0
        self.skips = 0

    def should_run(self, t, moving, n_tracks, n_fast) -> bool:
        dt = t - self.t_last
        if dt < 1.0 / self.max_hz:
            self.skips += 1
            return False
        if not self.use_gate:
            self.reason = "always"
        elif moving or n_fast > 0:
            self.reason = "motion"
        elif n_tracks > 0:
            # slow / stationary objects: a few Hz is enough to keep them
            if dt < 1.0 / 4.0:
                self.skips += 1
                return False
            self.reason = "tracks"
        elif dt >= 1.0 / self.idle_hz:
            self.reason = "heartbeat"
        else:
            self.skips += 1
            return False
        self.t_last = t
        self.runs += 1
        return True

    def duty(self):
        tot = self.runs + self.skips
        return 0.0 if tot == 0 else self.runs / tot
