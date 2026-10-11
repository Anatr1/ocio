# Handoff: live IMX219 -> real NN -> Grove outputs on UNO Q

**Branch: `codex/live-board-gpio`, based on master `e2c61bf`.**
**Results: `docs/board_results/LIVE_GPIO_RESULTS.md` plus anonymous evidence there.**

This is the current hardware task. Read this handoff first; the older
`HANDOFF_BOARD.md` uses a ZED and different wiring. The IMX219 on CAM0 through
`libcamerify` remains the deployment camera. Work in small steps with the
electronics operator, commit measured results on this branch, and push only
when Federico asks. Keep detector, tracking, counting and signal-policy
decisions unchanged unless a demonstrated bug requires a focused fix.

## What was found and prepared on the laptop

The only unmerged remote branch, `origin/codex/setup-GPIO-app` (`21f2aeb`), is an
independent five-file App Lab app with unrelated Git history. Its entire contents
already exist byte-for-byte in master as `firmware/grove_oled_buzzer_test/`.
Merging its root tree would put app files at the repository root; it is unnecessary.
Keep that app as an isolated wiring reference/recovery tool.

That test cycles LEDs on a clock, beeps once and displays random values. It has
no crosswalk RPCs. Running it beside a healthy camera cannot prove integrated
deployment. The new packaged Grove profile uses the production MCU sketch,
its signal RPCs and two-second watchdog, with the same physical wiring.
No camera, detector, counter, tracker or signal algorithm was changed.

Linux MCU readiness now requires a working `ping` RPC. `mcu.enabled=true` refuses
silent virtual fallback if the socket is absent; `auto` remains suitable for
laptop modes. Failed connection attempts close their client and retry in the
worker. A new read-only `get_status` RPC identifies the profile and effective
watchdog/signal state. The evidence collector never supplies heartbeats.

The repository also includes host execution tests of the actual sketch with
fake peripherals. These check both pin profiles, normal outputs, warning
blinks, passive waveform slices, audio shutdown and watchdog recovery. They
cannot establish Arduino/Zephyr compilation, I2C operation, electrical behaviour,
sound quality or physical timing.

## 1. Get the branch and preserve the board's current deployment

Federico must first make this locally committed branch available to your laptop
(push or transfer a Git bundle). On your laptop, fetch and check out the branch:

```bash
git fetch origin
git switch --track origin/codex/live-board-gpio
git status --short
git rev-parse HEAD
```

If the branch already exists locally, use `git switch codex/live-board-gpio`
and `git pull --ff-only` instead. Do not reset unrelated local edits.

Record the commit, existing firmware/app name, running processes, calibration
file and `/etc/default/occhio` in the results. On the board:

```bash
systemctl status occhio occhio-mcu --no-pager
cat /etc/default/occhio
arduino-app-cli app list
pgrep -af 'python.*crosswalk'
uname -a
python3 --version
```

Stop the vision service before copying code or running a direct MCU test:

```bash
sudo systemctl stop occhio occhio-mcu
```

Stopping the oneshot MCU service does not necessarily stop its App Lab app.
Use `arduino-app-cli app stop <EXACT_ACTIVE_APP_PATH>` for the actual running
test/crosswalk app reported above. Do not run two App Lab apps or two camera
pipelines. Leave `.venv`, `models/`, recordings, site calibration and `data/stats/`
in place. Copy the old environment file, active app and measured config to a
dated backup before changing them. Back up the stats directory after vision
has stopped so the SQLite/WAL files form a consistent set.

For example, after stopping the services/apps, on the board:

```bash
BACKUP="$HOME/occhio-before-grove-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP"
sudo cp /etc/default/occhio "$BACKUP/occhio.env"
cp -a ~/occhio/configs "$BACKUP/configs"
if [ -d ~/occhio/data/stats ]; then cp -a ~/occhio/data/stats "$BACKUP/stats"; fi
```

Also copy the exact active App Lab folder reported by `app list` to this backup.
Keep this backup on the board; it is not a Git deliverable.

