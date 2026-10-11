#!/bin/sh
# Temporary software read-failure test on CAM0. Production systemd service is restored on exit.
set -eu
cd /home/arduino/occhio
occhio_fault_pid=""
cleanup() {
  rm -f /tmp/occhio-cam0-read-failure
  if [ -n "$occhio_fault_pid" ]; then
    kill -TERM "$occhio_fault_pid" 2>/dev/null || true
    wait "$occhio_fault_pid" 2>/dev/null || true
  fi
  sudo systemctl start occhio.service
}
trap cleanup EXIT
sudo systemctl stop occhio.service
PYTHONPATH=/home/arduino/occhio/docs/board_results/camera_fault_hook \
  libcamerify .venv/bin/python -u -m crosswalk --config configs/board_imx219.yaml \
  > docs/board_results/autostart_cam0_fault_node.log 2>&1 < /dev/null &
occhio_fault_pid=$!
.venv/bin/python - <<'PY'
import json, time, urllib.request
deadline = time.monotonic() + 30
while time.monotonic() < deadline:
    try:
        with urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=1) as response:
            health = json.load(response)
        if health.get('ok') and health.get('mcu_connected') and not health.get('failsafe'):
            break
    except Exception:
        pass
    time.sleep(0.25)
else:
    raise SystemExit('Temporary CAM0 test node did not become healthy within 30 s')
PY
.venv/bin/python -u docs/board_results/check_autostart_fault.py camera --pid "$occhio_fault_pid" \
  --out docs/board_results/autostart_cam0_fault.jsonl
