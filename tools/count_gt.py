"""Fast manual ground truth: play a video and press a key every time somebody passes through the crosswalk.

    python tools/count_gt.py data/recordings/rec_X.mp4            # -> rec_X.gt.csv
    python tools/count_gt.py rec.mp4 --speed 2                     # play at 2x (counting is easy for humans)

Keys:  p = pedestrian   b = bicycle   s = e-scooter   c = car/vehicle   m = motorcycle   u = bus/truck
       z = undo last    SPACE = pause  , . = back/forward 2 s   + - = speed   q = save & quit
Press the key when the road user crosses the middle line of the crosswalk (same definition as the counter).
Then: python tools/eval_counts.py --video rec_X.mp4 --gt rec_X.gt.csv --config configs/site.yaml
"""
from __future__ import annotations

import argparse
import csv
import os

import cv2

KEYS = {ord("p"): ("pedestrian", "pedestrian"), ord("b"): ("bicycle", "bicycle"),
        ord("s"): ("micromobility", "e-scooter"), ord("c"): ("vehicle", "car"),
        ord("m"): ("vehicle", "motorcycle"), ord("u"): ("vehicle", "bus")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--out", default=None)
    ap.add_argument("--speed", type=float, default=1.0)
    args = ap.parse_args()
    out = args.out or os.path.splitext(args.video)[0] + ".gt.csv"
    cap = cv2.VideoCapture(args.video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 15
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    marks = []
    if os.path.exists(out):
        with open(out) as f:
            marks = [(float(r["t"]), r["kind"], r["cls"]) for r in csv.DictReader(f)]
        print(f"resuming with {len(marks)} marks")
    speed = args.speed
    paused = False
    frame = None
    idx = 0
    while True:
        if not paused or frame is None:
            ok, frame = cap.read()
            if not ok:
                break
            idx = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
        t = idx / fps
        img = frame.copy()
        totals = {}
        for _, k, _ in marks:
            totals[k] = totals.get(k, 0) + 1
        hud = f"t={t:7.1f}s  {idx}/{n}  x{speed:g}  " + "  ".join(f"{k[:3]}:{v}" for k, v in totals.items())
        cv2.putText(img, hud, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(img, hud, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 1, cv2.LINE_AA)
        recent = [m for m in marks if 0 <= t - m[0] < 1.0]
        for i, m in enumerate(recent):
            cv2.putText(img, f"+1 {m[2]}", (8, 50 + 24 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2, cv2.LINE_AA)
        cv2.imshow("count_gt (p b s c m u | z undo | space | , . | + - | q)", img)
        k = cv2.waitKey(max(1, int(1000 / fps / speed))) & 0xFF
        if k in KEYS:
            kind, cls = KEYS[k]
            marks.append((t, kind, cls))
        elif k == ord("z") and marks:
            marks.pop()
        elif k == ord(" "):
            paused = not paused
        elif k in (ord(","), ord(".")):
            target = max(0, idx + int((2 if k == ord(".") else -2) * fps))
            cap.set(cv2.CAP_PROP_POS_FRAMES, target)
            frame = None
        elif k == ord("+"):
            speed = min(8, speed * 1.5)
        elif k == ord("-"):
            speed = max(0.25, speed / 1.5)
        elif k == ord("q"):
            break
    marks.sort()
    with open(out, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["t", "kind", "cls"])
        for m in marks:
            wr.writerow([f"{m[0]:.2f}", m[1], m[2]])
    print(f"saved {len(marks)} marks -> {out}")


if __name__ == "__main__":
    main()
