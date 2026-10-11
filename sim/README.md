# OCCHIO Virtual Proving Ground

Luigi's simulator work, based on master `33e389a` and the updated simulator handoff.
This is a testing baseline, **not a deployment certificate**. No real site calibration,
footage, reviewed detector labels, or board HIL results have been supplied yet.

## Start Here

Run from the repository root, with the existing virtual environment activated:

```powershell
python -m pip install -r requirements-sim.txt
python tools/fetch_assets.py
python tools/fetch_sim_assets.py
python tools/sim_run.py --scenario mixed --fps 5 --realtime --set sim.browser=chrome --port 8001
```

Open http://localhost:8001. The camera is a Three.js render; detections, tracks,
counts and lamps come from the actual board detector and production pipeline.
The MCU is virtual. The generic street is not the real Turin site. The original
`python -m crosswalk --sim mixed` remains the lightweight L1 demo.

Use Chrome on this laptop: bundled Playwright Chromium fails with Windows SxS
error 14001. The renderer requests the high-performance GPU and has been verified
on the NVIDIA RTX 1000 Ada, rather than the integrated Intel GPU.

## Tests And Reports

```powershell
python -m pytest -q tests --basetemp runs/pytest-local
python tools/sim_suite.py --level L0 --out runs/suite-l0
python tools/sim_suite.py --level L1 --out runs/suite-l1
python tools/sim_soak.py --minutes 10
python tools/sim_suite.py --level L2 --fps 5 --scenarios single_a_b child_crossing driver_yields night_crossing --set sim.browser=chrome --set sim.render_cache=runs/render_cache --out runs/suite-l2-new
python tools/camera_sweep.py --set sim.browser=chrome --set sim.render_cache=runs/render_cache
```

Current seed-0 results (2026-10-10):

| Test | Result | Meaning |
|---|---|---|
| Regression tests | 87 pass including GPU | Original 16 production tests retained; 12 continuous-traffic contracts added |
| Continuous soak | 24/24 runs flow, 0 careful-user collisions | 10 min x 4 scenarios x 2 signal modes x 3 seeds, World only |
| L0, perfect tracks | 40/40 scenarios PASS | Exact counts/directions and scripted logic expectations |
| L1, default noise | 34/40 PASS | Noise is heuristic, not fitted to real detections |
| L2, YOLO11n ONNX 320 | 6/10 PASS | Real NN on pixels, no injected GT detections |
| GPU geometry | < 1 px corner error; exact ID-mask boxes | Virtual geometry only; real-site G0 pending |
| L2 render performance | 5.7-10.6 rendered fps | 640x480, NVIDIA rendering, CPU inference |
| Pixel replay | 125 frames / 25 sim seconds in 1.2 wall seconds | Same raw detections/counts; not a 50x claim |

Existing local reports: `runs/suite-l0-release/report.html`,
`runs/suite-l1-release/report.html`, `runs/suite-l2/report.html`,
`runs/camera-sweep/report.html`. JSON preserves seeds, scenario/model/asset hashes,
configuration, raw detector observations, perfect-world events and rule timing.
New runs also record implementation hashes and dependency versions. Wall-clock
event labels are excluded from deterministic evaluation output.

L1 failures: e-scooters counted as bicycles (by design, `tracker.fast_person_kind`), group undercount, missed yield, late-braking B2 timing, queued vehicle
undercount. L2 failures (before buses were removed): child count, night count, bus count under occlusion, missed
yield. A passing count is not evidence of high frame-level detector recall.

## Cached Pixels And Board Transport

```powershell
python tools/sim_replay.py runs/render_cache/SCENARIO/SEED/FINGERPRINT/run-0001 --out runs/replay
python tools/stream_cache.py runs/render_cache/SCENARIO/SEED/FINGERPRINT/run-0001 --host 0.0.0.0 --port 8090 --loop
```

On the board, select `source.type=network`, `source.url=http://LAPTOP_IP:8090/video.mjpg`,
`source.timestamp_policy=sender`, and the matching camera dimensions/calibration
(available at `/calibration.json`). Only expose this unauthenticated stream on a
trusted test LAN. This tests transport; the UNO Q/MCU watchdog and 30-minute HIL
run are **not yet tested**. Sender times and sequences are checked, and old/reordered
frames are rejected. When a reconnected sender restarts its clock (`--loop` replays
restart on every connection), frames are rebased to continue after the real gap
(`network_rebases` in the stats). Standard IP cameras may explicitly use `timestamp_policy=local`.

Caches are immutable camera trajectories. Replay is suitable for detector/tracker/
count settings, but changed signal policies require a fresh closed-loop render.
Incomplete caches and presentation mode are rejected; `--allow-partial` scores
a valid prefix without scenario certification. Never silently reuse old pixels.

## Real Data Plug-In

```powershell
python tools/detector_eval.py --data PATH/data.yaml --split val --sample-hz 5 --representative --label-policy visible --condition day:clear --config configs/site.yaml --out runs/detection-real.json
python tools/fit_noise.py --report runs/detection-real.json --out sim/noise_site.yaml
python tools/validate_transfer.py --sim runs/render-probe/probe.json --real runs/detection-real.json
python tools/report.py --events PATH/events.jsonl --gt PATH/recording.gt.csv --out runs/real-report
```

Use uniformly sampled reviewed images, **including empty frames**, with visible
boxes. Autolabelled teacher output needs review. Negative downsampling/random
train-val splits do not establish a representative FP/min reference. Fit one
condition at a time. G2 rejects different models/preprocessing, sparse bins and
incompatible labels. Fitted L1 rejects unobserved bins by default. G2-G6 remain
unassessed until measured real evidence is available.

## Handoff

See `ASSETS.md`, `BEHAVIOUR.md`, and `DIVERGENCES.md` before presenting numbers.
Only `crosswalk/sources.py` was extended (generic NetworkSource); protected
counting/safety/signal/tracker/scene modules were not changed. Inform Federico
about the new source type before deploying it to the board.

Next priorities: team testing of the live simulator, better child/scooter assets, bicycle detection at board resolution,
measured site lighting/sensor calibration, real-data noise fitting, and actual HIL.
CARLA has not been downloaded; a 20 GB fallback install is a separate decision.
