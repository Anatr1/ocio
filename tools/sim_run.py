"""Live L2 dashboard: rendered pixels -> real detector -> production node -> virtual MCU."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from crosswalk.config import Cfg, deep_merge, load_config
from crosswalk.pipeline import Node
from sim.render_source import RenderSource
from sim.scenarios import load_scenario


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="mixed")
    ap.add_argument("--config", default=str(ROOT / "configs/board.yaml"))
    ap.add_argument("--set", action="append", default=[])
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--fps", type=float, default=5)
    ap.add_argument("--port", type=int, default=8001)
    ap.add_argument("--max-seconds", type=float, help="wall-clock runtime, not simulated time")
    ap.add_argument("--stop-file", type=Path, help="stop cleanly when this file exists")
    ap.add_argument("--realtime", action="store_true", help="pace output at camera rate when processing is faster")
    args = ap.parse_args()
    cfg = load_config(args.config, args.set)
    if cfg.detector.backend not in ("onnx", "ncnn", "tflite", "ultralytics"):
        ap.error("L2 requires the real board detector")
    spec = load_scenario(args.scenario)
    cfg.scene = Cfg.wrap(deep_merge(cfg.scene, spec.get("scene", {})))
    cfg.source.type = "render"
    if not any(o.startswith("public.mock_month=") for o in args.set):
        cfg.public.mock_month = True
    cfg.server.enabled, cfg.server.host, cfg.server.port = True, "127.0.0.1", args.port
    cfg.mcu.enabled = False
    cfg.setdefault("sim", {})["realtime"] = args.realtime
    if not any(o.startswith("signal.mode=") for o in args.set):
        cfg.signal.mode = spec.get("signal_mode", "beacon")
    source = RenderSource(cfg, spec, args.seed, fps=args.fps)
    if not cfg.scene.calibration.get("image_points") and not cfg.scene.calibration.get("H"):
        cfg.scene.calibration.update(source.calibration())
    try:
        node = Node(cfg, source=source)
        source.bind_signal(node.signal)
    except Exception:
        source.close()
        raise
    from sim.gt_match import match as gt_match

    def gt_provider(tracks, src=source):
        gt = src.ground_truth()
        return {"t": round(src.world.t, 3), "agents": gt, "match": gt_match(tracks, gt)}

    node.gt_provider = gt_provider  # dashboard 'Ground truth' layer; the pipeline never sees it
    node.inject_scenario = source.inject  # dashboard demo buttons (near-miss, slow walker)
    if args.stop_file:
        node.on_step = lambda n, *_: setattr(n, "running", False) if args.stop_file.exists() else None
    print("L2 pixels-only; actual detector; generic virtual site; MCU virtual; real-site gates unassessed.", flush=True)
    print(f"GPU: {source.renderer_info['gpu']}", flush=True)
    node.run(max_seconds=args.max_seconds)


if __name__ == "__main__":
    main()
