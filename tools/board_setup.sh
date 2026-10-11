#!/usr/bin/env bash
# Run ON the Arduino UNO Q (Debian, aarch64) inside ~/occhio. Idempotent.
#   bash tools/board_setup.sh
set -uo pipefail
cd "$(dirname "$0")/.."
echo "== system"
cat /etc/os-release 2>/dev/null | grep PRETTY_NAME
uname -m
python3 --version
nproc
grep -m1 -i "model name\|CPU part" /proc/cpuinfo || true
free -m | head -2
for z in /sys/class/thermal/thermal_zone*/temp; do echo "$z: $(( $(cat "$z") / 1000 ))C"; done 2>/dev/null | head -4

echo "== python venv"
if [[ ! -d .venv ]]; then
  python3 -m venv --system-site-packages .venv || { echo "need: sudo apt install python3-venv"; exit 1; }
fi
PIP=".venv/bin/pip"
if [[ -d wheels ]] && ls wheels/*.whl >/dev/null 2>&1; then
  echo "installing from offline wheels"
  $PIP install --no-index --find-links wheels numpy opencv-python-headless onnxruntime msgpack pyyaml scipy segno
  $PIP install --no-index --find-links wheels --no-deps ncnn || true
else
  $PIP install --upgrade pip
  $PIP install -r requirements-board.txt
  $PIP install --no-deps ncnn || echo "ncnn not available (optional)"
  $PIP install scipy || echo "scipy not available (optional)"
fi
.venv/bin/python - <<'EOF'
import importlib
for m in ("numpy", "cv2", "onnxruntime", "msgpack", "yaml", "scipy", "ncnn"):
    try:
        mod = importlib.import_module(m)
        print(f"  ok  {m:12s} {getattr(mod, '__version__', '')}")
    except Exception as e:
        print(f"  --  {m:12s} {e}")
EOF

echo "== camera"
ls -l /dev/video* 2>/dev/null || echo "no /dev/video* - is the webcam on a POWERED USB-C hub?"
command -v v4l2-ctl >/dev/null && v4l2-ctl --list-devices 2>/dev/null | head -20
.venv/bin/python - <<'EOF'
import cv2, time
cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640); cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480); cap.set(cv2.CAP_PROP_FPS, 30)
ok, f = cap.read()
if not ok:
    print("  camera read FAILED")
else:
    n, t = 0, time.time()
    while time.time() - t < 3:
        ok, f = cap.read(); n += ok
    print(f"  camera ok {f.shape[1]}x{f.shape[0]} @ {n/3:.1f} fps (MJPG decode on CPU)")
    cv2.imwrite("runs/camera_test.jpg", f) if __import__("os").makedirs("runs", exist_ok=True) is None else None
cap.release()
EOF

echo "== MCU link"
if [[ -S /var/run/arduino-router.sock ]]; then
  echo "  arduino-router socket present"
  .venv/bin/python - <<'EOF'
from crosswalk.mcu import RouterClient
try:
    c = RouterClient(); c.connect(); print("  MCU ping ->", c.call("ping"))
except Exception as e:
    print("  MCU not answering (flash firmware/crosswalk_mcu with App Lab):", e)
EOF
else
  echo "  no /var/run/arduino-router.sock (is arduino-router running? systemctl status arduino-router)"
fi
echo "== done. next: .venv/bin/python tools/bench.py   then   .venv/bin/python tools/calibrate.py --camera 0"
