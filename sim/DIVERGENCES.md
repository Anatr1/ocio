# Known Limitations And Presentation Policy

`sim.presentation_mode` defaults false. All evaluation paths reject true; current
reports use false. No cosmetic divergence is silently enabled for scoring.

| Limitation | Impact / current treatment |
|---|---|
| Real site footage/calibration absent | Board geometry + virtual camera/generic facades; not real-site G0/G2 |
| Rigged human is textured, not scanned | Measured intermittent recall; child is height-scaled adult, not a true child mesh |
| Only cars as motor vehicles | Buses, trucks, vans and motorbikes are no longer generated (not present at the test site, assets were schematic); the production pipeline still handles those classes |
| Bicycles small for the board detector | Real bicycle meshes, but at this camera pose YOLO11n@320 rarely detects the bicycle (rider found as person); see ASSETS.md |
| Scooter assets schematic | Class realism unvalidated |
| Wheelchair/stroller accessories provisional | Mobility behaviour exists, appearance/class recognition not validated |
| Lighting/sensor values not measured | Night count fails; no calibrated auto-exposure, physical motion blur, SSAO, bloom or chromatic aberration |
| One walking clip | No validated run/idle/cycling/fall animation library |
| Real-fitted L1 unavailable | Default miss/jitter/confusion noise is heuristic; do not call it a realistic detector proxy |
| Marginal fitted-noise model | Does not fit temporal correlation, full class confusion or joint rider detections; G3 still needs comparison |
| Synthetic rule identity matching | L2 evaluator associates tracks to true agents after NN processing; approximate nearest matching can be ambiguous in crowds |
| Cached replay is open-loop | Pixels cannot react to new lamp commands; rerender signal-policy comparisons |
| Network source only locally tested | UNO Q latency, temperature, drops and F1 watchdog are unassessed. A sender that restarts its clock after a reconnect (e.g. `stream_cache.py --loop`) is rebased onto the receiver timeline after the real gap (`network_rebases`) |
| Continuous-traffic rules are heuristic | Kerb waiting places, lane checks, detours, 30 s give-up, zebra rule and arrival pre-roll keep long runs flowing and crash-free for careful users (see BEHAVIOUR.md); none is fitted to Turin data |
| Arrivals and queues | Random vehicles appear 58 m from the zebra, at the end of the rendered road; saturated queues are capped 150 m further upstream and excess arrivals are dropped (`arrival_dropped`) |
| Camera view weak spot | Virtual sweep sees +X car first at 6 m for curb/raised poses vs 12 m upstream; not a validated site recommendation |
| Performance targets incomplete | Render >=5 fps met on this GPU; dense headless/replay 50x targets not established |
| CARLA fallback absent | No large download/install undertaken; renderer realism decision awaits real comparison |

L0/L1/L2 PASS labels describe scenario expectations, not road-deployment readiness.
G2-G6 cannot be certified from the synthetic tests alone. Do not present missing
bins, unreviewed teacher labels, or manually supplied rank scores as real evidence.
Real recordings with faces/plates and model weights remain out of Git.
