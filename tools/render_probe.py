"""Render an L2 detector spike, recording RGB/masks, raw predictions and per-bin recall."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2

from crosswalk.config import load_config
from crosswalk.detectors import create_detector
from sim.detection_eval import DetectionEvaluator
from sim.render_source import RenderSource
from sim.runner import file_hash


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default="driver_yields")
    parser.add_argument("--config", default=str(ROOT / "configs/board.yaml"))
    parser.add_argument("--frames", type=int, default=50)
    parser.add_argument("--fps", type=float, default=5)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--set", action="append", default=[])
    parser.add_argument("--out", type=Path, default=ROOT / "runs/render-probe")
    args = parser.parse_args()
    if args.frames <= 0:
        parser.error("--frames must be positive")
    cfg = load_config(args.config, args.set)
    if cfg.get("sim", {}).get("presentation_mode", False):
        parser.error("evaluation refuses presentation_mode")
    if cfg.detector.backend not in ("onnx", "ncnn", "ultralytics", "tflite"):
        parser.error("a real detector backend is required")
    cfg.setdefault("sim", {})["render_cache"] = str(args.out / "cache")
    detector = create_detector(cfg.detector)
    source = RenderSource(cfg, args.scenario, args.seed, args.fps)
    scorer = DetectionEvaluator(cfg.detector.conf)
    condition = source.spec["conditions"]
    condition_key = f"{condition['time_of_day']}:{condition['weather']}"
    result = {}
    try:
        for i in range(args.frames):
            image, t, seq = source.read()
            predictions = [d.to_dict() for d in detector(image)]
            scorer.observe(t, source.frame_meta["boxes"], predictions, condition_key, [source.width, source.height])
            if i in (0, args.frames // 2, args.frames - 1):
                annotated = image.copy()
                for label in source.frame_meta["boxes"]:
                    if label["box"]:
                        x0, y0, x1, y1 = label["box"]
                        cv2.rectangle(annotated, (x0, y0), (x1, y1), (40, 190, 60), 1)
                for p in predictions:
                    x0, y0, x1, y1 = map(int, p["box"])
                    cv2.rectangle(annotated, (x0, y0), (x1, y1), (35, 85, 240), 1)
                    cv2.putText(annotated, f"{p['cls']} {p['score']:.2f}", (x0, max(12, y0 - 3)), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (35, 85, 240), 1)
                cv2.imwrite(str(args.out / f"probe-{seq:03d}.jpg"), annotated)
            if i % 10 == 0:
                print(f"rendered {i + 1}/{args.frames}, sim t={t:.1f}s", flush=True)
        result = {"domain": "synthetic", "level": "L2", "seed": args.seed, "model_hash": file_hash(cfg.detector.model),
                  "config": cfg.to_plain(), "render": source.cache_metadata, "performance": source.stats(),
                  "detection": scorer.summarize(source.world.t), "frame_results": scorer.frames,
                  "G2": "UNASSESSED: no real-site teacher-labelled comparison supplied",
                  "control": "detector-only spike, unsignalised World; not a closed-loop pipeline run"}
        (args.out / "probe.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    finally:
        source.close()
    for key, row in result["detection"]["bins"].items():
        recall = f"{row['recall']:.1%}" if row["recall"] is not None else "n/a"
        print(f"{key}: recall {recall}, GT={row['gt']}, matched={row['matched_gt']}")
    print("report:", args.out / "probe.json")


if __name__ == "__main__":
    main()
