# Optional intersection mode

This branch adds a four-arm, right-hand-traffic intersection to the simulator and
digital twin. The existing crosswalk node, camera/replay modes, detector, tracker,
firmware, public page, economics planner and original simulators keep their
existing execution paths. The command-line dispatcher and shared pixel renderer
gain opt-in branches; the existing crosswalk renderer takes its original path.

## Run

From this branch's checkout, using the project Python:

```powershell
& C:/Users/fedem/.venvs/hackturin/Scripts/python.exe -m crosswalk --intersection --intersection-scenario commute --port 8010
```

Open <http://127.0.0.1:8010>. Stop with Ctrl+C. The server binds to localhost.
It uses existing locally bundled Three.js, avatars and fonts; no model downloads,
external assets or new packages are needed for the default twin mode.

For the photoreal camera and actual YOLO inference:

```powershell
& C:/Users/fedem/.venvs/hackturin/Scripts/python.exe -m crosswalk --intersection --intersection-render photoreal --intersection-detector real --intersection-model models/yolo11n_416.onnx --intersection-camera N --intersection-scenario commute --port 8010
```

The **camera card** shows the photoreal world that supplies the NN's pixels.
The main 3D/top/street/cinema scene is a digital twin reconstructed from the
model's metric tracks. Four fixed N/E/S/W cameras capture the same physical
simulation timestamp; selecting or hiding a displayed camera does not stop any
camera's inference or reset shared identities. Raw RGB and NN-box overlays are
available independently of the twin.

Photoreal mode uses the existing licensed PBR cars, textured rigged people,
bicycles, asphalt and HDR sky; binary assets and weights stay out of Git.
On a fresh checkout run `python tools/fetch_sim_assets.py` and provide an ONNX
model. This worktree already has the verified assets and YOLO11n 320/416 models.

Flags: `--intersection-render twin|photoreal` (default twin),
`--intersection-detector none|real` (default none; real requires photoreal),
`--intersection-model <onnx-path>`, `--intersection-camera overview|N|E|S|W`,
`--intersection-condition day|night|rain|fog`, and
`--intersection-render-fps .5..15` (default 5 synchronized batches per simulated
second). With real inference, overview selects N; the four crossing cameras are
the active sensors. Chrome and Playwright are required, as in the existing L2
workflow. Rendering/inference is serialized on one GPU context. A slow GPU slows
virtual time instead of advancing through unsensed seconds; the pace control
sets an upper bound on simulation speed.

The data flow is:

`physical simulator -> four photoreal RGB images -> ONNX NN -> calibrated ground
projection -> cross-camera fusion -> shared metric tracker -> twin + signal
queues/occupancy + observed passage/wait statistics`

Instance masks and simulator IDs are confined to renderer diagnostics. They are
never supplied to inference, fusion or the perception twin. Cross-camera fusion
allows one observation per camera in a spatial cluster, uses conservative
covariance intersection and the existing Kalman/ByteTrack-style tracker.
Missing detections leave gaps in the twin; false positives may create tracks.
Changing the displayed view preserves shared IDs. A restart resets physical
actors, perception, counters, camera frames and scores together. Scoring retains
at most 3,000 frames per view; no calibrated accuracy is claimed.

In real detector mode the controller uses **perceived** demand and occupancy.
Stale observations hold all red (1.5 simulated seconds by default; at low
configured camera rates, one frame period plus 0.2 s if longer). Curb users create pedestrian demand; users on
zebras/inside the junction block clearance. Through/right intent remains unknown
until an exit is observed because those movements share an incoming lane and
signal phase. Counts require an observed approach and exit on one track; wait
means observed stationary time, not unseen full-journey delay. Model errors,
occlusions and approximate vehicle footpoints can affect counts and control.

Default twin mode remains the perfect-observation baseline. Photoreal with
`--intersection-detector none` is an RGB preview of that baseline. No simulator
truth fallback is applied in real detector mode. `/api/ground-truth` explicitly
exposes the physical world for lab diagnosis; `/api/state` and `/api/report`
publish the perception reconstruction and its statistics. Offline camera scores
are explicitly identified as diagnostics in the exported report.

