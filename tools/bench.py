"""Benchmark detector runtimes / models / input sizes / threads ON THE BOARD (first thing to run on site).

    python tools/bench.py                                  # every model in models/, threads 2,3,4
    python tools/bench.py --models models/yolo11n_320.onnx models/yolo26n_320_ncnn_model --threads 3 4
    python tools/bench.py --video data/videos/vtest.avi    # also report detections/confidence (quality proxy)
    python tools/bench.py --sustained 120 --models models/yolo11n_320.onnx --threads 3   # thermal throttling check
    python tools/bench.py --camera 0                        # camera capture fps (MJPG vs YUYV)

Writes runs/bench_<timestamp>.md + .json. Pick the fastest model whose quality proxy is acceptable.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import platform
import sys
import time

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crosswalk.detectors import create_detector  # noqa: E402


def backend_of(path):
    if os.path.isdir(path) or path.endswith(".param"):
        return "ncnn"
    if path.endswith(".tflite"):
        return "tflite"
    if path.endswith(".onnx"):
        return "onnx"
    if path.endswith(".pt"):
        return "ultralytics"
    return None


def imgsz_of(path):
    for tok in os.path.basename(path).replace(".", "_").split("_"):
        if tok.isdigit() and 128 <= int(tok) <= 1280:
            return int(tok)
    return 320


def cpu_temp():
    best = None
    for z in glob.glob("/sys/class/thermal/thermal_zone*/temp"):
        try:
            v = int(open(z).read()) / 1000
            best = v if best is None else max(best, v)
        except (OSError, ValueError):
            pass
    return best


def load_frames(video, n=20):
    frames = []
    if video and os.path.exists(video):
        cap = cv2.VideoCapture(video)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 200
        for i in np.linspace(0, total - 1, n).astype(int):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
            ok, f = cap.read()
            if ok:
                frames.append(cv2.resize(f, (640, 480)))
    if not frames:
        rng = np.random.default_rng(0)
        frames = [rng.integers(0, 255, (480, 640, 3), dtype=np.uint8) for _ in range(4)]
    return frames


def bench_model(path, threads, frames, iters, warmup):
    be = backend_of(path)
    cfg = {"backend": be, "model": path, "imgsz": imgsz_of(path), "threads": threads, "conf": 0.35, "conf_low": 0.25}
    t0 = time.perf_counter()
    det = create_detector(cfg)
    load_s = time.perf_counter() - t0
    for i in range(warmup):
        det(frames[i % len(frames)])
    pre, inf, post, ndet, conf = [], [], [], [], []
    for i in range(iters):
        f = frames[i % len(frames)]
        a = time.perf_counter()
        lb, meta = det.preprocess(f)
        b = time.perf_counter()
        out = det._infer(lb)
        c = time.perf_counter()
        d = det.postprocess(out, meta, f.shape)
        e = time.perf_counter()
        pre.append(b - a)
        inf.append(c - b)
        post.append(e - c)
        ndet.append(sum(1 for x in d if x.score >= 0.35))
        conf.extend(x.score for x in d if x.score >= 0.35)
    ms = lambda v: 1000 * float(np.median(v))  # noqa: E731
    total = ms(pre) + ms(inf) + ms(post)
    return {"model": os.path.basename(path.rstrip("/\\")), "backend": be, "imgsz": cfg["imgsz"], "threads": threads,
            "pre_ms": round(ms(pre), 1), "infer_ms": round(ms(inf), 1), "post_ms": round(ms(post), 1),
            "total_ms": round(total, 1), "fps": round(1000 / max(total, 1e-3), 1),
            "p90_infer_ms": round(1000 * float(np.percentile(inf, 90)), 1), "load_s": round(load_s, 2),
            "dets_per_frame": round(float(np.mean(ndet)), 2), "mean_conf": round(float(np.mean(conf)) if conf else 0.0, 3),
            "temp_c": cpu_temp()}


def bench_camera(dev, modes=None):
    """modes: list of 'WxH:FOURCC' (default: 640x480 / 1280x720 in MJPG and YUYV)."""
    res = []
    if modes:
        combos = [(m.split(":")[1] if ":" in m else "MJPG", tuple(int(v) for v in m.split(":")[0].split("x"))) for m in modes]
    else:
        combos = [(fc, wh) for fc in ("MJPG", "YUYV") for wh in ((640, 480), (1280, 720))]
    for fourcc, (w, h) in combos:
        if True:
            cap = cv2.VideoCapture(dev, cv2.CAP_V4L2 if platform.system() == "Linux" else cv2.CAP_ANY)
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
            cap.set(cv2.CAP_PROP_FPS, 30)
            ok, f = cap.read()
            if not ok:
                res.append({"fourcc": fourcc, "req": f"{w}x{h}", "ok": False})
                cap.release()
                continue
            n, t0 = 0, time.time()
            while time.time() - t0 < 3:
                ok, f = cap.read()
                n += ok
            res.append({"fourcc": fourcc, "req": f"{w}x{h}", "got": f"{f.shape[1]}x{f.shape[0]}", "fps": round(n / 3, 1), "ok": True})
            cap.release()
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="*", default=None)
    ap.add_argument("--threads", nargs="*", type=int, default=[2, 3, 4])
    ap.add_argument("--iters", type=int, default=30)
    ap.add_argument("--warmup", type=int, default=5)
    ap.add_argument("--video", default=os.path.join(ROOT, "data/videos/vtest.avi"))
    ap.add_argument("--sustained", type=float, default=0.0, help="seconds of continuous inference (thermal check)")
    ap.add_argument("--camera", default=None)
    ap.add_argument("--camera-modes", nargs="*", default=None,
                    help="e.g. 1344x376:YUYV 2560x720:YUYV (ZED Mini side-by-side modes)")
    args = ap.parse_args()

    models = args.models
    if models is None:  # no --models flag: everything in models/ ; bare --models: skip model benchmarks
        models = sorted(glob.glob(os.path.join(ROOT, "models", "*.onnx")) + glob.glob(os.path.join(ROOT, "models", "*_ncnn_model"))
                        + glob.glob(os.path.join(ROOT, "models", "*.tflite")))
    frames = load_frames(args.video)
    info = {"machine": platform.machine(), "python": platform.python_version(), "cpus": os.cpu_count(),
            "time": time.strftime("%Y-%m-%d %H:%M:%S"), "temp_start_c": cpu_temp()}
    print(json.dumps(info))
    rows = []
    if args.camera is not None:
        cam = bench_camera(int(args.camera) if str(args.camera).isdigit() else args.camera, args.camera_modes)
        print(json.dumps(cam, indent=1))
        info["camera"] = cam
    for m in models:
        for th in args.threads:
            try:
                r = bench_model(m, th, frames, args.iters, args.warmup)
                rows.append(r)
                print(f"{r['model']:34s} {r['backend']:6s} {r['imgsz']:4d} t{th}  infer {r['infer_ms']:7.1f} ms  total {r['total_ms']:7.1f} ms "
                      f"({r['fps']:5.1f} fps)  dets {r['dets_per_frame']:.2f} conf {r['mean_conf']:.2f}  {r['temp_c']}C")
            except Exception as e:  # noqa: BLE001
                print(f"{os.path.basename(m)} t{th}: FAILED {e}")
                rows.append({"model": os.path.basename(m), "threads": th, "error": str(e)})
    if args.sustained > 0 and models:
        m, th = models[0], args.threads[0]
        det = create_detector({"backend": backend_of(m), "model": m, "imgsz": imgsz_of(m), "threads": th})
        print(f"sustained {args.sustained:.0f}s on {os.path.basename(m)} t{th}")
        t0 = time.time()
        series = []
        n = 0
        tw = t0
        while time.time() - t0 < args.sustained:
            det(frames[n % len(frames)])
            n += 1
            if time.time() - tw >= 10:
                fps = n / (time.time() - tw)
                series.append({"t": round(time.time() - t0), "fps": round(fps, 2), "temp_c": cpu_temp()})
                print("  ", series[-1])
                n, tw = 0, time.time()
        info["sustained"] = series
    ok = [r for r in rows if "error" not in r]
    ok.sort(key=lambda r: r["total_ms"])
    os.makedirs(os.path.join(ROOT, "runs"), exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    with open(os.path.join(ROOT, "runs", f"bench_{stamp}.json"), "w") as f:
        json.dump({"info": info, "results": rows}, f, indent=1)
    lines = [f"# Detector benchmark - {info['time']} ({info['machine']}, {info['cpus']} cpus, py {info['python']})\n",
             "| model | backend | imgsz | threads | pre ms | infer ms | post ms | total ms | fps | dets/frame | conf |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in ok:
        lines.append(f"| {r['model']} | {r['backend']} | {r['imgsz']} | {r['threads']} | {r['pre_ms']} | {r['infer_ms']} | "
                     f"{r['post_ms']} | **{r['total_ms']}** | {r['fps']} | {r['dets_per_frame']} | {r['mean_conf']} |")
    with open(os.path.join(ROOT, "runs", f"bench_{stamp}.md"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines[:12]))
    print(f"\nreport: runs/bench_{stamp}.md")


if __name__ == "__main__":
    main()
