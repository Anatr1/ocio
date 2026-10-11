**Current live-hardware task (2026-10-11):** `codex/live-board-gpio` builds on current
master with the Grove wiring from `setup-GPIO-app`. Read `docs/HANDOFF_LIVE_GPIO.md`
and report into `docs/board_results/LIVE_GPIO_RESULTS.md`. The new branch contains
laptop preparation only; integrated physical deployment is still to be tested.

You are joining **OCCHIO**, our entry to HackTurin 2026 (GOMA Elettronica "Smart Crossing" challenge). Read this, then
`README.md`, `docs/VALIDATION.md` and `docs/PRIORITIES.md`, before changing anything. Work with Federico step by step:
propose one step, wait for his feedback, then continue.

## The challenge and the deadline

- **What it has to be:** an embedded device with fully local CV/AI on an Arduino UNO Q 4 GB (QRB2210, 4× A53, no NPU,
  Debian 13, Python 3.13). It must:
  - recognise pedestrians, cyclists and vehicles approaching a crossing
  - drive a light signal by an explicit rule
  - count crossings and their direction
  - work offline
- **Deadline: Sunday 16:00 on Devpost.** Deliverables: description with photos, demo video ≤ 2 min, public GitHub repo.
- **What wins:** measured, honest, on-device results. GOMA builds rugged edge hardware, so performance and robustness
  on the board count.

## Repo map (`git@github.com:Anatr1/hackturin-task1.git`, branch `master`)

- `crosswalk/`: the on-board pipeline.
  - Capture: `sources.py`, which reopens the camera if it stalls.
  - Detector: `detectors/`, NCNN YOLO11n at 320 px on the board.
  - BEV tracking: `tracker.py`, `classes.py`.
  - Counting: `counting.py`.
  - Safety (TTC/DRAC/PET): `safety.py`.
  - Explicit rules: `rules.py`, `signal.py`.
  - MCU link: `mcu.py`, msgpack-RPC to the STM32. The heartbeat is sent only while camera frames are fresh, so a
    frozen camera puts the lamps in fail-safe.
  - Web server and dashboard API: `server.py`, including `/api/health`, which returns 503 when vision is stale.
  - Raw-footage recorder: `recorder.py` (dashboard **● Rec**, `/record.html`, `/recordings`).
- `dashboard/`: Three.js digital twin and controls.
- `firmware/crosswalk_mcu/`: App Lab sketch (lamps, LED matrix, 2 s watchdog).
- `sim/`: agent-based simulator with ground truth.
  - Perfect-track checks (L0) and the noisy virtual detector (L1).
  - Three.js photoreal renderer so the real network runs on pixels (L2).
  - MJPEG transport to the board (L3).
  - Scenario catalogue: `sim/scenarios/catalogue.yaml`. Behaviour notes: `sim/BEHAVIOUR.md`. Known limitations:
    `sim/DIVERGENCES.md`.
- `configs/`:
  - `board_imx219.yaml`: the board, CSI camera through `libcamerify`.
  - `site.yaml`: the real-site recording, replayed with the board's detector settings.
  - `board.yaml`: the base. The ZED configs are unused.
- `deploy/`: systemd units and `install_autostart.sh`. The board starts the MCU app and the pipeline at boot.
- `tools/`:
  - Evaluation: `eval_counts.py`, `count_gt.py`, `sim_eval.py`, `sim_suite.py`, `sim_soak.py`.
  - Setup and assets: `calibrate.py`, `fetch_sim_assets.py`.
  - Board: `record.py`, `bench.py`.
- `docs/board_results/RESULTS.md`: everything the electronics colleague measured on the real board.

## Laptop environment (Windows, PowerShell)

- **Project Python:** `C:/Users/fedem/.venvs/hackturin/Scripts/python.exe` (has `ncnn`, ultralytics, playwright). Its
  OpenCV is **headless**: tools that open a window (`count_gt.py`, `calibrate.py`) must run with the plain system
  `python`.
- **Tests:** `C:/Users/fedem/.venvs/hackturin/Scripts/python.exe -m pytest -q tests` → **92 passed, 1 skipped** (the
  skip is the opt-in GPU test). Keep it green.
- **Fast simulator** at http://localhost:8000:
  `C:/Users/fedem/.venvs/hackturin/Scripts/python.exe -m crosswalk --sim mixed --port 8000`.
- **Photoreal simulator** with the real NN, port 8004:
  `C:/Users/fedem/.venvs/hackturin/Scripts/python.exe tools/sim_run.py --scenario mixed --fps 5 --realtime --set sim.browser=chrome --port 8004`.
- **Real-site replay:** `C:/Users/fedem/.venvs/hackturin/Scripts/python.exe -m crosswalk --config configs/site.yaml`.
- **Real-site score:** `C:/Users/fedem/.venvs/hackturin/Scripts/python.exe tools/eval_counts.py --video data/recordings/site_traffic.mp4 --gt data/recordings/site_traffic.gt.csv --config configs/site.yaml`.
- **Scenario suites:** `tools/sim_suite.py --level L0` (40/40) and `--level L1` (34/40, see the known failures below).

## The real-site data (the only real clip we have; no better clips will come)

- **Video:** `data/recordings/site_traffic.mp4`. 105 s from the board's IMX219, 632×480, 15 fps, raw.
  Hand count in `site_traffic.gt.csv`: 17 pedestrians and 3 cars, no cyclists.
- **The zebra:** 11 stripes, each 0.5 × 3 m, with 0.5 m gaps (10.5 m in total).
- **What the camera sees:** a cut stripe at the left edge, then 7 full stripes, the last one just before a pole.
  Neither kerb is in view.
