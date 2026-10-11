"""Configuration: defaults + YAML/JSON override, with attribute access.

World frame convention (used everywhere):
    origin  = centre of the crosswalk, on the ground
    X axis  = along the road (direction vehicles travel)            -> crosswalk "width"  W (stripe length)
    Y axis  = across the road (direction pedestrians cross)         -> crosswalk "length" L (curb to curb)
    Z axis  = up
    Curb A is at Y = -L/2, curb B at Y = +L/2.
"""
from __future__ import annotations

import copy
import json
import os
from typing import Any

DEFAULTS: dict[str, Any] = {
    "node": {
        "id": "cw-01",
        "name": "Crosswalk 01",
        "brand": "\u00f2cio",
        "tagline": "the crosswalk that watches out for you",
        # optional geo-reference for the multi-node city map
        "geo": {"lat": 45.0703, "lon": 7.6869, "road_bearing_deg": 90.0},
    },
    "source": {
        "type": "camera",          # camera | video | sim
        "device": 0,               # camera index or /dev/videoN
        "path": "",                # video file for type=video
        "width": 640,
        "height": 480,
        "fps": 30,
        "fourcc": "MJPG",
        "realtime": True,          # video: pace to the file's fps and drop frames like a real camera
        "loop": True,
        "speed": 1.0,
        "rotate": 0,               # 0, 90, 180, 270
        "reopen_s": 2.0,           # camera: no frame for this long -> close and reopen the device
    },
    "detector": {
        "backend": "onnx",         # ultralytics | onnx | ncnn | tflite | sim | none
        "model": "models/yolo11n_320.onnx",
        "imgsz": 320,
        "conf": 0.35,              # high-confidence threshold (spawns tracks)
        "conf_low": 0.15,          # low-confidence detections may only extend existing tracks (ByteTrack)
        "iou": 0.5,
        "threads": 3,
        "class_names": None,       # override model class names (list) if the export lost them
        "roi": None,               # [x, y, w, h] crop of the full frame fed to the detector
        "max_hz": 15.0,            # cap on detector rate
        "idle_hz": 1.0,            # heartbeat rate when nothing moves
        "motion_gate": True,
        "motion_threshold": 0.004, # fraction of changed pixels that counts as motion
    },
    "scene": {
        "crosswalk": {"width": 4.0, "length": 8.0},
        "curb_depth": 2.5,          # pedestrian waiting area depth on each side (m)
        "approach": 25.0,           # road length monitored on each side of the crosswalk (m)
        "sidewalk_width": 3.0,
        "lanes": 2,
        "speed_limit_kmh": 50.0,
        "stripe": {"width": 0.5, "gap": 0.5},   # zebra stripes (IT: 50 cm stripes)
        # human names for the counted directions (set on site, e.g. "A>B": "verso Corso Re Umberto")
        "direction_names": {"A>B": "A → B", "B>A": "B → A", "+X": "→ (+X)", "-X": "← (−X)"},
        "calibration": {
            # image points of the 4 crosswalk corners, in this order:
            #   P1 (-W/2,-L/2)  P2 (+W/2,-L/2)  [curb A]   P3 (+W/2,+L/2)  P4 (-W/2,+L/2)  [curb B]
            "image_points": None,
            "world_points": None,   # optional explicit world points (>=4) matching image_points
            "H": None,              # optional 3x3 image->world homography (overrides points)
            "image_size": [640, 480],
            "hfov_deg": 70.0,       # used only if focal length cannot be estimated from the homography
            "focal_px": None,
        },
    },
    "tracker": {
        "min_hits": 3,
        "max_age_s": {"pedestrian": 1.5, "bicycle": 1.2, "micromobility": 1.2, "vehicle": 1.0},
        "tentative_max_age_s": 0.6,
        "accel_noise": {"pedestrian": 1.5, "bicycle": 2.5, "micromobility": 2.5, "vehicle": 4.0},
        "gate_m": {"pedestrian": 1.6, "bicycle": 3.0, "micromobility": 3.0, "vehicle": 5.0},
        "pixel_sigma": 3.0,         # foot-point pixel noise (px)
        "pixel_sigma_rel": 0.04,    # + fraction of box height
        "min_meas_sigma_m": 0.15,
        "history_s": 20.0,
        "micromobility_speed": 3.6, # a "pedestrian" sustaining > 3.6 m/s (13 km/h) is on wheels ...
        "fast_person_kind": "bicycle",
        "min_person_height_m": 0.75,  # person boxes shorter than this in metres are clutter (0 = off)  # ... and counted as this kind (bicycle | micromobility)
        "world_margin": 6.0,        # tracks outside the monitored area (+margin) are dropped
    },
    "counting": {
        "min_inside_s": 0.25,
        "min_inside_path_m": 0.4,
        "crosswalk_margin_m": 0.75,  # tolerance around the painted crosswalk
        "complete_fraction": 0.7,    # fraction of L a VRU must cover to count as a full crossing
    },
    "safety": {
        "ttc_horizon_s": 4.0,
        "ttc_levels_s": [1.0, 2.0, 3.0],       # critical / serious / potential
        "pet_levels_s": [1.0, 2.0, 3.0],
        "vru_radius_m": 0.35,
        "yield_stop_speed": 1.5,                # m/s: below this the vehicle is yielding
        "yield_lookahead_m": 20.0,
        "waiting_speed": 0.6,                   # m/s: VRU slower than this in the curb zone is waiting
        "waiting_min_s": 0.8,
        "stationary_alert_s": 12.0,             # person not moving on the crosswalk (fall?)
        "blocking_alert_s": 6.0,                # vehicle stopped on the crosswalk
        "warning_hold_s": 1.5,
        "beacon_tta_s": 6.0,                    # rule B1: vehicle arriving within this many seconds
        "drac_min": 3.0,                        # m/s2: braking needed above which a TTC situation is a conflict
        "slow_walker_speed": 0.8,               # m/s
    },
    "signal": {
        "enabled": True,
        "mode": "adaptive",        # adaptive | fixed | beacon (unsignalised zebra: warning light only)
        "veh_min_green_s": 8.0,
        "veh_max_green_s": 40.0,
        "veh_yellow_s": 3.0,
        "all_red_s": 1.5,
        "ped_min_green_s": 5.0,
        "ped_max_green_s": 20.0,
        "ped_clearance_s": None,   # None -> L / design_speed
        "design_walk_speed": 1.2,  # m/s used for fixed clearance
        "max_clearance_extension_s": 8.0,
        "fixed_cycle_veh_green_s": 20.0,
    },
    "record": {                    # dashboard "Rec": raw camera footage for ground truth / training (on device)
        "dir": "data/recordings",
        "fps": 15.0,
        "segment_s": 300.0,        # 5-minute files: a crash or power cut loses at most one segment
        "max_s": 3600.0,           # stops by itself after an hour
    },
    "public": {
        "enabled": True,
        "stats_dir": "data/stats",  # persistent real-camera aggregates, separate from run logs
        "url": None,               # full public /public/ URL for printed QR codes (HTTPS gateway)
        "demo": None,              # auto: simulator/render/video data is isolated per run
        "mock_month": False,       # enabled by tools/sim_run.py only, never on real sources
    },
    "mcu": {
        "enabled": "auto",         # auto: virtual fallback; true: require router socket; false: virtual
        "socket": "/var/run/arduino-router.sock",
        "heartbeat_s": 0.5,
        "vision_timeout_s": 1.5,   # no fresh camera frame for this long -> stop the heartbeat (lamps fail safe)
        "matrix_hz": 4.0,
    },
    "server": {
        "enabled": True,
        "host": "0.0.0.0",
        "port": 8000,
        "stream_hz": 10.0,
        "mjpeg": True,
        "mjpeg_fps": 5.0,
        "privacy_blur": True,
        "background_every_s": 5.0,
        "bev_px_per_m": 20.0,
    },
    "log": {
        "dir": "runs",
        "save_tracks": True,
        "replay_before_s": 6.0,
        "replay_after_s": 3.0,
    },
}