In Git Bash on the laptop, transfer **tracked code only**, including new tools,
headers and deploy files (this excludes private recordings and ignored weights):

```bash
mkdir -p runs
git archive --format=tar --output=runs/live-board-code.tar HEAD
scp runs/live-board-code.tar arduino@<BOARD_IP>:/home/arduino/live-board-code.tar
ssh arduino@<BOARD_IP>
```

Then on the board:

```bash
mkdir -p ~/occhio
tar xf ~/live-board-code.tar -C ~/occhio
cd ~/occhio
.venv/bin/python -c 'import cv2, ncnn, numpy, msgpack, yaml; print("board dependencies OK")'
```

Extraction overwrites tracked code but does not remove existing `.venv`, weights,
recordings or public statistics. Keep the old site-specific calibration file;
do not use `site.yaml` for a newly positioned live camera. Do not run the old
deploy script with model weights merely to refresh this code.

## 2. Confirm the actual wiring before flashing

This pin assignment has priority over the original crosswalk pin table.
Updated 2026-10-11 after the operator reported swapped green/yellow during the
live physical test; the isolated standalone timer app retains its old mapping:

| Grove connection | Output |
|---|---|
| Shield switch | 3.3 V |
| D2 socket, yellow wire | Yellow vehicle LED, D2 |
| D2 socket, white wire | Green vehicle LED, D3 |
| D6 socket, yellow wire | Red vehicle LED, D6 |
| D6 socket, white wire | White alert LED, D7 |
| D4 socket | Passive buzzer, D4 |
| I2C socket | 128x64 OLED using the existing SSD1315/SSD1306 U8g2 driver |

Use one 330-ohm resistor per LED and common ground, as in the standalone app.
Do not put the original firmware on this wiring: its D4 vehicle-green output
would drive the buzzer, and its D6 pedestrian-green output would drive red.
Do not add an assumed pedestrian LED, red beacon or button on an occupied pin.
Record the OLED/module identification and wiring photo. SSD1308 requires separate
verification. Power down before moving wiring; never unplug a powered CSI ribbon.

The Grove variant has **no separate pedestrian lamps or physical button**.
Pedestrian STOP/WALK/CLEARANCE is shown on the OLED, with the matrix pages.
The dashboard Call button is available. White D7 is a monochrome warning:
B1 slow blink, B2 fast blink plus sound. It does not reproduce the original
amber/red beacon colours. Report these limits honestly in the demo.

