# Architecture

```
camera (V4L2, MJPG 640x480, grabber thread keeps only the newest frame)
  │
  ▼
MotionGate (160 px thumbnail, background difference, ~1 ms) ──► Scheduler: run detector? (motion / live tracks / 1 Hz heartbeat, max_hz cap)
  │                                                                     │ (duty cycle: compute follows traffic)
  ▼                                                                     ▼
Detector (ONNX Runtime | NCNN | TFLite | Ultralytics | simulator)  → boxes (letterbox, ROI crop, NMS / NMS-free YOLO26)
  ▼
fuse_riders (person on bicycle/motorcycle/e-scooter = 1 road user)
  ▼
Scene.localize: foot point → ground (homography), covariance via homography Jacobian, 3D box fit for vehicles,
                metric height (camera pose recovered from the homography)
  ▼
Tracker (BEV Kalman CV, Mahalanobis gating, 2-stage ByteTrack association, re-identification of lost tracks,
         class voting, speed-based e-scooter detection, duplicate merge)
  ▼
Counter (counting lines on the ground, history-driven)   SafetyMonitor (TTC+DRAC, PET, yield, alerts, warning level)
  ▼                                                        ▼
SignalController (beacon | fixed | adaptive + Green Man+) ─► MCU worker thread ─► arduino-router ─► STM32 sketch
  ▼
EventBus (ids, events.jsonl, tracks.jsonl, 3D replay clips) ─► HTTP server (stdlib): SSE stream, REST, MJPEG, static dashboard
```

## Threads on the board
`camera` (grab + MJPG decode) · main loop (gate → detector → tracking → logic) · `mcu-worker` (RPC, never blocks vision)
· `http` + one thread per client (SSE, MJPEG). Detector threads = `detector.threads` (default 3 → one A53 core left free).

## World frame
Origin at the crosswalk centre; **X along the road**, **Y across** (curb A at −L/2, curb B at +L/2), Z up. Every module
works in metres in this frame; the dashboard maps it to Three.js as (x = X, y = Z, z = −Y).

## Data formats
- **State (SSE `state`, ~10 Hz)**: `{t, tracks:[{id, kind, cls, x, y, vx, vy, speed, heading, zone, height, dims, bbox}],
  counts:{counts, sub_counts, directions, vehicle_v85_kmh, ped_mean_speed, timeline}, safety:{near_miss, yield_rate,
  pet_min, active_conflicts, warning_level, safety_score}, signal:{mode, state, veh, ped, extension_s}, mcu:{veh, ped,
  warning, matrix[104], connected}, perf:{det_hz, infer_ms, duty, cpu_temp_c, ...}}`
- **Events** (SSE `event`, `runs/<run>/events.jsonl`): `passage`, `crossing`, `vehicle_pass`, `jaywalk`, `conflict`,
  `pet`, `yield`, `violation`, `alert`, `ped_extension`, `signal`, `count_corrected`, `calibrated`.
- **Replay** (`/api/replay/<id>`): `{event, frames:[{t, tracks:[{id, k, c, x, y, vx, vy, h}], signal}]}` - 6 s before to
  3 s after the event, a few KB.

## Key decisions
- **Ground-plane (BEV) tracking** instead of image-space: speeds, distances, TTC and counting lines are physical;
  perspective noise is handled by propagating pixel noise through the homography Jacobian.
- **Counting lines evaluated on the full track history** (including pre-confirmation samples): fast cars confirmed
  mid-crosswalk are counted; jitter of stationary objects never counts.
- **Conflicts need TTC *and* DRAC**: avoids flagging cars that stop normally (constant-velocity TTC alone over-alarms).
- **No web framework, no broker**: stdlib HTTP + SSE → nothing to install on the board, any phone can connect.
- **MCU owns safety-critical outputs** with its own watchdog; Linux only sends desired state.
