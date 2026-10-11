"""Lockstep Three.js RGB source. No detections() method: L2 uses the real NN."""
from __future__ import annotations

import base64
import functools
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import platform
import random
import threading
import time
from urllib.parse import unquote, urlsplit

import cv2
import numpy as np

from .camera import camera_for_config
from .scenarios import load_scenario, scenario_hash
from .repro import file_hash
from .world import DET_CLASS, World

ROOT = Path(__file__).resolve().parents[1]
# The photoreal renderer imports the twin's avatar factory and its module graph.
# Use the same explicit dependency list for HTTP access and cache provenance.
TWIN_MODULES = ("dashboard/js/twin.js", "dashboard/js/avatars.js",
                "dashboard/js/streetscape.js", "dashboard/js/visual-geometry.js")


class RenderHandler(SimpleHTTPRequestHandler):
    def send_head(self):
        root = Path(self.directory).resolve()
        target = (root / unquote(urlsplit(self.path).path).replace("\\", "/").lstrip("/")).resolve()
        if not (target.is_relative_to(root / "sim/render") or target.is_relative_to(root / "dashboard/vendor") or
                target in (root / name for name in TWIN_MODULES)):
            self.send_error(404)
            return None
        self.path = "/" + target.relative_to(root).as_posix()
        return super().send_head()

    def list_directory(self, path):
        self.send_error(403)
        return None

    def log_message(self, *args):
        pass


