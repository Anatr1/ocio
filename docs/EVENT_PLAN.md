# HackTurin 2026 — battle plan

**Hardware hours:** Sat 10:00–20:00 (10 h) · Sun 09:00–16:00 (7 h) · **submission 16:00 Sun** · awards 18:00.
Sat night: no organiser hardware → software, data, model training, pitch.

**Team:** Federico (CE · ML · robotics) = integration lead + pitch · **Mech** (aerospace-mechatronics) = physical rig ·
**Elec** (electronics) = MCU side, power, wiring · **Claude** = on-call coding / analysis / docs ·
**Codex** = parallel, well-specified tickets ([CODEX_TASKS.md](CODEX_TASKS.md)).

> **Rule check — "the core must be done on site".** The repo history shows what was prepared before the event (tooling,
> simulator, dashboard). What is genuinely built on site, and what we should *show* being built on site: bring-up and
> optimisation on the UNO Q, data collection at a real Turin crosswalk, calibration, the fine-tuned detector trained on
> our footage, accuracy measured against our own ground truth, the MCU firmware + physical signal/beacon rig, and the
> integration. Be upfront in the pitch: "we came with a toolkit; in 30 hours we deployed, trained, measured and built
> the device". Commit early and often on site so the history tells that story.

---

## 0. Before 10:00 (tonight / tomorrow morning)

- [ ] **Pack** (see [HARDWARE.md](HARDWARE.md) shopping list): powered USB-C hub with PD, USB webcam(s) (wide FOV), USB-C PD
      charger 5 V/3 A, **travel router** (own Wi-Fi network for the demo), tripod / light stand 2.5–3 m + clamp, tape measure,
      white + black gaffer tape (5 cm), LEDs / resistors / button / piezo / jumpers, USB power meter, power bank, extension cord,
      USB stick with `C:\Users\fedem\hackturin-offline\` (offline wheels) + `models/`.
- [ ] Laptop: `git pull`, venv works (`python -m crosswalk --sim mixed`), dashboard opens.
- [ ] **Scout a real crosswalk near the venue** (Via Vela 17): ideally signalised, visible from an elevated, safe, legal spot
      (footbridge, balcony, raised sidewalk, or a tripod at 2.5–3 m on the sidewalk). Note where the sun will be.
- [ ] Optional (great value): record 10 min of the crosswalk with a phone from the planned viewpoint, 1080p → becomes the
      first dataset + demo video even before the board is configured.

## 1. Saturday 10:00–11:30 — bring-up (everybody on their track in parallel)

**Federico + Claude — board bring-up (critical path)**
1. Power the UNO Q from the USB-C PD supply **through the powered hub**, webcam on the hub. Run App Lab first-time setup
   (board name, password, Wi-Fi = our travel router). SSH must be enabled. Note the IP.
2. `tools/deploy.sh arduino@<ip> --wheels <offline dir> --setup` → checks Python/OS, installs deps, tests camera + MCU link.
   (Without internet the offline wheels cover numpy/opencv/onnxruntime/ncnn/msgpack/pyyaml/scipy for Python 3.13 aarch64.)
3. `.venv/bin/python tools/bench.py --threads 2 3 4` → **pick model/runtime/threads/imgsz** (target ≥ 8 Hz total).
   Then `--sustained 120` on the winner (thermal throttling? → heatsink/fan).
4. `.venv/bin/python -m crosswalk --config configs/board.yaml` → open `http://<ip>:8000` on the laptop **and a phone**.
   - **GO/NO-GO 11:30**: pipeline running on the board with live camera. If inference < 4 Hz: imgsz 256, ROI crop,
     ncnn, yolo26n; if the camera is not detected: other port/hub/webcam; if the board is dead: laptop fallback (say so).

**Elec — MCU side**
1. Wire the mini signal: vehicle R/Y/G on D2/D3/D4, pedestrian R/G on D5/D6, amber beacon D7, piezo D8, push button D9→GND
   (see [HARDWARE.md](HARDWARE.md)). 3.3 V logic: 220–330 Ω per LED, transistor/MOSFET for anything bigger.
2. App Lab: copy `firmware/crosswalk_mcu` into ArduinoApps, Launch (compiles + flashes the STM32). Lamps start **flashing
   amber** (fail-safe until Linux sends heartbeats).
3. SSH: `.venv/bin/python tools/mcu_test.py` → every lamp, beacon, buzzer, LED-matrix page, button. `--watchdog` shows fail-safe.
4. Measure power with the USB meter (idle / pipeline running) → number for the pitch ("X W, solar-friendly").

**Mech — physical rig**
1. Camera mount at 2.5–3 m (tripod/light stand/pole) for the **indoor demo crosswalk**; design + 3D-print an enclosure
   for UNO Q + hub + camera (ventilation slots! the A53s get hot) and a mini traffic-light housing.
2. Indoor zebra: 6–8 white stripes of tape, 50 cm wide (or scaled), on a dark floor area at the demo spot; measure it.
3. Prepare the street-recording kit (tripod, power bank, laptop or board) with Federico for 11:30.

## 2. Saturday 11:30–14:00 — real data

