"""Emulate five SSE consumers on the board; not five phones or browser renderers."""
import json
import pathlib
import statistics
import threading
import time
import urllib.request

BASE = "http://127.0.0.1:8000"
stop = threading.Event()
clients = [{"state_events": 0, "max_state_gap_s": 0, "errors": []} for _ in range(5)]


def consume(index):
    previous = None
    try:
        with urllib.request.urlopen(BASE + "/api/stream", timeout=10) as response:
            for raw in response:
                if stop.is_set():
                    break
                if raw.startswith(b"event: state"):
                    now = time.monotonic()
                    if previous is not None:
                        clients[index]["max_state_gap_s"] = max(clients[index]["max_state_gap_s"], now - previous)
                    previous = now
                    clients[index]["state_events"] += 1
    except Exception as exc:
        clients[index]["errors"].append(str(exc))


def measure(seconds):
    samples = []
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        with urllib.request.urlopen(BASE + "/api/state", timeout=5) as response:
            state = json.load(response)
        samples.append(dict(wall=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            t=state["t"], perf=state["perf"], mcu={k: state["mcu"].get(k)
                                                               for k in ["connected", "rtt_ms", "error"]}))
        time.sleep(2)
    return samples


result = {"conditions": "Live uncalibrated ZED 1344x376 left eye, NCNN 320/t4; one laptop viewer plus five localhost SSE clients; uncontrolled desk scene"}
result["baseline_60s"] = measure(60)
threads = [threading.Thread(target=consume, args=(i,), daemon=True) for i in range(5)]
for thread in threads:
    thread.start()
result["five_extra_clients_120s"] = measure(120)
stop.set()
for thread in threads:
    thread.join(12)
result["recovery_30s"] = measure(30)
result["clients"] = clients
result["medians"] = {phase: {key: statistics.median(sample["perf"][key] for sample in result[phase]
                                                    if sample["perf"].get(key) is not None)
                              for key in ["cpu_pct", "infer_ms", "det_hz", "camera_fps"]}
                     for phase in ["baseline_60s", "five_extra_clients_120s", "recovery_30s"]}
pathlib.Path("docs/board_results/zed_viewer_load.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps({"medians": result["medians"], "clients": clients}, indent=2), flush=True)
