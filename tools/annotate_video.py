"""Run the full pipeline on a video and write an annotated MP4 (overlay + BEV inset + counts), plus the
event log. Great for checking calibration/counting by eye, and for the pitch video.

    python tools/annotate_video.py --config configs/video_demo.yaml --out runs/demo_annotated.mp4
    python tools/annotate_video.py --config configs/board.yaml --video data/recordings/site_0930.mp4 --out runs/site.mp4
    python tools/annotate_video.py --sim mixed --seconds 60 --out runs/sim.mp4
"""
from __future__ import annotations

import argparse
import os
import sys

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crosswalk.config import load_config  # noqa: E402
from crosswalk.pipeline import Node  # noqa: E402
from crosswalk.render import COLORS, draw_overlay  # noqa: E402


def bev_inset(node, size=(260, 200)):
    """Top-down minimap of zones + tracks."""
    sc = node.scene
    w, h = size
    img = np.full((h, w, 3), 18, np.uint8)
    x0, y0, x1, y1 = -sc.W / 2 - 10, -sc.L / 2 - sc.D - 1, sc.W / 2 + 10, sc.L / 2 + sc.D + 1
    s = min(w / (x1 - x0), h / (y1 - y0))

    def P(x, y):
        return int((x - x0) * s), int((y1 - y) * s)

    cv2.rectangle(img, P(x0, -sc.L / 2), P(x1, sc.L / 2), (45, 45, 48), -1)
    yy = -sc.L / 2 + 0.25
    while yy + 0.5 <= sc.L / 2:
        cv2.rectangle(img, P(-sc.W / 2, yy), P(sc.W / 2, yy + 0.5), (200, 200, 200), -1)
        yy += 1.0
    for tr in node.tracker.confirmed():
        col = COLORS.get(tr.kind, (200, 200, 200))
        pts = [P(hh[1], hh[2]) for hh in list(tr.history)[-30:]]
        for a, b in zip(pts, pts[1:]):
            cv2.line(img, a, b, col, 1, cv2.LINE_AA)
        cv2.circle(img, P(*tr.pos), 4, col, -1, cv2.LINE_AA)
    cv2.rectangle(img, (0, 0), (w - 1, h - 1), (90, 90, 90), 1)
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--video", default=None)
    ap.add_argument("--sim", default=None)
    ap.add_argument("--seconds", type=float, default=None)
    ap.add_argument("--out", default="runs/annotated.mp4")
    ap.add_argument("--set", action="append", default=[])
    ap.add_argument("--no-blur", action="store_true")
    args = ap.parse_args()

    cfg = load_config(args.config, args.set)
    cfg.server.enabled = False
    source = None
    if args.sim:
        from sim.source import SimSource

        cfg.detector.backend = "sim"
        source = SimSource(cfg, scenario=args.sim, realtime=False, fps=15)
        cfg.scene.calibration.update(source.calibration())
    else:
        cfg.source.type = "video"
        if args.video:
            cfg.source.path = args.video
        cfg.source.realtime = False
        cfg.source.loop = False
    node = Node(cfg, source=source)
    if args.sim:
        source.world.signal = node.signal
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    fps = getattr(node.source, "fps", 15) or 15
    writer = None

    def on_step(n, frame, dets):
        nonlocal writer
        img = frame.copy()
        conf = n.tracker.confirmed()
        if not args.no_blur:
            from crosswalk.render import privacy_blur

            privacy_blur(img, [(tr.bbox, tr.kind) for tr in conf])
        c = n.counter.counts
        sf = n.safety
        hud = [f"{cfg.node.get('brand', '')}  ped {c['pedestrian']}  bike {c['bicycle']}  scooter {c['micromobility']}  veh {c['vehicle']}",
               f"near-miss {sum(sf.near_miss.values())}  yield {sf.yields['yielded']}/{sf.yields['yielded'] + sf.yields['not_yielded']}",
               f"t={n.t:6.1f}s  det {n.ema['det_hz'].v or 0:.1f} Hz"]
        draw_overlay(img, n.scene, conf, dets, hud, n.signal, cfg.detector.get("roi"))
        inset = bev_inset(n)
        h, w = img.shape[:2]
        ih, iw = inset.shape[:2]
        if h > ih + 20 and w > iw + 20:
            img[h - ih - 10 : h - 10, w - iw - 10 : w - 10] = inset
        if writer is None:
            writer = cv2.VideoWriter(args.out, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
        writer.write(img)

    node.on_step = on_step
    max_frames = int(args.seconds * fps) if args.seconds else None
    node.run(max_frames=max_frames)
    if writer:
        writer.release()
    print("counts:", node.counter.counts, "->", args.out, " events:", node.run_dir)


if __name__ == "__main__":
    main()
