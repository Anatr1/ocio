"""Frame sources: live camera (threaded, always-latest frame) and video files (real-time paced or offline)."""
from __future__ import annotations

import os
from email.parser import BytesParser
from email import policy
import math
import platform
import threading
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import cv2
import numpy as np


def _postprocess(frame, stereo, resize_width):
    """Side-by-side stereo cameras used as webcams (e.g. ZED Mini over UVC): keep one eye; optional downscale."""
    if stereo in ("left", "right"):
        w = frame.shape[1] // 2
        frame = frame[:, :w] if stereo == "left" else frame[:, w:]
    if resize_width and frame.shape[1] > resize_width:
        h = int(round(frame.shape[0] * resize_width / frame.shape[1]))
        frame = cv2.resize(frame, (int(resize_width), h), interpolation=cv2.INTER_AREA)
    return frame


def _rotate(frame, rot):
    if rot == 90:
        return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    if rot == 180:
        return cv2.rotate(frame, cv2.ROTATE_180)
    if rot == 270:
        return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return frame


class CameraSource:
    """USB camera via V4L2 (Linux) / MSMF-DSHOW (Windows). A grabber thread keeps only the newest frame so
    the vision loop never processes stale images."""

    live = True

    def __init__(self, cfg):
        self.cfg = cfg
        self.cap = self._open()
        if not self.cap.isOpened():
            raise RuntimeError(f"cannot open camera {cfg.get('device', 0)}")
        # a camera that stops delivering frames (USB hiccup, driver timeout) is closed and reopened
        self.reopen_s = float(cfg.get("reopen_s", 2.0))
        self.reopens = 0
        self.rot = int(cfg.get("rotate", 0))
        self.stereo = cfg.get("stereo")              # None | "left" | "right" (side-by-side stereo webcams)
        self.resize_width = cfg.get("resize_width")  # e.g. 640: downscale after cropping
        self.raw_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.raw_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.width, self.height = self.raw_width, self.raw_height
        if self.stereo in ("left", "right"):
            self.width //= 2
        if self.resize_width and self.width > int(self.resize_width):
            self.height = int(round(self.height * int(self.resize_width) / self.width))
            self.width = int(self.resize_width)
        if self.rot in (90, 270):
            self.width, self.height = self.height, self.width
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30
        self.lock = threading.Lock()
        self.frame = None
        self.t = 0.0
        self.seq = 0
        self.grabbed = 0
        self.t0 = time.monotonic()
        self.running = True
        self.th = threading.Thread(target=self._loop, daemon=True, name="camera")
        self.th.start()

    def _open(self):
        cfg = self.cfg
        dev = cfg.get("device", 0)
        if isinstance(dev, str) and dev.isdigit():
            dev = int(dev)
        api = cv2.CAP_ANY
        if platform.system() == "Linux":
            api = cv2.CAP_V4L2
        elif platform.system() == "Windows":
            api = cv2.CAP_DSHOW
        cap = cv2.VideoCapture(dev, api)
        fourcc = cfg.get("fourcc")
        if fourcc:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(cfg.get("width", 640)))
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(cfg.get("height", 480)))
        cap.set(cv2.CAP_PROP_FPS, int(cfg.get("fps", 30)))
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:  # noqa: BLE001
            pass
        return cap

    def _reopen(self):
        try:
            self.cap.release()
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.3)
        try:
            self.cap = self._open()
        except Exception:  # noqa: BLE001
            pass
        self.reopens += 1

    def _loop(self):
        last_ok = time.monotonic()
        while self.running:
            ok, f = self.cap.read()
            if not ok or f is None:
                if time.monotonic() - last_ok > self.reopen_s:
                    self._reopen()
                    last_ok = time.monotonic()  # one attempt per reopen_s, not a tight retry loop
                time.sleep(0.01)
                continue
            last_ok = time.monotonic()
            f = _rotate(_postprocess(f, self.stereo, self.resize_width), self.rot)
            with self.lock:
                self.frame = f
                self.t = time.monotonic() - self.t0
                self.seq += 1
                self.grabbed += 1

    def read(self, last_seq=-1, timeout=1.0):
        """Return (frame, t, seq) of the newest frame newer than last_seq (blocks up to timeout)."""
        t_end = time.monotonic() + timeout
        while time.monotonic() < t_end:
            with self.lock:
                if self.frame is not None and self.seq != last_seq:
                    return self.frame, self.t, self.seq
            time.sleep(0.002)
        return None, None, last_seq

    def stats(self):
        el = max(1e-6, time.monotonic() - self.t0)
        with self.lock:
            age = None if self.frame is None else round(el - self.t, 2)
        return {"camera_fps": round(self.grabbed / el, 1), "width": self.width, "height": self.height,
                "raw": f"{self.raw_width}x{self.raw_height}", "frame_age_s": age, "camera_reopens": self.reopens}

    def close(self):
        self.running = False
        self.th.join(timeout=1.0)
        self.cap.release()