def decode_image(data):
    encoded = base64.b64decode(data.split(",", 1)[1])
    image = cv2.imdecode(np.frombuffer(encoded, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError("renderer returned an invalid image")
    return image


def mask_boxes(mask, agents):
    ids = mask[:, :, 2].astype(np.uint32) + (mask[:, :, 1].astype(np.uint32) << 8) + (mask[:, :, 0].astype(np.uint32) << 16)
    result = []
    for agent in agents:
        ys, xs = np.where(ids == agent["id"])
        result.append({"id": agent["id"], "cls": agent["det_class"], "kind": agent["kind"],
                       "box": [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1] if len(xs) else None,
                       "pixels": len(xs)})
    return result


class RenderSource:
    live = False

    def __init__(self, cfg, scenario="mixed", seed=0, fps=15.0, signal=None):
        from playwright.sync_api import sync_playwright

        if not math.isfinite(fps) or fps <= 0:
            raise ValueError("fps must be positive and finite")
        if not isinstance(seed, int) or seed < 0:
            raise ValueError("seed must be a nonnegative integer")
        self.cfg, self.seed = cfg, seed
        self._pending = []
        self._stage_rng = random.Random(seed + 7)
        self.spec = load_scenario(scenario)
        if cfg.get("sim", {}).get("presentation_mode") or self.spec.get("presentation_mode"):
            raise ValueError("evaluation refuses presentation_mode")
        self.width, self.height = int(cfg.source.width), int(cfg.source.height)
        self.camera, self.scene = camera_for_config(cfg, self.width, self.height)
        self.world = World(cfg.scene, self.spec, seed, signal, cfg)
        self.seq, self.dt, self.fps = 0, 1 / fps, fps
        self.t0 = time.perf_counter()
        self.realtime = bool(cfg.get("sim", {}).get("realtime", False))
        self.wall0 = None
        self.visible_vehicles = {}
        self.frame_meta = None
        self.mask = None
        self.sensor = cfg.get("sim", {}).get("sensor", {})
        self.frames_written = 0
        self.render_seconds = 0.0
        self.captured_frames = 0
        self.failed = False
        self.closed = False
        self.browser = self.playwright = None
        manifest = ROOT / "sim/render/assets/manifest.json"
        if not manifest.exists():
            raise FileNotFoundError("renderer assets missing: run python tools/fetch_sim_assets.py")
        assets = json.loads(manifest.read_text(encoding="utf-8"))
        for name, record in assets.items():
            path = (ROOT / "sim/render" / name).resolve()
            if not path.is_relative_to(ROOT / "sim/render") or file_hash(path) != record["sha256"]:
                raise ValueError(f"renderer asset changed or invalid path: {name}; recreate/record the asset bundle")
        code = {name: file_hash(ROOT / name) for name in
                ("sim/render/renderer.js", "sim/render/context.js", "sim/render/index.html", "dashboard/vendor/three.module.js", *TWIN_MODULES,
                 "sim/render_source.py", "sim/world.py", "sim/behaviour.py", "sim/gt.py",
                 "sim/camera.py", "sim/scenarios.py", "sim/repro.py")}
        self.asset_hash = hashlib.sha256(json.dumps({"assets": assets, "code": code}, sort_keys=True).encode()).hexdigest()
        self.cache = None
        self.cache_root = cfg.get("sim", {}).get("render_cache")
        handler = functools.partial(RenderHandler, directory=str(ROOT))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True, name="render-http")
        self.thread.start()
        try:
            self.playwright = sync_playwright().start()
            angle = cfg.get("sim", {}).get("angle", "d3d11" if platform.system() == "Windows" else "gl")
            channel = cfg.get("sim", {}).get("browser", "chromium")
            self.browser = self.playwright.chromium.launch(headless=True, channel=channel, args=[
                "--enable-gpu", "--force-high-performance-gpu", "--ignore-gpu-blocklist", f"--use-angle={angle}",
                "--disable-background-timer-throttling",
            ])
            self.page = self.browser.new_page(viewport={"width": self.width, "height": self.height}, device_scale_factor=1)
            self.page_errors = []
            self.page.on("pageerror", lambda error: self.page_errors.append(str(error)))
            self.page.on("response", lambda response: self.page_errors.append(f"HTTP {response.status}: {response.url}")
                         if response.status >= 400 else None)
            self.page.goto(f"http://127.0.0.1:{self.server.server_port}/sim/render/index.html")
            self.page.wait_for_function("window.provingGround !== undefined")
            options = {"scene": cfg.scene.to_plain(), "camera": self.camera.to_dict(), "K": self.camera.K.tolist(),
                       "width": self.width, "height": self.height, "conditions": self.spec["conditions"], "seed": seed,
                       "human_asset": cfg.get("sim", {}).get("human_asset", "rocketbox")}
            self.renderer_info = self.page.evaluate("options => provingGround.initialize(options)", options)
            self.renderer_info.update({"browser": channel, "browser_version": self.browser.version})
            W, L = self.world.W, self.world.L
            corners = [[-W / 2, -L / 2, 0], [W / 2, -L / 2, 0], [W / 2, L / 2, 0], [-W / 2, L / 2, 0]]
            rendered = np.array(self.page.evaluate("points => provingGround.project(points)", corners))
            expected, _ = self.camera.project(corners)
            self.geometry_error_px = float(np.linalg.norm(rendered - expected, axis=1).max())
            if self.geometry_error_px > 1:
                raise ValueError(f"G0 camera mismatch: {self.geometry_error_px:.3f} px")
            if self.scene.calibrated:
                ground = self.scene.world_to_image([p[:2] for p in corners])
                self.geometry_error_px = max(self.geometry_error_px, float(np.linalg.norm(rendered - ground, axis=1).max()))
                if self.geometry_error_px > 1:
                    raise ValueError(f"site homography is inconsistent with its camera: {self.geometry_error_px:.3f} px")
            self.cache_metadata = {"scenario": self.spec, "scenario_hash": scenario_hash(self.spec), "seed": seed,
                                   "fps": fps, "asset_hash": self.asset_hash, "renderer": self.renderer_info,
                                   "calibration": self.calibration(), "sensor": self.sensor,
                                   "geometry_error_px": self.geometry_error_px, "presentation_mode": False,
                                   "human_asset": options["human_asset"], "scene": cfg.scene.to_plain(), "bundle_code": code,
                                   "control": {"mode": signal.mode if signal else "unsignalised", "closed_loop": signal is not None},
                                   "frame_count": 0, "complete": False}
            self._start_cache()
        except Exception as error:
            self.close()
            if getattr(self, "page_errors", []):
                raise RuntimeError(f"renderer initialization failed: {self.page_errors}") from error
            raise

    def _start_cache(self):
        fingerprint = {k: self.cache_metadata[k] for k in
                       ("scenario_hash", "seed", "fps", "asset_hash", "calibration", "sensor", "human_asset", "scene", "control")}
        self.cache_metadata["fingerprint"] = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()
        if self.cache_root:
            directory = Path(self.cache_root) / self.spec["name"] / str(self.seed) / self.cache_metadata["fingerprint"][:16]
            if self.cache and self.cache.exists() and not list(self.cache.glob("*.jpg")):
                # Binding the controller before frame one only leaves a metadata-only attempt.
                self.cache_metadata["supersedes"] = str(self.cache)
            for attempt in range(1, 10000):
                self.cache = directory / f"run-{attempt:04d}"
                try:
                    self.cache.mkdir(parents=True, exist_ok=False)
                    break
                except FileExistsError:
                    continue
            else:
                raise RuntimeError("too many cache attempts")
            self._write_manifest()

    def _write_manifest(self):
        if self.cache:
            temporary = self.cache / "manifest.json.tmp"
            temporary.write_text(json.dumps(self.cache_metadata, indent=2), encoding="utf-8")
            temporary.replace(self.cache / "manifest.json")

    def inject(self, name):
        """Dashboard demo buttons (near-miss, slow walker...). Recorded in the cache metadata: an injected run is
        not the scripted scenario any more."""
        self._pending.append(name)
        return True

    def bind_signal(self, signal):
        if self.seq:
            raise RuntimeError("bind the signal controller before capturing frames")
        self.world.signal = signal
        self.cache_metadata["control"] = {"mode": signal.mode, "closed_loop": True,
                                          "signal_config": self.cfg.signal.to_plain(),
                                          "detector_config": self.cfg.detector.to_plain(),
                                          "model_hash": file_hash(self.cfg.detector.model)}
        self._start_cache()

    def calibration(self):
        W, L = self.world.W, self.world.L
        uv, _ = self.camera.project([[-W / 2, -L / 2, 0], [W / 2, -L / 2, 0], [W / 2, L / 2, 0], [-W / 2, L / 2, 0]])
        return {"H": self.camera.H_i2w.tolist(), "image_points": uv.tolist(), "image_size": [self.width, self.height],
                "focal_px": float(self.camera.K[0, 0])}

    def snapshot(self):
        return {"t": self.world.t, "agents": [{"id": a.id, "cls": a.cls, "det_class": DET_CLASS[a.cls],
                  "kind": a.kind, "x": a.x, "y": a.y, "vx": a.vx, "vy": a.vy, "speed": a.speed,
                  "heading": a.heading, "dims": list(a.dims), "color": list(a.color), "state": a.state}
                 for a in self.world.agents]}

    GT_RANGE_M = 90.0  # the dashboard twin's street ends here (dashboard/js/twin.js `far`)
    GT_FULL_PIXELS = 200  # instance pixels from which an agent counts as fully detectable (~10x20 px)

    def ground_truth(self) -> list[dict]:
        """True agents of the last rendered frame for the dashboard ghost layer (same fields as
        SimSource.ground_truth). Visibility comes from the rendered instance mask, so occlusion is exact;
        it is scaled by GT_FULL_PIXELS because the unoccluded size is not rendered."""
        meta = getattr(self, "frame_meta", None)
        if not meta:
            return []
        pixels = {b["id"]: b["pixels"] for b in meta["boxes"]}
        return [{"id": a["id"], "kind": a["kind"], "cls": a["cls"], "x": round(a["x"], 3), "y": round(a["y"], 3),
                 "vx": round(a["vx"], 3), "vy": round(a["vy"], 3), "heading": round(a["heading"], 3),
                 "dims": a["dims"], "state": a["state"],
                 "visible": round(min(1.0, pixels.get(a["id"], 0) / self.GT_FULL_PIXELS), 2)}
                for a in meta["agents"] if abs(a["x"]) <= self.GT_RANGE_M]

    def capture(self):
        snapshot = self.snapshot()
        started = time.perf_counter()
        payload = self.page.evaluate("state => provingGround.render(state)", snapshot)
        if payload["errors"]:
            raise RuntimeError(f"renderer error: {payload['errors']}")
        frame, mask = decode_image(payload["rgb"]), decode_image(payload["mask"])
        frame, mask = self.camera_response(frame, mask)
        boxes = mask_boxes(mask, snapshot["agents"])
        for box, jsbox in zip(boxes, payload["boxes"]):
            box["asset_quality"] = jsbox["asset_quality"]
            if not self.spec["conditions"].get("shake_px") and (box["box"] != jsbox["box"] or box["pixels"] != jsbox["pixels"]):
                raise ValueError("G0 instance IDs/boxes disagree between Python and WebGL")
        self.mask = mask
        self.frame_meta = {"t": self.world.t, "seq": self.seq, "boxes": boxes, "agents": snapshot["agents"]}
        agents_by_id = {a["id"]: a for a in snapshot["agents"]}
        for box in boxes:
            if box["kind"] == "vehicle" and box["pixels"] > 0 and box["id"] not in self.visible_vehicles:
                a = agents_by_id[box["id"]]
                distance = max(0.0, abs(a["x"]) - self.world.W / 2)
                self.visible_vehicles[box["id"]] = {"id": box["id"], "t": self.world.t, "distance_to_zebra_m": distance,
                                                    "late_under_10m": distance < 10, "pixels": box["pixels"]}
        quality = int(self.sensor.get("jpeg_quality", 85))
        ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if not ok:
            raise RuntimeError("cannot encode rendered camera frame")
        frame = cv2.imdecode(jpeg, cv2.IMREAD_COLOR)
        if self.cache:
            path = self.cache / f"{self.seq:06d}"
            path.with_suffix(".jpg").write_bytes(jpeg.tobytes())
            if not cv2.imwrite(str(path.with_suffix(".mask.png")), mask):
                raise RuntimeError("cannot write instance mask")
            self.frame_meta["sha256"] = {"jpg": file_hash(path.with_suffix(".jpg")),
                                         "mask": file_hash(path.with_suffix(".mask.png"))}
            path.with_suffix(".json").write_text(json.dumps(self.frame_meta), encoding="utf-8")
            self.frames_written += 1
        self.render_seconds += time.perf_counter() - started
        self.captured_frames += 1
        return frame

    def camera_response(self, frame, mask):
        rng = np.random.default_rng(self.seed * 1_000_003 + self.seq)
        image = frame.astype(np.float32)
        noise = float(self.sensor.get("read_noise", 0.7))
        shot = float(self.sensor.get("shot_noise", 0.015))
        if noise or shot:
            sigma = np.sqrt(noise ** 2 + shot * image)
            image += rng.normal(0, 1, image.shape) * sigma
        vignette = float(self.sensor.get("vignette", 0.08))
        yy, xx = np.mgrid[-1:1:complex(self.height), -1:1:complex(self.width)]
        image *= (1 - vignette * np.minimum(1, xx ** 2 + yy ** 2))[:, :, None]
        frame = np.clip(image, 0, 255).astype(np.uint8)
        blur = float(self.sensor.get("blur_sigma", 0.25))
        if blur > 0:
            frame = cv2.GaussianBlur(frame, (3, 3), blur)
        shake = float(self.spec["conditions"].get("shake_px", 0))
        if shake:
            dx, dy = rng.normal(0, shake, 2)
            matrix = np.float32([[1, 0, dx], [0, 1, dy]])
            frame = cv2.warpAffine(frame, matrix, (self.width, self.height), borderMode=cv2.BORDER_REFLECT_101)
            mask = cv2.warpAffine(mask, matrix, (self.width, self.height), flags=cv2.INTER_NEAREST)
        return frame, mask

    def read(self, last_seq=-1, timeout=1.0):
        if self.realtime:
            if self.wall0 is None:
                self.wall0 = time.perf_counter()
            wait = (self.seq + 1) * self.dt - (time.perf_counter() - self.wall0)
            if wait > 0:
                time.sleep(wait)
        while self._pending:  # dashboard demo buttons, applied here so they never race the step
            from sim.source import apply_stage
            name = self._pending.pop(0)
            if apply_stage(self.world, self._stage_rng, name):
                self.cache_metadata.setdefault("injected", []).append({"t": round(self.world.t, 2), "name": name})
        self.world.step(self.dt)
        self.seq += 1
        try:
            return self.capture(), self.world.t, self.seq
        except Exception:
            self.failed = True
            raise

    def stats(self):
        return {"camera_fps": self.seq / max(1e-6, time.perf_counter() - self.t0), "width": self.width, "height": self.height,
                "render_fps": self.captured_frames / max(self.render_seconds, 1e-6), "fidelity": "L2", "renderer": self.renderer_info,
                "geometry_error_px": self.geometry_error_px, "cached_frames": self.frames_written,
                "first_visible_vehicles": list(self.visible_vehicles.values())}

    def close(self):
        if self.closed:
            return
        self.closed = True
        if hasattr(self, "cache_metadata"):
            self.cache_metadata.update({"frame_count": self.frames_written, "duration_s": self.world.t,
                                        "complete": not self.failed, "scenario_complete": self.world.t >= self.spec["duration_s"] - 1e-8,
                                        "first_visible_vehicles": list(self.visible_vehicles.values())})
            if self.cache:
                (self.cache / "ground_truth.json").write_text(json.dumps({"events": self.world.gt_events,
                  "frames": self.world.truth.frames}), encoding="utf-8")
                self._write_manifest()
        if self.browser:
            self.browser.close()
            self.browser = None
        if self.playwright:
            self.playwright.stop()
        if hasattr(self, "server"):
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=2)
