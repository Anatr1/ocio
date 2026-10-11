"""Export YOLO models for the UNO Q (run on the laptop / training box, NOT on the board).

Examples
--------
    python tools/export_models.py                              # yolo11n + yolo26n, ONNX @ 256/320/384/416 + NCNN @ 320
    python tools/export_models.py --weights runs/train/xw/weights/best.pt --name xw --sizes 320 384
    python tools/export_models.py --int8-onnx --calib data/videos/person-bicycle-car-detection.mp4
    python tools/export_models.py --tflite                     # needs tensorflow (heavy) - better on Linux

Outputs land in models/:  <name>_<imgsz>.onnx, <name>_<imgsz>_int8.onnx, <name>_<imgsz>_ncnn_model/, ...
A models/manifest.json describes every exported file (class names, imgsz, format) for tools/bench.py.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = os.path.join(ROOT, "models")
sys.path.insert(0, ROOT)


def load_manifest():
    p = os.path.join(MODELS, "manifest.json")
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return {}


def save_manifest(m):
    with open(os.path.join(MODELS, "manifest.json"), "w") as f:
        json.dump(m, f, indent=2)


def calib_frames(paths, n=64, imgsz=320):
    import cv2
    import numpy as np

    from crosswalk.detectors.base import letterbox

    frames = []
    for p in paths:
        cap = cv2.VideoCapture(p)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1000
        for i in np.linspace(0, total - 1, max(1, n // len(paths))).astype(int):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
            ok, fr = cap.read()
            if ok:
                img, _, _ = letterbox(fr, imgsz)
                x = img[:, :, ::-1].transpose(2, 0, 1)[None].astype("float32") / 255.0
                frames.append(np.ascontiguousarray(x))
    return frames


def quantize_onnx(src, dst, frames):
    from onnxruntime.quantization import CalibrationDataReader, QuantFormat, QuantType, quantize_static
    from onnxruntime.quantization.shape_inference import quant_pre_process

    import onnx

    inp = onnx.load(src).graph.input[0].name

    class Reader(CalibrationDataReader):
        def __init__(self):
            self.it = iter([{inp: f} for f in frames])

        def get_next(self):
            return next(self.it, None)

    pre = dst.replace(".onnx", "_pre.onnx")
    try:
        quant_pre_process(src, pre)
    except Exception as e:  # noqa: BLE001
        print("  pre-process failed, quantising raw model:", e)
        shutil.copy(src, pre)
    # Only quantise convolutions: the YOLO head concatenates box coordinates (0..imgsz) and class scores
    # (0..1) into one tensor - a single int8 scale for it destroys the scores (0 detections / conf > 1).
    m = onnx.load(pre)
    tail = [n.name for n in m.graph.node if n.op_type in ("Concat", "Sigmoid", "Mul", "Add", "Sub", "Div", "Softmax",
                                                           "Split", "Reshape", "Transpose", "Slice", "TopK", "Gather")]
    quantize_static(
        pre,
        dst,
        Reader(),
        quant_format=QuantFormat.QDQ,
        per_channel=True,
        activation_type=QuantType.QUInt8,
        weight_type=QuantType.QInt8,
        op_types_to_quantize=["Conv"],
        nodes_to_exclude=tail,
    )
    os.remove(pre)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", nargs="*", default=["yolo11n.pt", "yolo26n.pt"])
    ap.add_argument("--name", default=None, help="output base name (single weights only)")
    ap.add_argument("--sizes", nargs="*", type=int, default=[256, 320, 384, 416])
    ap.add_argument("--ncnn-sizes", nargs="*", type=int, default=[320])
    ap.add_argument("--int8-onnx", action="store_true")
    ap.add_argument("--calib", nargs="*", default=sorted(glob.glob(os.path.join(ROOT, "data/videos/*.mp4"))))
    ap.add_argument("--tflite", action="store_true")
    ap.add_argument("--no-end2end", action="store_true", help="YOLO26: export the classic one-to-many head")
    args = ap.parse_args()

    from ultralytics import YOLO

    os.makedirs(MODELS, exist_ok=True)
    manifest = load_manifest()
    cwd = os.getcwd()
    for w in args.weights:
        os.chdir(MODELS)
        try:
            model_path = w if os.path.isabs(w) or os.path.exists(w) else os.path.join(MODELS, w)
            if not os.path.exists(model_path):
                model_path = os.path.basename(w)  # bare name -> ultralytics downloads into models/
            base = args.name or os.path.splitext(os.path.basename(w))[0]
            for sz in args.sizes:
                m = YOLO(model_path)
                names = [m.names[i] for i in sorted(m.names)]
                kw = {}
                if args.no_end2end:
                    kw["end2end"] = False
                out = m.export(format="onnx", imgsz=sz, simplify=True, dynamic=False, opset=17, **kw)
                dst = os.path.join(MODELS, f"{base}_{sz}.onnx")
                shutil.move(out, dst)
                manifest[os.path.basename(dst)] = {"format": "onnx", "imgsz": sz, "names": names, "src": w}
                print("exported", dst)
                if args.int8_onnx and args.calib:
                    q = dst.replace(".onnx", "_int8.onnx")
                    quantize_onnx(dst, q, calib_frames(args.calib, 64, sz))
                    manifest[os.path.basename(q)] = {"format": "onnx", "imgsz": sz, "names": names, "src": w, "int8": True}
                    print("quantised", q)
            for sz in args.ncnn_sizes:
                m = YOLO(model_path)
                names = [m.names[i] for i in sorted(m.names)]
                out = m.export(format="ncnn", imgsz=sz)
                dst = os.path.join(MODELS, f"{base}_{sz}_ncnn_model")
                if os.path.exists(dst):
                    shutil.rmtree(dst)
                shutil.move(out, dst)
                manifest[os.path.basename(dst)] = {"format": "ncnn", "imgsz": sz, "names": names, "src": w}
                print("exported", dst)
            if args.tflite:
                for sz in args.ncnn_sizes:
                    m = YOLO(model_path)
                    names = [m.names[i] for i in sorted(m.names)]
                    out = m.export(format="tflite", imgsz=sz, int8=True, data="coco8.yaml")
                    sm_dir = os.path.dirname(out)
                    for f in glob.glob(os.path.join(sm_dir, "*.tflite")):
                        dst = os.path.join(MODELS, f"{base}_{sz}_" + os.path.basename(f).split("_", 1)[-1])
                        shutil.copy(f, dst)
                        manifest[os.path.basename(dst)] = {"format": "tflite", "imgsz": sz, "names": names, "src": w}
                        print("exported", dst)
        finally:
            os.chdir(cwd)
    save_manifest(manifest)
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "names"} for k, v in manifest.items()}, indent=1))


if __name__ == "__main__":
    main()
