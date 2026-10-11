"""Ultralytics backend - for development on the laptop (GPU) and as the auto-labelling teacher."""
from __future__ import annotations

import numpy as np

from .base import Detection, Detector


class UltralyticsYolo(Detector):
    backend = "ultralytics"

    def __init__(self, cfg):
        super().__init__(cfg)
        from ultralytics import YOLO

        self.model = YOLO(cfg.get("model", "yolo11n.pt"))
        self.names = [self.model.names[i] for i in sorted(self.model.names)]
        self.device = cfg.get("device", None)

    def __call__(self, frame):
        import time

        t0 = time.perf_counter()
        img = frame
        x0 = y0 = 0
        if self.roi:
            x0, y0, w, h = [int(v) for v in self.roi]
            img = frame[y0 : y0 + h, x0 : x0 + w]
        ids = sorted(self.keep_ids())
        r = self.model.predict(img, imgsz=self.imgsz, conf=self.conf_low, iou=self.iou, classes=ids,
                               verbose=False, device=self.device)[0]
        t1 = time.perf_counter()
        out = []
        if r.boxes is not None and len(r.boxes):
            b = r.boxes.xyxy.cpu().numpy()
            s = r.boxes.conf.cpu().numpy()
            c = r.boxes.cls.cpu().numpy().astype(int)
            for (x1, y1, x2, y2), sc, ci in zip(b, s, c):
                out.append(Detection(float(x1 + x0), float(y1 + y0), float(x2 + x0), float(y2 + y0), float(sc), self.names[ci]))
        self.timing = {"pre_ms": 0.0, "infer_ms": (t1 - t0) * 1000.0, "post_ms": 0.0}
        return out

    def _infer(self, lb):  # pragma: no cover - not used
        return np.zeros((0, 6))
