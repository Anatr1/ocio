# Digital twin visual refresh

The twin uses a stylised daytime street inspired by Crocetta: warm plaster and stone,
green shutters, balconies, shops, leafy trees, granite paving and understated street
furniture. This scenery is illustrative; the crossing dimensions, calibration and
anonymous agent trajectories still come from the node.

The visual reference is the neighbourhood’s residential architecture, including the
[Liberty buildings described by VisitPiemonte](https://old.visitpiemonte.com/it/arte-cultura-e-unesco/itinerari-del-liberty-torino-e-piemonte).
No photographs, downloaded models or external asset requests are used.

## Visual modules

- `dashboard/js/avatars.js`: articulated pedestrians, posed cyclists and scooters,
  sculpted cars, and the existing supported bus/truck/motorcycle classes.
- `dashboard/js/streetscape.js`: procedural facades, roofs, irregular foliage, street
  furniture, pavement/asphalt textures and a daylight reflection environment.
- `dashboard/js/visual-geometry.js`: bevelled shapes, body sections and static mesh batching.
- `dashboard/js/twin.js`: integrates the visuals. Its code from `_buildSignal` onward
  matches master, including projection, track interpolation, headings, analytical
  layers, signal updates, replay and the animation loop.

Static scenery and car details are merged by material. Shadows use one 1024-square
map, and nearby trees cast shadows. Rebuilding the calibrated scene releases its
old visual geometry, materials and textures. All assets are generated locally using
the already vendored Three.js, so the twin continues to work offline.

## Preview and verification

From this branch’s checkout, in PowerShell:

```powershell
& C:/Users/fedem/.venvs/hackturin/Scripts/python.exe -m crosswalk --sim mixed --port 8006 --set server.host=127.0.0.1
& C:/Users/fedem/.venvs/hackturin/Scripts/python.exe -m pytest -q tests
node --check dashboard/js/twin.js
node --check dashboard/js/avatars.js
node --check dashboard/js/streetscape.js
node --check dashboard/js/visual-geometry.js
```

Open http://localhost:8006. On 2026-10-10: **92 tests passed, 1 skipped** (the existing
opt-in GPU simulator test). Chrome browser checks passed for all four views, layer
toggles, live signal and conflict overlays, replay start/seek/return, track retirement,
all supported vehicle classes, and a 390-pixel mobile viewport; no JavaScript errors.
Desktop and mobile screenshots were inspected. These are laptop browser checks;
graphics performance on the board and on physical phones has not been measured.
Pipeline counting and safety validation figures are unchanged.

## Photoreal integration regression (2026-10-10)

The L2 renderer imports the twin's avatar factory. After the module split, its HTTP
allowlist must serve `twin.js`, `avatars.js`, `streetscape.js` and `visual-geometry.js`.
The same explicit list now includes all four modules in the render-cache fingerprint.
The HTTP regression traverses the twin's relative imports and verifies they load,
while unrelated application files remain inaccessible. It reproduced the 404 before
the fix and passed afterward.

All **93 standard tests passed**, and the opt-in Chrome GPU test passed separately
with its temporary cache inside the project (`--basetemp=runs/renderer-test-20261010-2352`;
the sandbox's default temporary directory blocked atomic cache-file replacement).
The GPU check covers camera geometry, rendered pixels, masks, motion, mobile sizing
and dependency hashes. Short runs also passed for `tools/sim_run.py` with the real
ONNX detector and `configs/site.yaml` with NCNN. These are integration checks, not
new counting-accuracy or board-performance measurements.
