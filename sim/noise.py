"""Fit empirical marginal detector errors. Correlated occlusions need G3 validation."""
import math


def fit_noise(report):
    if report.get("domain") != "real":
        raise ValueError("a site noise profile must be fitted on a real-labelled report")
    if not report.get("sampling", {}).get("representative"):
        raise ValueError("FP/min fitting requires representative sampling including empty frames")
    if report.get("label_policy") != "visible":
        raise ValueError("L1 fitting requires visible boxes to match the L2 mask definition")
    duration = report["detection"]["duration_s"]
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("invalid observation duration")
    bins, fp = {}, {}
    conditions = {":".join(key.split(":")[2:]) for key in report["detection"]["bins"]}
    if len(conditions) > 1:
        raise ValueError("fit one uniformly sampled condition at a time, with its own duration")
    for key, row in report["detection"]["bins"].items():
        if row["gt"]:
            bins[key] = {"miss": 1 - row["recall"], "gt_samples": row["gt"],
                         "edge_errors_rel": row["edge_errors_rel"], "scores": row["matched_scores"]}
        condition = ":".join(key.split(":")[2:])
        out = fp.setdefault(condition, {"per_minute": 0, "samples": []})
        out["per_minute"] += row["false_positives"] * 60 / duration
        out["samples"].extend(row.get("fp_samples", []))
    return {"version": 1, "fitted": True, "domain": "real", "model_hash": report["model_hash"],
            "detector_config": report["config"]["detector"], "score_threshold": report["detection"]["score_threshold"],
            "label_policy": report.get("label_policy"), "bins": bins, "false_positives": fp,
            "class_flip": 0, "fp_rate": 0,
            "limitations": "marginal misses/jitter/confidence; temporal correlation and class confusion are not fitted; G3 unassessed"}
