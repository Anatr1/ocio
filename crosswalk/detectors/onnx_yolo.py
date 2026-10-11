"""ONNX Runtime backend (CPU). Works on the laptop and on the UNO Q (aarch64 wheels)."""
from __future__ import annotations

import ast
import os

import numpy as np

from .base import Detector


class OnnxYolo(Detector):
    backend = "onnx"

    def __init__(self, cfg):
        super().__init__(cfg)
        import onnxruntime as ort

        path = cfg["model"]
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        so = ort.SessionOptions()
        so.intra_op_num_threads = int(cfg.get("threads", 3))
        so.inter_op_num_threads = 1
        so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        providers = cfg.get("providers") or ["CPUExecutionProvider"]
        self.sess = ort.InferenceSession(path, so, providers=providers)
        self.inp = self.sess.get_inputs()[0]
        shp = self.inp.shape
        if isinstance(shp[2], int):
            self.imgsz = int(shp[2])
        # Ultralytics stores class names in metadata
        meta = self.sess.get_modelmeta().custom_metadata_map or {}
        if not cfg.get("class_names") and "names" in meta:
            try:
                d = ast.literal_eval(meta["names"])
                self.names = [d[i] for i in sorted(d)]
            except (ValueError, SyntaxError):
                pass
        self.fp16 = "float16" in self.inp.type

    def _infer(self, lb):
        x = self.to_blob_nchw(lb)
        if self.fp16:
            x = x.astype(np.float16)
        return self.sess.run(None, {self.inp.name: x})[0]
