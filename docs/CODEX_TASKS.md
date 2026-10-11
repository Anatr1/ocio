# Parallel tickets (self-contained - hand one to Codex or a teammate)

Context for every ticket: repo `hackturin-task1`, Python package `crosswalk/` (edge node), `sim/` (simulator),
`dashboard/` (static Three.js app served by `crosswalk/server.py`). Run the simulator with
`python -m crosswalk --sim mixed` and open http://localhost:8000. Don't add heavy dependencies (the node runs on an
Arduino UNO Q: numpy, opencv, onnxruntime only). Keep the world frame convention in `crosswalk/config.py`.

## T1 - Fleet view (multi-node city map)  [high pitch value]
`tools/hub.py`: given N node URLs, subscribe to each node's `/api/stream` (SSE; parse `event:`/`data:` lines with
urllib, one thread per node), keep the latest state per node, and serve `dashboard/fleet.html` on :9000 with an SVG map
(no external tiles; position nodes by `config.node.geo` lat/lon, equirectangular projection) showing per-node KPIs
(counts, near-misses, yield rate, safety score as colour) and a click-through link to each node's dashboard.
Test by running two simulators on ports 8000/8001 (`--port`) with different `--seed` and `--set node.id=... node.geo.lat=...`.

## T2 - Analytics panel  [medium]
Add `/api/analytics` to `crosswalk/server.py` computed from `node.counter` and `node.safety`: counts per 5 min per class
(last 2 h), vehicle speed histogram (5 km/h bins), pedestrian crossing-time and walking-speed histograms, PET histogram,
list of conflict locations (x, y, level). Add a toggleable "Analytics" overlay in `dashboard/` drawing them with
`<canvas>` (no chart library) in the existing dark style (`dashboard/css/style.css`).

## T3 - Unit tests  [medium]
`tests/` with pytest: geometry (homography round trip, `Camera.from_ground_homography` recovers height/focal from a
`Camera.look_at` camera), tracker (two crossing pedestrians keep their ids; a 1.5 s occlusion is re-identified with the
same id), counting (synthetic straight-line tracks across the crosswalk produce exactly one passage each; a stationary
jittering pedestrian at the curb produces none), safety (`ttc_box` and `drac` on hand-computed cases), msgpack_lite
round trip vs. the `msgpack` package.

## T4 - Safety report generator  [medium]
`tools/report.py runs/<run>/events.jsonl` → standalone HTML report (inline CSS/SVG, no deps): counts by class and hour,
V85, yield compliance, near-miss list with times/levels, conflict location scatter on a crosswalk schematic,
recommendations (e.g. "V85 = 47 km/h > limit 30 → traffic calming").

## T5 - QR code card  [quick]
Add `/api/qr.svg` to the server generating a QR code for `http://<board LAN IP>:<port>/` (pure-Python QR encoder - e.g.
vendor `segno` as a single module or implement byte-mode QR v1-v4) and a printable `dashboard/qr.html` card with the
OCCHIO logo, the QR and "scan me - live 3D twin".

## T6 - Robustness  [Sunday morning]
systemd user service (or cron @reboot) + `tools/healthcheck.sh` (restart the pipeline if `/api/health` stops answering),
log rotation of `runs/`, and a `--record-events-only` mode.
