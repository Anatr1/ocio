"""Read-only live-board evidence collector. Software evidence never substitutes for watching the outputs.

Run ON THE BOARD. This never sends a heartbeat, changes signal mode, or opens the camera.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import sys
import time
from urllib.error import HTTPError
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from crosswalk.mcu import RouterClient


def fetch(url, path):
    try:
        with urlopen(url.rstrip("/") + path, timeout=3) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)


def checks(config, health_code, health, state, status, allow_uncalibrated=False, profile="grove"):
    failures = []
    if config.get("source", {}).get("type") != "camera":
        failures.append("source is not a live local camera")
    detector = config.get("detector", {})
    if detector.get("backend") not in ("ncnn", "onnx", "tflite") or detector.get("model") in (None, "simulated"):
        failures.append("real neural-network detector is not configured")
    if config.get("mcu", {}).get("virtual") is not False:
        failures.append("MCU is virtual")
    if not allow_uncalibrated and not config.get("scene", {}).get("calibrated"):
        failures.append("camera is uncalibrated")
    if health_code != 200 or health.get("ok") is not True:
        failures.append("vision is stale or unhealthy")
    mcu = state.get("mcu", {})
    if mcu.get("connected") is not True or mcu.get("error"):
        failures.append("crosswalk MCU is disconnected or has an RPC error")
    if health.get("failsafe") is not False or mcu.get("failsafe") is not False:
        failures.append("Linux reports fail-safe")
    perf = state.get("perf", {})
    if not (perf.get("infer_ms", 0) > 0 and perf.get("det_runs", 0) > 0):
        failures.append("no measured inference yet")
    if not isinstance(status, list) or len(status) != 8 or status[0] != 1:
        failures.append("new firmware get_status RPC is unavailable or has an unknown schema")
    else:
        if status[1] != int(profile == "grove"):
            failures.append("wrong MCU hardware profile")
        if status[2] != 0 or not 0 <= status[7] <= 2000:
            failures.append("MCU watchdog is in fail-safe or has no recent heartbeat")
    return failures


def progress_checks(rows):
    if len(rows) < 2:
        return ["fewer than two successful samples; progress cannot be verified"]
    first, last = rows[0]["perf"], rows[-1]["perf"]
    failures = []
    for key in ("frames", "det_runs", "camera_frames"):
        if key in first and key in last and last[key] <= first[key]:
            failures.append(f"{key} did not advance")
        elif key in ("frames", "det_runs") and (key not in first or key not in last):
            failures.append(f"{key} progress is unavailable")
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--socket", default="/var/run/arduino-router.sock")
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--every", type=float, default=2)
    parser.add_argument("--profile", choices=("grove", "original"), default="grove")
    parser.add_argument("--allow-uncalibrated", action="store_true", help="bring-up only, not functional acceptance")
    parser.add_argument("--out", required=True, help="new JSONL file containing anonymous software evidence")
    args = parser.parse_args()
    if args.seconds <= 0 or not 0 < args.every <= min(60, args.seconds / 2):
        parser.error("use positive seconds and an interval <= 60 s and <= half the duration")
    path = Path(args.out)
    summary_path = path.with_suffix(".summary.json")
    if path.exists() or summary_path.exists():
        parser.error("evidence files already exist; choose a new output name")
    path.parent.mkdir(parents=True, exist_ok=True)
    rows, errors = [], []
    client = RouterClient(args.socket)
    start = time.monotonic()
    config = None
    with path.open("x", encoding="utf-8") as stream:
        while time.monotonic() - start < args.seconds:
            row = {"at": datetime.now(timezone.utc).isoformat(), "elapsed_s": round(time.monotonic() - start, 3)}
            try:
                _, config = fetch(args.url, "/api/config")
                health_code, health = fetch(args.url, "/api/health")
                _, state = fetch(args.url, "/api/state")
                if not client.alive:
                    client.close()
                    client = RouterClient(args.socket)
                    client.connect()
                status = client.call("get_status")
                failures = checks(config, health_code, health, state, status, args.allow_uncalibrated, args.profile)
                row.update(source=config.get("source"), detector=config.get("detector"),
                           calibrated=config.get("scene", {}).get("calibrated"), virtual=config.get("mcu", {}).get("virtual"),
                           health_http=health_code, health=health, perf=state.get("perf", {}),
                           signal=state.get("signal"), counts=state.get("counts"), mcu=state.get("mcu"),
                           warning_level=state.get("safety", {}).get("warning_level"), firmware_status=status,
                           failures=failures)
                rows.append(row)
                errors.extend(failures)
                print(f"{row['elapsed_s']:6.1f}s frames={row['perf'].get('frames')} infer={row['perf'].get('infer_ms')}ms "
                      f"MCU={status[2:6] if isinstance(status, list) else status} "
                      f"{'OK' if not failures else '; '.join(failures)}", flush=True)
            except Exception as exc:
                row["error"] = str(exc)
                errors.append(str(exc))
                print(f"{row['elapsed_s']:6.1f}s ERROR: {exc}", flush=True)
            stream.write(json.dumps(row) + "\n")
            stream.flush()
            time.sleep(min(args.every, max(0, args.seconds - (time.monotonic() - start))))
    client.close()
    errors.extend(progress_checks(rows))
    performance = {}
    for key in ("det_hz", "infer_ms", "decision_ms", "cpu_pct", "cpu_temp_c", "mem_used_mb"):
        values = [r["perf"][key] for r in rows if isinstance(r["perf"].get(key), (int, float))]
        if values:
            performance[key] = {"min": min(values), "median": statistics.median(values), "max": max(values)}
    summary = {"software_checks_passed": not errors, "functional_acceptance": False,
               "physical_outputs": "UNMEASURED: operator must verify LEDs, buzzer and OLED",
               "allow_uncalibrated": args.allow_uncalibrated, "profile": args.profile,
               "requested_seconds": args.seconds, "elapsed_seconds": round(time.monotonic() - start, 3),
               "samples": len(rows), "failures": sorted(set(errors)), "performance": performance}
    with summary_path.open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2)
        stream.write("\n")
    print(f"Software checks {'PASS' if not errors else 'FAIL'}; physical acceptance still requires the operator. {summary_path}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
