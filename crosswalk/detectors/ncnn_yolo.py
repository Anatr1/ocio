"""NCNN backend - usually the fastest CPU runtime on ARM Cortex-A cores.

Export on the laptop (``tools/export_models.py``): exporting on the UNO Q crashes with
"illegal instruction" (pnnx/torch wheels), but the exported model runs fine.
"""
from __future__ import annotations

import os

import numpy as np

from .base import Detector


def _read_names(model_dir):
    meta = os.path.join(model_dir, "metadata.yaml")
    if not os.path.exists(meta):
        return None
    try:
        import yaml

        with open(meta) as f:
            d = yaml.safe_load(f)
        names = d.get("names")
        if isinstance(names, dict):
            return [names[i] for i in sorted(names)]
        return names
    except Exception:  # noqa: BLE001
        return None


class NcnnYolo(Detector):
    backend = "ncnn"

    def __init__(self, cfg):
        super().__init__(cfg)
        import ncnn

        path = cfg["model"]
        if os.path.isdir(path):
            param = os.path.join(path, "model.ncnn.param")
            binf = os.path.join(path, "model.ncnn.bin")
            names = _read_names(path)
            if names and not cfg.get("class_names"):
                self.names = names
        else:
            param, binf = path, path.replace(".param", ".bin")
        self.net = ncnn.Net()
        self.net.opt.use_vulkan_compute = bool(cfg.get("vulkan", False))
        self.net.opt.num_threads = int(cfg.get("threads", 3))
        self.net.opt.use_fp16_packed = True
        self.net.opt.use_fp16_storage = True
        self.net.opt.use_fp16_arithmetic = False  # Cortex-A53 has no FP16 arithmetic
        self.net.load_param(param)
        self.net.load_model(binf)
        self.ncnn = ncnn
        self.in_name = cfg.get("ncnn_input", "in0")
        self.out_name = cfg.get("ncnn_output", "out0")

    def _infer(self, lb):
        x = self.to_blob_nchw(lb)[0]
        with self.net.create_extractor() as ex:
            ex.input(self.in_name, self.ncnn.Mat(x).clone())
            _, out = ex.extract(self.out_name)
        return np.array(out)[None]