class Cfg(dict):
    """dict with attribute access (recursive)."""

    def __getattr__(self, k):
        try:
            v = self[k]
        except KeyError as e:
            raise AttributeError(k) from e
        return v

    def __setattr__(self, k, v):
        self[k] = v

    @staticmethod
    def wrap(obj):
        if isinstance(obj, Cfg):
            return obj
        if isinstance(obj, dict):
            return Cfg({k: Cfg.wrap(v) for k, v in obj.items()})
        if isinstance(obj, list):
            return [Cfg.wrap(v) for v in obj]
        return obj

    def to_plain(self):
        def unwrap(o):
            if isinstance(o, dict):
                return {k: unwrap(v) for k, v in o.items()}
            if isinstance(o, list):
                return [unwrap(v) for v in o]
            return o

        return unwrap(self)


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _load_file(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    if path.endswith((".yaml", ".yml")):
        import yaml  # pyyaml

        data = yaml.safe_load(text) or {}
    else:
        data = json.loads(text)
    # support "include: other.yaml" for small per-site overrides
    inc = data.pop("include", None)
    if inc:
        inc_path = inc if os.path.isabs(inc) else os.path.join(os.path.dirname(path), inc)
        data = deep_merge(_load_file(inc_path), data)
    return data


def set_dotted(d: dict, dotted: str, value):
    keys = dotted.split(".")
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value


def parse_override(s: str):
    """'detector.imgsz=256' -> ('detector.imgsz', 256)"""
    k, v = s.split("=", 1)
    try:
        val = json.loads(v)
    except json.JSONDecodeError:
        val = v
    return k.strip(), val


def load_config(path: str | None = None, overrides: list[str] | None = None) -> Cfg:
    data = copy.deepcopy(DEFAULTS)
    if path:
        data = deep_merge(data, _load_file(path))
    for o in overrides or []:
        k, v = parse_override(o)
        set_dotted(data, k, v)
    return Cfg.wrap(data)


def save_config(cfg: dict, path: str):
    plain = cfg.to_plain() if isinstance(cfg, Cfg) else cfg
    with open(path, "w", encoding="utf-8") as f:
        if path.endswith((".yaml", ".yml")):
            import yaml

            yaml.safe_dump(plain, f, sort_keys=False)
        else:
            json.dump(plain, f, indent=2)
