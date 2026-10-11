"""Sim-to-real gates cannot pass on synthetic evidence alone or missing bins."""
import math
from scipy.stats import spearmanr


def detector_signature(report):
    cfg = report["config"]["detector"]
    return {k: cfg.get(k) for k in ("backend", "imgsz", "conf", "conf_low", "iou", "roi", "class_names")}


def compare_detection(simulated, real, minimum=30):
    if not isinstance(minimum, int) or minimum <= 0:
        raise ValueError("minimum observations must be a positive integer")
    if real.get("domain") != "real" or simulated.get("level") != "L2":
        raise ValueError("G2 requires actual L2 pixels and a real-labelled reference")
    if simulated.get("render", {}).get("presentation_mode"):
        raise ValueError("presentation mode is not evaluation evidence")
    if not real.get("model_hash") or real.get("model_hash") != simulated.get("model_hash") or detector_signature(real) != detector_signature(simulated):
        raise ValueError("G2 requires the identical detector model and preprocessing configuration")
    if real.get("label_policy") != "visible" or not real.get("sampling", {}).get("representative"):
        raise ValueError("the reference must use reviewed visible boxes and representative sampling")
    sim, ref = simulated["detection"], real["detection"]
    if (sim.get("score_threshold"), sim.get("iou_threshold")) != (ref.get("score_threshold"), ref.get("iou_threshold")):
        raise ValueError("G2 scoring thresholds must match")
    for r in (sim, ref):
        if not math.isfinite(r["duration_s"]) or r["duration_s"] <= 0 or r["frames"] <= 0:
            raise ValueError("G2 requires a nonempty, finite observation duration")
    rows = []
    for key in sorted(sim["bins"].keys() | ref["bins"].keys()):
        a, b = sim["bins"].get(key, {}), ref["bins"].get(key, {})
        if not a.get("gt", 0) and not b.get("gt", 0):
            continue
        enough = min(a.get("gt", 0), b.get("gt", 0)) >= minimum
        gap = a["recall"] - b["recall"] if enough else None
        rows.append({"bin": key, "sim_gt": a.get("gt", 0), "real_gt": b.get("gt", 0), "recall_gap": gap,
                     "sim_precision": a.get("precision"), "real_precision": b.get("precision"),
                     "status": "UNASSESSED" if not enough else "PASS" if abs(gap) <= 0.1 + 1e-9 else "FAIL"})
    # A per-minute rate is only comparable at the same raw-detector sampling rate.
    sim_hz = sim["frames"] / sim["duration_s"]
    ref_hz = ref["frames"] / ref["duration_s"]
    comparable = abs(sim_hz / ref_hz - 1) <= 0.1
    a, b = sim["fp_per_minute"], ref["fp_per_minute"]
    fp_pass = (a == b == 0) or min(a, b) > 0 and max(a, b) / min(a, b) <= 10
    fp = {"sim_per_minute": a, "real_per_minute": b, "sim_sample_hz": sim_hz, "real_sample_hz": ref_hz,
          "status": "UNASSESSED" if not comparable else "PASS" if fp_pass else "FAIL"}
    statuses = [r["status"] for r in rows] + [fp["status"]]
    status = "FAIL" if "FAIL" in statuses else "PASS" if rows and all(s == "PASS" for s in statuses) else "UNASSESSED"
    return {"gate": "G2", "status": status, "bins": rows, "false_positives": fp, "minimum_observations_per_bin": minimum,
            "limitations": "PASS covers observed bins only, not unseen classes/conditions; adjacent frames are correlated"}


def decision_transfer(rows):
    if len(rows) < 3 or len({r["config_hash"] for r in rows}) != len(rows):
        raise ValueError("G6 needs at least three distinct configurations paired between sim and real")
    sim, real = [r["sim_accuracy"] for r in rows], [r["real_accuracy"] for r in rows]
    if not all(math.isfinite(v) for v in sim + real):
        raise ValueError("rank scores must be finite")
    if len(set(sim)) < 2 or len(set(real)) < 2:
        return {"gate": "G6", "status": "UNASSESSED", "reason": "constant ranks do not establish transfer", "n": len(rows)}
    result = spearmanr(sim, real)
    rho = float(result[0])  # SciPy < 1.9 has no .statistic; the tuple form works everywhere
    return {"gate": "G6", "status": "UNASSESSED", "rho": rho,
            "p_value": float(result.pvalue), "n": len(rows), "criterion_met": rho >= 0.8,
            "evidence": "supplied rank scores; paired underlying reports have not been verified, so this is not certification"}