- [ ] **Street recording** (Federico + Mech, 45–60 min outside): camera at the chosen viewpoint, `tools/record.py --camera 0
      --minutes 30 --segment 10` (on the board with a power bank, or on the laptop with the same webcam at 640×480).
      Measure on site: stripe length **W**, zebra block length **L** (outer edge of first to last stripe), camera height,
      lane count, speed limit. Photos of the setup (pitch!). Footage stays private; delete after the event.
- [ ] Meanwhile **Claude**: watch for issues, tune configs; **Codex**: tickets from CODEX_TASKS.md.
- [ ] Back inside: `tools/calibrate.py --video <rec> --config configs/site.yaml` (or the `/calibrate.html` page) →
      check the grid overlay, camera height ≈ measured → **site config done**.
- [ ] `tools/annotate_video.py --config configs/site.yaml --video <rec> --out runs/site.mp4` → eyeball counts/trails.

## 3. Saturday 14:00–17:00 — make it accurate (ML) + make it physical

**Federico + Claude — model**
1. `tools/autolabel.py --src data/recordings --out datasets/xw --every 0.5 --open-vocab` (laptop GPU or L40S).
   Quick review of `datasets/xw/preview/sheet.jpg` (optionally fix in Roboflow: upload folder as YOLO format).
2. On the L40S: `python tools/train.py --data datasets/xw/data.yaml --imgsz 320 --epochs 80` (~10 min) → `models/xw_320*.onnx`
   + `_ncnn_model` → copy to the board → `tools/bench.py --models ...` → update `configs/board.yaml`.
3. Ground truth: `tools/count_gt.py <rec>.mp4 --speed 2` on 10–15 min of footage (~15 min of a human) →
   `tools/eval_counts.py --video <rec>.mp4 --gt <rec>.gt.csv --config configs/site.yaml` (baseline vs fine-tuned) →
   **accuracy table for the pitch**.

**Elec + Mech — integration**
- Board + camera + hub + mini signal + beacon + LED matrix in the enclosure at the indoor crosswalk; run the pipeline
  on the live camera; calibrate the indoor zebra (`/calibrate.html` from a phone).
- Test: walk across → count + LED matrix + twin; stand at the curb → adaptive signal gives you green; walk slowly →
  "Green Man+" extension; push button works; pull the Ethernet/kill the pipeline → flashing amber (fail-safe).

## 4. Saturday 17:00–20:00 — demo complete + backups

- [ ] **Checkpoint 17:00**: indoor live demo end-to-end on the board.
- [ ] Street video as the "vehicle" part: run the pipeline on the recorded street footage **on the board**
      (`--video` source) for the near-miss / speed / yield demo; render `annotated` versions for the slides.
- [ ] QR code to the dashboard URL on a printed card; test 3–4 phones at the same time on the travel router.
- [ ] **19:30 dress rehearsal #1** (full pitch + demo, timed). Record a backup video of the working demo (screen + phone).
- [ ] Commit + push everything. Copy recordings/datasets off the board (board stays at the venue overnight).

## 5. Saturday night (no hardware)

- Federico: pitch deck (see [PITCH.md](PITCH.md)), numbers from eval + bench + sim_eval, demo script.
- Claude/Codex: dashboard polish, analytics view, fleet view (multi-node), bug fixes found in rehearsal, more training
  (more data / 416 px / longer) on the L40S, `tools/sim_eval.py` final report.
- Sleep at least 5 h. Seriously.

## 6. Sunday 09:00–16:00

- 09:00–11:30 deploy night work to the board, re-validate (bench, live demo), fix.
- **11:30 FEATURE FREEZE.** Only bug fixes after this.
- 11:30–14:30 rehearse ×3 (pitch 5 min + demo 3 min + Q&A); each person knows their part; time it.
- 14:30–15:30 submission package: repo link, README with numbers, demo video (60–90 s), slides PDF, photos.
- **16:00 submission.** Leave the demo running for the judges' walk-around if there is one.

---

## Fallbacks (decide fast, don't debug for hours)

| Problem | Fallback |
|---|---|
| Webcam not detected on UNO Q | other hub / powered hub / different webcam (UVC, MJPG) / check `dmesg` |
| Inference too slow | imgsz 256, ROI crop on the crosswalk, ncnn, yolo26n, `detector.max_hz` lower; tracker is fine at 4–5 Hz |
| ONNX Runtime / NCNN won't install | offline wheels; `ai-edge-litert` (tflite); last resort: App Lab `video_object_detection` brick + our tracker on its detections |
| MCU / App Lab problems | dashboard shows a virtual MCU (lamps + LED matrix) — still demo-able |
| Venue Wi-Fi blocks devices | our travel router; or USB-Ethernet; or the board's own hotspot |
| No real crosswalk footage | sample videos + simulator (`--sim`) for the vehicle/near-miss part, indoor zebra for live |
| Live demo fails on stage | backup video recorded Saturday 19:30 + simulator running on the laptop |

## Definition of done (what we show)
1. Live: people crossing the indoor zebra are counted on the board, the twin on the judges' phones shows them in 3D.
2. Real street footage processed on the board: pedestrians / bicycles / vehicles counted, speeds, a near-miss with 3D replay.
3. The signal reacts: waiting pedestrian → green; slow walker → clearance extended; danger → beacon flashes.
4. Numbers: counting accuracy on our real footage, FPS / latency / watts on the UNO Q, simulator validation.
5. Pull the plug on Linux → flashing amber within 2 s (fail-safe).
