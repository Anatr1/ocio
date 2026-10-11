"""Optional intersection RGB/mask camera, with actual NN inference on rendered pixels.

Neither mask IDs nor simulator boxes are supplied to the detector or tracker.
Four synchronized views supply localized NN observations to the perception twin.
"""
from __future__ import annotations

import functools
from collections import deque
from http.server import ThreadingHTTPServer
import json
import math
from pathlib import Path
import platform
import threading
import time

import cv2
import numpy as np

from crosswalk.config import load_config
from crosswalk.geometry import Camera, h_jacobian
from crosswalk.detectors import create_detector
from crosswalk.tracker import Tracker
from sim.render_source import RenderHandler, decode_image, TWIN_MODULES
from sim.repro import file_hash, json_hash
from sim.detection_eval import DetectionEvaluator

ROOT = Path(__file__).resolve().parents[2]
CAMERAS = ("overview", "N", "E", "S", "W")


def camera_for_view(view, width=640, height=480):
    if view not in CAMERAS:
        raise ValueError("unknown intersection camera")
    if view == "overview":
        return Camera.look_at([-24, -28, 21], [0, 0, 0], width, height, hfov_deg=76)
    angle = ("N", "E", "S", "W").index(view)*math.pi/2
    def rotate(point):
        x,y,z = point
        return [x*math.cos(angle)+y*math.sin(angle), -x*math.sin(angle)+y*math.cos(angle), z]
    return Camera.look_at(rotate([-11, 19, 7]), rotate([1, 10, 0]), width, height, hfov_deg=76)


