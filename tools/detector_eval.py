"""Score the real board detector on reviewed YOLO-format site labels, exactly as L2.

Use a uniformly sampled set including empty frames. Random train/val splitting and
autolabel.py's default negative downsampling bias FP/min; they are not a G2 reference.
"""
import argparse
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2
import yaml

from crosswalk.config import load_config
from crosswalk.detectors import create_detector
from sim.detection_eval import DetectionEvaluator
from sim.repro import file_hash


def load_yolo_labels(path, names, width, height):
    if not path.exists():
        raise FileNotFoundError(f"missing label file {path}; empty frames need an empty .txt file")
    labels = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        values = list(map(float, line.split()))
        if len(values) != 5 or not all(math.isfinite(v) for v in values) or int(values[0]) != values[0]:
            raise ValueError(f"invalid YOLO detection label in {path}")
        cls, cx, cy, w, h = values
        if not all(math.isfinite(v) for v in values) or min(w, h) <= 0 or not all(0 <= v <= 1 for v in (cx, cy, w, h)):
            raise ValueError(f"invalid normalized box in {path}")
        if int(cls) < 0 or (int(cls) not in names if isinstance(names, dict) else int(cls) >= len(names)):
            raise ValueError(f"unknown class index in {path}")
        labels.append({"cls": names[int(cls)], "box": [(cx - w / 2) * width, (cy - h / 2) * height,
                                                      (cx + w / 2) * width, (cy + h / 2) * height]})
    return labels


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True, help="reviewed dataset's data.yaml")
    ap.add_argument("--split", default="val", choices=["train", "val", "test"])
    ap.add_argument("--condition", default="day:clear")
    ap.add_argument("--sample-hz", type=float, required=True, help="uniform sampling rate of this labelled set")
    ap.add_argument("--representative", action="store_true", help="assert all sampled frames, including negatives, are retained")
    ap.add_argument("--label-policy", choices=["visible", "amodal"], required=True)
    ap.add_argument("--config", default=str(ROOT / "configs/board.yaml"))
    ap.add_argument("--set", action="append", default=[])
    ap.add_argument("--out", type=Path, default=ROOT / "runs/detection-real.json")
    args = ap.parse_args()
    if not math.isfinite(args.sample_hz) or args.sample_hz <= 0:
        ap.error("sample-hz must be positive and finite")
    metadata = yaml.safe_load(args.data.read_text(encoding="utf-8"))
    dataset = (args.data.resolve().parent / Path(metadata.get("path", "."))).resolve()
    names = metadata["names"]
    if isinstance(names, dict):
        names = {int(k): v for k, v in names.items()}
    images = dataset / metadata[args.split]
    if not images.is_dir():
        raise ValueError("this evaluator accepts YOLO image directories, not image-list files")
    cfg = load_config(args.config, args.set)
    if cfg.detector.backend not in ("onnx", "ncnn", "tflite", "ultralytics"):
        ap.error("a real detector backend is required")
    scorer = DetectionEvaluator(cfg.detector.conf)
    detector = create_detector(cfg.detector)
    sample_hashes = {}
    paths = sorted(p for p in images.rglob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    if not paths:
        raise ValueError("no labelled images")
    for i, path in enumerate(paths):
        image = cv2.imread(str(path))
        if image is None:
            raise ValueError(f"cannot decode {path}")
        h, w = image.shape[:2]
        label_path = dataset / "labels" / args.split / path.relative_to(images).with_suffix(".txt")
        labels = load_yolo_labels(label_path, names, w, h)
        predictions = [d.to_dict() for d in detector(image)]
        scorer.observe((i + 1) / args.sample_hz, labels, predictions, args.condition, [w, h])
        sample_hashes[path.relative_to(images).as_posix()] = {"image": file_hash(path), "label": file_hash(label_path)}
    report = {"domain": "real", "level": "real-labelled", "model_hash": file_hash(cfg.detector.model),
              "config": cfg.to_plain(), "sampling": {"hz": args.sample_hz, "representative": args.representative},
              "label_policy": args.label_policy, "data": str(args.data.resolve()), "sample_hashes": sample_hashes,
              "detection": scorer.summarize(len(paths) / args.sample_hz), "frame_results": scorer.frames}
    report["detection"]["box_policy"] = f"reviewed {args.label_policy} YOLO labels"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"scored {len(paths)} frames; report: {args.out}")


if __name__ == "__main__":
    main()
