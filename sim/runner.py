"""Run the production logic at L0, or the production node at L1/L2."""
from __future__ import annotations

import json
import math
import platform
import time
from pathlib import Path

from crosswalk.config import Cfg, deep_merge, load_config
from crosswalk.counting import Counter
from crosswalk.safety import SafetyMonitor
from crosswalk.scene import Scene
from crosswalk.signal import SignalController
from .evaluation import check_expectations, evaluate_events
from .detection_eval import DetectionEvaluator, RecordingDetector
from .gt import GroundTrack
from .repro import file_hash, implementation_stamp, json_hash
from .scenarios import load_scenario, scenario_hash
from .temporal import TemporalEvaluator
from .world import World


def run_scenario(scenario, level="L1", seed=0, config=None, overrides=(), fps=15.0, duration=None):
    spec = load_scenario(scenario)
    cfg = load_config(config, list(overrides))
    if cfg.get("sim", {}).get("presentation_mode", False) or spec.get("presentation_mode", False):
        raise ValueError("evaluation refuses presentation_mode")
    cfg.scene = Cfg.wrap(deep_merge(cfg.scene, spec.get("scene", {})))
    cfg.server.enabled, cfg.mcu.enabled, cfg.log.dir = False, False, ""
    if not any(o.startswith("signal.mode=") for o in overrides):
        cfg.signal.mode = spec.get("signal_mode", "beacon")
    seconds = float(spec["duration_s"] if duration is None else duration)
    if not math.isfinite(fps) or not math.isfinite(seconds) or fps <= 0 or seconds <= 0:
        raise ValueError("fps and duration must be positive and finite")
    events, identity = [], {}
    scorer = None
    track_lookup = lambda: []

    def record_event(event):
        e = dict(event)
        e.pop("wall", None)  # Wall-clock labels are not part of deterministic sim-time evidence.
        if e["type"] == "passage" and not e.get("dir"):
            tr = next((tr for tr in track_lookup() if tr.id == e["track"]), None)
            if tr is not None:
                if tr.kind == "vehicle" or abs(tr.vel[0]) > 1.5 * abs(tr.vel[1]):
                    e["dir"] = "+X" if tr.vel[0] > 0 else "-X"
                else:
                    e["dir"] = "A>B" if tr.vel[1] > 0 else "B>A"
        events.append(e)
    clock = time.perf_counter()
    if level == "L0":
        scene = Scene(cfg.scene, tracker_cfg=cfg.tracker)
        signal = SignalController(cfg.signal, scene, events.append)
        world = World(cfg.scene, spec, seed, signal, cfg)
        counter = Counter(scene, cfg.counting, record_event)
        safety = SafetyMonitor(scene, cfg.safety, events.append, signal.mode)
        temporal = TemporalEvaluator(scene, cfg.safety)
        traces, dead = {}, []
        track_lookup = lambda: list(traces.values()) + dead[-200:]
        frames = 0
        while world.t < seconds - 1e-8:
            world.step(min(1 / fps, seconds - world.t))
            ended = []
            live_ids = {a.id for a in world.agents}
            for aid in list(traces):
                if aid not in live_ids:
                    tr = traces.pop(aid)
                    tr.state = "ended"
                    ended.append(tr)
                    dead.append(tr)
            for a in world.agents:
                if a.id in traces:
                    traces[a.id].update(a, world.t)
                else:
                    traces[a.id] = GroundTrack(a, world.t)
                identity[a.id] = a.id
            live = list(traces.values())
            counter.update(world.t, live, ended)
            safety.exposure = counter.counts["vehicle"]
            safety.update(world.t, live, ended, signal, dead[-200:])
            vehicle_close = any(tr.kind == "vehicle" and tr.speed > 1.5 and
                                0 < abs(tr.pos[0]) - scene.W / 2 < 3 * tr.speed and
                                tr.pos[0] * tr.vel[0] < 0 for tr in live)
            signal.update(world.t, safety.vru_waiting, safety.vru_crossing, safety.max_time_to_clear, vehicle_close)
            temporal.observe(world.t, live, safety, identity, signal)
            frames += 1
        source, node = None, None
    else:
        from crosswalk.pipeline import Node

        if level == "L1":
            from .source import SimSource

            cfg.detector.backend = "sim"
            # Headless L1 tests detector errors, not image-based motion gating.
            cfg.detector.motion_gate = False
            source = SimSource(cfg, spec, seed, realtime=False, fps=fps, render=False)
        elif level == "L2":
            from .render_source import RenderSource

            if cfg.detector.backend not in ("onnx", "ncnn", "tflite", "ultralytics"):
                raise ValueError("L2 requires a real detector backend")
            source = RenderSource(cfg, spec, seed, fps=fps)
        else:
            raise ValueError("level must be L0, L1 or L2")
        cfg.source.type = "sim" if level == "L1" else "render"
        if not cfg.scene.calibration.get("image_points") and not cfg.scene.calibration.get("H"):
            cfg.scene.calibration.update(source.calibration())
        try:
            node = Node(cfg, source=source)
        except Exception:
            source.close()
            raise
        world = source.world
        if level == "L2":
            scorer = DetectionEvaluator(cfg.detector.conf)
            node.detector = RecordingDetector(node.detector, source, scorer)
        if hasattr(source, "bind_signal"):
            source.bind_signal(node.signal)
        else:
            world.signal = node.signal
        temporal = TemporalEvaluator(node.scene, cfg.safety)
        track_lookup = lambda: node.tracker.tracks + list(node.tracker.dead)
        node.bus.subscribe(lambda message: record_event(message["event"]) if message["type"] == "event" else None)
        try:
            while world.t < seconds - 1e-8:
                if not node.step():
                    raise RuntimeError("source ended before the scenario duration")
                if level == "L1":
                    for tr in node.tracker.tracks:
                        if tr.gt_id is not None:
                            identity[tr.id] = tr.gt_id
                else:
                    from scipy.optimize import linear_sum_assignment
                    import numpy as np

                    tracks, agents = node.tracker.confirmed(), world.agents
                    if tracks and agents:
                        cost = np.array([[np.hypot(tr.pos[0] - a.x, tr.pos[1] - a.y)
                                          if tr.kind == a.kind else 1e6 for a in agents] for tr in tracks])
                        for i, j in zip(*linear_sum_assignment(cost)):
                            if cost[i, j] < 3.0:
                                identity.setdefault(tracks[i].id, agents[j].id)
                temporal.observe(world.t, node.tracker.tracks, node.safety, identity, node.signal)
            frames = node.frames
            counter, safety, signal = node.counter, node.safety, node.signal
        finally:
            node.close()
    detector_hash = file_hash(cfg.detector.model) if level == "L2" else None
    result = {"scenario": spec["name"], "level": level, "seed": seed,
              "scenario_hash": scenario_hash(spec), "model_hash": detector_hash,
              "config": cfg.to_plain(), "config_hash": json_hash(cfg.to_plain()), "implementation": implementation_stamp(),
              "python": platform.python_version(),
              "duration_s": world.t, "frames": frames,
              "wall_seconds": time.perf_counter() - clock,
              "events": events, "ground_truth": world.gt_events,
              "signal": signal.to_dict(), "safety": safety.stats(),
              "actual_pedestrian_waits": world.wait_times,
              "temporal": temporal.evaluate(world.truth.frames, world.t),
              "metrics": evaluate_events(events, world.gt_events),
              "gates": {"G2": "pending real site data", "G3": "pending fitted noise", "G4": "literature defaults; site validation pending",
                        "G5": "pending real site data", "G6": "pending matched configuration sweep"}}
    if source is not None:
        result["source"] = source.stats()
        if level == "L2":
            result["render"] = source.cache_metadata
            result["cache"] = str(source.cache) if source.cache else None
            result["detection"] = scorer.summarize(world.t)
            result["frame_results"] = scorer.frames
    predicted_pairs = {(identity.get(e["vru"], f"unknown-{e['vru']}"), identity.get(e["veh"], f"unknown-{e['veh']}"))
                       for e in events if e["type"] == "conflict"}
    true_pairs = {p for p, ttc in world.pairs_min_ttc.items() if ttc <= 3}
    serious = {p for p, ttc in world.pairs_min_ttc.items() if ttc <= 2}
    result["metrics"]["conflicts"] = {
        "precision": len(predicted_pairs & true_pairs) / len(predicted_pairs) if predicted_pairs else None,
        "recall_serious": len(predicted_pairs & serious) / len(serious) if serious else None,
        "predicted_pairs": len(predicted_pairs), "gt_pairs": len(true_pairs)}
    result["checks"] = check_expectations(result, spec["expected"])
    return result
