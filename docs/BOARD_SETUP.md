# Arduino UNO Q bring-up

Facts gathered before the event (verify on the board): Debian 13 "trixie" aarch64, Python 3.13, user `arduino`,
SSH enabled by the App Lab first-run wizard, the MCU is reachable from Linux through the **arduino-router** at
`/var/run/arduino-router.sock` (MessagePack-RPC: `[0, id, method, params]`). QRB2210 = 4x Cortex-A53 @ 2.0 GHz,
Adreno 702, **no usable NPU** → inference on the CPU. A USB webcam needs a **powered USB-C hub**.

## 1. First boot
1. Connect hub (PD) → UNO Q, webcam on the hub, PD charger on the hub.
2. Laptop: install/open **Arduino App Lab**, connect the board by USB-C (or over the network), run the first-time
   wizard: board name, password, Wi-Fi (our travel router). This also enables SSH.
3. `ssh arduino@<board-name>.local` (or the IP shown by App Lab / router). If SSH is off:
   `adb shell` → `arduino-app-cli system network-mode enable`.
4. `sudo apt update` only if there is internet (not required).

## 2. Deploy OCCHIO
From the laptop (Git Bash):
```bash
tools/deploy.sh arduino@<ip> --wheels /c/Users/fedem/hackturin-offline/wheels-aarch64-cp313 --setup
```
`board_setup.sh` prints OS/Python/CPU/temperature, creates `~/occhio/.venv`, installs the deps (offline if `wheels/`
exists), tests the camera (fps) and pings the MCU.

If `python3 -m venv` is missing: `sudo apt install python3-venv python3-pip` (needs internet) or install deps with
`pip install --user --break-system-packages ...` as a last resort.

## 3. Pick the detector
```bash
cd ~/occhio
.venv/bin/python tools/bench.py --threads 2 3 4                       # all models in models/
.venv/bin/python tools/bench.py --models models/yolo26n_320_ncnn_model --threads 4 --sustained 120
.venv/bin/python tools/bench.py --camera 0                             # MJPG vs YUYV capture fps
```
Edit `configs/board.yaml` → `detector.backend/model/imgsz/threads`. Rule of thumb: leave one core free (threads 3).

## 4. MCU firmware
App Lab → copy `firmware/crosswalk_mcu` into your ArduinoApps folder (or create an app and paste `sketch.ino`) → Launch.
Then `~/occhio/.venv/bin/python tools/mcu_test.py` (and `--watchdog`). The Python side of the App only keeps the App
alive; the vision pipeline runs separately and talks to the sketch directly through the router socket.

If `Bridge.provide` signatures fail to compile on the installed library version, check the
`Arduino_RouterBridge` examples in App Lab (the API used: `Bridge.begin()`, `Bridge.provide(name, fn)`,
`Bridge.notify(name, value)`).

## 5. Run
```bash
cd ~/occhio && .venv/bin/python -m crosswalk --config configs/board.yaml
# phone/laptop: http://<ip>:8000   calibration: http://<ip>:8000/calibrate.html
```
Autostart (optional, Sunday): `crontab -e` → `@reboot cd /home/arduino/occhio && .venv/bin/python -m crosswalk --config configs/board.yaml >> runs/node.log 2>&1`
(or a systemd user service).

## 6. Useful checks
```bash
v4l2-ctl --list-devices; v4l2-ctl -d /dev/video0 --list-formats-ext
cat /sys/class/thermal/thermal_zone*/temp            # millidegrees
top -H -p $(pgrep -f "crosswalk")                     # per-thread CPU
systemctl status arduino-router
```
