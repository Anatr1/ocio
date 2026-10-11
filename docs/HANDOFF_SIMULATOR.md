# Handoff — OCCHIO Virtual Proving Ground (simulator & evaluation)

**Owner:** <colleague> + coding agent(s) · **Branch:** `sim-eval` (PRs into `master`, merge often)
**Compute for simulation:** a dedicated laptop — Dell Precision 5690, Intel Core Ultra 7, 32 GB RAM, **NVIDIA RTX 1000 Ada
(6 GB VRAM)**. The 2× L40S are a *remote training cluster only* (detector fine-tuning, incl. on synthetic data) — no
simulation/rendering there. Design everything for 6 GB VRAM: rendering runs in **sim time (lockstep)**, not real time.

## Mission
Build a **virtual proving ground** that is a *trustworthy proxy* for the real crosswalk: photoreal enough that the
**real neural network on the real pipeline** behaves in simulation as it does on the street, so that we can test,
tune and certify OCCHIO **before deploying it** — including situations that are impossible or unethical to stage
(near-misses, a child running out, night + rain, a bus hiding a pedestrian, a car running the red).

"Trustworthy" is not an adjective, it is a **measured property** (section 4): we will show the judges the sim-to-real
gap numbers and that decisions taken in simulation transfer to reality.

Challenge (Smart Crossing) — every test maps to one of: recognise pedestrians / cyclists / vehicles **approaching** the
crossing · trigger a **light signal in real time by an explicit rule** · **count crossings and direction** · **offline**.

