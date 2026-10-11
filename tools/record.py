"""Record raw footage from the camera (on the board or laptop) for ground truth, fine-tuning and demo fallback.

    python tools/record.py --camera 0 --minutes 10                     # -> data/recordings/rec_<time>.mp4 (+ .json)
    python tools/record.py --camera 0 --minutes 60 --segment 5         # 5-minute files
    python tools/record.py --camera 0 --frames-every 2.0 --minutes 20  # also dump a JPG every 2 s for labelling

Raw footage contains faces/plates: keep it on the team's machines, use it only for labelling/evaluation, delete
after the event. The running system never stores video.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import time

import cv2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", default="0")
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--fps", type=int, default=15)
    ap.add_argument("--minutes", type=float, default=10)
    ap.add_argument("--segment", type=float, default=0, help="split into N-minute files")
    ap.add_argument("--frames-every", type=float, default=0, help="also save a JPG every N seconds")
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "recordings"))
    ap.add_argument("--fourcc", default="MJPG", help="MJPG for normal webcams, YUYV for the ZED Mini")
    ap.add_argument("--stereo", choices=["left", "right"], default=None, help="side-by-side stereo camera: keep one eye")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    dev = int(args.camera) if str(args.camera).isdigit() else args.camera
    cap = cv2.VideoCapture(dev, cv2.CAP_V4L2 if platform.system() == "Linux" else cv2.CAP_ANY)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*args.fourcc))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    cap.set(cv2.CAP_PROP_FPS, 30)
    import sys

    sys.path.insert(0, ROOT)
    from crosswalk.sources import _postprocess

    ok, f = cap.read()
    if not ok:
        raise SystemExit("camera read failed")
    f = _postprocess(f, args.stereo, None)
    h, w = f.shape[:2]
    frames_dir = os.path.join(args.out, "frames")
    if args.frames_every:
        os.makedirs(frames_dir, exist_ok=True)
    t_end = time.time() + args.minutes * 60
    writer = None
    seg_start = 0
    period = 1.0 / args.fps
    t_next = time.time()
    t_jpg = 0
    n = 0
    meta = None
    while time.time() < t_end:
        ok, f = cap.read()
        if not ok:
            continue
        f = _postprocess(f, args.stereo, None)
        now = time.time()
        if now < t_next:
            continue
        t_next += period
        if writer is None or (args.segment and now - seg_start > args.segment * 60):
            if writer:
                writer.release()
            stamp = time.strftime("%Y%m%d-%H%M%S")
            path = os.path.join(args.out, f"rec_{stamp}.mp4")
            writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), args.fps, (w, h))
            seg_start = now
            meta = {"file": path, "start": stamp, "fps": args.fps, "size": [w, h]}
            with open(path.replace(".mp4", ".json"), "w") as fj:
                json.dump(meta, fj)
            print("recording ->", path)
        writer.write(f)
        n += 1
        if args.frames_every and now - t_jpg >= args.frames_every:
            t_jpg = now
            cv2.imwrite(os.path.join(frames_dir, f"f_{time.strftime('%H%M%S')}_{n:06d}.jpg"), f)
        if n % (args.fps * 10) == 0:
            print(f"  {n} frames, {int(t_end - now)} s left")
    if writer:
        writer.release()
    cap.release()
    print("done", n, "frames")


if __name__ == "__main__":
    main()
