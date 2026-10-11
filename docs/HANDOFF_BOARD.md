# Handoff — Real-board bring-up, testing & verification (Arduino UNO Q)

**Owner:** <electronics colleague> + coding agent · **Branch:** `board-bringup` (already created; work and push ONLY here)
**Results go to:** `docs/board_results/RESULTS.md` (+ artefacts in `docs/board_results/`) — commit & push after **every
phase**, even partial. The main team pulls this branch to read results; nothing else is needed to report.

## Context (read in 10 min)
OCCHIO = edge-AI crosswalk node for the HackTurin "Smart Crossing" challenge (recognise pedestrians / cyclists /
vehicles approaching, explicit light-signal rules, counting with direction, offline). Everything must run **on the
UNO Q** (QRB2210: 4× Cortex-A53, no usable NPU, Debian, Python 3.13 expected). Read: `README.md`, `docs/BOARD_SETUP.md`,
`docs/RULES.md`, `docs/HARDWARE.md`. The software was validated on a laptop + simulator; **this handoff finds out what
is true on the real board** — every number we put in the pitch about the device comes from your results.

**Hardware available now:** UNO Q (configured, on your laptop's network), one **Stereolabs ZED Mini used as a plain UVC
webcam**, the UNO Q's built-in 8×13 LED matrix. **This afternoon:** LEDs, buzzer, button → phase 7b.

### ZED Mini specifics (important)
- No ZED SDK (needs CUDA). Over UVC the ZED streams **both eyes side by side**, **YUYV only** (no MJPG).
  UVC modes (side-by-side): 2560×720 @30/60, 1344×376 @30/60/100, 3840×1080 @30, 4416×1242 @15.
- 2560×720 YUYV @30 ≈ 110 MB/s → needs **USB 3**; on USB 2 expect only 1344×376 (or lower fps).
- The pipeline handles it via config: `source.stereo: left` (keep left eye) and `source.resize_width` (optional
  downscale). Ready-made config: **`configs/board_zed.yaml`** (1344×376 YUYV → 672×376 left eye).
- Mount it with the **left lens** looking at the scene (we only use the left image).

## Ground rules for the agent
1. Work on branch `board-bringup`. `git pull` before starting; commit small, push after each phase.
2. **Do not change pipeline logic** (`crosswalk/counting.py`, `safety.py`, `signal.py`, `tracker.py`, `scene.py`,
   `rules.py`, `approach.py`). Portability / bug fixes needed to *run* on the board are OK (e.g. a library API
   difference, a path, a V4L2 quirk): keep them minimal, run `python -m pytest -q tests` on the laptop, and list each one
   in RESULTS.md → "Code changes" with the reason. Anything bigger: write it in "Proposed changes", don't do it.
3. **Never block on one problem > 20 min.** Record it in RESULTS.md (exact error text, what you tried), take the
   fallback listed in the phase, continue. Paste full error messages, not summaries.
4. Measurements: always record **conditions** (model, imgsz, threads, camera mode, scene: empty/1 person/several,
   ambient temperature, heatsink yes/no) — a number without conditions is useless.
5. Privacy: don't commit raw camera video or images with recognisable people to git. Screenshots of the dashboard
   (pixelated video) and calibration images of an empty floor are fine.
6. The board has no display: run everything over SSH. Long runs: use `tmux` or `nohup ... &` so a dropped SSH doesn't
   kill them. The dashboard is at `http://<board-ip>:8000` from the laptop.

---

## Phase 0 — Facts about the board (10 min)
On the board (SSH), paste outputs into RESULTS.md §0:
```bash
cat /etc/os-release | grep PRETTY; uname -a; python3 --version; nproc; lscpu | head -20; free -m; df -h /
ls -l /dev/video*; v4l2-ctl --list-devices; v4l2-ctl -d /dev/video0 --list-formats-ext
ls -l /var/run/arduino-router.sock; systemctl status arduino-router --no-pager | head -5
cat /sys/class/thermal/thermal_zone*/type; cat /sys/class/thermal/thermal_zone*/temp
lsusb; lsusb -t          # is the ZED on a USB 3 (5000M) or USB 2 (480M) link?
```
**Verify:** Python version (3.13 expected — offline wheels are built for it), aarch64, 4 cores, ~3.7 GB RAM, router
socket present, ZED visible, **USB speed of the ZED link**, which thermal zone is the CPU.
(`v4l2-ctl`: `sudo apt install v4l-utils` if missing and online.)

## Phase 1 — Deploy (20 min)
From the laptop (Git Bash/Linux/macOS shell), in the repo:
```bash
python tools/fetch_assets.py            # models/ + data/videos/ (not in git) — needs requirements-dev.txt
tools/deploy.sh arduino@<board-ip> --setup
```
(Offline wheels: ask Federico for `hackturin-offline/wheels-aarch64-cp313` if the board has no internet; then
`--wheels <dir>`.) `board_setup.sh` tests a 640×480 MJPG camera — with the ZED that part may fail: expected, Phase 2
covers the camera. **Verify:** all modules `ok` (numpy, cv2, onnxruntime, msgpack, yaml, scipy, ncnn, segno).
**Record:** install method (online/offline), any pip errors verbatim, time taken.

## Phase 2 — Camera (ZED Mini over UVC) (30 min)
```bash
cd ~/occhio
.venv/bin/python tools/bench.py --camera 0 --camera-modes 1344x376:YUYV 2560x720:YUYV 672x376:YUYV --models
```
(`--models` with no value = skip model benchmarks.) Then a visual check: start the node with the ZED config
(Phase 4 command) and open `http://<board-ip>:8000/video.mjpg` → the image must be **one eye, not two side by side**,
correct aspect, not upside down (else `source.rotate: 180`).
**Measure (§2):** per mode: requested vs obtained resolution, fps, any errors; which USB speed; CPU % of the capture
alone (`top` while only the camera runs). **Decide:** mode for the rest of the tests (best resolution that sustains
≥ 15 fps). Edit `configs/board_zed.yaml` accordingly and commit.
**Fallback:** if the ZED won't stream at all: `dmesg | tail -30` into RESULTS, try another hub port / direct port,
lower mode (`1344x376 @15`); if still nothing, use any other UVC webcam and mark it.

## Phase 3 — Detector benchmark (40 min) — THE key numbers
```bash
.venv/bin/python tools/bench.py --threads 2 3 4                    # all models in models/ (onnx fp32/int8, ncnn)
.venv/bin/python tools/bench.py --models models/<winner> --threads <best> --sustained 300   # thermal: 5 min
```
Commit `runs/bench_*.md` + `.json` → copy to `docs/board_results/`.
**Record (§3):** the full table; the winner by **total ms**, provided its `dets/frame` is not clearly below the fp32
yolo11n_320 reference (int8 / small imgsz can lose detections); sustained fps over time + temperature (does it
throttle? at what temperature? with/without heatsink); idle temperature before.
**Decide & set** in `configs/board_zed.yaml`: `detector.backend`, `model`, `imgsz`, `threads`. Target: ≥ 6 Hz total
(< 160 ms); great: ≥ 10 Hz.
**Fallback:** if NCNN segfaults or won't import → ONNX; if everything > 300 ms → imgsz 256 + `detector.roi` crop.

## Phase 4 — Live pipeline on the board (45 min)
```bash
cd ~/occhio && .venv/bin/python -m crosswalk --config configs/board_zed.yaml
```
Open `http://<board-ip>:8000` on the laptop **and a phone** (same Wi-Fi; "Share" button → QR).
**Verify:** header shows `LIVE · on-device`, the real model name, `det Hz` / `ms` non-zero; boxes on people in the
Camera layer; no exceptions in the terminal (copy any traceback). MCU status shows "STM32 via arduino-router" once
Phase 7 firmware is flashed (before that "virtual MCU" is expected).
**Measure (§4)** with `tools/soak_monitor.py` (run on the board in a second SSH session):
```bash
.venv/bin/python tools/soak_monitor.py --minutes 5 --every 2 --out docs/board_results/live_empty.csv     # nobody in view
.venv/bin/python tools/soak_monitor.py --minutes 5 --every 2 --out docs/board_results/live_busy.csv      # 2-3 people moving
```
Report: det Hz, infer ms, decision_ms (frame → lamp command), loop fps, camera fps, **duty cycle empty vs busy**
(motion gating: should be low when empty), CPU %, temp, RAM. Also: dashboard responsiveness with 3+ phones connected
(CPU delta).

## Phase 5 — Calibration on a test "crosswalk" (30 min)
Make a rectangle on the floor with tape (e.g. **2.0 m across (L) × 1.0 m along (W)**, or larger if space allows; note
exact measures). Mount the ZED high (≥ 2 m if possible, on a shelf/tripod), looking down at it diagonally.
1. Step out of view for ~10 s (the person-free background builds up).
2. `http://<board-ip>:8000/calibrate.html` → click P1..P4 (P1/P2 near edge, P3/P4 far edge, same ends), enter W and L, Save.
3. Measure the real lens height with a tape.
**Record (§5):** W, L, real camera height vs estimated height, tilt, estimated HFOV (ZED Mini left eye ≈ 85–90° H for
reference), screenshot of `/api/calib_preview.jpg` (empty floor only) → `docs/board_results/calib_preview.jpg`.
**Pass:** estimated height within ±15 % of the tape measure, grid visually aligned with the tape.

## Phase 6 — Functional tests of the challenge requirements (60 min)
Signal mode **adaptive** (default). For each test: what you did, what the dashboard showed, pass/fail, notes. Repeat
counting tests **10×** each for statistics.
| # | Test | Expected |
|---|---|---|
| F1 | Walk across the rectangle A→B (10×) and B→A (10×), normal speed | pedestrian count +1 each, correct direction under the counter and in the event feed |
| F2 | Walk along the near edge past the rectangle (5×) | **no** count |
| F3 | Two people cross together, opposite directions (5×) | +2, one per direction |
| F4 | Walk towards the rectangle and stop at the edge ≥ 2 s | "Approaching" card: pedestrian approaching → waiting; 3D label "· waiting"; signal rule log: **S1** → yellow → all red → walk (S1), then S2, S3, S4 |
| F5 | Cross very slowly (≈ 0.5 m/s) during the walk phase | **S3 Green Man+** extension in the rule log / toast |
| F6 | Bicycle (if available) or e-scooter pushed/ridden across | counted as bicycle/e-scooter, not as pedestrian (+1 total, not +2) |
| F7 | Nobody in view for 5 min | no counts, no rule changes except S0/B0, duty cycle low |
| F8 | Dashboard "Call" button (virtual push button) | S1 call registered → walk phase |
| F9 | **Offline**: disconnect the board from Wi-Fi (or unplug the router's uplink) for 2 min while walking across | pipeline keeps running (SSH via USB/adb if needed); counts continue in `runs/<run>/events.jsonl`; after reconnect the dashboard shows them |
| F10 | Cars: run the pipeline on a video ON THE BOARD: `.venv/bin/python -m crosswalk --config configs/video_demo.yaml` | vehicles/people counted, record det Hz on the board for a 768×432 video |
Note: the tape rectangle is tiny compared with a real street, so speeds/vehicle rules aren't meaningful here; F10
covers vehicles. B1/B2 beacon rules need vehicles → verified in F10 and in Phase 7 via the matrix.

## Phase 7 — MCU side
### 7a — Now (no external parts): firmware + LED matrix + watchdog (45 min)
1. App Lab: create an app from `firmware/crosswalk_mcu` (or copy the folder into ArduinoApps), **Launch** (compiles +
   flashes the STM32). **Record compile errors verbatim** — the most likely ones: `Bridge.provide` with 2-argument
   functions or `std::vector<uint8_t>`, `INPUT_PULLUP`, `matrix.setGrayscaleBits`. Allowed fixes: adapt signatures to
   the installed `Arduino_RouterBridge` examples; keep the RPC names and semantics. `USE_TONE` stays 0.
2. After flashing, with no heartbeat yet, the matrix must show a **blinking "!"** (fail-safe F1).
3. `.venv/bin/python tools/mcu_test.py` → ping round-trip time; every page on the matrix (car, walk, numbers, warning).
   Lamps can't be seen yet (no LEDs) — record that the RPC calls succeed without error.
4. `.venv/bin/python tools/mcu_test.py --watchdog` → after heartbeats stop, **"!" must blink within 2 s**.
   Measure with a phone slow-motion video: time from the "stopping heartbeats" print to the first "!" frame.
5. Run the pipeline (Phase 4) → dashboard MCU status "STM32 via arduino-router · N ms"; the physical matrix mirrors the
   dashboard's LED-matrix widget (count pages / walk icon / warning icon). Then **kill the pipeline (Ctrl+C)** →
   fail-safe "!" within 2 s; restart → normal.
**Record (§7a):** compile result, RTT (ms), watchdog reaction time, matrix pages OK, any RPC errors in the dashboard's
MCU status / terminal.
### 7b — This afternoon, when LEDs/buzzer/button arrive (60 min)
Wire per `docs/HARDWARE.md` (D2–D4 vehicle R/Y/G, D5–D6 ped R/G, D7 amber beacon, **D10 red danger beacon**, D8 active
buzzer, D9 button→GND; 220–330 Ω; 3.3 V logic). Photo of the wiring → `docs/board_results/wiring.jpg`.
`tools/mcu_test.py` again → each lamp in each step; button prints "push button pressed"; buzzer ticks during walk.
Pipeline: repeat F4/F5 and watch the real lamps follow the rule log; video of one full cycle (≤ 30 s) for the demo.
Power: if a USB power meter is available, measure board+camera idle / pipeline empty / pipeline busy / + LEDs (§7b).

## Phase 8 — Robustness (30 min)
| # | Action | Expected / record |
|---|---|---|
| R1 | Unplug the ZED for 10 s while the pipeline runs, plug back | does the pipeline recover? (it may not — record exactly what happens) |
| R2 | 30-min soak with people occasionally walking: `soak_monitor.py --minutes 30 --every 5 --out docs/board_results/soak_30min.csv` | no crash, no memory growth, temperature plateau, det Hz stable |
| R3 | Reboot the board; how long until SSH; does the MCU app/firmware persist? | times; matrix state after boot |
| R4 | 5 phones on the dashboard for 2 min | CPU delta, any stalls |

## Deliverable checklist (what the main team needs from you, in priority order)
1. §3 benchmark table + chosen detector config (pushed in `configs/board_zed.yaml`).
2. §4 live numbers (det Hz, infer ms, decision ms, duty empty/busy, temp, CPU).
3. §7a firmware compile status + watchdog time + RTT.
4. §6 functional table with counts/directions accuracy over the repetitions.
5. §5 calibration accuracy. 6. §8 robustness. 7. §7b lamps + power (afternoon).
Push after each. If something blocks a phase, still push what you have with the blocker described.
