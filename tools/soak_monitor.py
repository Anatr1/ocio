"""Sample a running node's /api/state into a CSV (soak / thermal / stability test) and print a summary.

    python tools/soak_monitor.py --url http://localhost:8000 --minutes 30 --every 5 \
        --out docs/board_results/soak_30min.csv
Run it ON THE BOARD (localhost) or from a laptop on the same network. Stdlib only.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import time
import urllib.request

FIELDS = ["wall", "t", "det_hz", "infer_ms", "det_ms", "decision_ms", "pipeline_ms", "loop_fps", "camera_fps", "duty",
          "cpu_pct", "cpu_temp_c", "mem_used_mb", "load1", "tracks", "ped", "bike", "micro", "veh", "warning_level",
          "beacon_rule", "signal_rule", "mcu_connected", "mcu_rtt_ms", "mcu_error"]


def sample(url):
    with urllib.request.urlopen(url.rstrip("/") + "/api/state", timeout=5) as r:
        s = json.loads(r.read().decode())
    p = s.get("perf", {})
    c = s.get("counts", {}).get("counts", {})
    m = s.get("mcu", {}) or {}
    return {
        "wall": time.strftime("%H:%M:%S"), "t": s.get("t"), "det_hz": p.get("det_hz"), "infer_ms": p.get("infer_ms"),
        "det_ms": p.get("det_ms"), "decision_ms": p.get("decision_ms"), "pipeline_ms": p.get("pipeline_ms"),
        "loop_fps": p.get("loop_fps"), "camera_fps": p.get("camera_fps"), "duty": p.get("duty"),
        "cpu_pct": p.get("cpu_pct"), "cpu_temp_c": p.get("cpu_temp_c"), "mem_used_mb": p.get("mem_used_mb"),
        "load1": p.get("load1"), "tracks": len(s.get("tracks", [])), "ped": c.get("pedestrian"), "bike": c.get("bicycle"),
        "micro": c.get("micromobility"), "veh": c.get("vehicle"),
        "warning_level": s.get("safety", {}).get("warning_level"),
        "beacon_rule": (s.get("safety", {}).get("beacon_rule") or {}).get("id"),
        "signal_rule": (s.get("signal", {}).get("rule") or {}).get("id"),
        "mcu_connected": m.get("connected"), "mcu_rtt_ms": m.get("rtt_ms"), "mcu_error": m.get("error"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--minutes", type=float, default=30)
    ap.add_argument("--every", type=float, default=5)
    ap.add_argument("--out", default="docs/board_results/soak.csv")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    rows, fails = [], 0
    t_end = time.time() + a.minutes * 60
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        while time.time() < t_end:
            try:
                r = sample(a.url)
                rows.append(r)
                w.writerow(r)
                f.flush()
                print(f"{r['wall']} det {r['det_hz']} Hz infer {r['infer_ms']} ms cpu {r['cpu_pct']}% "
                      f"{r['cpu_temp_c']}C mem {r['mem_used_mb']} MB tracks {r['tracks']} mcu {r['mcu_connected']}")
            except Exception as e:  # noqa: BLE001
                fails += 1
                print("sample failed:", e)
            time.sleep(a.every)

    def stat(k):
        v = [float(r[k]) for r in rows if r.get(k) not in (None, "")]
        if not v:
            return "n/a"
        return f"min {min(v):.1f} / median {statistics.median(v):.1f} / max {max(v):.1f}"

    print("\n## Soak summary")
    print(f"samples {len(rows)}, failed requests {fails}")
    for k in ("det_hz", "infer_ms", "decision_ms", "loop_fps", "camera_fps", "duty", "cpu_pct", "cpu_temp_c", "mem_used_mb"):
        print(f"- {k}: {stat(k)}")


if __name__ == "__main__":
    main()
