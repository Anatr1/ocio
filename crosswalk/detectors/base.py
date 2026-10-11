"""Detector interface + shared YOLO pre/post-processing (pure numpy, board-friendly)."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


@dataclass
class Detection:
    x1: float
    y1: float
    x2: float
    y2: float
    score: float
    cls: str                     # fine class name, e.g. "person", "car", "bicycle"
    kind: str = ""               # coarse kind: pedestrian | bicycle | vehicle | micromobility
    ridden: bool = False         # bicycle/motorcycle with a rider merged in
    world: tuple | None = None   # (X, Y) ground position in metres
    cov: np.ndarray | None = None  # 2x2 measurement covariance (m^2)
    height_m: float | None = None
    extra: dict = field(default_factory=dict)

    @property
    def foot(self):
        return ((self.x1 + self.x2) * 0.5, self.y2)

    @property
    def w(self):
        return self.x2 - self.x1

    @property
    def h(self):
        return self.y2 - self.y1

    def to_dict(self):
        return {
            "box": [round(self.x1, 1), round(self.y1, 1), round(self.x2, 1), round(self.y2, 1)],
            "score": round(float(self.score), 3),
            "cls": self.cls,
            "kind": self.kind,
            "ridden": self.ridden,
            "world": None if self.world is None else [round(float(self.world[0]), 2), round(float(self.world[1]), 2)],
        }


COCO80 = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat", "traffic light",
    "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
    "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove", "skateboard", "surfboard",
    "tennis racket", "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
    "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote", "keyboard",
    "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase",
    "scissors", "teddy bear", "hair drier", "toothbrush",
]


def letterbox(img: np.ndarray, size: int, color=(114, 114, 114)):
    """Resize keeping aspect ratio and pad to size x size. Returns (img, scale, (padx, pady))."""
    h, w = img.shape[:2]
    s = min(size / h, size / w)
    nh, nw = int(round(h * s)), int(round(w * s))
    if (nh, nw) != (h, w):
        img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    px, py = (size - nw) // 2, (size - nh) // 2
    out = np.full((size, size, 3), color, dtype=np.uint8)
    out[py : py + nh, px : px + nw] = img
    return out, s, (px, py)


def nms(boxes: np.ndarray, scores: np.ndarray, iou: float) -> np.ndarray:
    """Plain greedy NMS. boxes Nx4 xyxy. Returns kept indices."""
    if len(boxes) == 0:
        return np.zeros(0, dtype=int)
    x1, y1, x2, y2 = boxes.T
    areas = (x2 - x1).clip(0) * (y2 - y1).clip(0)
    order = scores.argsort()[::-1]
    keep = []
    while order.size:
        i = order[0]
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = (xx2 - xx1).clip(0) * (yy2 - yy1).clip(0)
        ov = inter / (areas[i] + areas[order[1:]] - inter + 1e-9)
        order = order[1:][ov <= iou]
    return np.asarray(keep, dtype=int)


def decode_yolo(out: np.ndarray, conf: float, iou: float, keep_ids: set | None, imgsz: int, nc: int | None = None) -> np.ndarray:
    """Decode Ultralytics YOLO raw output to an Nx6 array [x1,y1,x2,y2,score,cls] in letterbox pixels.

    Handles:
      * v8/v11 style  (1, 4+nc, N) or (N, 4+nc)  - xywh centre + class scores, needs NMS
      * end-to-end    (1, K, 6) or (K, 6)         - YOLO26 / v10 NMS-free head, xyxy+score+cls
    ``nc`` (number of classes) disambiguates the layout; without it a shape heuristic is used.
    """
    a = np.asarray(out, dtype=np.float32)
    if a.ndim == 3:
        a = a[0]
    if a.ndim != 2:
        raise ValueError(f"unexpected output shape {out.shape}")
    feat = 4 + nc if nc else None
    is_e2e = a.shape[1] in (6, 7) and (a.shape[0] != feat if feat else (a.shape[0] >= a.shape[1] and a.shape[0] <= 1000))
    if is_e2e:  # end-to-end
        det = a[:, :6]
        if det[:, :4].max() <= 2.0:  # normalised coords (tflite)
            det = det.copy()
            det[:, :4] *= imgsz
        det = det[det[:, 4] >= conf]
        if keep_ids is not None:
            det = det[np.isin(det[:, 5].astype(int), list(keep_ids))]
        return det
    if feat:
        if a.shape[0] != feat and a.shape[1] == feat:  # (N, 4+nc) -> (4+nc, N)
            a = a.T
    elif a.shape[0] > a.shape[1]:  # heuristic: anchors outnumber features
        a = a.T
    boxes = a[:4].T
    scores_all = a[4:].T
    cls = scores_all.argmax(1)
    scores = scores_all[np.arange(len(cls)), cls]
    m = scores >= conf
    if keep_ids is not None:
        m &= np.isin(cls, list(keep_ids))
    boxes, scores, cls = boxes[m], scores[m], cls[m]
    if len(boxes) == 0:
        return np.zeros((0, 6), dtype=np.float32)
    if boxes.max() <= 2.0:  # normalised (tflite)
        boxes = boxes * imgsz
    xyxy = np.column_stack(
        [boxes[:, 0] - boxes[:, 2] / 2, boxes[:, 1] - boxes[:, 3] / 2, boxes[:, 0] + boxes[:, 2] / 2, boxes[:, 1] + boxes[:, 3] / 2]
    )
    # class-aware NMS via coordinate offset trick
    off = cls[:, None].astype(np.float32) * 4096.0
    keep = nms(xyxy + off, scores, iou)
    return np.column_stack([xyxy[keep], scores[keep], cls[keep].astype(np.float32)])


class Detector:
    """Base class: subclasses implement ``_infer(blob) -> raw output``."""

    backend = "base"

    def __init__(self, cfg):
        self.cfg = cfg
        self.imgsz = int(cfg.get("imgsz", 320))
        self.conf_low = float(cfg.get("conf_low", 0.15))
        self.conf = float(cfg.get("conf", 0.35))
        self.iou = float(cfg.get("iou", 0.5))
        self.roi = cfg.get("roi")
        self.names: list[str] = list(cfg.get("class_names") or COCO80)
        self.keep_names = {"person", "bicycle", "car", "motorcycle", "bus", "truck", "e-scooter", "scooter",
                           "pedestrian", "cyclist", "wheelchair", "stroller", "van"}
        self.timing = {"pre_ms": 0.0, "infer_ms": 0.0, "post_ms": 0.0}

    def keep_ids(self):
        return {i for i, n in enumerate(self.names) if n in self.keep_names}

    def preprocess(self, frame):
        x0 = y0 = 0
        img = frame
        if self.roi:
            x0, y0, w, h = [int(v) for v in self.roi]
            img = frame[y0 : y0 + h, x0 : x0 + w]
        lb, s, (px, py) = letterbox(img, self.imgsz)
        return lb, (s, px, py, x0, y0)

    def to_blob_nchw(self, lb):
        return np.ascontiguousarray(lb[:, :, ::-1].transpose(2, 0, 1)[None], dtype=np.float32) * (1.0 / 255.0)

    def _infer(self, lb) -> np.ndarray:  # pragma: no cover - abstract
        raise NotImplementedError

    def __call__(self, frame) -> list[Detection]:
        t0 = time.perf_counter()
        lb, meta = self.preprocess(frame)
        t1 = time.perf_counter()
        out = self._infer(lb)
        t2 = time.perf_counter()
        dets = self.postprocess(out, meta, frame.shape)
        t3 = time.perf_counter()
        a = 0.2
        for k, v in (("pre_ms", t1 - t0), ("infer_ms", t2 - t1), ("post_ms", t3 - t2)):
            self.timing[k] = (1 - a) * self.timing[k] + a * v * 1000.0 if self.timing[k] else v * 1000.0
        return dets

    def postprocess(self, out, meta, shape) -> list[Detection]:
        s, px, py, x0, y0 = meta
        det = decode_yolo(out, self.conf_low, self.iou, self.keep_ids(), self.imgsz, nc=len(self.names))
        H, W = shape[:2]
        res = []
        for x1, y1, x2, y2, sc, c in det:
            x1 = (x1 - px) / s + x0
            x2 = (x2 - px) / s + x0
            y1 = (y1 - py) / s + y0
            y2 = (y2 - py) / s + y0
            x1, x2 = max(0.0, x1), min(W - 1.0, x2)
            y1, y2 = max(0.0, y1), min(H - 1.0, y2)
            if x2 - x1 < 2 or y2 - y1 < 2:
                continue
            ci = int(c)
            name = self.names[ci] if 0 <= ci < len(self.names) else str(ci)
            res.append(Detection(float(x1), float(y1), float(x2), float(y2), float(sc), name))
        return res
