"""Event bus: ids, JSONL persistence, live fan-out, and 3D replay clips built from track history.

No video is ever stored: a "replay" of a near-miss is the trajectories of everybody involved, which the
dashboard re-animates in 3D (a few KB instead of a privacy-sensitive video clip).
"""
from __future__ import annotations

import itertools
import json
import os
import threading
import time
from collections import OrderedDict, deque


class EventBus:
    def __init__(self, log_cfg, node_id="cw-01", run_dir=None):
        self.cfg = log_cfg
        self.node = node_id
        self.ids = itertools.count(1)
        self.events = deque(maxlen=1000)
        self.subscribers = []
        self.lock = threading.Lock()
        self.before = float(log_cfg.get("replay_before_s", 6.0))
        self.after = float(log_cfg.get("replay_after_s", 3.0))
        self.history = deque()
        self.pending = []
        self.replays = OrderedDict()
        self.run_dir = run_dir
        self._f_events = None
        self._f_tracks = None
        self._t_track_write = -1e9
        if run_dir:
            os.makedirs(run_dir, exist_ok=True)
            os.makedirs(os.path.join(run_dir, "replays"), exist_ok=True)
            self._f_events = open(os.path.join(run_dir, "events.jsonl"), "a", encoding="utf-8")
            if log_cfg.get("save_tracks", True):
                self._f_tracks = open(os.path.join(run_dir, "tracks.jsonl"), "a", encoding="utf-8")

    def subscribe(self, fn):
        with self.lock:
            self.subscribers.append(fn)

    def unsubscribe(self, fn):
        with self.lock:
            if fn in self.subscribers:
                self.subscribers.remove(fn)

    def emit(self, ev: dict):
        ev = dict(ev)
        ev["id"] = next(self.ids)
        ev["node"] = self.node
        ev["wall"] = time.strftime("%H:%M:%S")
        for k in ("t",):
            if k in ev and ev[k] is not None:
                ev[k] = round(float(ev[k]), 3)
        with self.lock:
            self.events.append(ev)
            subs = list(self.subscribers)
        if self._f_events:
            self._f_events.write(json.dumps(ev) + "\n")
            self._f_events.flush()
        if ev.get("replay"):
            self.pending.append(ev)
        for fn in subs:
            try:
                fn({"type": "event", "event": ev})
            except Exception:  # noqa: BLE001
                pass
        return ev

    def record(self, t, tracks_compact, signal=None):
        """Store a track snapshot for replays (and optionally disk)."""
        self.history.append((t, tracks_compact, signal))
        horizon = self.before + self.after + 3.0
        while self.history and t - self.history[0][0] > horizon:
            self.history.popleft()
        if self._f_tracks and t - self._t_track_write >= 0.2:
            self._t_track_write = t
            self._f_tracks.write(json.dumps({"t": round(t, 3), "tracks": tracks_compact}) + "\n")
        self._finalize(t)

    def _finalize(self, t):
        keep = []
        for ev in self.pending:
            if t >= ev["t"] + self.after:
                frames = [{"t": round(ts, 3), "tracks": tr, "signal": sg} for ts, tr, sg in self.history
                          if ev["t"] - self.before <= ts <= ev["t"] + self.after]
                clip = {"event": ev, "frames": frames}
                self.replays[ev["id"]] = clip
                while len(self.replays) > 60:
                    self.replays.popitem(last=False)
                if self.run_dir:
                    with open(os.path.join(self.run_dir, "replays", f"{ev['id']}.json"), "w") as f:
                        json.dump(clip, f)
                with self.lock:
                    subs = list(self.subscribers)
                for fn in subs:
                    try:
                        fn({"type": "replay_ready", "id": ev["id"], "event_type": ev.get("type")})
                    except Exception:  # noqa: BLE001
                        pass
            else:
                keep.append(ev)
        self.pending = keep

    def recent(self, n=100, since_id=0):
        with self.lock:
            return [e for e in list(self.events)[-n:] if e["id"] > since_id]

    def close(self):
        for f in (self._f_events, self._f_tracks):
            if f:
                f.close()