References: [UNO Q manual](https://docs.arduino.cc/tutorials/uno-q/user-manual/),
[Base Shield V2](https://wiki.seeedstudio.com/Base_Shield_V2/),
[Seeed SSD1315 driver example](https://wiki.seeedstudio.com/Grove-OLED-Display-0.96-SSD1315/).
Keep the already working core/library versions; record them before upgrading.

## 3. Build and launch the integrated MCU app

On the board, choose a **new** app directory; the packager refuses overwrites:

```bash
cd ~/occhio
.venv/bin/python tools/prepare_mcu_app.py --profile grove --out ~/ArduinoApps/crosswalk_grove_live
arduino-app-cli app start ~/ArduinoApps/crosswalk_grove_live
```

For a repeat run use a new name and update the service path accordingly.
Save `occhio-build.json` in the evidence directory, along with exact compiler
errors or success logs. The generated Python app only keeps the sketch alive;
it never opens CAM0. U8g2 2.36.5 is the existing test's dependency. For offline
use ensure it is cached in App Lab first.

The manifest revision can be null in a tar deployment without `.git`; record the
source commit from the laptop separately. The manifest's file hashes still
identify the exact app contents.

If OLED/I2C is the only blocker, stop this app and prepare a new folder with
`--no-oled`. Prove GPIO separately, but record OLED acceptance as **pending**.
Do not claim that the GPIO-only fallback completed the whole hardware target.

With vision still stopped, expect flashing yellow, vehicle red/green off,
white alert off, buzzer silent, matrix `!`, and OLED `FAILSAFE`. Confirm these
physically; `app running` alone is not a pass.

Now run direct actuator diagnostics, still with vision stopped:

```bash
.venv/bin/python tools/mcu_test.py --watchdog
```

Check each vehicle colour, pedestrian text, warning blink rate and sound;
button tests are inapplicable to this wiring. The tool supplies its own
heartbeats and keeps running until Ctrl+C. Stop it completely before starting
vision, or it would mask camera-loss fail-safe. Measure the stop-heartbeat
watchdog trial with slow-motion video. `get_status()` must report Grove profile 1.
These forced states prove actuators/RPCs, **not camera-derived signal decisions**.

## 4. Start one live pipeline and calibrate this viewpoint

Preserve an existing correctly measured config for this exact mounting, or copy
the new template to the ignored local config and calibrate it:

```bash
cd ~/occhio
cp -n configs/board_grove_live.yaml configs/board_grove_local.yaml
```

Edit `/etc/default/occhio` with `sudoedit`, preserving other settings:

```text
OCCHIO_CONFIG=configs/board_grove_local.yaml
OCCHIO_WRAPPER=libcamerify
OCCHIO_MCU_APP=/home/arduino/ArduinoApps/crosswalk_grove_live
```

Install/update the existing boot services (this restarts the MCU app and vision):

```bash
sudo sh deploy/install_autostart.sh
systemctl status occhio occhio-mcu --no-pager
curl -s http://127.0.0.1:8000/api/health
journalctl -u occhio -b --no-pager -n 80
```

There must be one CAM0 capture process, real NCNN YOLO11n at 320, nonzero
inference timing, `mcu.virtual=false`, MCU connected, no RPC errors and fresh
vision. `/api/health` proves frame freshness, not complete hardware acceptance.

Use `http://<BOARD_IP>:8000/calibrate.html` on the operator laptop. Measure a
test rectangle/zebra, ensure both waiting areas are visible, step out while the
background builds, enter real dimensions and save the four corners. Save to the
local config, not the tracked template. Keep identifiable camera frames local.
The old real-site clip has no visible kerbs; its replay success cannot validate
camera-driven waiting detection at a new live viewpoint.

For initial uncalibrated bring-up only:

```bash
.venv/bin/python tools/board_acceptance.py --allow-uncalibrated --seconds 60 --out docs/board_results/grove_bringup.jsonl
```

After calibration, collect integrated software evidence with strict checks:

```bash
.venv/bin/python tools/board_acceptance.py --seconds 120 --out docs/board_results/grove_live.jsonl
```

The collector reads HTTP telemetry and `get_status`, never camera frames or
heartbeats. It rejects replay/synthetic sources, virtual MCU, wrong firmware,
RPC errors, stale vision, missing inference, stalled counters and uncalibrated
views. A software pass explicitly leaves physical/functional acceptance pending.

## 5. Prove the camera causes the physical signal changes

Keep the board in adaptive mode on a controlled bench scene. Have an operator
watch the physical outputs while another watches the detector/tracks and rule
events. Record timestamps, conditions and manual counts in the results table.

1. **Empty scene:** rest S0 gives vehicle green; OLED says cars GREEN / peds STOP.
   No unexplained counts; monitor an empty scene for at least two minutes.
2. **Vision demand:** walk into a visible waiting area and stop. Do not press
   Call or issue RPC commands. A real detection/track must produce waiting, S1,
   yellow -> all red -> vehicle red plus OLED WALK. Repeat three times. Record
   any missed demand, detection delay and physical output timing separately.
3. **Clearance:** cross slowly during WALK. Confirm S2/CLEARANCE and, when triggered,
   S3 extension; the buzzer changes cadence, vehicle red stays on, then S4 returns
   to green. Film a whole cycle with the rule/event timeline in view if possible.
4. **Counting/directions:** ten A->B and ten B->A pedestrian journeys, plus a
   return crossing without restarting the tracker. Record GT, observed totals,
   directions, misses and false counts. Also test walking past the crossing.
5. **Riding/vehicles:** use a real bicycle/e-scooter and vehicles only in a safe,
   controlled area if available. E-scooters remain bicycles. Do not stage a real
   collision. Missing hardware/scenes mean **unmeasured**, not simulator-proven
   deployment accuracy. A board video replay can verify NN/RPC throughput but
   must be labelled replay and cannot replace the live-camera trial.
6. **Button fallback:** dashboard Call proves the request/actuator path, but
   report it separately from step 2. No physical push button is currently fitted.
7. **Warnings:** direct `mcu_test.py` proves B1/B2 white blink patterns and sound.
   Live B1 needs a visible approaching vehicle and VRU. Retain simulator evidence
   for dangerous B2 conditions unless safe real evidence exists; never introduce
   artificial danger into adaptive traffic or claim a forced RPC as a live conflict.

The public page should show `live` data with no mock-month banner. Check a known
crossing increments stored history, then restart vision and confirm persistence.
Do not clear `data/stats/` or change the deployment's node ID during this check.

## 6. Fail-safe, recovery, reboot and soak

Stop all direct diagnostic heartbeat senders first. Film physical yellow/green
and sound with a monotonic time reference. Obtain the **service's exact PID**:

```bash
PID=$(systemctl show -p MainPID --value occhio)
test "$PID" -gt 1
sudo kill -STOP "$PID"
```

After observing fail-safe, resume that same PID:

```bash
sudo kill -CONT "$PID"
```

The MCU watchdog threshold is **2000 ms after the last heartbeat**. Camera or
process freezes additionally wait for the Linux freshness gate (default 1.5 s),
so do not promise a two-second reaction from the last camera frame. Record both
reference times where measurable; GPIO/I2C scheduling adds physical latency.
During fail-safe: green/red off, yellow flashing, white alert off, audio off,
matrix/OLED fail-safe. Recovery must restore the current commanded phase.

Crash the exact service process next, with an observer already recording:

```bash
PID=$(systemctl show -p MainPID --value occhio)
test "$PID" -gt 1
sudo kill -KILL "$PID"
```

Record fail-safe onset, restarted PID and time to fresh vision/normal outputs.
Reboot and check app + camera + real GPIO without manual start. Verify the service
path points to the packaged Grove app, not the standalone timer test.

Do not disconnect the CSI camera while powered. A USB camera unplug/replug or
the existing synthetic camera fault helper can test software recovery, with the
method labelled. To claim capture reopen, capture `perf.camera_reopens` increasing
and subsequent progressing fresh frames; process SIGSTOP alone cannot prove reopen.

Once stable, complete 30 minutes with occasional real crossings:

```bash
.venv/bin/python tools/board_acceptance.py --seconds 1800 --every 5 --out docs/board_results/grove_soak_30min.jsonl
```

Record all errors/stale samples, temperatures, CPU, RAM, inference rate and
physical anomalies. A partial run is a partial run. Offline testing should
disconnect only the router's internet uplink when possible, leaving local
operator access; verify live NN and actuation continue without cloud services.

## Acceptance and report

Fill `LIVE_GPIO_RESULTS.md` phase by phase. Include the source commit, firmware
manifest, app/core/library versions, actual pin map, calibration conditions,
model/threads, ambient temperature/cooling, measurements and exact error text.
Copy logs and anonymous software evidence there; never commit raw video,
recognisable camera frames, weights, credentials or Wi-Fi details.

Minimum integrated live demonstration: target compile/flash + physical outputs
confirmed, fresh IMX219 + real inference + real MCU, calibrated camera-driven S1
and a full clearance/return cycle, directional counts, and observed fail-safe
and recovery. Keep incomplete soak, vehicle/cyclist coverage or warning colours
explicit. Update `docs/VALIDATION.md` only when real measurements are obtained;
no new accuracy/performance claim is justified by this laptop branch.

If a step blocks, save the exact error and partial evidence, use the stated
fallback, and continue independent checks. Do not silently replace the live
camera with replay or the integrated firmware with the timer test.

Rollback: stop vision and the Grove app, restore the backed-up environment
file/config/app, then restart the original services. Match original firmware
to original wiring, or use the standalone Grove test only for component checks;
the standalone test is not a production rollback that provides signal RPCs.
