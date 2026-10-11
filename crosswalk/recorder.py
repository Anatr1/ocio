"""Raw-footage recorder driven from the dashboard ("Rec" button).

The pipeline already owns the camera, so recording happens inside it: no need to stop the service. Frames are
the raw camera frames (no overlay, no privacy blur) because they are ground-truth / training material; files
stay on the device under record.dir and are fetched by the team (dashboard -> Recordings). Encoding runs in its
own thread with a small queue, so a slow disk can never stall the vision loop (frames are dropped instead).
"""
from __future__ import annotations

import os
import queue
import re
import threading
import time

import cv2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Recorder:
    def __init__(self, cfg=None):
        cfg = cfg or {}
        self.dir = os.path.join(ROOT, cfg.get("dir", "data/recordings"))
        self.fps = float(cfg.get("fps", 15.0))
        self.segment_s = float(cfg.get("segment_s", 300.0))
        self.max_s = float(cfg.get("max_s", 3600.0))
        self._q: queue.Queue = queue.Queue(maxsize=30)
        self._lock = threading.Lock()
        self._active = False
        self._name = None
        self._t_start = self._t_next = 0.0
        self.frames = self.dropped = 0
        self.file = None
        self.files: list[str] = []
        threading.Thread(target=self._writer, daemon=True, name="recorder").start()

    # ------------------------------------------------------------------ control
    def start(self, name="rec"):
        name = re.sub(r"[^A-Za-z0-9_-]", "", name or "rec")[:40] or "rec"
        with self._lock:
            if self._active:
                return False
            os.makedirs(self.dir, exist_ok=True)
            self._name = f"{name}_{time.strftime('%Y%m%d-%H%M%S')}"
            self._t_start = time.monotonic()
            self._t_next = 0.0
            self.frames = self.dropped = 0
            self.files = []
            self._active = True
        return True

    def stop(self):
        with self._lock:
            was = self._active
            self._active = False
        if was:
            self._q.put(None)  # close the current file
        return was

    def push(self, frame, t):
        """Called by the pipeline for every new camera frame; keeps record.fps frames per second."""
        if not self._active:
            return
        elapsed = time.monotonic() - self._t_start
        if elapsed > self.max_s:
            self.stop()
            return
        if elapsed < self._t_next:
            return
        self._t_next = max(self._t_next + 1.0 / self.fps, elapsed - 1.0 / self.fps)
        try:
            self._q.put_nowait((int(elapsed // self.segment_s), elapsed, frame.copy()))
        except queue.Full:
            self.dropped += 1

    def status(self):
        return {"recording": self._active, "name": self._name,
                "seconds": round(time.monotonic() - self._t_start, 1) if self._active else None,
                "frames": self.frames, "dropped": self.dropped, "file": self.file, "files": list(self.files)}

    # ------------------------------------------------------------------ files
    def list(self):
        if not os.path.isdir(self.dir):
            return []
        out = []
        for f in sorted(os.listdir(self.dir)):
            full = os.path.join(self.dir, f)
            if f.endswith(".mp4") and os.path.isfile(full):
                out.append({"name": f, "mb": round(os.path.getsize(full) / 1e6, 1)})
        return out

    def path(self, name):
        """Safe path of a recording for download (None if not a recording in record.dir)."""
        if not re.fullmatch(r"[A-Za-z0-9_.-]+\.mp4", name or ""):
            return None
        full = os.path.join(self.dir, name)
        return full if os.path.isfile(full) else None

    # ------------------------------------------------------------------ writer thread
    def _writer(self):
        writer, segment = None, None
        written, previous = 0, None
        while True:
            item = self._q.get()
            if item is None:
                if writer is not None:
                    writer.release()
                writer, segment, self.file = None, None, None
                continue
            seg, elapsed, frame = item
            if writer is None or seg != segment:
                if writer is not None:
                    writer.release()
                segment = seg
                written, previous = 0, None
                fname = f"{self._name}_part{seg + 1}.mp4"
                h, w = frame.shape[:2]
                writer = cv2.VideoWriter(os.path.join(self.dir, fname), cv2.VideoWriter_fourcc(*"mp4v"), self.fps, (w, h))
                self.file = fname
                self.files.append(fname)
            # The vision loop may deliver fewer frames than the declared file FPS.
            # Repeat the preceding raw frame over gaps to preserve wall-clock time.
            target = max(0, int((elapsed - seg * self.segment_s) * self.fps))
            if target < written:
                previous = frame
                continue
            while written < target:
                writer.write(previous if previous is not None else frame)
                written += 1
                self.frames += 1
            writer.write(frame)
            written += 1
            previous = frame
            self.frames += 1