class VideoSource:
    """Video file. ``realtime=True`` emulates a live camera (frames are skipped if processing is slow), so
    performance numbers on the board are honest. ``realtime=False`` processes every frame (evaluation)."""

    live = False

    def __init__(self, cfg):
        path = cfg["path"]
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        self.path = path
        self.cap = cv2.VideoCapture(path)
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 25.0
        self.n = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        self.realtime = bool(cfg.get("realtime", True))
        self.loop = bool(cfg.get("loop", True))
        self.speed = float(cfg.get("speed", 1.0))
        self.rot = int(cfg.get("rotate", 0))
        self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if self.rot in (90, 270):
            self.width, self.height = self.height, self.width
        self.idx = -1
        self.t_offset = 0.0     # accumulates across loops so time is monotonic
        self.t_wall0 = None
        self.loops = 0
        self.decoded = 0
        self.t0 = time.monotonic()

    def _seek_read(self, target):
        # sequential decode is cheaper than seeking for small skips
        while self.idx < target:
            ok = self.cap.grab()
            if not ok:
                return None
            self.idx += 1
            self.decoded += 1
        ok, f = self.cap.retrieve()
        return f if ok else None

    def read(self, last_seq=-1, timeout=1.0):
        if self.t_wall0 is None:
            self.t_wall0 = time.monotonic()
        if self.realtime:
            el = (time.monotonic() - self.t_wall0) * self.speed
            target = int(el * self.fps) - int(self.t_offset * self.fps)
            target = max(target, self.idx + 1)
            # wait for the next frame time (don't run faster than real time)
            t_target = (target + int(self.t_offset * self.fps)) / self.fps / self.speed
            wait = t_target - (time.monotonic() - self.t_wall0)
            if wait > 0:
                time.sleep(min(wait, timeout))
        else:
            target = self.idx + 1
        if self.n and target >= self.n:
            if not self.loop:
                return None, None, last_seq
            self.loops += 1
            self.t_offset += self.n / self.fps
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            self.idx = -1
            target = 0
        f = self._seek_read(target)
        if f is None:
            if self.loop and self.idx > 0:
                self.loops += 1
                self.t_offset += (self.idx + 1) / self.fps
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                self.idx = -1
                f = self._seek_read(0)
            if f is None:
                return None, None, last_seq
        t = self.t_offset + self.idx / self.fps
        seq = self.loops * 10_000_000 + self.idx
        return _rotate(f, self.rot), t, seq

    def stats(self):
        el = max(1e-6, time.monotonic() - self.t0)
        return {"camera_fps": round(self.decoded / el, 1), "width": self.width, "height": self.height,
                "video_pos": self.idx, "video_frames": self.n}

    def close(self):
        self.cap.release()


def read_mjpeg_part(stream, boundary, max_bytes=4_000_000):
    """Bounded multipart parser for Content-Length MJPEG camera streams."""
    marker = b"--" + boundary
    for _ in range(128):
        line = stream.readline(4097)
        if not line or line.strip() == marker + b"--":
            return None
        if len(line) > 4096:
            raise ValueError("MJPEG boundary line is too long")
        if line.strip() == marker:
            break
    else:
        raise ValueError("MJPEG boundary not found")
    raw = bytearray()
    while True:
        line = stream.readline(4097)
        if not line or len(line) > 4096 or len(raw) + len(line) > 16384:
            raise ValueError("invalid or oversized MJPEG headers")
        if line in (b"\r\n", b"\n"):
            break
        raw.extend(line)
    headers = BytesParser(policy=policy.default).parsebytes(bytes(raw))
    if headers.get_content_type() != "image/jpeg":
        raise ValueError("MJPEG part is not image/jpeg")
    length = int(headers.get("Content-Length", "0"))
    if not 0 < length <= max_bytes:
        raise ValueError("MJPEG part requires a bounded Content-Length")
    data = bytearray()
    while len(data) < length:
        chunk = stream.read(length - len(data))
        if not chunk:
            raise ValueError("truncated MJPEG frame")
        data.extend(chunk)
    return headers, bytes(data)


