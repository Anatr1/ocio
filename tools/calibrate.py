"""Interactive ground-plane calibration (OpenCV window). Alternative: the /calibrate.html page on the node.

    python tools/calibrate.py --camera 0 --config configs/board.yaml          # local camera (laptop / board with display)
    python tools/calibrate.py --video data/recordings/site.mp4 --config configs/site.yaml
    python tools/calibrate.py --url http://<board-ip>:8000 --push              # use the board's background, push result back

Keys: click P1..P4 | a = auto-detect zebra | r = reset | s = save | g = toggle grid | q = quit
P1/P2 = the two stripe ends on curb A (near side), P3/P4 = curb B, same order (P3 above P2, P4 above P1).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crosswalk.calibration import auto_calibrate, draw_calibration, estimate_length  # noqa: E402
from crosswalk.config import _load_file, load_config, save_config  # noqa: E402
from crosswalk.scene import Scene  # noqa: E402


def grab(args):
    if args.url:
        with urllib.request.urlopen(args.url.rstrip("/") + "/api/background.jpg", timeout=5) as r:
            data = np.frombuffer(r.read(), np.uint8)
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    if args.image:
        return cv2.imread(args.image)
    src = args.video if args.video else (int(args.camera) if str(args.camera).isdigit() else args.camera)
    cap = cv2.VideoCapture(src)
    if args.video:
        cap.set(cv2.CAP_PROP_POS_FRAMES, args.frame)
    else:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    # median of a few frames removes passers-by
    frames = []
    for _ in range(15 if not args.video else 1):
        ok, f = cap.read()
        if ok:
            frames.append(f)
    cap.release()
    if not frames:
        raise SystemExit("could not read a frame")
    return np.median(np.stack(frames), axis=0).astype(np.uint8) if len(frames) > 1 else frames[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", default="0")
    ap.add_argument("--video", default=None)
    ap.add_argument("--frame", type=int, default=0)
    ap.add_argument("--image", default=None)
    ap.add_argument("--url", default=None)
    ap.add_argument("--push", action="store_true", help="POST the result to the node (--url)")
    ap.add_argument("--config", default=os.path.join(ROOT, "configs", "board.yaml"))
    ap.add_argument("--width-m", type=float, default=None, help="stripe length W (m)")
    ap.add_argument("--length-m", type=float, default=None, help="zebra block length L (m)")
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    args = ap.parse_args()

    cfg = load_config(args.config if os.path.exists(args.config) else None)
    W = args.width_m or float(cfg.scene.crosswalk.width)
    L = args.length_m or float(cfg.scene.crosswalk.length)
    frame = grab(args)
    h, w = frame.shape[:2]
    pts = list(cfg.scene.calibration.get("image_points") or [])
    show_grid = True
    state = {"scene": None}

    def rebuild():
        state["scene"] = None
        if len(pts) == 4:
            cfg.scene.crosswalk.width = W
            cfg.scene.crosswalk.length = L
            cfg.scene.calibration.image_points = pts
            cfg.scene.calibration.image_size = [w, h]
            cfg.scene.calibration.H = None
            state["scene"] = Scene(cfg.scene, (w, h), cfg.tracker)
            ci = state["scene"].cal_info
            print(f"camera height {ci.get('camera_height_m', 0):.2f} m | tilt {ci.get('tilt_deg', 0):.1f} deg | "
                  f"hfov {ci.get('hfov_deg', 0):.0f} ({ci.get('focal_source')}) | mirrored-fixed {ci.get('auto_flipped_x', False)}")

    def on_mouse(ev, x, y, *_):
        if ev == cv2.EVENT_LBUTTONDOWN:
            if len(pts) >= 4:
                pts.clear()
            pts.append([float(x), float(y)])
            rebuild()

    rebuild()
    cv2.namedWindow("calibrate", cv2.WINDOW_NORMAL)
    cv2.setMouseCallback("calibrate", on_mouse)
    while True:
        img = frame.copy()
        draw_calibration(img, state["scene"] if show_grid else None, pts)
        txt = f"W={W:.2f} m  L={L:.2f} m   click P1..P4 | a auto | r reset | s save | g grid | q quit"
        cv2.putText(img, txt, (8, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(img, txt, (8, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.imshow("calibrate", img)
        k = cv2.waitKey(30) & 0xFF
        if k == ord("q") or k == 27:
            break
        if k == ord("r"):
            pts.clear()
            rebuild()
        if k == ord("g"):
            show_grid = not show_grid
        if k == ord("a"):
            r = auto_calibrate(frame)
            if r:
                pts[:] = r["image_points"]
                if not args.length_m:
                    L = estimate_length(r["n_stripes"])
                print(f"auto: {r['n_stripes']} stripes, L ~ {L:.2f} m (check!)")
                rebuild()
            else:
                print("auto: no zebra found")
        if k == ord("s") and len(pts) == 4:
            if args.push and args.url:
                body = json.dumps({"image_points": pts, "width": W, "length": L}).encode()
                req = urllib.request.Request(args.url.rstrip("/") + "/api/calibrate", data=body,
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=5) as r:
                    print("pushed:", r.read().decode()[:300])
            data = _load_file(args.config) if os.path.exists(args.config) else {}
            data.setdefault("scene", {}).setdefault("crosswalk", {})
            data["scene"]["crosswalk"].update({"width": W, "length": L})
            data["scene"].setdefault("calibration", {})
            data["scene"]["calibration"].update({"image_points": pts, "image_size": [w, h]})
            data["scene"]["calibration"].pop("H", None)
            save_config(data, args.config)
            cv2.imwrite(os.path.splitext(args.config)[0] + "_calibration.jpg", draw_calibration(frame.copy(), state["scene"], pts))
            print("saved ->", args.config)
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
