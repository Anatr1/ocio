"""Detector factory. Backends are imported lazily so the board only needs the runtime it uses."""
from __future__ import annotations

from .base import COCO80, Detection, Detector, decode_yolo, letterbox, nms  # noqa: F401


def create_detector(cfg):
    backend = (cfg.get("backend") or "onnx").lower()
    if backend in ("none", "sim"):
        return None
    if backend == "onnx":
        from .onnx_yolo import OnnxYolo

        return OnnxYolo(cfg)
    if backend == "ncnn":
        from .ncnn_yolo import NcnnYolo

        return NcnnYolo(cfg)
    if backend == "tflite":
        from .tflite_yolo import TfliteYolo

        return TfliteYolo(cfg)
    if backend == "ultralytics":
        from .ultra import UltralyticsYolo

        return UltralyticsYolo(cfg)
    raise ValueError(f"unknown detector backend {backend}")
