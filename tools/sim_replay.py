"""Evaluate the production node on cached L2 pixels (open-loop, no renderer)."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crosswalk.config import Cfg, load_config
from crosswalk.pipeline import Node
from sim.cache_source import CacheSource
from sim.detection_eval import DetectionEvaluator, RecordingDetector
from sim.evaluation import check_expectations, evaluate_events, write_html
from sim.repro import file_hash


def replay(cache, config, overrides=(), allow_partial=False):
    cfg = load_config(config, list(overrides))
    if cfg.get("sim", {}).get("presentation_mode"):
        raise ValueError("evaluation refuses presentation_mode")
    if cfg.detector.backend not in ("onnx", "ncnn", "tflite", "ultralytics"):
        raise ValueError("cached L2 requires the real detector")
    source = CacheSource(cache, require_scenario_complete=not allow_partial)
    cfg.scene = Cfg.wrap(source.metadata["scene"])
    cfg.scene.calibration.update(source.calibration())
    cfg.server.enabled, cfg.mcu.enabled, cfg.log.dir, cfg.source.type = False, False, "", "cache"
    if not any(o.startswith("signal.mode=") for o in overrides):
        mode = source.metadata.get("control", {}).get("mode")
        cfg.signal.mode = mode if mode in ("beacon", "fixed", "adaptive") else source.spec.get("signal_mode", "beacon")
    scorer, events = DetectionEvaluator(cfg.detector.conf), []
    started = time.perf_counter()
    try:
        node = Node(cfg, source=source)
    except Exception:
        source.close()
        raise
    node.detector = RecordingDetector(node.detector, source, scorer)
    node.bus.subscribe(lambda m: events.append({k: v for k, v in m["event"].items() if k != "wall"}) if m["type"] == "event" else None)
    try:
        while node.step():
            pass
    finally:
        node.close()
    truth = json.loads((source.path / "ground_truth.json").read_text(encoding="utf-8"))
    result = {"scenario": source.spec["name"], "level": "L2", "execution": "cached-open-loop", "seed": source.metadata["seed"],
              "scenario_hash": source.metadata["scenario_hash"], "model_hash": file_hash(cfg.detector.model),
              "config": cfg.to_plain(), "cache": str(source.path), "cache_content_hash": source.content_hash,
              "render": source.metadata, "duration_s": node.t, "frames": node.frames,
              "wall_seconds": time.perf_counter() - started, "events": events, "ground_truth": truth["events"],
              "metrics": evaluate_events(events, truth["events"]), "detection": scorer.summarize(node.t),
              "frame_results": scorer.frames, "source": source.stats(), "signal": node.signal.to_dict(),
              "limitations": ["Recorded trajectories do not react to replayed signal commands. Use a new closed-loop render for policy comparisons."]}
    # No signal certification on immutable trajectories, even if count checks pass.
    expected = {k: v for k, v in source.spec["expected"].items() if k in ("counts", "directions", "min_passages")}
    result["checks"] = check_expectations(result, expected) if source.metadata.get("scenario_complete") else []
    result["gates"] = {"G2": "pending representative real site reference", "G5": "pending comparable real count GT",
                       "G6": "open-loop detector/count configuration comparison only; changed signal policy requires closed-loop runs"}
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cache", type=Path)
    ap.add_argument("--config", default=str(ROOT / "configs/board.yaml"))
    ap.add_argument("--set", action="append", default=[])
    ap.add_argument("--allow-partial", action="store_true")
    ap.add_argument("--out", type=Path, default=ROOT / "runs/replay")
    args = ap.parse_args()
    result = replay(args.cache, args.config, args.set, args.allow_partial)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "results.json").write_text(json.dumps([result], indent=2), encoding="utf-8")
    write_html(args.out / "report.html", [result])
    print(f"{result['frames']} cached frames in {result['wall_seconds']:.2f}s; count accuracy {result['metrics']['count_accuracy']:.1%}")
    print(f"Open-loop report: {args.out / 'report.html'}")
    return int(any(not c["passed"] for c in result["checks"]))


if __name__ == "__main__":
    raise SystemExit(main())