- **Calibration** (`configs/site.yaml`) covers the 6 fully visible stripes: W = 3 m, L = 5.5 m.
- **Current score: 20/20 crossings, no false counts.** Two bugs found on this clip are fixed:
  - Return crossings were not counted: a track is now re-armed once it reaches the far side.
  - Hanging leaves were detected as a 0.55 m "person": person boxes shorter than `tracker.min_person_height_m` (0.75 m)
    are now dropped.

## Validated numbers (docs/VALIDATION.md; keep them honest and in sync)

- **Simulated counting:** 91–94 % on about 1,860 ground-truth passages (count_test 93.9 % after the return-crossing fix).
- **Near-miss detection:** 48 % precision / 62 % recall in dangerous traffic. In calm traffic, about 0.8 false alarms
  per minute under heavy detector noise.
- **Adaptive signal:**
  - Pedestrian wait −46 % (23.4 → 12.7 s).
  - Serious conflicts 16 → 0 in the same dangerous traffic.
- **Board:**
  - Detector: NCNN YOLO11n 320 at ~9 Hz in the benchmark, ~6 Hz live with the IMX219.
  - Health: healthy 41 s after boot.
  - Fail-safe triggers verified in software. Physical LED timing is not measured.

## Team decisions (do not reopen without asking Federico)

- **Cyclists:** a "person" faster than 3.6 m/s is counted as a **bicycle** (`tracker.fast_person_kind`). E-scooters
  are therefore counted as bicycles too, by choice: the task requires bicycles, not e-scooters. `scooter_zebra` and
  `scooter_road` fail in L1 by design.
- **Simulated vehicles:** cars only. No buses, trucks, vans or motorbikes. The pipeline still supports those classes
  on real footage.
- **Kerb-waiting detection:** closed. It cannot be tested on the site clip, so it is accepted on simulator evidence.
- **Camera:** the IMX219 through `libcamerify`. The ZED is not used.
- **Privacy blur** on the camera stream: people's heads, and the lowest 20 % of vehicle boxes. Recordings are raw
  and stay local.
- **The adaptive signal really is conflict-free in this traffic.** Do **not** add artificial danger. For the demo,
  show "Zebra + warning beacon" with **Stage near-miss**, then switch to Adaptive.

## Open items (rough priority)

1. **Deploy the latest `master` to the board**, keeping its `.venv` and `models/`, then
   `sudo systemctl restart occhio`. The board does not yet have:
   - the counting fix
   - the height filter
   - the final timestamp guard in the recorder
   - the shared demo staging
2. **Demo video** (≤ 2 min) and the Devpost text. Use `docs/PITCH.md` and the numbers above.
3. **Bicycle detection is weak at 320 px.** On 25 rendered zebra frames:
   - YOLO11n at 320 px: 1/25
   - YOLO11n at 640 px: 9/25
   - YOLO11x at 640 px: 23/25

   The speed rule covers riding cyclists. A real fix would be fine-tuning on frames auto-labelled by YOLO11x
   (`tools/autolabel.py`, `tools/train.py`).
4. **Known minor issues:**
   - a turning car is sometimes classed as a truck (still counted as a vehicle)
   - near-miss false alarms from cars still braking to yield
   - L1 failures: `group_a_b`, `driver_yields`, `near_miss_late_braking`, `queue_two_lanes`, plus the two scooter
     cases
5. **Unmeasured on the board:** physical watchdog LED timing, a real camera reopen, a full 30-minute soak.

## How we work

- **Small, verified steps:**
  - Run the tests and the relevant check, and quote measured numbers.
  - Add a regression test for every bug fix, and show it fails before the fix.
  - Never claim what was not measured; update `docs/VALIDATION.md` when the numbers change.
- **Git:** a branch per task, focused commits with clear messages, LF line endings (`.gitattributes` enforces it).
  Push only when Federico asks.
- **Never commit or paste into chat:** raw footage or frames from the real site (faces, number plates; the
  `data/recordings/` folder is ignored), model weights, downloaded assets, credentials, or the venue Wi-Fi password.
- **The board:** `ssh arduino@<BOARD_IP>`, code in `~/occhio`, services `occhio` and `occhio-mcu`, logs with
  `journalctl -u occhio -f`. Do not unplug the CSI ribbon while powered.
- **Handoffs:** for tasks done by other people, write a handoff in `docs/HANDOFF_*.md`, with exact commands and where to
  record the results.

## Optional intersection simulation (2026-10-11)

`python -m crosswalk --intersection --intersection-scenario commute --port 8010`
runs the additional four-arm simulator and digital twin. It supports four
crosswalks, twelve straight/left/right movements, protected signal phases,
fixed/adaptive scheduling, live controls and paired policy comparisons. Existing
crosswalk commands retain their execution paths. This mode uses perfect simulator
observations; vision-only control and board integration are still unvalidated.
Add `--intersection-render photoreal --intersection-detector real` for four
synchronized N/E/S/W RGB views, actual ONNX inference, cross-camera fusion and a
shared metric tracker. The camera card shows simulated reality; the main twin,
queues, occupancy and observed passage/wait metrics come from model tracks.
Simulator truth is restricted to an explicit lab endpoint/renderer diagnostics.
Vision accuracy and field control safety remain unvalidated.
See [INTERSECTION.md](INTERSECTION.md) for commands and model boundaries, and
[VALIDATION.md](VALIDATION.md) for measured results, including saturation losses.
