"""Fine-tune the nano detector on the auto-labelled site dataset (run on an L40S / any CUDA box), then export.

    python tools/train.py --data datasets/xw/data.yaml                       # yolo26n, 320 px, 80 epochs
    python tools/train.py --data datasets/xw/data.yaml --model yolo11n.pt --imgsz 416 --epochs 120

On 1-3k images an L40S finishes 80 epochs at 320 px in ~10 minutes. Outputs models/<name>_<imgsz>.onnx (+int8, +ncnn)
ready for tools/bench.py on the board. Fine-tuning at the deployment viewpoint is what makes a 2.5 MB model accurate.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--model", default="yolo26n.pt")
    ap.add_argument("--imgsz", type=int, default=320)
    ap.add_argument("--epochs", type=int, default=80)
    ap.add_argument("--batch", type=int, default=128)
    ap.add_argument("--name", default="xw")
    ap.add_argument("--device", default="0")
    ap.add_argument("--no-export", action="store_true")
    args = ap.parse_args()

    from ultralytics import YOLO

    model = YOLO(args.model)
    res = model.train(
        data=args.data, imgsz=args.imgsz, epochs=args.epochs, batch=args.batch, device=args.device,
        project=os.path.join(ROOT, "runs", "train"), name=args.name, exist_ok=True,
        patience=25, cos_lr=True, close_mosaic=10,
        # the camera is fixed: geometric augmentation light, photometric augmentation strong (day/night/rain)
        degrees=0.0, shear=0.0, perspective=0.0, flipud=0.0, fliplr=0.5, scale=0.5, translate=0.1,
        hsv_h=0.015, hsv_s=0.6, hsv_v=0.5, mosaic=1.0, mixup=0.05,
    )
    best = os.path.join(ROOT, "runs", "train", args.name, "weights", "best.pt")
    print("best weights:", best)
    m = YOLO(best)
    metrics = m.val(data=args.data, imgsz=args.imgsz, device=args.device)
    print("mAP50-95:", getattr(metrics.box, "map", None), "mAP50:", getattr(metrics.box, "map50", None))
    dst = os.path.join(ROOT, "models", f"{args.name}.pt")
    shutil.copy(best, dst)
    if not args.no_export:
        subprocess.run([sys.executable, os.path.join(ROOT, "tools", "export_models.py"), "--weights", dst, "--name", args.name,
                        "--sizes", str(args.imgsz), "--ncnn-sizes", str(args.imgsz), "--int8-onnx"], check=False)


if __name__ == "__main__":
    main()
