"""Auto-label on-site footage with a big teacher model -> YOLO dataset for fine-tuning the tiny on-board model.

Teacher-student distillation: a large COCO model (GPU) labels person/bicycle/car/motorcycle/bus/truck, and an
optional open-vocabulary model (YOLO-World) adds classes COCO doesn't have (e-scooter, wheelchair, stroller).
The nano student, fine-tuned on frames from OUR camera at OUR viewing angle, is then exported for the UNO Q.

    python tools/autolabel.py --src data/recordings --out datasets/xw --every 1.0
    python tools/autolabel.py --src data/recordings --out datasets/xw --open-vocab      # + e-scooter / wheelchair / stroller
    python tools/autolabel.py --src data/recordings/frames --out datasets/xw --teacher yolo11x.pt
Then review / fix labels (Roboflow: upload the dataset folder as "YOLO" format, or open the preview sheets in
datasets/xw/preview/), and train:  python tools/train.py --data datasets/xw/data.yaml
"""
from __future__ import annotations

import argparse
import glob
import os
import random
import sys

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

NAMES = ["person", "bicycle", "car", "motorcycle", "bus", "truck", "e-scooter", "wheelchair", "stroller"]
COCO_MAP = {0: 0, 1: 1, 2: 2, 3: 3, 5: 4, 7: 5}  # coco id -> our id
OPEN_VOCAB = {"electric scooter": 6, "kick scooter": 6, "wheelchair": 7, "baby stroller": 8}


def iter_frames(src, every):
    paths = []
    if os.path.isdir(src):
        imgs = sorted(glob.glob(os.path.join(src, "**", "*.jpg"), recursive=True) + glob.glob(os.path.join(src, "**", "*.png"), recursive=True))
        vids = sorted(glob.glob(os.path.join(src, "**", "*.mp4"), recursive=True) + glob.glob(os.path.join(src, "**", "*.avi"), recursive=True))
    else:
        imgs, vids = ([src], []) if src.lower().endswith((".jpg", ".png")) else ([], [src])
    for p in imgs:
        f = cv2.imread(p)
        if f is not None:
            yield os.path.splitext(os.path.basename(p))[0], f
    for v in vids:
        cap = cv2.VideoCapture(v)
        fps = cap.get(cv2.CAP_PROP_FPS) or 15
        step = max(1, int(round(every * fps)))
        i = 0
        base = os.path.splitext(os.path.basename(v))[0]
        while True:
            ok = cap.grab()
            if not ok:
                break
            if i % step == 0:
                ok, f = cap.retrieve()
                if ok:
                    yield f"{base}_{i:06d}", f
            i += 1
        cap.release()
    return paths


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    return inter / max(1e-9, (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", default=os.path.join(ROOT, "datasets", "xw"))
    ap.add_argument("--teacher", default="yolo11x.pt")
    ap.add_argument("--open-vocab", action="store_true")
    ap.add_argument("--ov-model", default="yolov8x-worldv2.pt")
    ap.add_argument("--every", type=float, default=1.0, help="seconds between sampled video frames")
    ap.add_argument("--conf", type=float, default=0.35)
    ap.add_argument("--imgsz", type=int, default=960)
    ap.add_argument("--val", type=float, default=0.15)
    ap.add_argument("--keep-empty", type=float, default=0.15, help="fraction of empty frames to keep (negatives)")
    ap.add_argument("--max", type=int, default=5000)
    args = ap.parse_args()

    from ultralytics import YOLO

    teacher = YOLO(args.teacher)
    ov = None
    if args.open_vocab:
        ov = YOLO(args.ov_model)
        ov.set_classes(list(OPEN_VOCAB.keys()))
    for sub in ("images/train", "images/val", "labels/train", "labels/val", "preview"):
        os.makedirs(os.path.join(args.out, sub), exist_ok=True)
    rng = random.Random(0)
    n = n_obj = 0
    sheet = []
    for name, f in iter_frames(args.src, args.every):
        if n >= args.max:
            break
        h, w = f.shape[:2]
        r = teacher.predict(f, imgsz=args.imgsz, conf=args.conf, classes=list(COCO_MAP.keys()), verbose=False)[0]
        boxes = []
        if r.boxes is not None:
            for (x1, y1, x2, y2), c, s in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.cls.cpu().numpy().astype(int), r.boxes.conf.cpu().numpy()):
                boxes.append([COCO_MAP[c], x1, y1, x2, y2, float(s)])
        if ov is not None:
            r2 = ov.predict(f, imgsz=args.imgsz, conf=0.25, verbose=False)[0]
            names = list(OPEN_VOCAB.keys())
            if r2.boxes is not None:
                for (x1, y1, x2, y2), c, s in zip(r2.boxes.xyxy.cpu().numpy(), r2.boxes.cls.cpu().numpy().astype(int), r2.boxes.conf.cpu().numpy()):
                    cid = OPEN_VOCAB[names[c]]
                    b = [cid, x1, y1, x2, y2, float(s)]
                    # an e-scooter overlapping a detected bicycle is probably a bicycle: skip
                    if any(o[0] == 1 and iou(o[1:5], b[1:5]) > 0.5 for o in boxes):
                        continue
                    boxes.append(b)
        if not boxes and rng.random() > args.keep_empty:
            continue
        split = "val" if rng.random() < args.val else "train"
        cv2.imwrite(os.path.join(args.out, "images", split, name + ".jpg"), f)
        with open(os.path.join(args.out, "labels", split, name + ".txt"), "w") as lf:
            for cid, x1, y1, x2, y2, _ in boxes:
                lf.write(f"{cid} {(x1 + x2) / 2 / w:.6f} {(y1 + y2) / 2 / h:.6f} {(x2 - x1) / w:.6f} {(y2 - y1) / h:.6f}\n")
        n += 1
        n_obj += len(boxes)
        if len(sheet) < 16 and boxes and rng.random() < 0.3:
            vis = f.copy()
            for cid, x1, y1, x2, y2, s in boxes:
                cv2.rectangle(vis, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 255), 2)
                cv2.putText(vis, f"{NAMES[cid]} {s:.2f}", (int(x1), int(y1) - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
            sheet.append(cv2.resize(vis, (480, 300)))
        if n % 100 == 0:
            print(f"{n} images, {n_obj} boxes")
    with open(os.path.join(args.out, "data.yaml"), "w") as f:
        f.write(f"path: {os.path.abspath(args.out)}\ntrain: images/train\nval: images/val\nnames:\n")
        for i, nm in enumerate(NAMES):
            f.write(f"  {i}: {nm}\n")
    if sheet:
        rows = [np.hstack(sheet[i:i + 4]) for i in range(0, len(sheet) - len(sheet) % 4, 4)]
        if rows:
            cv2.imwrite(os.path.join(args.out, "preview", "sheet.jpg"), np.vstack(rows))
    print(f"done: {n} images, {n_obj} boxes -> {args.out}/data.yaml")


if __name__ == "__main__":
    main()
