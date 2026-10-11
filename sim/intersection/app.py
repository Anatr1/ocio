"""Local live intersection simulator, twin controls and optional RGB camera transport."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit, parse_qs

from .controller import PHASES
from .evaluation import compare
from .world import SCENARIOS, IntersectionWorld

ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = ROOT / "dashboard"


class IntersectionApp:
    def __init__(self, scenario="balanced", policy="adaptive", seed=0, speed=1.):
        if not .1 <= speed <= 30 or not math.isfinite(speed):
            raise ValueError("simulation speed must be .1–30")
        self.world = IntersectionWorld(scenario, policy, seed)
        self.speed, self.paused = speed, False
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.job = None
        self.render_mode = "twin"
        self.camera_name = "overview"
        self.generation = 0
        self.camera_frame = self.camera_raw = None
        self.sensor = self.vision_report = None
        self.perception = None
        self.max_frame_age = 1.5
        self.camera_feeds = {}
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="intersection-comparison")

    def snapshot(self):
        with self.lock:
            if self.perception:
                state = {"t": self.world.t, "scenario": self.world.scenario, "seed": self.world.seed,
                         "signal": self.world.controller.payload(), **self.perception.snapshot(self.world.t)}
            else:
                state = self.world.snapshot()
            return {**state, "paused": self.paused, "speed": self.speed,
                    "render_mode": self.render_mode, "camera": self.sensor,
                    "observation_mode": "vision" if self.perception else "ground_truth"}

    def enable_perception(self):
        from .perception import IntersectionPerception
        self.perception = IntersectionPerception(self.world.geometry,max_frame_age=self.max_frame_age)
        self.world.observation_provider = self.perception.control_observations
        self.camera_name = "N" if self.camera_name == "overview" else self.camera_name

    def report(self):
        with self.lock:
            if self.perception:
                return {**self.perception.report(), "scenario": self.world.scenario, "seed": self.world.seed,
                        "seconds": self.world.t, "policy": self.world.controller.policy,
                        "camera_diagnostics": self.vision_report}
            return {**self.world.report(), "camera": self.vision_report}

    def config(self):
        with self.lock:
            return {"geometry": self.world.geometry.payload(), "scenarios": list(SCENARIOS),
                    "phases": [{"id": p.id, "label": p.label, "movements": p.movements, "pedestrian": p.pedestrian} for p in PHASES],
                    "observation_mode": "vision" if self.perception else "ground_truth", "render_mode": self.render_mode,
                    "cameras": ["N","E","S","W"] if self.perception else ["overview","N","E","S","W"]}

    def control(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("control body must be an object")
        action = payload.get("action")
        with self.lock:
            if action == "pause":
                if not isinstance(payload.get("paused"), bool):
                    raise ValueError("paused must be boolean")
                self.paused = payload["paused"]
            elif action == "speed":
                value = float(payload["speed"])
                if not math.isfinite(value) or not .1 <= value <= 30:
                    raise ValueError("speed must be .1–30")
                self.speed = value
            elif action == "policy":
                self.world.controller.set_policy(payload["policy"])
            elif action == "camera":
                from .render_source import CAMERAS
                if self.render_mode != "photoreal" or payload.get("camera") not in CAMERAS:
                    raise ValueError("camera requires photoreal mode and a valid view")
                self.camera_name = payload["camera"]
                if self.perception and self.camera_name == "overview":
                    self.camera_name = "N"
                if self.camera_name in self.camera_feeds:
                    feed = self.camera_feeds[self.camera_name]
                    self.camera_frame,self.camera_raw,self.sensor = feed["overlay"],feed["raw"],feed["metadata"]
            elif action == "call":
                self.world.controller.request(payload.get("crossing", "N"))
            elif action == "slow_walker":
                self.world.spawn_pedestrian(payload.get("crossing", "N"), speed=.55)
            elif action == "reset":
                scenario = payload.get("scenario", self.world.scenario)
                policy = payload.get("policy", self.world.controller.policy)
                seed = payload.get("seed", self.world.seed)
                if not isinstance(seed, int) or isinstance(seed, bool):
                    raise ValueError("seed must be an integer")
                self.world = IntersectionWorld(scenario, policy, seed)
                self.generation += 1
                self.camera_frame = self.camera_raw = self.sensor = self.vision_report = None
                self.camera_feeds = {}
                if self.perception:
                    self.enable_perception()
            elif action == "compare":
                if self.job and self.job["status"] == "running":
                    raise ValueError("comparison already running")
                scenario = self.world.scenario
                seed = self.world.seed
                self.job = {"status": "running", "progress": 0., "scenario": scenario}
                self.executor.submit(self._compare, scenario, seed)
            else:
                raise ValueError("unknown action")
        return {"ok": True}

    def _compare(self, scenario, seed):
        try:
            def progress(value):
                with self.lock:
                    self.job["progress"] = value
            result = compare(scenario, 300., (seed,), progress)
            with self.lock:
                self.job = {"status": "complete", "progress": 1., "result": result}
        except Exception as exc:
            with self.lock:
                self.job = {"status": "error", "error": str(exc)}

    def close(self):
        self.stop_event.set()
        self.executor.shutdown(wait=True, cancel_futures=True)


class Handler(BaseHTTPRequestHandler):
    server_version = "ocio-intersection/1"

    def log_message(self, fmt, *args):
        pass

    @property
    def app(self):
        return self.server.app

    def send(self, value, status=200, content_type="application/json; charset=utf-8"):
        body = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8") if isinstance(value, dict) else value
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionError):
            pass

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/state":
            return self.send(self.app.snapshot())
        if path == "/api/config":
            return self.send(self.app.config())
        if path == "/api/health":
            return self.send({"ok": True, "mode": "intersection", "simulated": True})
        if path == "/api/report":
            return self.send(self.app.report())
        if path == "/api/ground-truth":
            with self.app.lock:
                return self.send({"diagnostic_only":True, "observation_mode":"simulator ground truth",
                                  "state":self.app.world.snapshot()})
        if path in ("/api/camera.jpg", "/api/camera-raw.jpg"):
            with self.app.lock:
                camera = parse_qs(urlsplit(self.path).query).get("camera",[self.app.camera_name])[0]
                feed = self.app.camera_feeds.get(camera)
                frame = feed["raw" if path == "/api/camera-raw.jpg" else "overlay"] if feed else (
                    self.app.camera_raw if path == "/api/camera-raw.jpg" else self.app.camera_frame)
            return self.send(frame or b"", status=200 if frame else 204, content_type="image/jpeg")
        if path == "/api/comparison":
            with self.app.lock:
                return self.send(self.app.job or {"status": "idle"})
        allowed = {"/": "intersection.html", "/intersection.html": "intersection.html",
                   "/js/intersection.js": "js/intersection.js", "/css/intersection.css": "css/intersection.css",
                   "/js/intersection-camera.js": "js/intersection-camera.js",
                   "/js/avatars.js": "js/avatars.js", "/js/visual-geometry.js": "js/visual-geometry.js",
                   "/css/style.css": "css/style.css", "/fonts/manrope-latin.woff2": "fonts/manrope-latin.woff2"}
        name = allowed.get(path)
        if name is None and path.startswith("/vendor/"):
            candidate = (DASHBOARD / path.lstrip("/")).resolve()
            if candidate.is_relative_to((DASHBOARD / "vendor").resolve()) and candidate.is_file():
                name = candidate.relative_to(DASHBOARD).as_posix()
        if name is None:
            return self.send({"error": "not found"}, 404)
        file = DASHBOARD / name
        if not file.is_file():
            return self.send({"error": "missing asset"}, 404)
        kinds = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".woff2": "font/woff2"}
        return self.send(file.read_bytes(), content_type=kinds.get(file.suffix, "application/octet-stream"))

    def do_POST(self):
        if urlsplit(self.path).path != "/api/control":
            return self.send({"error": "not found"}, 404)
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            return self.send({"error": "JSON required"}, 415)
        origin = self.headers.get("Origin")
        if origin and origin != f"http://{self.headers.get('Host')}":
            return self.send({"error": "cross-origin control rejected"}, 403)
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 4096:
                raise ValueError("invalid request size")
            result = self.app.control(json.loads(self.rfile.read(size)))
            return self.send(result)
        except (ValueError, KeyError, TypeError) as exc:
            return self.send({"error": str(exc)}, 400)


def serve(app, port):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.app = app
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def run(args):
    if not math.isfinite(args.intersection_render_fps) or not .5 <= args.intersection_render_fps <= 15:
        raise ValueError("--intersection-render-fps must be .5–15")
    if args.max_seconds is not None and (not math.isfinite(args.max_seconds) or args.max_seconds <= 0):
        raise ValueError("--max-seconds must be finite and positive")
    if args.max_frames is not None and args.max_frames <= 0:
        raise ValueError("--max-frames must be positive")
    if args.no_server and args.max_seconds is None and args.max_frames is None:
        raise ValueError("headless intersection mode requires --max-seconds or --max-frames")
    app = IntersectionApp(args.intersection_scenario, args.intersection_policy, args.seed, args.intersection_speed)
    app.render_mode, app.camera_name = args.intersection_render, args.intersection_camera
    app.max_frame_age = max(1.5, 1/args.intersection_render_fps+.2)
    sensor = None
    if args.intersection_render == "photoreal":
        from .render_source import IntersectionRenderer
        try:
            sensor = IntersectionRenderer(app.world.geometry, args.seed, args.intersection_detector,
                                          args.intersection_model, args.intersection_camera, args.intersection_condition)
            if args.intersection_detector == "real":
                app.enable_perception()
        except Exception:
            app.close()
            raise
    try:
        server, thread = serve(app, args.port if args.port is not None else 8010) if not args.no_server else (None, None)
    except Exception:
        app.close()
        if sensor: sensor.close()
        raise
    if server:
        print(f"[intersection] http://127.0.0.1:{server.server_port} · {args.intersection_scenario} · {args.intersection_policy}", flush=True)
    print(f"[intersection] Observations={'four-camera NN' if app.perception else 'ground truth'}; render={app.render_mode}; detector={args.intersection_detector}; no physical actuation", flush=True)
    frames = 0
    previous = time.perf_counter()
    accumulator = 0.
    last_render = -math.inf
    last_generation = -1
    try:
        while not app.stop_event.is_set():
            now = time.perf_counter()
            with app.lock:
                if args.fast and not app.paused:
                    accumulator += app.world.dt
                elif not app.paused:
                    accumulator += min(.25, now - previous) * app.speed
                previous = now
                if app.perception:
                    # Pace simulation to sensor batches: a slow GPU slows the
                    # virtual world instead of skipping unsensed seconds.
                    accumulator = min(accumulator, max(app.world.dt, 1/args.intersection_render_fps))
                ticks = 0
                while accumulator >= app.world.dt - 1e-9 and ticks < 30:
                    app.world.step()
                    frames += 1
                    ticks += 1
                    accumulator -= app.world.dt
                    if args.max_seconds is not None and app.world.t >= args.max_seconds or args.max_frames is not None and frames >= args.max_frames:
                        app.stop_event.set()
                        break
                snapshot = app.world.snapshot() if sensor and (app.world.t-last_render >= 1/args.intersection_render_fps-1e-8 or
                            app.generation != last_generation or (not app.perception and app.camera_name != sensor.camera_name)) else None
                camera_name, generation = app.camera_name, app.generation
            if snapshot:
                if app.perception:
                    feeds,observations = sensor.capture_all(snapshot,generation)
                else:
                    frame, raw, metadata, _ = sensor.capture(snapshot, camera_name, generation)
                with app.lock:
                    if app.generation == generation:
                        if app.perception:
                            app.perception.update(snapshot["t"],observations)
                            app.camera_feeds = feeds
                            for feed in feeds.values():
                                feed["metadata"]["active_cameras"] = ["N","E","S","W"]
                                feed["metadata"]["fused_tracks"] = len(app.perception.tracker.confirmed())
                            selected = feeds[app.camera_name]
                            app.camera_frame,app.camera_raw,app.sensor = selected["overlay"],selected["raw"],selected["metadata"]
                        elif app.camera_name == camera_name:
                            app.camera_frame, app.camera_raw, app.sensor = frame, raw, metadata
                        if sensor.frames == 1 or sensor.frames % 20 == 0:
                            app.vision_report = sensor.report()
                last_render, last_generation = snapshot["t"], generation
            if not args.fast or app.paused:
                time.sleep(.01)
    except KeyboardInterrupt:
        pass
    finally:
        if server:
            server.shutdown()
            server.server_close()
            thread.join()
        app.close()
        if sensor:
            app.vision_report = sensor.report()
            sensor.close()
    report = app.report()
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return report