Read first: `README.md`, `docs/ARCHITECTURE.md`, `docs/RULES.md`, `sim/world.py`, `sim/source.py`, `tools/sim_eval.py`,
`crosswalk/scene.py`, `crosswalk/approach.py`, `crosswalk/rules.py`.
Run: `python -m crosswalk --sim mixed` (http://localhost:8000) · `python tools/sim_eval.py --scenario count_test`.

---

## 0. Contract updates from the main team (read + `git pull` / rebase before continuing)

**2026-10-10 ~12:15 — commit `2a0a39d` "Explicit light-signal rules, approaching road users, counts by direction"**
Touches production code (`crosswalk/counting.py`, `safety.py`, `signal.py`, `pipeline.py`, `config.py`, new `rules.py`,
`approach.py`) and **`sim/world.py::_gt_passage`** — rebase your branch now; if you already refactored GT into
`sim/gt.py`, port the `dir` field there.

1. **Directions are part of the counting contract.**
   - Every `passage` event now has `dir` (`A>B` / `B>A` for people crossing; `+X` / `-X` for vehicles and cyclists
     riding along the road) and `dir_name` (human label from `scene.direction_names`). `count_corrected` carries `dir`.
   - `counts.directions` in the state = per-kind direction counters (incremented at count time, moved on reclass).
   - Ground truth: `World.gt_events` passages now have `dir` with the *same* definition (sign of y change at the
     mid-line for crossers, sign of x change at the cross-line for road users). `tools/sim_eval.py` reports
     **direction-resolved accuracy** (currently 93.0 % vs 93.4 % overall). Every scripted scenario's expected outcome
     must specify counts **per class and direction**.
   - **Counting rule change:** pedestrians are counted *only* on the crossing mid-line; the vehicle cross-line applies
     to vehicles and to cyclists/e-scooters *riding along the carriageway* (|vx| > 1.5|vy|, speed > 2 m/s, on the road).
     Your GT already behaves like this (only crossers use the mid-line) — keep it that way. Add a scenario "people
     walking along the curb / sidewalk past the zebra" with expected count 0 (it was a real bug).
2. **The light signal follows explicit, numbered rules** (`crosswalk/rules.py` → `docs/RULES.md`, thresholds from the
   config): beacon **B0/B1/B2**, traffic light **S0–S4** (adaptive) / **SF** (fixed), MCU **F1** (fail-safe).
   - `signal` events carry `rule` + `why`; new `beacon` events (`rule`, `level`, `why`) on every beacon level change.
   - State: `signal.rule`, `signal.history`, `safety.beacon_rule`, `safety.beacon_history`, `perf.decision_ms`
     (frame in → lamp command; the board adds `mcu.rtt_ms`).
   - **Use rule IDs in scenario expectations**, e.g. "B2 fires within 0.5 s of GT TTC < 2 s", "S1 within 1 s of the
     pedestrian waiting ≥ 0.8 s once vehicle min-green elapsed", "S3 extension ≥ 3 s for the 0.6 m/s walker",
     "B1 never fires in the empty-street scenario".
   - **Rule-trigger evaluation (WP5 item 3) — define GT conditions from World state with the same definitions:**
     B1-GT = a crosser on the zebra / waiting / walking up to the curb AND a vehicle with true time-to-arrival
     < `safety.beacon_tta_s`; B2-GT = true TTC ≤ 2 s AND DRAC ≥ `safety.drac_min`. Report per-rule precision/recall
     (time-overlap based), onset latency (GT condition true → rule fired, in sim time and in frames) and false-on time
     per hour. F1 is testable only at L3 (kill the pipeline on the board, expect flashing amber within 2 s).
3. **"Approaching" has a single production definition: `crosswalk/approach.py`** (`classify()`, `vehicle_eta()`).
   - Categories: pedestrian / cyclist (= bicycle + e-scooter) / vehicle. Statuses: vehicles `approaching` (≤ 40 m,
     moving towards the zebra, ETA = distance / speed along the road) / `on_crosswalk`; people `crossing` /
     `waiting` / `approaching` (≤ 8 m, moving towards the zebra's curb edge).
   - State: `approach` summary per category (`approaching`, `waiting`, `crossing`, `next_eta`, `seen`) and per-track
     `approach` + `eta` fields.
   - **Evaluate it (requirement "recognise users approaching"):** GT approaching set from World with the same
     thresholds (import the constants, don't copy numbers); metrics: per-category recall of approaching users,
     **lead time** (first flagged approaching → arrival at the zebra) histogram, ETA error (predicted vs true arrival).
     Vehicles that enter the camera view < 10 m from the zebra are the known weak spot (see VALIDATION.md) — make the
     camera-pose sweep (WP2/P2 "what-if") report it.
4. **Honesty in the UI:** in L1 (`--sim`, synthesised detections) the dashboard now shows "SIMULATION" and
   "simulated detector (GT + noise model, no NN)" instead of the model name / "100% on-device". Your L2/L3 sources must
   report the real model (config `detector.backend` onnx/ncnn) and keep a visible "SIMULATED SCENE" badge
   (`source.type` ≠ camera) — never present rendered scenes as live footage.
5. **Hook for L2 is in place:** `python -m crosswalk --sim <scenario> --sim-detector real` keeps the configured
   detector (onnx/ncnn) and runs it on `SimSource.read()` frames instead of synthesised detections. **Baseline with
   today's schematic renderer: real YOLO11n@416 detects 0 of ~575 visible road users in 60 s of `rush`** → G2 starts
   from 0 %. Make your Three.js renderer a drop-in for `SimSource.render()` (or a `RenderedSource` with the same API)
   and this flag + `tools/sim_eval.py --set detector.backend=onnx` measure it immediately.
6. **Visual ground truth (commit "Ground-truth ghost layer"):** `SimSource.ground_truth()` (true agents + `visible`
   fraction in the camera) and `SimSource.in_view()`; `sim/gt_match.py::match(tracks, gt)` (Hungarian, gates 2.5 m VRU /
   5 m vehicles, misses only for visible agents) → served on a **separate SSE channel `gt`** and `/api/gt` (sim only;
   `Node.gt_provider` is a generic hook, the pipeline never reads it). Dashboard layer "Ground truth": translucent cyan
   ghosts (matched), red (missed), grey (out of view), lines ghost→avatar coloured by error, live stats (recall,
   position error, false positives, class ok). **If World 2.0 changes agent fields, update only `ground_truth()`.**
   Reuse `gt_match.match` in your evaluator so dashboard and reports agree; L2 renderer → watch the red ghosts turn
   cyan (current schematic render + real YOLO: 0 % tracked).
7. Tests now at 16 (`pytest -q tests`): new ones cover directions, the curb-walker case, `vehicle_eta`, rule tagging and
   the rules doc — keep them green.

---

## 1. Architecture

```
                       ┌──────────────── scenario spec (YAML, seeded) ────────────────┐
                       ▼                                                              │
        World / behaviour engine  (Python, deterministic, sim time)  ── ground truth ─┤
        agents: pedestrians, groups, children, elderly, wheelchair, strollers,        │
        cyclists, e-scooters, cars, vans, buses, trucks, motorbikes; signal; weather  │
                       │ agent states @ fixed dt (lockstep)                           │
          ┌────────────┼──────────────────────────────┐                               │
          ▼            ▼                              ▼                               │
   L0 analytic    L1 noise-model camera        L2 PHOTOREAL RENDERER                  │
   (no camera)    (current SimSource:          (Three.js + headless Chromium on the sim laptop,    │
                   projected boxes + noise      camera = calibrated site pose)        │
                   fitted on reality)                 │ RGB frames (+ seg/depth/2D GT) │
          │            │                              ▼                               │
          │            │                      REAL detector (onnx/ncnn, same model)    │
          ▼            ▼                              ▼                               │
   ┌─────────────────── crosswalk/ (PRODUCTION CODE, unmodified) ───────────────────┐ │
   │ fuse_riders → Scene.localize → Tracker → Counter / Safety / Signal → MCU/events │ │
   └──────────────────────────────────────────────┬─────────────────────────────────┘ │
                                                  ▼                                   ▼
                                       evaluator: events vs ground truth  →  reports, gates, dashboards
   L3 HARDWARE-IN-THE-LOOP: L2 frames streamed to the **real UNO Q** (NetworkSource) → real board, real model
      latency, real LEDs/beacon/MCU watchdog; the evaluator reads the board's /api/stream.
```

**Fidelity levels** — every scenario runs at any level; each level answers a different question:
| Level | What is real | Speed | Answers |
|---|---|---|---|
| L0 analytic | logic only (GT tracks → counter/safety/signal) | 1000× RT | are the *rules* right? |
| L1 noise model | pipeline + statistically realistic detector errors | 50× RT | tracker/counting robustness, sweeps |
| L2 photoreal | pipeline + **real NN on rendered pixels** | ~0.2–0.5× RT (lockstep, 640×480) | detector + full stack, conditions |
| L3 HIL | everything incl. the UNO Q, its latency and the LEDs | RT | the device itself |

## 2. Non-negotiable contract (sim ≡ reality)
1. **`crosswalk/` is production code.** No `if simulator` inside it. Pipeline changes go through `crosswalk/` with
   `pytest` green and are announced to the board team.
2. **Interfaces:** sources implement `read() -> (frame, t, seq)`, `width/height`, `stats()` (+ `detections(t)` for L1).
   L2/L3 produce **pixels only**; the detector is the real one (`detector.backend: onnx|ncnn`, same model file and
   config as the board).
3. **One scene definition.** The virtual site is generated from the same `configs/site.yaml` (crosswalk W/L, lanes,
   curbs, sidewalks, speed limit) and the virtual camera from the **real calibration** (K, R, t recovered by
   `Scene`/`Camera.from_ground_homography`). Unit test: project the 4 virtual crosswalk corners → must match the
   config's `image_points` within 1 px.
4. **One ground-truth definition** shared with the pipeline (counting lines, TTC ≤ 3 s ∧ DRAC ≥ 3 m/s², yield, PET),
   implemented once in `sim/gt.py` and unit-tested against `crosswalk/` on hand-made cases.
5. **One evaluator** for sim runs and real runs (events.jsonl + GT) — identical metrics, identical report.
6. **Determinism:** seed + scenario + fidelity level + model hash ⇒ identical results (L2: fixed render settings).
   Every report records them.

## 3. Work packages (parallelise across people/agents)

### WP1 — Behaviour engine (World 2.0)
Upgrade `sim/world.py` (keep it pure Python/numpy, ≥ 50× real time headless):
- **Pedestrians:** social-force model (Helbing) for crowds & groups; desired speed distributions by age (children,
  adults, elderly 0.6–0.9 m/s), wheelchairs, strollers; gap acceptance (logit on vehicle time-to-arrival, impatience
  grows with waiting); red-light compliance probability; hesitation/stop-and-go; running at end of green; phone
  distraction (slower, late reaction); sidewalk walkers that never cross (must not be counted); jaywalkers.
- **Vehicles:** IDM car-following + MOBIL lane change; yielding model (probability depends on speed/distance and on
  pedestrian conspicuity), late braking, red-light running, stopping on the zebra (blocking), queues, buses at stops,
  turning vehicles (if the site has an intersection), motorbikes filtering.
- **Cyclists & e-scooters:** on the road, on the zebra (riding/dismounted), wrong-way riders.
- **Signal:** the production `SignalController` drives the world (fixed / adaptive / beacon).
- **Calibrated against literature** (HCM / FHWA walking speeds, PTV/Helbing parameters) and, if available, against our
  site tracks (speed and gap distributions) — table in the report.
- No physical overlaps ever (collision checks; a real collision is a scenario outcome, logged as such).

### WP2 — Photoreal renderer (L2): **Three.js (plan A)** on the sim laptop (RTX 1000 Ada, 6 GB)
Goal: frames where **the real YOLO11n/YOLO26n at 320 px detects people, bikes and vehicles like on the real street**.
Why Three.js: runs well on 6 GB, reuses the dashboard's scene code (`dashboard/js/twin.js`), fully under our control,
deterministic, scriptable from Python, no 20 GB engine install.

- **Runtime:** `sim/render/` = a Three.js page driven in **headless Chromium via Playwright** (GPU/ANGLE, WebGL2).
  Python `World` sends agent states each sim tick (lockstep over a local websocket / CDP), the page renders one frame
  from the calibrated camera and returns it (PNG/JPEG + per-agent 2D GT boxes and an instance-ID pass rendered with
  flat colours for pixel-exact GT). `sim/render_source.py` exposes it as a frame source to the pipeline.
- **Realism budget (what makes YOLO fire):**
  - *People:* photogrammetry-scanned, rigged humans (Renderpeople free rigged samples, other CC-BY scanned
    characters) retargeted to Mixamo animations (walk, run, idle, look around, cycling pose); variety via clothing
    textures/colours, height scaling (children), accessories (bags, umbrellas, strollers, wheelchairs). Avoid low-poly
    stylised assets: they are exactly what fails detection.
  - *Vehicles/bikes:* scanned or detailed PBR models (Sketchfab CC-BY, Poly Haven), several makes and colours, glass
    with reflections, wheels rotating, headlights/brake lights; real bicycles and e-scooters with riders posed on them.
  - *Lighting:* physically based (`MeshPhysicalMaterial`), HDRI environment maps (Poly Haven CC0) per time of day,
    sun directional light with soft shadow maps (PCSS), night: street lamps + headlights; ACES tone mapping.
  - *Environment:* road textured from **our real site background** (`/api/background.jpg`, ortho-rectified like the BEV
    texture) or CC0 asphalt/porphyry PBR textures; Italian zebra paint with wear; curbs, poles, signs, parked cars,
    building facades from photos → the scene the camera sees should look like the site.
  - *Camera/sensor model (post-processing pass):* same resolution/FOV/pose as our webcam calibration; SSAO, slight
    bloom, motion blur at the exposure time, sensor noise (shot + read noise), vignetting, chromatic aberration,
    auto-exposure response, **MJPG/JPEG compression at the webcam's quality**. Calibrate these against a real frame
    (histograms, noise level, sharpness via Laplacian variance).
  - *Conditions:* sun position/overcast, wet road (roughness + reflections), rain streaks + fog, dusk/night.
- **Performance:** target ≥ 5 rendered fps at 640×480 on the RTX 1000 Ada; render each scenario **once** into a frame
  cache (`runs/render_cache/<scenario>/<seed>/` JPEG + GT JSON) and re-run the pipeline on cached pixels at 50×+ RT.
  Overnight: render the full suite unattended. Run YOLO on the CPU (as on the board), not concurrently on the 6 GB GPU.
- **Realism loop (G2 is the arbiter):** each asset/lighting change is measured by YOLO recall per class × box-size ×
  condition vs real site frames. Iterate on the worst bin first. Keep a `sim/ASSETS.md` table: asset, licence,
  measured detection recall.
- **Plan B: CARLA 0.9.15/0.9.16 (Unreal Engine 4)** — only if Three.js cannot pass G2 for people after a serious
  attempt. It runs on 6 GB at `-quality-level=Low -RenderOffScreen`, synchronous mode, 640×480; drive CARLA actors from
  our World (transforms + animation each tick) so behaviour stays ours. Start its ~20 GB download early as insurance.
- **Synthetic data for training (optional, L40S cluster):** export the cache's GT as a YOLO dataset; fine-tune on
  real + synthetic; report on real footage only.

### WP3 — Hardware-in-the-loop (L3)
- `crosswalk/sources.py`: add `NetworkSource` (pull MJPEG over HTTP from the renderer host, timestamps from the
  sender) — production code, also useful for IP cameras. Renderer host serves frames at the camera fps in sim time.
- Run the **real UNO Q** on the virtual crosswalk: real model latency, real frame drops, real MCU/LEDs/watchdog.
  Evaluator subscribes to the board's `/api/stream` and compares with GT. Report: end-to-end latency
  (event in sim → lamp command on the board → MCU ack), CPU temp/throttling over a 30-min virtual rush hour.

### WP4 — Scenario library & certification suite
- `sim/scenarios/*.yaml`: scripted (exact agents and timing) + stochastic (rates) + conditions (weather/time) +
  fidelity level. Each has **expected outcomes** (counts per class & direction, events that must/must not fire,
  signal timing constraints, max latency).
- Minimum catalogue (≥ 40 scenarios): single/groups A→B/B→A; child; elderly (Green Man+); wheelchair; stroller;
  cyclist on zebra (riding/dismounted); cyclist along road; e-scooter; sidewalk walkers (no count); jaywalker;
  bus occlusion; two-lane queue; car yields / doesn't yield; near-miss (TTC 0.5–2 s sweep); red-light runner;
  ped on red; person falls on the crosswalk (motionless alert); vehicle blocking; night; rain; low sun glare;
  heavy rush hour (30 agents); empty street for 10 min (no false events, duty cycle); camera shake.
- `tools/sim_suite.py`: runs the suite at a chosen level, PASS/FAIL table, exit code, HTML report — this is the
  **pre-deployment certification**: "OCCHIO v1.3 passes 41/42 scenarios at L2; known limitation: …".

### WP5 — Evaluator & reports
- `sim/gt.py` (shared GT definitions), `tools/report.py` (sim or real) → HTML: per-requirement sections
  (recognition per class, approach lead time, rule-trigger precision/recall + latency, counting accuracy per class and
  direction, offline), safety metrics, signal policy comparison, per-condition breakdown, sweep plots, sim-to-real
  table (section 4). Dashboards for the pitch (screenshots + a 60-s video montage of L2 renders with the twin).

### WP6 — Sim-to-real validation (the credibility layer)
See section 4. Needs a **small** real dataset (we'll record it; goal of the simulator is still simulation):
~15–30 min of site footage + teacher labels (`tools/autolabel.py`) + 10 min manual count GT (`tools/count_gt.py`).

## 4. Validating the simulator itself (gates)

| Gate | Test | Pass criterion |
|---|---|---|
| G0 geometry | virtual corners/markers reprojected through the calibration; GT boxes vs rendered silhouettes | ≤ 1 px corners, IoU ≥ 0.9 |
| G1 GT consistency | `sim/gt.py` vs `crosswalk/` on hand cases; L0 suite (perfect detections) | 100 % counts, 0 spurious events |
| G2 detector realism | YOLO recall & precision **per class × box-height bin × condition** on L2 frames vs on real site frames (teacher-labelled); confidence histograms; FP rate per minute | per-bin recall within ±10 pts, FP/min same order |
| G3 noise-model fidelity | L1 noise model fitted on real detections (`tools/fit_noise.py` → `sim/noise_site.yaml`) vs L2 measured errors | L1 ≈ L2 ≈ real within ±10 pts |
| G4 behaviour realism | walking speeds, vehicle approach speeds/V85, gap acceptance, yield rate vs literature (+ site tracks if any) | KS test / within literature ranges |
| G5 pipeline transfer | counting accuracy and near-miss metrics: sim vs real GT on comparable traffic | within ±5 pts |
| G6 **decision transfer** | rank configs (model, imgsz, Hz, ROI, thresholds) by accuracy in sim and on real footage | Spearman ρ ≥ 0.8 — *the* proof that "tested in sim" means something |

If G2 fails for a class/condition: fix the renderer (assets, materials, camera model), add domain randomisation, or
— only for evaluation — use L1 with the real-fitted noise model for that class and say so in the report.

## 5. Last resort: presentation divergence (allowed, but explicit)
If something cannot be made realistic in time, we may diverge **for display only**, never silently:
- everything behind `sim.presentation_mode: true` (default false); evaluation reports refuse to run in that mode;
- every divergence listed in `sim/DIVERGENCES.md` (what, why, impact on metrics);
- allowed: nicer assets/lighting in the pitch video, scripted "hero" scenarios, smoothing of displayed tracks;
- not allowed: changing `crosswalk/` behaviour for the sim, or reporting numbers from presentation mode.

## 6. Milestones
| When | Deliverable |
|---|---|
| Sat 13:00 | World 2.0 skeleton + scenario YAML + `sim/gt.py`; Three.js renderer in headless Chromium driven by World, one crosswalk frame from our camera pose with scanned people + PBR car; G0; **first G2 spike: YOLO recall on 50 rendered frames** |
| Sat 16:00 | L2 lockstep loop: World → Three.js → frames → real YOLO → pipeline → events; G2 numbers on 10 scenarios; decide if CARLA plan B is needed |
| Sat 20:00 | scenario library ≥ 25, `sim_suite.py` + HTML report, NetworkSource; PR merged |
| Sat night | sim laptop renders the full suite × conditions × seeds into the frame cache unattended; sweeps at L1; noise model fit from real footage (G3); optional synthetic+real fine-tune on the L40S |
| Sun 10:00 | HIL run on the UNO Q (L3) for ≥ 30 virtual minutes; G5/G6 with real GT; certification report |
| Sun 11:30 | **freeze**; slides: architecture, gates table, certification table, 60-s render montage |

## 7. Logistics
- `git clone git@github.com:Anatr1/hackturin-task1.git && git checkout -b sim-eval`; Python 3.11 venv +
  `pip install -r requirements-dev.txt`; then **`python tools/fetch_assets.py`** → sample videos in `data/videos/` and the
  exact detector models the board uses in `models/` (ONNX fp32/int8 256/320/416 + NCNN 320; not in git on purpose).
- **Real site footage + real calibration do not exist yet.** They will be recorded on site (`tools/record.py`, ~15–30
  min) and shared out of git (faces/plates: never commit). Until then: develop against `configs/board.yaml` geometry
  and the sample videos (`configs/video_demo.yaml` has an approximate calibration); design `fit_noise.py` / G2 so the
  real data just plugs in. Ask Federico for the files when ready.
- 3D assets: commit only small/licensed ones (glTF, compressed textures, Git LFS if > 10 MB); render cache and CARLA
  (plan B, ~20 GB — start the download early as insurance) stay on the sim laptop, not in git; commit configs, scripts, small reference images, reports. Licences: CARLA (MIT code, CC-BY assets),
  Renderpeople free samples / Mixamo / Sketchfab models — record each licence in `sim/ASSETS.md`.
- Talk to Federico before touching `crosswalk/{counting,safety,signal,tracker,scene}.py`. Commit small and often.