class NetworkSource:
    """Always-latest HTTP MJPEG. Sender timestamps are seconds, not arrival time.

    Timestamp policy 'sender' requires X-Timestamp/X-Sequence on every part.
    Ordinary IP cameras can explicitly choose 'local' (not suitable for HIL latency).
    """
    live = True

    def __init__(self, cfg):
        self.url = str(cfg["url"])
        if urlsplit(self.url).scheme not in ("http", "https"):
            raise ValueError("network camera URL must use http or https")
        self.timestamp_policy = cfg.get("timestamp_policy", "sender")
        if self.timestamp_policy not in ("sender", "local"):
            raise ValueError("timestamp_policy must be sender or local")
        self.width, self.height = int(cfg.get("width", 640)), int(cfg.get("height", 480))
        self.timeout = float(cfg.get("timeout_s", 2.0))
        self.max_bytes = int(cfg.get("max_frame_bytes", 4_000_000))
        if min(self.width, self.height, self.max_bytes) <= 0 or not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("invalid network camera dimensions/timeout/frame limit")
        self.condition = threading.Condition()
        self.stop = threading.Event()
        self.frame, self.t, self.seq = None, -1.0, 0
        self.sender_seq = -1
        # A sender that restarts (camera reboot, cache replay reconnect) starts its clock again: its frames are
        # then rebased onto our timeline, continuing after the real gap, instead of being rejected forever.
        self.offset, self.last_arrival = 0.0, None
        self.grabbed = self.dropped = self.rejected = self.reconnects = self.rebases = 0
        self.error = None
        self.response = None
        self.t0 = time.monotonic()
        self.thread = threading.Thread(target=self._loop, daemon=True, name="network-camera")
        self.thread.start()

    def _loop(self):
        while not self.stop.is_set():
            try:
                request = Request(self.url, headers={"Accept": "multipart/x-mixed-replace"})
                with urlopen(request, timeout=self.timeout) as response:
                    self.response = response
                    boundary = response.headers.get_param("boundary")
                    if response.headers.get_content_type() != "multipart/x-mixed-replace" or not boundary:
                        raise ValueError("network camera must return multipart MJPEG with a boundary")
                    boundary = boundary.encode("ascii")
                    if len(boundary) > 200:
                        raise ValueError("MJPEG boundary is too long")
                    first = True  # no part of this connection accepted yet
                    while not self.stop.is_set():
                        part = read_mjpeg_part(response, boundary, self.max_bytes)
                        if part is None:
                            break
                        headers, payload = part
                        if self.timestamp_policy == "sender":
                            raw_t, sender_seq = float(headers["X-Timestamp"]), int(headers["X-Sequence"])
                        else:
                            raw_t, sender_seq = time.monotonic() - self.t0, self.sender_seq + 1
                        if not math.isfinite(raw_t) or raw_t < 0 or sender_seq < 0:
                            self.rejected += 1
                            continue
                        restarted = raw_t + self.offset <= self.t or sender_seq <= self.sender_seq
                        if restarted and not (first and self.t >= 0):
                            self.rejected += 1  # reordered or repeated within one connection
                            continue
                        frame = cv2.imdecode(np.frombuffer(payload, np.uint8), cv2.IMREAD_COLOR)
                        if frame is None or frame.shape[:2] != (self.height, self.width):
                            raise ValueError("network frame dimensions differ from source config")
                        now = time.monotonic()
                        with self.condition:
                            if restarted:  # new connection, sender clock restarted: continue after the real gap
                                self.offset = self.t + max(1e-3, now - self.last_arrival) - raw_t
                                self.sender_seq = -1
                                self.rebases += 1
                            if self.sender_seq >= 0:
                                self.dropped += max(0, sender_seq - self.sender_seq - 1)
                            first = False
                            self.last_arrival = now
                            self.frame, self.t, self.sender_seq = frame, raw_t + self.offset, sender_seq
                            self.seq += 1
                            self.grabbed += 1
                            self.error = None
                            self.condition.notify_all()
            except Exception as error:  # reconnect after camera/network failure
                self.error = f"{type(error).__name__}: {error}"
            finally:
                self.response = None
            self.reconnects += 1
            self.stop.wait(0.25)

    def read(self, last_seq=-1, timeout=1.0):
        with self.condition:
            self.condition.wait_for(lambda: self.stop.is_set() or self.frame is not None and self.seq > last_seq, timeout)
            if self.frame is not None and self.seq > last_seq and not self.stop.is_set():
                return self.frame, self.t, self.seq
        return None, None, last_seq

    def stats(self):
        return {"camera_fps": self.grabbed / max(1e-6, time.monotonic() - self.t0), "width": self.width, "height": self.height,
                "timestamp_policy": self.timestamp_policy, "network_dropped": self.dropped,
                "network_rejected": self.rejected, "network_reconnects": self.reconnects,
                "network_rebases": self.rebases, "network_error": self.error}

    def close(self):
        self.stop.set()
        with self.condition:
            self.condition.notify_all()
        if self.response is not None:
            self.response.close()
        self.thread.join(timeout=self.timeout + 1)


def create_source(cfg):
    typ = cfg.get("type", "camera")
    if typ == "camera":
        return CameraSource(cfg)
    if typ == "video":
        return VideoSource(cfg)
    if typ == "network":
        return NetworkSource(cfg)
    raise ValueError(f"unknown source type {typ}")
