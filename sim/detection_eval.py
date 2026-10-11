"""Identical class/size/condition scoring for labelled real or rendered frames."""
from collections import defaultdict

import numpy as np
from scipy.optimize import linear_sum_assignment


def height_bin(height):
    return "small" if height < 30 else "medium" if height < 80 else "large"


def iou(a, b):
    overlap = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    total = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - overlap
    return overlap / max(total, 1e-9)


def bin_key(label, condition):
    return f"{label['cls']}:{height_bin(label['box'][3] - label['box'][1])}:{condition}"


def match_boxes(labels, predictions, threshold=0.5):
    if not labels or not predictions:
        return []
    scores = np.array([[iou(g["box"], p["box"]) if g["cls"] == p["cls"] else 0
                        for p in predictions] for g in labels])
    valid = scores >= threshold
    objective = valid * (1 + scores / (max(scores.shape) + 1))
    return [(int(i), int(j), float(scores[i, j])) for i, j in zip(*linear_sum_assignment(-objective)) if valid[i, j]]


class DetectionEvaluator:
    def __init__(self, score_threshold=0.35, iou_threshold=0.5):
        self.score_threshold, self.iou_threshold = score_threshold, iou_threshold
        self.frames = []

    def observe(self, t, labels, predictions, condition, image_size=None):
        gt = [dict(g) for g in labels if g.get("box") and g.get("pixels", 1) > 0]
        for label in gt:
            if label.get("kind") == "pedestrian":
                label["cls"] = "person"
        pred = [dict(p) for p in predictions if p["score"] >= self.score_threshold]
        matched = match_boxes(gt, pred, self.iou_threshold)
        self.frames.append({"t": t, "condition": condition, "ground_truth": gt, "predictions": pred,
                            "image_size": image_size,
                            "matches": [{"gt": i, "pred": j, "iou": overlap} for i, j, overlap in matched]})

    def summarize(self, duration):
        bins = defaultdict(lambda: {"gt": 0, "matched_gt": 0, "predicted": 0, "matched_predicted": 0,
                                    "scores": [], "matched_scores": [], "edge_errors_rel": [], "fp_samples": []})
        for frame in self.frames:
            condition, gt, pred = frame["condition"], frame["ground_truth"], frame["predictions"]
            for g in gt:
                bins[bin_key(g, condition)]["gt"] += 1
            for p in pred:
                row = bins[bin_key(p, condition)]
                row["predicted"] += 1
                row["scores"].append(p["score"])
            for m in frame["matches"]:
                g, p = gt[m["gt"]], pred[m["pred"]]
                row = bins[bin_key(g, condition)]
                row["matched_gt"] += 1
                row["matched_scores"].append(p["score"])
                bins[bin_key(p, condition)]["matched_predicted"] += 1
                scale = np.array([g["box"][2] - g["box"][0], g["box"][3] - g["box"][1]] * 2)
                row["edge_errors_rel"].append(((np.array(p["box"]) - g["box"]) / np.maximum(1, scale)).tolist())
            matched_indices = {m["pred"] for m in frame["matches"]}
            if frame.get("image_size"):
                w, h = frame["image_size"]
                for i, p in enumerate(pred):
                    if i not in matched_indices:
                        bins[bin_key(p, condition)]["fp_samples"].append({"box_rel": (np.array(p["box"]) / [w, h, w, h]).tolist(),
                          "score": p["score"], "cls": p["cls"]})
        false_positives = 0
        for row in bins.values():
            row["recall"] = row["matched_gt"] / row["gt"] if row["gt"] else None
            row["precision"] = row["matched_predicted"] / row["predicted"] if row["predicted"] else None
            row["false_positives"] = row["predicted"] - row["matched_predicted"]
            false_positives += row["false_positives"]
        return {"bins": dict(bins), "frames": len(self.frames), "duration_s": duration,
                "false_positives": false_positives, "fp_per_minute": false_positives * 60 / max(duration, 1e-6),
                "score_threshold": self.score_threshold, "iou_threshold": self.iou_threshold,
                "box_policy": "visible mask silhouettes; fully hidden/offscreen agents excluded",
                "precision_binning": "predicted box height; recall binning uses GT box height"}


class RecordingDetector:
    """Observe raw NN predictions before rider fusion; GT is never passed to the NN."""
    def __init__(self, detector, source, scorer):
        self.detector, self.source, self.scorer = detector, source, scorer

    def __getattr__(self, name):
        return getattr(self.detector, name)

    def __call__(self, frame):
        detections = self.detector(frame)
        condition = self.source.spec["conditions"]
        t = self.source.frame_meta.get("t")
        if t is None:
            t = self.source.world.t
        self.scorer.observe(t, self.source.frame_meta["boxes"],
                            [d.to_dict() for d in detections], f"{condition['time_of_day']}:{condition['weather']}",
                            [self.source.width, self.source.height])
        return detections
