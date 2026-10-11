"""TFLite / LiteRT backend (XNNPACK CPU delegate). Handles float and int8 I/O."""
from __future__ import annotations

import numpy as np

from .base import Detector


def _interpreter_cls():
    try:
        from ai_edge_litert.interpreter import Interpreter  # new name of tflite-runtime

        return Interpreter
    except ImportError:
        pass
    try:
        from tflite_runtime.interpreter import Interpreter

        return Interpreter
    except ImportError:
        pass
    from tensorflow.lite import Interpreter  # type: ignore

    return Interpreter


class TfliteYolo(Detector):
    backend = "tflite"

    def __init__(self, cfg):
        super().__init__(cfg)
        Interp = _interpreter_cls()
        self.it = Interp(model_path=cfg["model"], num_threads=int(cfg.get("threads", 3)))
        self.it.allocate_tensors()
        self.inp = self.it.get_input_details()[0]
        self.out = self.it.get_output_details()[0]
        self.imgsz = int(self.inp["shape"][1])

    def _infer(self, lb):
        x = lb[:, :, ::-1][None].astype(np.float32) / 255.0  # NHWC
        if self.inp["dtype"] in (np.int8, np.uint8):
            s, z = self.inp["quantization"]
            x = (x / s + z).round().clip(-128 if self.inp["dtype"] == np.int8 else 0, 127 if self.inp["dtype"] == np.int8 else 255)
            x = x.astype(self.inp["dtype"])
        self.it.set_tensor(self.inp["index"], x)
        self.it.invoke()
        y = self.it.get_tensor(self.out["index"])
        if self.out["dtype"] in (np.int8, np.uint8):
            s, z = self.out["quantization"]
            y = (y.astype(np.float32) - z) * s
        return y