class IntersectionRenderer:
    def __init__(self, geometry, seed=0, detector="none", model="models/yolo11n_320.onnx", camera="overview", condition="day"):
        from playwright.sync_api import sync_playwright
        if detector not in ("none", "real") or condition not in ("day", "night", "rain", "fog"):
            raise ValueError("invalid intersection camera mode")
        self.width,self.height = 640,480
        self.camera_name = camera
        self.camera = camera_for_view(camera,self.width,self.height)
        self.condition = condition
        self.closed=False
        self.browser=self.playwright=self.server=self.thread=None
        self.frames,self.elapsed=0,0.
        self.generation=None
        self.last_detections={}
        self.errors=[]
        self.scorers={name:DetectionEvaluator() for name in CAMERAS}
        for scorer in self.scorers.values(): scorer.frames=deque(maxlen=3000)
        self.cfg=load_config(None,[])
        self.detector=None
        if detector == "real":
            path=Path(model)
            if not path.is_absolute(): path=ROOT/path
            self.cfg.detector.model=str(path)
            self.cfg.detector.backend="onnx"
            self.detector=create_detector(self.cfg.detector)
        self.tracker=Tracker(self.cfg.tracker)
        manifest=ROOT/"sim/render/assets/manifest.json"
        if not manifest.is_file():
            raise FileNotFoundError("photoreal assets missing; run tools/fetch_sim_assets.py")
        assets=json.loads(manifest.read_text(encoding="utf-8"))
        for name,record in assets.items():
            path=(ROOT/"sim/render"/name).resolve()
            if not path.is_relative_to(ROOT/"sim/render") or not path.is_file() or file_hash(path)!=record["sha256"]:
                raise ValueError(f"photoreal asset missing/changed: {name}; run tools/fetch_sim_assets.py")
        code={name:file_hash(ROOT/name) for name in ("sim/render/renderer.js","sim/render/context.js",
              "sim/render/intersection-environment.js","sim/render/index.html",*TWIN_MODULES,
              "sim/intersection/render_source.py","sim/intersection/perception.py","sim/intersection/controller.py","sim/intersection/app.py",
              "crosswalk/tracker.py","crosswalk/detectors/base.py","sim/intersection/world.py","sim/intersection/geometry.py")}
        self.provenance={"assets_hash":json_hash(assets),"code_hash":json_hash(code),"code":code,
                         "model_hash":file_hash(self.cfg.detector.model) if self.detector else None}
        try:
            self.server=ThreadingHTTPServer(("127.0.0.1",0),functools.partial(RenderHandler,directory=str(ROOT)))
            self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
            self.playwright=sync_playwright().start()
            angle="d3d11" if platform.system()=="Windows" else "gl"
            self.browser=self.playwright.chromium.launch(channel="chrome",headless=True,args=["--enable-gpu",
                "--force-high-performance-gpu","--ignore-gpu-blocklist",f"--use-angle={angle}",
                "--disable-background-timer-throttling"])
            self.page=self.browser.new_page(viewport={"width":self.width,"height":self.height},device_scale_factor=1)
            self.page.on("pageerror",lambda error:self.errors.append(str(error)))
            self.page.on("response",lambda r:self.errors.append(f"HTTP {r.status}: {r.url}") if r.status>=400 else None)
            self.page.goto(f"http://127.0.0.1:{self.server.server_port}/sim/render/index.html")
            self.page.wait_for_function("window.provingGround !== undefined")
            conditions={"time_of_day":"night" if condition=="night" else "day",
                        "weather":condition if condition in ("rain","fog") else "clear"}
            options={"scene":{"intersection":geometry.payload()},"camera":self.camera.to_dict(),"K":self.camera.K.tolist(),
                     "width":self.width,"height":self.height,"conditions":conditions,"seed":seed,"human_asset":"rocketbox"}
            self.info=self.page.evaluate("options => provingGround.initialize(options)",options)
            self.info.update({"browser":"chrome","browser_version":self.browser.version})
            self.geometry=geometry
            self._check_projection()
            if self.errors: raise RuntimeError("; ".join(self.errors))
        except Exception:
            self.close()
            raise

    def _check_projection(self):
        points=[[x,y,0] for crossing in self.geometry.payload()["crosswalks"].values() for x,y in (crossing["start"],crossing["end"])]
        actual=np.asarray(self.page.evaluate("points => provingGround.project(points)",points))
        expected,_=self.camera.project(points)
        error=float(np.linalg.norm(actual-expected,axis=1).max())
        if error>1: raise ValueError(f"intersection camera projection mismatch: {error:.3f}px")
        self.projection_error=error

    def capture(self, snapshot, camera="overview", generation=0):
        started=time.perf_counter()
        if camera != self.camera_name:
            self.camera=camera_for_view(camera,self.width,self.height)
            self.camera_name=camera
            self.page.evaluate("options => provingGround.setCamera(options)",{"camera":self.camera.to_dict(),"K":self.camera.K.tolist()})
            self._check_projection()
            self.tracker=Tracker(self.cfg.tracker)
        if generation != self.generation:
            self.page.evaluate("state => provingGround.render(state)",{"t":snapshot["t"],"agents":[]})
            self.tracker=Tracker(self.cfg.tracker)
            if self.generation is not None:
                self.frames,self.elapsed=0,0.
                self.scorers={name:DetectionEvaluator() for name in CAMERAS}
                for scorer in self.scorers.values(): scorer.frames=deque(maxlen=3000)
            self.generation=generation
        actors=[]
        for a in snapshot["agents"]:
            color=[[124,157,178],[179,151,119],[102,130,110],[176,102,79]][a["id"]%4]
            actors.append({**a,"color":color,"det_class":"person" if a["kind"]=="pedestrian" else a["cls"]})
        payload=self.page.evaluate("state => provingGround.render(state)",{"t":snapshot["t"],"agents":actors,"signal":snapshot["signal"]})
        if payload["errors"] or self.errors: raise RuntimeError("; ".join(payload["errors"]+self.errors))
        frame=decode_image(payload["rgb"])
        raw=frame.copy()
        predictions=self.detector(frame) if self.detector else []
        # Footpoint homography with metric covariance; no ground-truth IDs/boxes used.
        for det in predictions:
            ground=self.camera.ground_from_pixel([det.foot])[0]
            if not np.isfinite(ground).all() or max(abs(ground))>80: continue
            det.world=tuple(ground)
            jacobian=h_jacobian(self.camera.H_i2w,*det.foot)
            det.cov=jacobian@jacobian.T*9+np.eye(2)*.04
        localized=[d for d in predictions if d.world is not None]
        self.last_detections[camera]=localized
        tracks=self.tracker.update(snapshot["t"],localized)
        for det in predictions:
            x1,y1,x2,y2=map(int,(det.x1,det.y1,det.x2,det.y2))
            cv2.rectangle(frame,(x1,y1),(x2,y2),(55,190,255),1)
            cv2.putText(frame,f"{det.cls} {det.score:.2f}",(x1,max(12,y1-4)),cv2.FONT_HERSHEY_SIMPLEX,.38,(55,190,255),1,cv2.LINE_AA)
        if self.detector:
            self.scorers[camera].observe(snapshot["t"],payload["boxes"],[d.to_dict() for d in predictions],self.condition,[self.width,self.height])
        self.frames+=1;self.elapsed+=time.perf_counter()-started
        def jpg(image):
            ok,encoded=cv2.imencode(".jpg",image,[cv2.IMWRITE_JPEG_QUALITY,88])
            if not ok: raise RuntimeError("cannot encode intersection camera")
            return encoded.tobytes()
        stats={"mode":"photoreal","detector":"real" if self.detector else "none","camera":camera,
               "condition":self.condition,"frame_t":snapshot["t"],"frames":self.frames,"generation":generation,
               "render_inference_fps":round(self.frames/max(self.elapsed,1e-6),2),
               "projection_error_px":round(self.projection_error,6),"predictions":[d.to_dict() for d in predictions],
               "tracks":[{"id":tr.id,"kind":tr.kind,"x":round(tr.pos[0],2),"y":round(tr.pos[1],2),"state":tr.state} for tr in tracks],
               "renderer":self.info,"control_observations":"NN perception" if self.detector else "simulator ground truth"}
        return jpg(frame),jpg(raw),stats,payload["boxes"]

    def capture_all(self, snapshot, generation=0):
        """Four fixed virtual cameras at one physical simulation timestamp.

        Rendering/inference is serialized on one GPU context. Display selection
        does not alter which sensors are sampled or reset the fusion tracker.
        """
        feeds, observations = {}, {}
        for camera in ("N","E","S","W"):
            overlay,raw,metadata,_ = self.capture(snapshot,camera,generation)
            feeds[camera] = {"overlay":overlay,"raw":raw,"metadata":metadata}
            observations[camera] = list(self.last_detections[camera])
        return feeds,observations

    def report(self):
        scores={}
        for name,scorer in self.scorers.items():
            if not scorer.frames: continue
            duration=max(f["t"] for f in scorer.frames)-min(f["t"] for f in scorer.frames)
            scores[name]=scorer.summarize(duration)
            # Switching/pausing views does not provide continuous camera exposure.
            scores[name]["fp_per_minute"]=None
        return {"provenance":self.provenance,"frames":self.frames,"renderer":self.info,"detector":"real" if self.detector else "none",
                "condition":self.condition,"image_size":[self.width,self.height],"model":self.cfg.detector.model if self.detector else None,
                "camera_scores":scores,
                "notes":["NN sees rendered RGB only; masks are used solely for offline scoring.",
                         "Four-camera NN observations drive the perception twin and signal demand in real detector mode.",
                         "Scores use the last 3000 sampled frames per view in the current reset generation; FP/min is omitted for switchable cameras.",
                         "Generic assets are shared with crosswalk L2; no calibrated field-transfer score is claimed."]}

    def close(self):
        if self.closed:return
        self.closed=True
        if self.browser:self.browser.close()
        if self.playwright:self.playwright.stop()
        if self.server:self.server.shutdown();self.server.server_close()
        if self.thread:self.thread.join()
