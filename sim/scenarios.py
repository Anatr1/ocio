"""Seeded scenario presets and validated YAML scenario specifications."""

import copy
import hashlib
import json
import math
import re
from pathlib import Path

from crosswalk.config import deep_merge

SCENARIOS = {
    "mixed": {
        "rates": {"pedestrian": 9, "car": 14, "bicycle": 2, "bike_cross": 1.5, "e-scooter": 0.5, "child": 0.6},
        "yield_p": 0.72, "speeder_p": 0.12, "risky_ped_p": 0.004, "elderly_p": 0.12, "jaywalk_p": 0.05,
        "car_speed": 12.0,
    },
    "quiet": {
        "rates": {"pedestrian": 3, "car": 5, "bicycle": 1, "bike_cross": 0.3},
        "yield_p": 0.85, "speeder_p": 0.05, "elderly_p": 0.1, "car_speed": 11.0,
    },
    "rush": {
        "rates": {"pedestrian": 22, "car": 26, "bicycle": 4, "bike_cross": 3, "e-scooter": 1, "child": 1},
        "yield_p": 0.65, "speeder_p": 0.1, "risky_ped_p": 0.006, "elderly_p": 0.1, "jaywalk_p": 0.06,
        "car_speed": 10.0,
    },
    "dangerous": {
        "rates": {"pedestrian": 8, "car": 16, "bicycle": 1, "bike_cross": 1, "e-scooter": 0.3},
        "yield_p": 0.35, "speeder_p": 0.35, "risky_ped_p": 0.02, "elderly_p": 0.15, "car_speed": 13.5,
        "caution_p": 0.6,  # many people step out without checking the lane: conflicts for the safety demo
    },
    "elderly": {
        "rates": {"pedestrian": 7, "car": 9},
        "yield_p": 0.8, "elderly_p": 0.6, "car_speed": 11.0,
    },
    "count_test": {  # for counting accuracy: moderate density, mixed classes, no jaywalkers
        "rates": {"pedestrian": 10, "car": 12, "bicycle": 3, "bike_cross": 2, "e-scooter": 0.5},
        "yield_p": 0.8, "speeder_p": 0.08, "elderly_p": 0.1, "car_speed": 11.5,
    },
}


def catalogue():
    import yaml

    path = Path(__file__).with_name("scenarios") / "catalogue.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8"))["scenarios"]


def load_scenario(value="mixed", _seen=()):
    """Resolve a preset, catalogue entry, YAML path, or already parsed specification."""
    if isinstance(value, dict):
        spec = copy.deepcopy(value)
    else:
        path = Path(value)
        if path.is_file():
            import yaml

            spec = yaml.safe_load(path.read_text(encoding="utf-8"))
        elif value in SCENARIOS:
            spec = {"name": value, **copy.deepcopy(SCENARIOS[value])}
        elif value in catalogue():
            spec = {"name": value, **catalogue()[value]}
        else:
            raise ValueError(f"unknown scenario: {value}")
    if not isinstance(spec, dict):
        raise ValueError("scenario must be a mapping")
    base = spec.pop("base", None)
    if base:
        if str(base) in _seen:
            raise ValueError("cyclic scenario inheritance")
        spec = deep_merge(load_scenario(base, (*_seen, str(base))), spec)
    spec.setdefault("name", "custom")
    spec.setdefault("duration_s", 45.0)
    spec["conditions"] = {"time_of_day": "day", "weather": "clear", **spec.get("conditions", {})}
    if spec["conditions"]["time_of_day"] not in ("day", "dusk", "night", "low_sun") or spec["conditions"]["weather"] not in ("clear", "rain", "fog"):
        raise ValueError("unsupported time_of_day or weather")
    shake = float(spec["conditions"].get("shake_px", 0))
    if not math.isfinite(shake) or shake < 0:
        raise ValueError("shake_px must be nonnegative and finite")
    spec.setdefault("rates", {})
    spec.setdefault("expected", {})
    if not re.fullmatch(r"[A-Za-z0-9_-]+", spec["name"]):
        raise ValueError("scenario name must be a simple filename component")
    if not math.isfinite(float(spec.get("physics_dt", 0.05))) or float(spec.get("physics_dt", 0.05)) <= 0:
        raise ValueError("physics_dt must be positive and finite")
    for name in ("yield_p", "speeder_p", "risky_ped_p", "elderly_p", "jaywalk_p", "red_violation_p", "vehicle_red_p",
                 "caution_p"):
        if name in spec and not 0 <= float(spec[name]) <= 1:
            raise ValueError(f"{name} must be a probability")
    for name, rate in spec["rates"].items():
        if not math.isfinite(float(rate)) or float(rate) < 0:
            raise ValueError(f"invalid arrival rate for {name}")
    if not math.isfinite(float(spec["duration_s"])) or float(spec["duration_s"]) <= 0:
        raise ValueError("duration_s must be positive and finite")
    script = []
    for item in spec.get("script", []):
        if isinstance(item, dict):
            t, cls = float(item.get("t", 0)), item["cls"]
            params = {k: v for k, v in item.items() if k not in ("t", "cls")}
        else:
            t, cls, params = item
            t, params = float(t), dict(params)
        if t < 0 or not math.isfinite(t):
            raise ValueError("script time must be nonnegative and finite")
        for key in ("v", "reaction"):
            if key in params and (not math.isfinite(float(params[key])) or float(params[key]) < 0):
                raise ValueError(f"invalid {key} for {cls}")
        for key in ("side", "dir"):
            if key in params and params[key] not in (-1, 1):
                raise ValueError(f"{key} must be -1 or +1")
        for key in ("x", "y", "x0", "cross_x", "exit_x"):
            if key in params and not math.isfinite(float(params[key])):
                raise ValueError(f"{key} must be finite")
        if "n" in params and (int(params["n"]) != params["n"] or int(params["n"]) < 1):
            raise ValueError("n must be a positive integer")
        if params.get("route", "crossing") not in ("crossing", "road", "sidewalk"):
            raise ValueError("route must be crossing, road or sidewalk")
        script.append((t, cls, params))
    spec["script"] = sorted(script, key=lambda item: item[0])
    return spec


def scenario_hash(spec):
    return hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
