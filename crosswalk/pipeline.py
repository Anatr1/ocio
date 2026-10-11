"""The edge node: camera -> motion gate -> detector -> rider fusion -> ground projection -> BEV tracker ->
counting / safety / signal -> MCU + live web stream. Everything runs on the board."""
from __future__ import annotations

import os
import hashlib
import sqlite3
import threading
import time

import cv2
import numpy as np

from .approach import ApproachMonitor
from .classes import fuse_riders
from .counting import Counter
from .detectors import create_detector
from .eventlog import EventBus
from .mcu import MCU
from .motion import MotionGate, Scheduler
from .recorder import Recorder
from .public_stats import PublicStats, KINDS
from .render import bev_background, draw_overlay, privacy_blur
from .rules import describe as describe_rules
from .safety import SafetyMonitor
from .scene import Scene
from .server import Server
from .signal import SignalController
from .sources import create_source
from .telemetry import Telemetry
from .tracker import Track, Tracker


class Ema:
    def __init__(self, a=0.1):
        self.a = a
        self.v = None

    def add(self, x):
        self.v = x if self.v is None else (1 - self.a) * self.v + self.a * x
        return self.v


class Node:
    def __init__(self, cfg, source=None, detector=None, run_dir=None):
        self.cfg = cfg
        self.node_id = cfg.node.id
        self.running = False
        self.source = source or create_source(cfg.source)
        w, h = self.source.width, self.source.height
        self.scene = Scene(cfg.scene, (w, h), cfg.tracker)
        if detector is not None:
            self.detector = detector
        else:
            self.detector = create_detector(cfg.detector)
        roi = cfg.detector.get("roi")
        self.gate = MotionGate(cfg.detector, roi)
        self.sched = Scheduler(cfg.detector)
        if run_dir is None and cfg.log.get("dir"):
            run_dir = os.path.join(cfg.log.dir, time.strftime("%Y%m%d-%H%M%S") + "_" + self.node_id)
        self.run_dir = run_dir
        self.bus = EventBus(cfg.log, self.node_id, run_dir)
        conf = float(cfg.detector.get("conf", 0.35))
        Track._next_id = 1
        self.tracker = Tracker(cfg.tracker, self.scene, conf_high=conf)
        self.counter = Counter(self.scene, cfg.counting, self.bus.emit)
        self.signal = SignalController(cfg.signal, self.scene, self.bus.emit)
        self.safety = SafetyMonitor(self.scene, cfg.safety, self.bus.emit, self.signal.mode)
        self.approach = ApproachMonitor(self.scene, cfg.safety)
        public = cfg.get("public", {})
        auto_demo = hasattr(self.source, "world") or cfg.source.type in ("sim", "render", "video")
        self.public_demo = auto_demo if public.get("demo") is None else bool(public["demo"])
        self.public_stats = None
        self.public_stats_error = None
        self._public_epoch = time.time()
        self._public_time = self._public_epoch
        self._public_last_frame = None
        self._public_observed = 0.0
        self._public_previous = None
        if public.get("enabled", True):
            if self.public_demo:
                path = os.path.join(run_dir, "public.sqlite3") if run_dir else ":memory:"
            else:
                name = hashlib.sha256(str(self.node_id).encode()).hexdigest()[:16] + ".sqlite3"
                path = os.path.join(public.get("stats_dir", "data/stats"), name)
            try:
                self.public_stats = PublicStats(path, self.node_id, self._public_epoch)
                if cfg.source.type == "render" and self.public_demo and public.get("mock_month", False):
                    from sim.public_history import populate

                    populate(self.public_stats, self._public_epoch, self.scene.L, self.scene.speed_limit * 3.6)
                self.public_stats.start()
                self.bus.subscribe(self._public_event)
            except (sqlite3.Error, OSError, ValueError) as exc:
                self.public_stats_error = str(exc)
                print("[public] statistics unavailable:", exc)
        self.mcu = MCU(cfg.mcu, on_button=self.request_crossing)
        self.recorder = Recorder(cfg.get("record", {}))  # dashboard 'Rec': raw footage, stays on the device
        self.telemetry = Telemetry()
        self.server = None
        if cfg.server.get("enabled", True):
            self.server = Server(self, cfg.server.get("host", "0.0.0.0"), int(cfg.server.get("port", 8000)))
        # runtime state
        self.t = 0.0
        self.frames = 0
        self.det_runs = 0
        self.last_dets = []
        self.state_version = 0
        self._state = {}
        self._lock = threading.Lock()
        self.mjpeg_clients = 0
        self._jpeg = None
        self._t_jpeg = -1e9
        self._frame = None
        self._bg = None
        self._t_bg = -1e9
        self._bg_png = None
        self._t_bg_png = -1e9
        self._t_state = -1e9
        self._t_wall0 = time.monotonic()
        self.ema = {"loop_fps": Ema(0.05), "det_hz": Ema(0.1), "det_ms": Ema(0.2), "pipeline_ms": Ema(0.2),
                    "decision_ms": Ema(0.2)}
        self._t_prev_loop = None
        self._t_prev_det = None
        self.on_step = None  # optional callback(node, frame, dets) for tools
        # optional, simulator only: callable(tracks) -> ground-truth payload for the dashboard's GT layer.
        # Output goes to a separate SSE channel ('gt'); nothing in the pipeline ever reads it.
        self.gt_provider = None
        self.gt_payload = None

    # ------------------------------------------------------------------ control API (used by the server)
    def request_crossing(self):
        self.signal.request()
        self.bus.emit({"type": "ped_button", "t": self.t, "log_only": True})

    def set_signal_mode(self, mode):
        if mode not in ("adaptive", "fixed", "beacon"):
            return False
        self.signal.mode = mode
        self.safety.signal_mode = mode
        # grace: people already on the crosswalk under the previous mode are not red-light violators
        for tr in self.tracker.tracks:
            tr.meta["red_checked"] = True
        self.bus.emit({"type": "mode", "t": self.t, "mode": mode})
        return True

    def reset_counts(self):
        self.counter.reset()
        self.bus.emit({"type": "reset", "t": self.t})

    # ------------------------------------------------------------------ calibration (from the web page / CLI)
    def calibrate(self, image_points, width=None, length=None, save=True):
        """Re-calibrate live from 4 clicked crosswalk corners; optionally persist to the config file."""
        sc = self.cfg.scene
        if width:
            sc.crosswalk.width = float(width)
        if length:
            sc.crosswalk.length = float(length)
        sc.calibration.image_points = [[float(u), float(v)] for u, v in image_points]
        sc.calibration.image_size = [self.source.width, self.source.height]
        sc.calibration.H = None
        new = Scene(sc, (self.source.width, self.source.height), self.cfg.tracker)
        self.scene = new
        for obj in (self.tracker, self.counter, self.safety, self.signal, self.approach):
            obj.scene = new
        self._bg_png = None
        path = self.cfg.node.get("config_path")
        if save and path:
            try:
                from .config import _load_file, save_config

                data = _load_file(path)
                data.setdefault("scene", {}).setdefault("crosswalk", {})
                data["scene"]["crosswalk"]["width"] = sc.crosswalk.width
                data["scene"]["crosswalk"]["length"] = sc.crosswalk.length
                data["scene"].setdefault("calibration", {})
                data["scene"]["calibration"]["image_points"] = sc.calibration.image_points
                data["scene"]["calibration"]["image_size"] = sc.calibration.image_size
                data["scene"]["calibration"].pop("H", None)
                save_config(data, path)
            except Exception as e:  # noqa: BLE001
                print("[node] could not save calibration:", e)
        info = {k: (float(v) if isinstance(v, (float, np.floating)) else v) for k, v in new.cal_info.items()}
        self.bus.emit({"type": "calibrated", "t": self.t, "info": info})
        return info

    def background_jpeg(self, overlay=False):
        """Person-free background (running average). Privacy-safe frame for calibration."""
        if self._bg is None:
            return None
        img = cv2.convertScaleAbs(self._bg)
        if overlay:
            from .calibration import draw_calibration

            img = draw_calibration(img.copy(), self.scene, self.cfg.scene.calibration.get("image_points"))
        ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        return buf.tobytes() if ok else None

    def auto_calibration(self):
        if self._bg is None:
            return None
        from .calibration import auto_calibrate, estimate_length

        r = auto_calibrate(cv2.convertScaleAbs(self._bg))
        if not r:
            return None
        return {"image_points": r["image_points"], "n_stripes": r["n_stripes"],
                "suggested_length": estimate_length(r["n_stripes"])}

    # ------------------------------------------------------------------ payloads
    def config_payload(self):
        c = self.cfg
        bev = None
        if self.scene.calibrated:
            x0, y0, x1, y1 = self.scene.bounds
            bev = {"x0": x0, "y0": y0, "x1": x1, "y1": y1, "url": "/api/background.png"}
        det = self.detector
        return {
            "node": {"id": self.node_id, "name": c.node.name, "brand": c.node.get("brand", ""),
                     "tagline": c.node.get("tagline", ""), "geo": c.node.get("geo")},
            "scene": self.scene.to_dict(),
            "bev": bev,
            "detector": {"backend": getattr(det, "backend", c.detector.backend) if det else c.detector.backend,
                         "model": "simulated" if det is None else os.path.basename(str(c.detector.get("model", ""))),
                         "imgsz": getattr(det, "imgsz", c.detector.get("imgsz"))},
            "source": {"type": c.source.type, "width": self.source.width, "height": self.source.height},
            "signal": {"mode": self.signal.mode},
            "mcu": {"virtual": self.mcu.virtual},
            "rules": describe_rules(c),
        }

    def state_payload(self):
        with self._lock:
            return self._state

    def _public_event(self, message):
        if message["type"] == "event" and self.public_stats:
            event = message["event"]
            at = self._public_time + min(0.0, float(event.get("t", self.t)) - self.t)
            self.public_stats.submit(event, at)

    def public_payload(self):
        """An explicit citizen-facing projection: no tracks, images or controls."""
        state = self.state_payload()
        healthy = self.mcu.vision_fresh()
        stats_ok = self.public_stats is not None and not self.public_stats.error
        summary = None
        if stats_ok:
            try:
                summary = self.public_stats.snapshot(self._public_time if self.public_demo else None)
            except sqlite3.Error as exc:
                self.public_stats.error = str(exc)
                stats_ok = False
        signal = state.get("signal", {})
        visible = {k: 0 for k in KINDS}
        if healthy:
            for track in state.get("tracks", []):
                if track.get("kind") in visible:
                    visible[track["kind"]] += 1
        return {"schema_version": 1, "generated_at": time.time(),
                "node": {"id": self.node_id, "name": self.cfg.node.name,
                         "geo": self.cfg.node.get("geo"), "brand": "òcio"},
                "data_mode": "demo" if self.public_demo else "live",
                "statistics_available": stats_ok, "statistics": summary,
                "live": {"healthy": healthy, "calibrated": self.scene.calibrated, "last_frame_at": self._public_last_frame,
                         "visible": visible if healthy else None,
                         "signal": {k: signal.get(k) for k in ("mode", "veh", "ped")},
                         "warning_level": state.get("safety", {}).get("warning_level", 0) if healthy else None},
                "direction_names": self.counter.dir_names,
                "speed_limit_kmh": round(self.scene.speed_limit * 3.6),
                "notes": ["Counts are detected passages, not unique people or registered vehicles.",
                          "Safety notices are automated estimates, not confirmed accidents.",
                          "Hours use the node's local timezone. Gaps are unobserved, not zero traffic.",
                          "Fast person tracks (including e-scooters) are counted as bicycles."]}

    def frame_jpeg(self):
        if self.mjpeg_clients <= 0 and self._jpeg is None:
            # one-off request: encode on demand
            self._encode_jpeg(force=True)
        return self._jpeg

    def background_png(self):
        if not self.scene.calibrated or self._bg is None:
            return None
        now = time.monotonic()
        if self._bg_png is None or now - self._t_bg_png > float(self.cfg.server.get("background_every_s", 5.0)):
            bg = cv2.convertScaleAbs(self._bg)
            rgba, _ = bev_background(bg, self.scene, float(self.cfg.server.get("bev_px_per_m", 20.0)))
            ok, buf = cv2.imencode(".png", rgba)
            if ok:
                self._bg_png = buf.tobytes()
                self._t_bg_png = now
        return self._bg_png

    # ------------------------------------------------------------------ internals
    def _encode_jpeg(self, force=False):
        f = self._frame
        if f is None:
            return
        now = time.monotonic()
        if not force and now - self._t_jpeg < 1.0 / float(self.cfg.server.get("mjpeg_fps", 5.0)):
            return
        self._t_jpeg = now
        img = f.copy()
        conf = self.tracker.confirmed()
        if self.cfg.server.get("privacy_blur", True):
            boxes = [((d.x1, d.y1, d.x2, d.y2), d.kind or "pedestrian") for d in self.last_dets]
            boxes += [(tr.bbox, tr.kind) for tr in conf]
            privacy_blur(img, boxes)
        p = self._perf_cache if hasattr(self, "_perf_cache") else {}
        c = self.counter.counts
        hud = [f"{self.cfg.node.get('brand', '')}  ped {c['pedestrian']}  bike {c['bicycle'] + c['micromobility']}  veh {c['vehicle']}",
               f"det {p.get('det_hz', 0):.1f}Hz {p.get('det_ms', 0):.0f}ms  loop {p.get('loop_fps', 0):.0f}fps"]
        draw_overlay(img, self.scene, conf, None, hud, self.signal, self.cfg.detector.get("roi"))
        ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
        if ok:
            self._jpeg = buf.tobytes()

    def _update_background(self, frame, t, busy):
        if self._bg is None:
            self._bg = frame.astype(np.float32)
            return
        if busy or t - self._t_bg < 0.5:
            return
        self._t_bg = t
        cv2.accumulateWeighted(frame.astype(np.float32), self._bg, 0.08)

    def _vehicle_close(self):
        for tr in self.tracker.confirmed():
            if tr.kind != "vehicle" or tr.speed < 1.5:
                continue
            x = tr.pos[0]
            d = abs(x) - self.scene.W / 2
            if 0 < d < 3.0 * tr.speed and x * tr.vel[0] < 0:
                return True
        return False

    def _plausible(self, dets):
        """Drop 'person' boxes whose real height (from the calibration) is impossible for a standing person:
        e.g. hanging leaves that a small detector mistakes for a tiny far-away person (site clip: 0.51-0.60 m,
        real people ~1.8 m). Riders are fused into their bicycle before this, so they are never dropped."""
        min_h = float(self.cfg.tracker.get("min_person_height_m", 0.75))
        if min_h <= 0:
            return dets
        return [d for d in dets if not (d.cls in ("person", "pedestrian") and d.height_m and d.height_m < min_h)]

    def step(self):
        frame, t, seq = self.source.read(getattr(self, "_seq", -1))
        if frame is None:
            return False
        self._seq = seq
        self.mcu.vision_frame()
        self.recorder.push(frame, t)
        t0 = time.perf_counter()
        self.t = t
        wall = time.time()
        self._public_time = self._public_epoch + t if self.public_demo else wall
        self._public_last_frame = wall
        if self.public_stats:
            if self._public_previous is not None:
                dt = self._public_time - self._public_previous
                # Exclude stalls from observation coverage; continue when fresh frames resume.
                if 0 < dt <= float(self.cfg.mcu.get("vision_timeout_s", 1.5)):
                    self._public_observed += dt
                elif self._public_observed:
                    self.public_stats.submit({"type": "observation", "seconds": self._public_observed}, self._public_previous)
                    self._public_observed = 0.0
            self._public_previous = self._public_time
            if self._public_observed >= 1.0:
                self.public_stats.submit({"type": "observation", "seconds": self._public_observed}, self._public_time)
                self._public_observed = 0.0
        self.frames += 1
        self._frame = frame
        if self._t_prev_loop is not None and t > self._t_prev_loop:
            self.ema["loop_fps"].add(1.0 / (t - self._t_prev_loop))
        self._t_prev_loop = t

        moving = True
        if self.sched.use_gate:
            self.gate.check(frame)
            moving = self.gate.moving
        n_tracks = len(self.tracker.tracks)
        n_fast = sum(1 for tr in self.tracker.tracks if tr.speed > 2.5)
        run = self.sched.should_run(t, moving, n_tracks, n_fast)
        dets = []
        if run:
            td = time.perf_counter()
            if self.detector is not None:
                dets = self.detector(frame)
            elif hasattr(self.source, "detections"):
                dets = self.source.detections(t)
            self.ema["det_ms"].add((time.perf_counter() - td) * 1000.0)
            if self._t_prev_det is not None and t > self._t_prev_det:
                self.ema["det_hz"].add(1.0 / (t - self._t_prev_det))
            self._t_prev_det = t
            self.det_runs += 1
            dets = fuse_riders(dets)
            self.scene.localize(dets)
            dets = self._plausible(dets)
            self.last_dets = dets
            tracks = self.tracker.update(t, dets)
            ended = self.tracker.ended_now
            self.counter.update(t, tracks, ended)
            self.safety.exposure = self.counter.counts["vehicle"]
            self.safety.update(t, tracks, ended, self.signal, self.tracker.dead)
            self.approach.update(tracks)
            if self.public_stats and ended:
                self.public_stats.submit({"type": "retire", "tracks": [tr.id for tr in ended]}, self._public_time)
            compact = [_compact(tr) for tr in self.tracker.confirmed()]
            self.bus.record(t, compact, {"veh": self.signal.veh_state(), "ped": self.signal.ped_state()})
        else:
            self.tracker.predict(t)
        self.signal.update(t, waiting=self.safety.__dict__.get("vru_waiting", 0),
                           crossing=self.safety.__dict__.get("vru_crossing", 0),
                           time_to_clear=self.safety.__dict__.get("max_time_to_clear", 0.0),
                           vehicle_close=self._vehicle_close())
        self.mcu.tick(t, self.signal if self.signal.mode != "beacon" else None, self.safety.warning_level,
                      self.counter.counts)
        if run:  # frame in -> rules evaluated -> lamp command issued (MCU round trip reported separately)
            self.ema["decision_ms"].add((time.perf_counter() - t0) * 1000.0)
        busy = bool(self.tracker.tracks) or moving
        self._update_background(frame, t, busy)
        self.ema["pipeline_ms"].add((time.perf_counter() - t0) * 1000.0)
        if self.on_step:
            self.on_step(self, frame, dets)
        self._publish(t)
        if self.mjpeg_clients > 0:
            self._encode_jpeg()
        return True

    def _publish(self, t):
        hz = float(self.cfg.server.get("stream_hz", 10.0))
        now = time.monotonic()
        if now - self._t_state < 1.0 / max(hz, 1.0):
            return
        self._t_state = now
        det = self.detector
        timing = getattr(det, "timing", {}) if det else {}
        perf = {
            "loop_fps": round(self.ema["loop_fps"].v or 0.0, 1),
            "det_hz": round(self.ema["det_hz"].v or 0.0, 1),
            "det_ms": round(self.ema["det_ms"].v or 0.0, 1),
            "infer_ms": round(timing.get("infer_ms", 0.0), 1),
            "pre_ms": round(timing.get("pre_ms", 0.0), 1),
            "post_ms": round(timing.get("post_ms", 0.0), 1),
            "pipeline_ms": round(self.ema["pipeline_ms"].v or 0.0, 1),
            "decision_ms": round(self.ema["decision_ms"].v or 0.0, 1),
            "duty": round(self.sched.duty(), 3),
            "gate_reason": self.sched.reason,
            "motion": round(self.gate.motion, 4),
            "frames": self.frames,
            "det_runs": self.det_runs,
            "on_device": True,
            **self.source.stats(),
            **self.telemetry.snapshot(),
        }
        self._perf_cache = perf
        tracks = []
        per = getattr(self.approach, "per_track", {})
        for tr in self.tracker.confirmed():
            d = tr.to_dict(t, self.scene.zone_of(*tr.pos))
            a = per.get(tr.id)
            if a:
                d["approach"] = a["status"]
                d["eta"] = a["eta"]
            tracks.append(d)
        state = {
            "t": round(t, 3),
            "node": self.node_id,
            "tracks": tracks,
            "counts": self.counter.stats(),
            "safety": self.safety.stats(),
            "signal": self.signal.to_dict(),
            "approach": getattr(self.approach, "summary", None),
            "mcu": self.mcu.state,
            "record": self.recorder.status(),
            "perf": perf,
            "last_event_id": self.bus.events[-1]["id"] if self.bus.events else 0,
        }
        if self.gt_provider is not None:
            try:
                self.gt_payload = self.gt_provider(tracks)
            except Exception as e:  # noqa: BLE001
                self.gt_payload = {"error": str(e)}
        with self._lock:
            self._state = state
            self.state_version += 1

    def run(self, max_seconds=None, max_frames=None, show=False):
        self.running = True
        if self.server:
            self.server.start()
            port = self.cfg.server.get("port", 8000)
            print(f"[node] dashboard on http://localhost:{port}  (LAN: http://<board-ip>:{port})")
        wall0 = time.monotonic()
        try:
            while self.running:
                if not self.step():
                    if max_seconds and time.monotonic() - wall0 > max_seconds:
                        break
                    if getattr(self.source, "live", False):
                        continue  # camera stalled: the MCU heartbeat stops after mcu.vision_timeout_s
                    break
                if show:
                    self._encode_jpeg(force=True)
                    if self._jpeg is not None:
                        img = cv2.imdecode(np.frombuffer(self._jpeg, np.uint8), cv2.IMREAD_COLOR)
                        cv2.imshow("crosswalk", img)
                        if cv2.waitKey(1) & 0xFF in (27, ord("q")):
                            break
                if max_frames and self.frames >= max_frames:
                    break
                if max_seconds and time.monotonic() - wall0 > max_seconds:
                    break
        except KeyboardInterrupt:
            pass
        finally:
            self.running = False
            self.close()

    def close(self):
        try:
            self.source.close()
        except Exception:  # noqa: BLE001
            pass
        self.recorder.stop()
        self.mcu.close()
        self.bus.close()
        if self.server:
            self.server.stop()
        if self.public_stats:
            if self._public_observed:
                self.public_stats.submit({"type": "observation", "seconds": self._public_observed}, self._public_time)
            self.public_stats.close()


def _compact(tr):
    x, y = tr.pos
    vx, vy = tr.vel
    return {"id": tr.id, "k": tr.kind[0], "c": tr.subclass, "x": round(x, 2), "y": round(y, 2),
            "vx": round(vx, 2), "vy": round(vy, 2), "h": None if tr.heading is None else round(tr.heading, 2)}
