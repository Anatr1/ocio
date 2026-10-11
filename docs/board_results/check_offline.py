"""Run as root under nohup on the board. Restore the same Wi-Fi profile in finally.

Tests live capture/inference and MCU continuity, not walking counts without calibration.
Does not log Wi-Fi profile names, UUIDs, passwords or camera images.
"""
import json
import pathlib
import subprocess
import time
import urllib.request

BASE = "http://127.0.0.1:8000"


def sample():
    with urllib.request.urlopen(BASE + "/api/state", timeout=5) as response:
        state = json.load(response)
    carrier = pathlib.Path("/sys/class/net/wlan0/carrier").read_text().strip()
    return dict(utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                wlan_carrier=carrier, t=state["t"], perf=state["perf"],
                mcu={k: state["mcu"].get(k) for k in ["connected", "rtt_ms", "error"]})


uuid = subprocess.check_output(["nmcli", "-g", "GENERAL.CON-UUID", "device", "show", "wlan0"], text=True).strip()
if not uuid or uuid == "--":
    raise RuntimeError("No active Wi-Fi profile to restore; refusing offline test")
result = dict(conditions="Live uncalibrated ZED + NCNN 320/t4; no crossing/counting accuracy asserted",
              before=sample(), offline_samples=[])
try:
    subprocess.run(["nmcli", "--wait", "10", "device", "disconnect", "wlan0"],
                   check=True, stdout=subprocess.DEVNULL)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        result["offline_samples"].append(sample())
        time.sleep(5)
finally:
    restored = False
    for attempt in range(3):
        command = subprocess.run(["nmcli", "--wait", "30", "connection", "up", "uuid", uuid],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if command.returncode == 0:
            restored = True
            break
        time.sleep(5)
    result["wifi_restored"] = restored
    try:
        result["after"] = sample()
    finally:
        pathlib.Path("/home/arduino/occhio/docs/board_results/zed_offline.json").write_text(json.dumps(result, indent=2) + "\n")
    print("Wi-Fi restored:", restored, "local offline samples:", len(result["offline_samples"]), flush=True)
    if not restored:
        raise RuntimeError("Automatic reconnection failed after three attempts")
