# OCCHIO - App Lab side.
#
# Two ways to run the vision pipeline on the UNO Q:
#   A) (recommended for development) launch this App once from App Lab to flash the sketch, then run the
#      pipeline over SSH:  cd ~/occhio && .venv/bin/python -m crosswalk --config configs/board.yaml
#      The pipeline talks to the sketch directly through /var/run/arduino-router.sock.
#   B) (appliance mode) set OCCHIO_DIR below and let this App start the pipeline itself, so the node comes up
#      on boot with the App.
#
# This file only needs to keep the App alive; the sketch keeps running and serving RPCs either way.
import os
import subprocess
import time

from arduino.app_utils import App, Bridge

OCCHIO_DIR = os.environ.get("OCCHIO_DIR", "")  # e.g. /home/arduino/occhio (appliance mode)
proc = None


def start_pipeline():
    global proc
    if not OCCHIO_DIR or not os.path.isdir(OCCHIO_DIR):
        print("[occhio] pipeline not managed by App Lab (run it over SSH)")
        return
    py = os.path.join(OCCHIO_DIR, ".venv", "bin", "python")
    if not os.path.exists(py):
        py = "python3"
    cfg = os.path.join(OCCHIO_DIR, "configs", "board.yaml")
    proc = subprocess.Popen([py, "-m", "crosswalk", "--config", cfg], cwd=OCCHIO_DIR)
    print("[occhio] pipeline started, pid", proc.pid)


def loop():
    global proc
    if proc is not None and proc.poll() is not None:
        print("[occhio] pipeline exited with", proc.returncode, "- restarting in 2 s")
        time.sleep(2)
        start_pipeline()
    time.sleep(1)


try:
    print("[occhio] MCU ping:", Bridge.call("ping"))
except Exception as e:  # noqa: BLE001
    print("[occhio] MCU not answering yet:", e)
start_pipeline()
App.run(user_loop=loop)
