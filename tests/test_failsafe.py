"""Fail-safe contracts: a frozen camera must stop the MCU heartbeat (lamps -> flashing amber), and a
stalled camera is reopened. Board evidence: docs/board_results/RESULTS.md section 8 (frozen ZED, heartbeat kept going)."""
from pathlib import Path
import sys
import threading
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crosswalk import sources
from crosswalk.config import load_config
from crosswalk.mcu import MCU


class FakeRouter:
    alive = True

    def __init__(self):
        self.calls = []

    def call(self, method, *args):
        self.calls.append((time.monotonic(), method))

    def close(self):
        pass


def heartbeats(router, since):
    return [t for t, m in router.calls if m == "heartbeat" and t >= since]


def test_heartbeat_only_while_vision_frames_are_fresh():
    cfg = load_config().mcu
    cfg.enabled = False
    cfg.heartbeat_s = 0.05
    cfg.vision_timeout_s = 0.3
    mcu = MCU(cfg)
    mcu.client = FakeRouter()
    worker = threading.Thread(target=mcu._worker, daemon=True)
    worker.start()
    try:
        time.sleep(0.3)  # no frame yet (boot): no heartbeat, the MCU stays in its boot fail-safe
        assert not heartbeats(mcu.client, 0) and mcu.state["failsafe"]
        t_live = time.monotonic()
        for _ in range(10):  # vision running
            mcu.vision_frame()
            time.sleep(0.05)
        assert len(heartbeats(mcu.client, t_live)) >= 5 and not mcu.state["failsafe"]
        time.sleep(0.4)  # camera frozen longer than vision_timeout_s
        t_frozen = time.monotonic()
        time.sleep(0.3)
        assert not heartbeats(mcu.client, t_frozen) and mcu.state["failsafe"]
        mcu.vision_frame()  # vision back: heartbeat resumes
        time.sleep(0.15)
        assert heartbeats(mcu.client, t_frozen)
    finally:
        mcu._stop = True
        worker.join(1)


class FakeCapture:
    """First device instance delivers 5 frames then stalls forever; reopened instances deliver frames."""
    instances = 0

    def __init__(self, *args):
        FakeCapture.instances += 1
        self.stalls = FakeCapture.instances == 1
        self.n = 0

    def isOpened(self):
        return True

    def set(self, *args):
        return True

    def get(self, prop):
        return {sources.cv2.CAP_PROP_FRAME_WIDTH: 64, sources.cv2.CAP_PROP_FRAME_HEIGHT: 48}.get(prop, 30)

    def read(self):
        time.sleep(0.01)
        self.n += 1
        if self.stalls and self.n > 5:
            return False, None
        return True, np.zeros((48, 64, 3), np.uint8)

    def release(self):
        pass


def test_stalled_camera_is_reopened(monkeypatch):
    FakeCapture.instances = 0
    monkeypatch.setattr(sources.cv2, "VideoCapture", FakeCapture)
    cam = sources.CameraSource({"device": 0, "reopen_s": 0.2})
    try:
        _, _, seq = cam.read(timeout=1)
        time.sleep(0.8)  # stall (5 frames, then nothing) longer than reopen_s
        frame, _, seq2 = cam.read(seq, timeout=1)
        assert frame is not None and seq2 > seq
        assert cam.reopens >= 1 and FakeCapture.instances >= 2
        assert cam.stats()["frame_age_s"] < 0.5
    finally:
        cam.close()
