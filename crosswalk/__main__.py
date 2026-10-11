"""Run the crosswalk node.

    python -m crosswalk --config configs/board.yaml                 # on the UNO Q with the USB camera
    python -m crosswalk --config configs/video_demo.yaml --show      # laptop: sample video + OpenCV window
    python -m crosswalk --sim mixed                                  # laptop: simulator, open http://localhost:8000
    python -m crosswalk --sim dangerous --set signal.mode=beacon
    python -m crosswalk --sim mixed --sim-detector real            # real YOLO on the rendered frames (needs realistic rendering)
    python -m crosswalk --config configs/board.yaml --set detector.imgsz=256 --set detector.model=models/yolo26n_256.onnx
"""
from __future__ import annotations

import argparse
import os
import sys

from .config import load_config


def main(argv=None):
    ap = argparse.ArgumentParser(prog="crosswalk")
    ap.add_argument("--config", "-c", default=None)
    ap.add_argument("--set", "-s", action="append", default=[], help="override, e.g. detector.imgsz=256")
    ap.add_argument("--sim", default=None, help="run the simulator with this scenario (mixed, rush, dangerous...)")
    ap.add_argument("--sim-detector", choices=["model", "real"], default="model",
                    help="sim: 'model' = synthesised detections (GT + noise model); 'real' = run the configured "
                         "neural network on the rendered images")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--video", default=None, help="video file (overrides source)")
    ap.add_argument("--camera", default=None, help="camera index/device (overrides source)")
    ap.add_argument("--show", action="store_true", help="OpenCV window with the overlay (laptop)")
    ap.add_argument("--fast", action="store_true", help="video/sim: process as fast as possible (not real time)")
    ap.add_argument("--max-seconds", type=float, default=None)
    ap.add_argument("--max-frames", type=int, default=None)
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--no-server", action="store_true")
    ap.add_argument("--intersection", action="store_true", help="optional four-arm intersection simulator and digital twin")
    ap.add_argument("--intersection-scenario", choices=["balanced", "commute", "pedestrian", "turning", "saturated", "empty"], default="balanced")
    ap.add_argument("--intersection-policy", choices=["fixed", "adaptive"], default="adaptive")
    ap.add_argument("--intersection-speed", type=float, default=1., help="intersection simulation time multiplier (.1–30)")
    ap.add_argument("--intersection-render", choices=["twin", "photoreal"], default="twin")
    ap.add_argument("--intersection-detector", choices=["none", "real"], default="none", help="optional actual ONNX detector on photoreal pixels")
    ap.add_argument("--intersection-model", default="models/yolo11n_320.onnx")
    ap.add_argument("--intersection-camera", choices=["overview", "N", "E", "S", "W"], default="overview")
    ap.add_argument("--intersection-condition", choices=["day", "night", "rain", "fog"], default="day")
    ap.add_argument("--intersection-render-fps", type=float, default=5.)
    args = ap.parse_args(argv)
    if args.intersection:
        if args.intersection_detector == "real" and args.intersection_render != "photoreal":
            ap.error("--intersection-detector real requires --intersection-render photoreal")
        if args.sim or args.video or args.camera is not None or args.config or args.set or args.show or args.sim_detector != "model":
            ap.error("--intersection is a standalone simulator; camera/video/config/--sim/--set/--show options belong to crosswalk mode")
        from sim.intersection.app import run
        try:
            return run(args)
        except ValueError as exc:
            ap.error(str(exc))


    cfg = load_config(args.config, args.set)
    if args.config:
        cfg.node.config_path = os.path.abspath(args.config)
    if args.port:
        cfg.server.port = args.port
    if args.no_server:
        cfg.server.enabled = False
    source = None
    if args.sim:
        from sim.source import SimSource

        if args.sim_detector == "model":
            cfg.detector.backend = "sim"   # no NN: detections synthesised from ground truth + noise model
        cfg.source.type = "sim"
        sim = SimSource(cfg, scenario=args.sim, seed=args.seed, realtime=not args.fast,
                        fps=float(cfg.get("sim", {}).get("fps", 15.0)))
        if not cfg.scene.calibration.get("image_points") and not cfg.scene.calibration.get("H"):
            cfg.scene.calibration.update(sim.calibration())
        source = sim
    elif args.video:
        cfg.source.type = "video"
        cfg.source.path = args.video
    elif args.camera is not None:
        cfg.source.type = "camera"
        cfg.source.device = args.camera
    if args.fast and cfg.source.type == "video":
        cfg.source.realtime = False

    from .pipeline import Node

    node = Node(cfg, source=source)
    if args.sim:
        from sim.gt_match import match as gt_match

        source.world.signal = node.signal
        node.inject_scenario = source.inject

        def gt_provider(tracks, src=source):
            gt = src.ground_truth()
            return {"t": round(src.world.t, 3), "agents": gt, "match": gt_match(tracks, gt)}

        node.gt_provider = gt_provider
    sc = node.scene
    if sc.calibrated:
        ci = sc.cal_info
        print(f"[node] calibrated: camera height {ci.get('camera_height_m', 0):.2f} m, tilt {ci.get('tilt_deg', 0):.1f} deg, "
              f"hfov {ci.get('hfov_deg', 0):.0f} deg ({ci.get('focal_source')}), reproj {ci.get('reproj_err_m', 0):.3f} m")
    else:
        print("[node] WARNING: no calibration - run tools/calibrate.py; counting needs ground coordinates")
    print(f"[node] detector: {cfg.detector.backend} {cfg.detector.get('model', '')}  run dir: {node.run_dir}")
    node.run(max_seconds=args.max_seconds, max_frames=args.max_frames, show=args.show)
    st = node.state_payload()
    if st:
        print("[node] final counts:", st["counts"]["counts"], " safety:", {k: st["safety"][k] for k in ("near_miss", "yield", "pet_count")})


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    main()