```powershell
# Fixed-time baseline; faster live simulation
& C:/Users/fedem/.venvs/hackturin/Scripts/python.exe -m crosswalk --intersection --intersection-policy fixed --intersection-speed 4 --seed 7 --port 8010

# Headless, maximum-speed run with a JSON report on stdout
& C:/Users/fedem/.venvs/hackturin/Scripts/python.exe -m crosswalk --intersection --no-server --fast --max-seconds 300

# Paired five-minute policy experiment, three identical-demand seeds
& C:/Users/fedem/.venvs/hackturin/Scripts/python.exe tools/intersection_eval.py --scenario commute --minutes 5 --seeds 0 1 2 --out runs/intersection/commute

# Sustained flow and footprint checks, three fifteen-minute scenarios
& C:/Users/fedem/.venvs/hackturin/Scripts/python.exe tools/intersection_soak.py --minutes 15 --seed 17

# Existing commands continue to use the existing pipeline
& C:/Users/fedem/.venvs/hackturin/Scripts/python.exe -m crosswalk --sim mixed
```

Intersection options are `--intersection`, `--intersection-scenario`,
`--intersection-policy` and `--intersection-speed` (.1–30). Shared options
`--seed`, `--port`, `--fast`, `--max-seconds`, `--max-frames` and `--no-server`
also work. Headless runs require a finite duration/frame limit. Camera/video,
`--config`, `--set`, `--show` and `--sim` belong to crosswalk mode and cannot be
combined with `--intersection`.

Presets: `balanced`, `commute`, `pedestrian`, `turning`, `saturated`, `empty`.
All rates and turning fractions are explicit in `sim/intersection/world.py`.
They are synthetic examples, not measured intersection demand.

## Geometry and behaviour

- Four arms, two incoming and two outgoing lanes per arm, 3.5 m wide.
- Dedicated inside left-turn lane; outside lane shared by straight/right traffic.
- Twelve vehicle routes with metric arc-length interpolation, curved left/right
  connectors, heading changes, speed limits in turns and IDM following.
- Four crosswalks, one across each arm. Walkers and crossing riders use separate
  directional paths and footprint-based longitudinal spacing; road riders use
  protected vehicle movements.
- Lane queues, safe stop-line admission and an outgoing-lane blockage check.
  Arrivals that cannot fit at the upstream boundary are explicitly counted as
  dropped/diverted; no unbounded upstream network is invented.
- Individual track IDs persist through a turn. One completed road journey counts
  once by origin and manoeuvre; its traversal of two zebras is also recorded in
  the corresponding crosswalk totals. Crossing walkers/riders count once, with
  direction. Road and crossing bicycles have separate underlying tallies and a
  combined bicycle-class total in the report.

## Coordinated signals

Five permitted phases:

| Phase | Green movements |
|---|---|
| NS | North/south straight and right |
| NS_LEFT | North/south protected left |
| EW | East/west straight and right |
| EW_LEFT | East/west protected left |
| PED | All four pedestrian crossings; vehicles red |

Concurrent protected paths are checked using oriented car footprints, including
opposing left turns. Shared-lane branches rely on following distance. These are
protected turns: there are no permissive opposing-traffic turns, right-on-red,
diagonal pedestrian crossings, lane changes or roundabouts in this mode.

Vehicle phases close with 3 s yellow, then at least 2 s all-red. Pedestrian green
ends with a 4 s flashing clearance indication, then all-red. In the perfect-observation baseline, a conflicting green
waits until every admitted vehicle has cleared the exit crossing and every
admitted walker/rider has finished. In vision mode this gate uses observed
occupied conflict zones and recently lost tracks; missed detections can affect it.
Occupancy extends clearance without a forced
unsafe timeout. A staged slow walker demonstrates this hold.

Fixed mode rotates through all five phases: 18 s vehicle green, 10 s pedestrian
green, plus transitions/occupancy clearance. Adaptive mode scores queued demand
and accumulated waiting, skips empty phases, batches vehicle service to avoid
switching losses, and prioritizes old requests. Defaults: 12 s minimum vehicle
green, 35 s maximum, 6–8 s pedestrian admission, age priority at 70 s. That age
threshold is a scheduling priority, **not a guaranteed maximum journey wait**;
congestion and clearance can extend it. Calls are remembered until a pedestrian
phase serves them. Changing policies live preserves the active clearance state.

## Dashboard

The new page has 3D/top/street/cinema views, orbit/zoom, route/trail/label layers,
live signal heads, phase explanations/history, queues and counts per approach,
completed-journey waiting averages, pause/resume, speed controls, preset restart,
crossing calls, slow-walker staging and JSON export. It reuses the established
anonymous avatar factory and sunlit styling without changing the original twin.

**Compare fixed & adaptive** is a separate perfect-observation policy benchmark.
It runs two independent fresh five-minute preset runs
with the current seed. The live world keeps running. Manual staging and calls
from the live world are not replayed into the comparison. The UI reports both
improvements and losses, throughput, residual queues and dropped arrivals; the
full result can be downloaded as JSON.

