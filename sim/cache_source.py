"""Replay validated camera pixels, never detections or World state into the node."""
from __future__ import annotations

import json
import math
from pathlib import Path
import time

import cv2

from .repro import file_hash


class CacheSource:
    live = False

    def __init__(self, path, realtime=False, require_scenario_complete=False):
        self.path = Path(path).resolve()
        self.metadata = json.loads((self.path / "manifest.json").read_text(encoding="utf-8"))
        if self.metadata.get("presentation_mode") or self.metadata.get("scenario", {}).get("presentation_mode"):
            raise ValueError("evaluation refuses presentation_mode")
        if not self.metadata.get("complete") or not self.metadata.get("frame_count"):
            raise ValueError("cache is incomplete or empty")
        if require_scenario_complete and not self.metadata.get("scenario_complete"):
            raise ValueError("cache is only a scenario prefix; use --allow-partial to score it without certification")
        self.spec = self.metadata["scenario"]
        self.width, self.height = self.metadata["calibration"]["image_size"]
        self.fps = float(self.metadata["fps"])
        if not math.isfinite(self.fps) or self.fps <= 0 or min(self.width, self.height) <= 0:
            raise ValueError("invalid cache dimensions or fps")
        self.entries = []
        previous = -math.inf
        self.verified_payload_hashes = True
        for seq in range(1, int(self.metadata["frame_count"]) + 1):
            image = self.path / f"{seq:06d}.jpg"
            meta = json.loads(image.with_suffix(".json").read_text(encoding="utf-8"))
            t = float(meta["t"])
            if meta["seq"] != seq or not math.isfinite(t) or t <= previous:
                raise ValueError("cache sequence/timestamps must be strictly increasing")
            if seq > 1 and not math.isclose(t - previous, 1 / self.fps, abs_tol=1e-6):
                raise ValueError("cache frame interval differs from its manifest")
            if not image.is_file():
                raise FileNotFoundError(image)
            hashes = meta.get("sha256", {})
            if hashes.get("jpg") and file_hash(image) != hashes["jpg"]:
                raise ValueError(f"cache pixels changed: {image.name}")
            self.verified_payload_hashes &= bool(hashes.get("jpg"))
            self.entries.append((image, meta))
            previous = t
        self.realtime = realtime
        self.idx = 0
        self.frame_meta = None
        self.closed = False
        self.t0 = time.monotonic()
        self.wall0 = None
        # The digest also covers legacy caches that predate per-frame hashes.
        self.content_hash = file_hash(self.path)

    def calibration(self):
        return dict(self.metadata["calibration"])

    def read(self, last_seq=-1, timeout=1.0):
        if self.closed or self.idx >= len(self.entries):
            return None, None, last_seq
        path, meta = self.entries[self.idx]
        if self.wall0 is None:
            self.wall0 = time.monotonic()
        if self.realtime:
            delay = (meta["t"] - self.entries[0][1]["t"]) - (time.monotonic() - self.wall0)
            if delay > 0:
                time.sleep(delay)
        frame = cv2.imread(str(path))
        if frame is None or frame.shape[:2] != (self.height, self.width):
            raise ValueError(f"invalid cached image: {path.name}")
        self.idx += 1
        self.frame_meta = meta
        return frame, meta["t"], meta["seq"]

    def stats(self):
        return {"camera_fps": self.idx / max(1e-6, time.monotonic() - self.t0),
                "width": self.width, "height": self.height, "fidelity": "L2-replay",
                "cached_frames": len(self.entries), "verified_payload_hashes": self.verified_payload_hashes}

    def close(self):
        self.closed = True
