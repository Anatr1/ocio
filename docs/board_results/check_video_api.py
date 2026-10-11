"""Run on the board after starting the VIDEO fallback on port 8002. Saves JSON, never images."""
import json
import pathlib
import time
import urllib.request

base = "http://127.0.0.1:8002"
out = pathlib.Path("docs/board_results/video_api.json")


def get(path):
    with urllib.request.urlopen(base + path, timeout=5) as response:
        return json.load(response)


def post(path, data=None):
    request = urllib.request.Request(base + path, json.dumps(data or {}).encode(),
                                     {"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)


result = {"source": "public sample VIDEO, not live IMX219", "health": get("/api/health"),
          "config": get("/api/config"), "state_before": get("/api/state")}
share = get("/api/share")
result["share"] = {"url": share["url"], "svg_present": bool(share.get("svg"))}
result["adaptive_mode"] = post("/api/mode", {"mode": "adaptive"})
result["call"] = post("/api/ped_request")
states = []
deadline = time.monotonic() + 65
while time.monotonic() < deadline:
    state = get("/api/state")
    states.append({"t": state["t"], "signal": state["signal"], "mcu": state["mcu"],
                   "counts": state["counts"]["counts"], "perf": state["perf"]})
    time.sleep(1)
result["call_observations"] = states
result["events"] = get("/api/events?since=0")
result["restore_beacon"] = post("/api/mode", {"mode": "beacon"})
result["state_after"] = get("/api/state")
out.write_text(json.dumps(result, indent=2) + "\n")
print("saved", out, "signal rules:", sorted({(s["signal"].get("rule") or {}).get("id") or "" for s in states}))