Routes: `/api/state`, `/api/config`, `/api/report`, `/api/health`,
`/api/comparison`; local controls use `/api/control`. The intersection server
serves an explicit asset allowlist and synthetic camera JPEGs, without exposing
real footage or project files. Camera endpoints are `/api/camera.jpg` and
`/api/camera-raw.jpg`, with optional `?camera=N|E|S|W`.
Crosswalk/public APIs remain available in their original mode.

## Model boundary

The default mode is **L0: perfect simulator observations**. The opt-in photoreal
real-detector mode is a four-camera vision/control prototype with the same
licensed renderer and actual ONNX inference used by the existing crosswalk L2
flow. It has no MCU actuation, persistent citizen database or field calibration.
Neither real intersection accuracy nor safe field signal control is validated.
The old crosswalk pipeline and its validations remain separate.

Driver behaviour is a simplified route/following model; geometric holds prevent
vehicle interpenetration and are counted when used. Queued pedestrians follow
fixed paths rather than a full sidewalk social-force model. It represents one
junction, not a connected road network. Turn speed caps, lane discharge and the
synthetic arrival presets require calibration before interpreting real capacity.

TTC screening includes vehicle–vehicle and vehicle–crossing-user pairs. It uses
constant velocity, so curved paths can produce false flags. These are possible
conflict indicators, not accident predictions or a measured detection score.

Finite-window comparisons have no warm-up. Accumulated vehicle delay is
`sum(max(0, 1 - speed/desired_speed) * dt)`; pedestrian wait sums time not admitted
or prevented from progressing in the curb queue. They include active unfinished
users. **Dropped arrivals are excluded from delay**, so inspect diversions and
throughput alongside delay. Completed-journey means can have completion bias;
residual populations are reported explicitly. V85/mean speed use the last 10,000
completed car samples; walking durations use the last 2,000 per crossing.

## Verification

```powershell
& C:/Users/fedem/.venvs/hackturin/Scripts/python.exe -m pytest -q tests
node --check dashboard/js/intersection.js
# Requires a running intersection server and installed Chrome:
& C:/Users/fedem/.venvs/hackturin/Scripts/python.exe tools/intersection_smoke.py
```

The earlier ground-truth/photoreal-diagnostic implementation passed **185 tests, 1 skipped** (existing optional
GPU test). New coverage includes all twelve routes, concurrent footprint geometry,
counts/classes/directions, policy transitions, slow walkers, downstream blockage,
manual calls, five continuous-flow presets, deterministic paired arrivals,
pedestrian crowd spacing, opt-in CLI dispatch, local controls and HTTP assets.
Camera tests also cover homography round trips, RGB-only detector input,
projected tracker measurements and optional camera flags/controls.

Chrome checks cover actual rendered desktop/390px/320px layouts, all four camera
views, layers, live updates, pause/resume, switching policies, staging, restart,
the background comparison and download. No JavaScript or HTTP errors were seen.
Screenshots and full experiment output are kept in ignored `runs/`.

Fifteen simulated minutes each of `commute`, `saturated`, `pedestrian`, seed 17:
321/380/243 completed road passages; all minutes after the initial minute had at
least 5 passages. All user footprints were checked once per simulated second:
900 samples per scenario, no overlap found. This is laptop simulator evidence;
it does not close the board's real-camera/physical-watchdog soak requirements.

Policy measurements and their limits are appended to `docs/VALIDATION.md`.

Photoreal checks:

```powershell
python tools/intersection_render_check.py --model models/yolo11n_416.onnx
python tools/intersection_smoke.py --photoreal
```

Five staged day-camera frames on the RTX 3060 Laptop GPU passed mask visibility
and <1 px projection checks. YOLO11n 416 returned 7/11/5/2/5 raw detections in
overview/N/E/S/W (confidence >=0.15). These are execution checks, not a detection
accuracy benchmark. The photoreal browser check passed camera switching,
raw/overlay selection and desktop/mobile layouts with no JS/HTTP errors.
Night and wet-road conditions also passed the five-camera render/NN execution
check. These conditions adjust lighting/materials; rain is not a calibrated
particle/sensor-drop model.

Four-camera perception checks additionally cover duplicate observations,
nearby same-camera users, conservative fused covariance, model-only identities,
unseen physical users remaining absent, false positives appearing in the twin,
perceived demand reaching the controller, stale-frame all-red, reset/view-change
identity contracts and curb versus occupied-zebra clearance. Browser QA verifies
the separate camera card and optional feed visibility while the twin stays visible.

Final full-suite result: **195 passed, 1 skipped**.
