# Live Grove deployment results

Hardware acceptance is **IN PROGRESS**. Corrected green/yellow wiring, connected lamps, OLED and buzzer were generally accepted by the operator. White LED testing is deferred. Corrected target flash and strict live software collection passed; freeze software recovery passed, physical observation was unmeasured. Scored live trials, remaining recovery/reboot and soak remain incomplete.
Branch: `codex/live-board-gpio`; base master: `e2c61bf`.

## Laptop preparation (2026-10-11)

- Standalone GPIO branch `21f2aeb`: all five files already preserved in master under
  `firmware/grove_oled_buzzer_test/`; its wiring is the reference.
- Grove profile and self-contained App Lab packager added; original profile retained.
- Required MCU virtual-fallback and false connection readiness regressions failed
  before their fixes (2 failed, 1 passed), then passed.
- Original firmware reproduced the immediate audio shutdown failure in the host
  sketch harness. Both hardware profiles are tested with fake peripherals.
- The danger audio override also failed on both profiles before its correction;
  urgent B2 audio now takes priority over ordinary walk/clearance ticks.
- Full laptop suite: **188 passed, 1 skipped** (the existing optional GPU test).
  After the final audio-transition/packaging adjustments, all **30 targeted
  firmware, connection, collector, packaging and fail-safe checks passed**.
- These are laptop checks only. Target compilation, physical sound/LED/OLED timing,
  live calibrated counting and board overhead remain unmeasured.

## Conditions (fill on the board)

Commit / firmware manifest: source `0dc35bcd9f590947e72562e478cb11a9efc311a4`; Grove + OLED laptop preview packaged successfully. Initial target app: `/home/arduino/ArduinoApps/crosswalk_grove_live_20261011_0dc35bc_r2`. Current corrected app/source: `crosswalk_grove_live_20261011_56e47cc` / `56e47cc1a3e50983c4759bb86b8d85dc2040e298`, green D3/yellow D2, target flash/start passed; physical correction verification requested. [Target manifest](grove_target_manifest.json) retrieved: all six app-file hashes match the laptop preview. Revision is null because the board uses a tracked-source tar deployment; the source commit above identifies the code.
Date/time and operator: preparation 2026-10-11T11:16:28+02:00; physical observer not yet confirmed.
App path / core version / libraries: new Grove path above; previous active app `/home/arduino/ArduinoApps/crosswalk_mcu`. `arduino:zephyr` **1.0.0**, Python **3.13.5**, kernel **7.0.0-g122c2c22d838**. U8g2 **2.36.5** cached; no upgrades performed.
Wiring / OLED identification / buzzer: **current corrected Grove map: green D3, yellow D2, red D6, white D7, passive buzzer D4, I2C OLED**. Operator initially confirmed the target pin map (shield 3.3 V; green D2, yellow D3, red D6, white D7; 330 Ω/common ground; passive D4; Grove I2C OLED). Later clarified **LEDs are not plugged in**. OLED and buzzer are connected; printed OLED/buzzer model and wiring photo remain uncollected. Lamp acceptance is unmeasured.
Camera mode / actual frame size / mount: IMX219 CAM0 bound after operator reseated the camera while powered down and rebooted. Capture-only check: 60 frames, zero missing, 632×480; [log](grove_cam0_capture.log). Mount and calibration remain unverified. Capture timing during compilation is not an inference benchmark.
Measured rectangle or zebra / calibration file: operator confirms the mounting is unchanged from yesterday's recording and that no waiting areas are visible. Found `configs/site.yaml`: six-stripe partial rectangle, 3.0×5.5 m, corners (6,348), (128,278), (513,317), (456,405), image 632×480. Copied only its measured crosswalk/calibration fields into ignored `configs/board_grove_local.yaml`; retained CAM0 and live node ID. [Applied config](grove_live_config.txt). This does not validate off-screen kerbs or waiting detection.
Detector / image size / threads: real NCNN YOLO11n 320 / four threads. Strict 120-second live software acceptance passed; sampled inference median 148.1 ms (133.9–223.3 ms). These measurements do not establish detection/count accuracy.
Ambient temperature / cooling / power:

## Results

| Test | Status | Method, observations, measured numbers and evidence |
|---|---|---|
| Target compile/flash | PASS | Compile-only exit 0: 123700 B flash (15%), 51784 B RAM (19%). App Lab upload/start exit 0; correct app running. [Initial compiler](grove_compile_only.log), [initial flash](grove_app_start.log), [initial RPC](grove_boot_rpc.txt). Corrected app 56e47cc target flash/start also PASS: 123700 B flash / 51780 B RAM, exit 0. [Corrected flash](grove_pinfix_flash.log). |
| Boot fail-safe outputs | PRE-FIX BASELINE OBSERVED / CORRECTED RETEST PENDING | With vision stopped and no heartbeat, `get_status=[1,1,1,4,0,0,1,-1]`: Grove profile 1, effective fail-safe, vehicle flash-yellow, warnings suppressed. Audio field is the configured enable flag. Operator confirmed OLED FAILSAFE and no buzzer sound after diagnostics stopped. After LEDs were connected, Federico observed yellow flashing, other LEDs off, buzzer silent, OLED FAILSAFE and a matrix “!”. Matrix blink rate and exact physical onset latency remain unmeasured. |
| Direct lamp/warning/buzzer/OLED RPC checks | CONNECTED OUTPUTS OBSERVED / WHITE DEFERRED | All eight forced states accepted and reported by Grove status; heartbeat pause entered fail-safe, resume recovered. Sender stopped cleanly, exit 0. Operator reports OLED FAILSAFE and unpleasant buzzing; reply overlapped diagnostics; follow-up confirmed no sound in fail-safe. LED outputs cannot be observed because LEDs are unplugged. [RPC log](grove_direct_rpc.log), [status samples](grove_direct_status.jsonl), [summary](grove_direct_summary.json). |
| IMX219 + real NN + real MCU progressing | SOFTWARE PASS | Corrected app/source 56e47cc: strict 120.002 s, 57 samples, zero failures, fresh CAM0, NCNN YOLO11n 320 and real connected Grove MCU. [Corrected samples](grove_pinfix_live.jsonl), [summary](grove_pinfix_live.summary.json). Earlier app: 59 samples/120.001 s also passed. Physical/functional acceptance remains incomplete. |
| Camera calibration | PARTIAL | Existing six-stripe 3×5.5 m geometry preserved for the operator-confirmed unchanged mount. Kerbs/waiting areas not visible; live alignment not independently checked. |
| Camera-driven waiting -> S1, 3 trials | UNMEASURED | Both waiting areas are outside the current view (operator report). |
| Full walk/clearance/return cycle | PENDING | |
| Slow crossing / S3 extension | PENDING | |
| Pedestrian counting A->B and B->A, 10 each | PENDING | |
| Return crossing / pass-by without count | PENDING | |
| Live bicycle/e-scooter / vehicle coverage | PENDING | |
| Physical B1/B2 indications, method labelled | WHITE LED DEFERRED | Operator reports white not plugged and requests testing later. B2 sound/RPC forced-state evidence remains separate from live conflict acceptance. White LED cannot reproduce amber/red colours. |
| Public stats persist across restart | PENDING | |
| Freeze / crash physical fail-safe and recovery | SOFTWARE PASS / CRASH OLED OBSERVED | Freeze physical observation unmeasured. Crash PID 3410 → 3739: fail-safe first sampled 1.813 s after KILL, heartbeat age 2029 ms; fresh real-MCU/vision recovery first sampled 6.377 s after KILL. Operator confirmed OLED FAILSAFE then normal; lamp/audio timing unmeasured. [Freeze](grove_pinfix_freeze.jsonl), [crash](grove_pinfix_crash.jsonl). |
| Confirmed camera reopen and recovery | SOFTWARE PASS / PHYSICAL UNMEASURED | Labelled eight-second synthetic CAM0 read failure; reopen counter 0 → 3 and processed frames 3 → 7, real MCU recovered. Operator missed physical observation. Normal production service restored. [Metadata](grove_cam0_fault.jsonl). No powered CSI disconnect. |
| Reboot without manual start | SOFTWARE PASS / PHYSICAL PENDING | Operator power interruption; services returned automatically, live CAM0 healthy, MCU connected, correct `_r2` Grove path, new PID 1682 and zero restarts. Physical onset/recovery timing unmeasured. [Evidence](grove_power_interruption.txt). |
| Full 30-minute soak | PENDING | |
| Offline inference + GPIO | SOFTWARE PASS | No default routes and wlan0 disconnected before and after corrected strict run; fresh CAM0, local NN and real MCU control progressed. No network configuration changed. [Before](grove_network_preflight.txt), [after](grove_network_after_live.txt). Physical internet-loss transition timing unmeasured. |

## Exact errors and changes made on the board

Read `docs/HANDOFF_LIVE_GPIO.md`, fetched the remote branch and checked out
`codex/live-board-gpio` at `0dc35bc`. Preserved unrelated untracked `hardware/`
files. Prepared tracked-only deployment archive in ignored `runs/`, and a local
Grove + OLED app preview with the source revision and file hashes. Packager
completed; this does not establish target compilation or peripheral operation.

Initial connection attempts to the previous board address failed:
```
ssh: connect to host 10.34.93.148 port 22: Connection timed out
curl: (28) Connection timeout after 3000 ms
```
Requested the current board IP, actual wiring/OLED identification and live scene
measurements/observer availability. No board files, processes, firmware, calibration
or statistics have been changed. Wiring confirmation is required before flashing.
The preview manifest is labelled laptop-only; retrieve the actual target-generated
manifest and compiler logs when board access is restored.

USB access subsequently succeeded using the already-installed Arduino ADB tool,
following [Arduino's USB shell instructions](https://docs.arduino.cc/tutorials/uno-q/debian-guide/).
Preserved [initial services/apps/versions](grove_before.txt) and
[initial camera/health state](grove_camera_before.txt). The initial health endpoint
reported `ok=false`, null vision age and fail-safe true. Kernel probe errors:
```
[   12.054978] imx219 2-0010: Error reading reg 0x0000: -6
[   12.062474] imx219 2-0010: error -ENXIO: failed to read chip id 219
```
No CSI GPIO reset or ribbon hot-unplug was attempted.

Stopped both services and the exact running crosswalk app, then preserved the old
environment, configs, active app and production code in
`/home/arduino/occhio-before-grove-20261011-0dc35bc-eoyv90` on the board. Statistics
were copied conditionally. The later [backup audit](grove_backup_audit.txt) confirmed no pre-existing stats directory or stats backup; the code backup passed `gzip -t`. [Backup log](grove_backup.log). Recordings, virtualenv and
weights were retained. Transferred/extracted tracked source only over USB. Verified
`cv2`, `ncnn`, `numpy`, `msgpack`, `yaml` imports and prepared the new Grove + OLED
app without starting or flashing it. [Preparation log](grove_deploy_prepare.log).

Board wall clock read **2026-10-10 17:06 UTC** while the client date was
**2026-10-11**. It is unsynchronised; archive extraction emitted nonfatal future
file-timestamp warnings. Do not use this clock for absolute event timing until it
is corrected; monotonic time remains the intended latency reference.

A compile-only check using cached versions was staged on the laptop, but its USB
transfer failed before execution:
```
adb: error: failed to get feature set: device '<board-serial>' not found
```
The device serial above is redacted from anonymous evidence. A follow-up USB/ADB inventory contained no UNO Q. Operator was asked to reconnect
and still needs to confirm wiring/OLED and calibration/physical-observer details.
**No flash, actuator commands, live functional pass or compile-only pass claimed.**
Both services and the previous app were stopped at the last connected check;
boot can restart the previous service settings if power is cycled. Keep the old
pin-map mismatch in mind until the Grove profile has been flashed.

## Remaining limits

No separate pedestrian LEDs, red warning beacon or physical button in the Grove
wiring. Record any additional unmeasured requirements; never convert a software
check, forced RPC or replay trial into a claimed live-camera physical pass.

## CAM0 recovery and target build (2026-10-11)

After the operator corrected the camera connection and rebooted, IMX219 bound at
`0-0010` and `cam --list` enumerated CAM0. [Reboot evidence](grove_camera_reboot.txt).
Capture yielded 60 nonempty frames without opening a USB camera. Nonfatal libcamera
warnings include unsupported controls and fallback to `uncalibrated.yaml`.
This establishes capture only, not calibrated detection or integrated operation.

The old service auto-restarted after reboot but repeatedly exited with code zero.
Inspection found zero-byte deployed `crosswalk/__main__.py` and `pipeline.py`;
the local tracked archive retained normal source files. The cause is not established.
Stopped both services and the old app, restored the tracked archive, ran `sync`,
and verified the two source hashes against the laptop. Existing dependencies
imported successfully. [Restoration log](grove_restore.log).

Prepared a fresh `_r2` Grove + OLED app rather than using the earlier folder.
The compile-only Arduino/Zephyr check passed using the cached core and library
versions, with two build jobs: exit 0, flash 123700 bytes (15%), RAM 51784 bytes (19%).
It did not upload or drive GPIO. App Lab flash/start was then launched for `_r2`. Wiring was
subsequently confirmed by the operator before any flash. Physical fail-safe,
actuator observations, exact viewpoint calibration and an observer remain required.

## Flash and boot RPC (2026-10-11)

App Lab successfully compiled/uploaded and launched the `_r2` app, exit 0.
Its log also contains discovery teardown messages `Stopped decode loop: EOF`
after upload; startup still completed and the production RPC answered. Only the
new Grove app is running; old production and standalone timer apps are stopped.
Vision and MCU systemd units remain inactive during the boot observation.
Read-only `get_status` returned `[1,1,1,4,0,0,1,-1]`; no test heartbeat was sent.
The operator was asked to report actual lamps, sound, matrix and OLED.

Updated the existing environment to the `_r2` app, `configs/board_grove_local.yaml`
and `libcamerify`, retaining other settings. Corrected the board clock from the
laptop reference to 2026-10-11 09:32:58 UTC. [Boot settings/time](grove_boot_config.txt).
No live pipeline or calibration-driven functional pass is claimed yet.

## Bounded direct RPC diagnostic

Ran `tools/mcu_test.py --watchdog` with vision stopped. A separate client polled
only `get_status` and never supplied heartbeats. Status showed green, yellow, red,
WALK, CLEARANCE, B1, B2 and count-page states in sequence. During the pause, the
first sampled fail-safe status had heartbeat age **2052 ms** at elapsed **26.236 s**;
recovery appeared at **30.726 s**, age 40 ms. These are sampled software states,
not physical output latency measurements. The diagnostic exited 0 after SIGINT;
no heartbeat sender remains. Three seconds later the read-only status again showed
fail-safe, heartbeat age 3457 ms. [Control/stop log](grove_direct_control.log).

Operator reply: “The buzzer is buzzing but not a nice sound. The hold says failsafe”.
Treat OLED FAILSAFE as observed, sound quality as unsatisfactory, and silence as
unresolved because the reply window overlapped the forced sound/watchdog test.
Stopped diagnostics and requested a fresh observation with vision still off.
Do not claim boot lamps, waveform quality or acoustic shutdown passed.

Follow-up operator observation with diagnostics stopped: **“No sound. LEDs are not
plugged on so I don’t see them.”** Fail-safe silence is now physically confirmed.
The earlier buzzing occurred during an overlapping diagnostic window; no continuous
fail-safe buzzing was reproduced. LED acceptance remains unmeasured. The target
pin map was confirmed before flashing, but that confirmation did not establish
that physical LEDs were fitted. Vision bring-up proceeds with OLED/buzzer/matrix;
missing LEDs prevent full GPIO physical acceptance.

## Boot service ownership and live bring-up

First `install_autostart.sh` attempt failed because the manually launched app was
already running; MCU service log: **`[ERROR] App "Occhio Crosswalk Mcu" Is Running`**,
exit 1. [Exact log](grove_mcu_service_first_start.txt). Stopped that exact `_r2` app,
then reran the installer. MCU service became active/exited and vision active/running
(PID 5232, no restarts after restored code). No algorithm or service-source change
was needed. On a fresh boot App Lab starts the app normally.

[Ready evidence](grove_live_ready.txt) confirms only one crosswalk pipeline, fresh
CAM0 frames, MCU connected, `failsafe=false`, and Grove status `[1,1,0,3,1,0,1,222]`.
The [baseline metadata](grove_live_baseline.json) records live source 632×480,
NCNN YOLO11n 320 and nonzero inference (sample 150.1 ms), real MCU, and the applied
geometry. Calibration height/tilt are fitted estimates, not new tape measurements.
`/public/api/stats` reports **live** data; local config disables demo and mock-month.
Counts were zero at baseline; no known crossing/persistence proof is claimed.
USB dashboard access is forwarded locally on port 18000. No camera image was
retrieved for chat or committed. Strict 120-second collection is in progress.

## Strict live acceptance and operator pause/resume

The strict collector completed **120.001 seconds / 59 samples / zero failures**.
It accepted calibrated-source metadata, live camera, real NN, Grove profile 1,
fresh vision and real MCU; frames advanced 408→3897 and inference runs 71→482.
The API does not expose a separate `camera_frames` counter in this run.
Sampled inference: median 148.1 ms, min 133.9 ms, max 223.3 ms; decision median
167.3 ms; CPU 41.3–84.8%, temperature 39.1–53.9 °C, reported memory 743–828 MB.
See [collector log](grove_live_collect.log) and [summary](grove_live.summary.json).
Counts stayed zero; no ground-truth crossing was supplied. Signal telemetry showed
vehicle green/yellow, all-red, WALK and CLEARANCE. These are software transitions
under the partial-stripe geometry, not proof of genuine waiting-zone demand.
Operator comment “idk buddy it all seems good” supplies no specific additional
physical pass.

The operator paused execution until Federico returned. No freeze, crash, synthetic
camera fault or reboot was started. At resume the same live service PID 5232 had
zero restarts, fresh health and MCU connection. All direct heartbeat tools were
stopped; the bounded collector had finished.

Federico is now available to observe/film the fail-safe tests and will power down
and connect the four LEDs, reporting when ready. Hold board fault tests until
that report; only local evidence documentation proceeds during wiring.
Remaining hardware minimum: physical lamps and signal pages/sound, freeze/crash
recovery, automatic reboot, and soak. Waiting-area trials remain unsupported by
this window view. Ambient/cooling conditions and scored crossing GT are unmeasured.

## LED-connected phase started

Federico reported “ready” after agreeing to connect the LEDs and observe/film.
The initial health check found the same service PID 5232, zero restarts and fresh
vision/real MCU. This does **not** prove a power cycle or automatic reboot.
Stopped only `occhio.service`, keeping the Grove app running. Read-only status
then returned `[1,1,1,4,0,0,1,8236]`, and no diagnostic/collector was running.
[Pre-test status](grove_led_failsafe_before.txt). Holding fail-safe until the operator
reports actual lamps, OLED, matrix and silence. A fresh bounded diagnostic has
been staged with separate `grove_led_direct_*` evidence paths; not started yet.

Physical baseline observation: **“yellow is flashing. other off. buzzer silent.
failsafe on oled and one !”** This confirms the static fail-safe indications and
silence with LEDs fitted. It does not measure watchdog latency or the matrix
blink cadence. Announced and started the separate ~40-second direct sequence;
vision stays stopped and the tool will terminate its heartbeat sender.

## Power interruption and requested repeat

The first LED-connected diagnostic exited 0 and showed expected status transitions.
The operator then reported disconnecting the power supply and requested a repeat;
physical sequence observations from that run remain unreported. Preserve its logs
without claiming physical acceptance. [Control log](grove_led_direct_control.log),
[status summary](grove_led_direct_summary.json).

After power restoration, both configured services were active without a manual
start. Vision PID changed to 1682, zero restarts, fresh health and real MCU; the
environment still selects the `_r2` Grove app and live CAM0 local config.
[Power-recovery evidence](grove_power_interruption.txt). This is software automatic
startup evidence; physical startup timing was not observed. Stopped vision again
and verified fail-safe plus nonempty restored source hashes after the power cycle.
[Repeat preflight](grove_repeat_before.txt). Announced and launched a repeat direct
sequence with new `grove_led_repeat_*` files. No raw media collected.

## Demonstrated green/yellow wiring mismatch and correction

During the repeated physical sequence, the operator reported **“the green and
yellow pin are swapped so resolve.”** Treat the original `_r2` mapping as a failed
physical colour check, not a complete actuator pass. Corrected only the Grove
profile to **green D3 / yellow D2**, retaining red D6, white D7 and passive buzzer D4.
Updated the physical pin contract in the existing host harness, firmware README,
handoff table and manifest wiring reference; the isolated standalone timer app
still has its earlier mapping. Source commit **56e47cc1a3e50983c4759bb86b8d85dc2040e298**.
Relevant host firmware/packaging/collector tests: **25 passed**.

Stopped the old app and deployed committed tracked code, preserving the ignored
local calibration, virtualenv, weights, recordings and stats. Packaged new app
`/home/arduino/ArduinoApps/crosswalk_grove_live_20261011_56e47cc`.
[Preparation](grove_pinfix_prepare.log), [manifest](grove_pinfix_manifest.json).
Boot environment now points to the corrected app; MCU service is compiling/flashing
it while vision remains stopped. Physical pin correction still needs observation
after upload. The original 120-second software run is evidence for the old app;
repeat integrated collection after corrected-app bring-up.

Corrected target manifest verification: all six packaged app-file hashes match a
laptop preview built from source commit `56e47cc`. Board revision is null because
it remains a tar deployment. The fresh app is owned by `occhio-mcu.service`;
vision stays inactive during compilation, avoiding a second heartbeat sender.
The clock was corrected again; tar extraction had emitted 379 future-timestamp
warnings (~14 seconds), retained as a first exact warning plus count in the
preparation log. These are nonfatal and do not establish latency measurements.

Corrected-app target compile/upload/start completed successfully through the MCU
service, `ExecMainStatus=0`, active/exited. [Flash log](grove_pinfix_flash.log).
Vision remained stopped. The bounded corrected-profile actuator diagnostic exited
0 and its heartbeat sender stopped; post-stop status `[1,1,1,4,0,0,1,3350]`.
[Control log](grove_pinfix_direct_control.log), [RPC sequence](grove_pinfix_direct_rpc.log),
[status samples](grove_pinfix_direct_status.jsonl). Operator was asked to verify
the corrected colours and remaining actuator states. No new physical pass yet.

Corrected target resource usage: **123700 bytes flash (15%), 51780 bytes RAM (19%)**.
The flash log contains the same nonfatal discovery teardown `Stopped decode loop:
EOF` messages; app startup and RPC diagnostic succeeded.
[Corrected diagnostic summary](grove_pinfix_direct_summary.json) records all forced
state transitions and the watchdog pause/recovery. Physical colours and remaining
actuators await the operator's answer. Keep vision stopped and fail-safe held
until that answer; freeze/crash, camera reopen, controlled reboot, corrected-app
strict live collection and 30-minute soak remain outstanding.

Operator corrected-sequence observation: **“white led is not plugged for now,
let’s test it later. everything else seemed all right.”** Accept this as a general
physical observation of corrected green/yellow, red, OLED WALK/CLEARANCE, buzzer
phases and fail-safe return, in response to the explicit checklist. White slow/fast
warning acceptance is **deferred at the user's request**, not passed. Exact physical
timing, sound frequency/quality and waveform measurements remain unmeasured.
Restarting live vision for a new strict run on corrected source `56e47cc` before
announced freeze/crash tests.

## Corrected live restart and offline conditions

Operator accepted the connected outputs after the correction; white LED testing
is deferred. Started the existing vision service only (new PID 3410, zero restarts).
[Ready evidence](grove_pinfix_live_ready.txt) confirms fresh vision, MCU connected
and fail-safe false; no diagnostic heartbeat sender is running. Strict corrected
app collection began with healthy samples and is still in progress.

Network preflight found **wlan0 disconnected and no IPv4/IPv6 default route**,
with only loopback/container interfaces connected. [Anonymous network state](grove_network_preflight.txt).
The board is already offline; no Wi-Fi profile, password, MAC or network address
is logged, and no interface was disconnected or reconfigured. Live CSI capture,
local NCNN inference and real MCU control continue in these conditions. This is
current offline operation evidence; no claim about internet-loss transition timing
is made. Verify again at the end of the live collection.

## Corrected strict run and exact-process freeze

Corrected source `56e47cc`: strict collector passed **120.002 s / 57 samples /
zero failures**. Inference median **143.1 ms** (130.2–179.3 ms), decision median
165.4 ms, measured detector frequency median 6.0 Hz (3.9–6.6), CPU 64.0–85.1%,
CPU temperature 38.5–53.9 °C, reported memory 723–812 MB. No counted passages
were independently scored. [Samples](grove_pinfix_live.jsonl),
[summary](grove_pinfix_live.summary.json), [collector log](grove_pinfix_live_collect.log).

Announced and performed an eight-second SIGSTOP of the service's exact healthy
PID 3410. Independent read-only MCU polling saw fail-safe first at **2.037 s after
STOP**, heartbeat age **2060 ms** (sampled software timing, not emitted light).
SIGCONT resumed **the same PID** and fresh real-MCU/vision health recovered in
**0.456 s after CONT**. The collector sent no heartbeats; no signal command was
forced. Requested physical observation and retained the recording if available.
Crash and physical onset timing remain unmeasured at this phase.

## Interrupted dashboard camera card

After freeze recovery the operator could not identify the physical fail-safe
sequence and reported a moving digital twin with a stale camera card. Physical
freeze acceptance remains **UNMEASURED**. CAM0 and inference were healthy
(PID 3410, no service restarts). Toggling Camera off/on restored the preview;
the operator confirmed **“Yes, the camera image is moving.”**

The dashboard reopened its SSE state connection but did not reopen the MJPEG
image on recovery. Added a focused UI fix: reopen an enabled camera card on SSE
connection, retry image errors after two seconds, cancel retries when hidden.
Deployed only `dashboard/js/main.js`, without restarting vision or changing
detection, tracking, calibration, policy or statistics. Module syntax check
passed. Live preview verification received six distinct frames over 1.562 s;
only hashes, byte lengths and timing were saved in
[metadata](grove_preview_frames.json), with no camera media retained.
Browser has the corrected query-bearing MJPEG source and no console errors.
Automatic recovery during the upcoming crash test remains to be verified.

## Crash, camera reopen and manual handover

Exact-process crash completed: PID 3410 was killed and systemd automatically
started PID 3739. MCU fail-safe first sampled 1.813 s after KILL (heartbeat age
2029 ms); healthy vision/real MCU first sampled 6.377 s after KILL. The helper's
end-of-window summary at 8.304 s is not the first recovery observation. Operator
confirmed **“Yes, FAILSAFE then normal”** on the OLED. Other crash outputs and
physical onset timing remain unmeasured. Browser SSE returned live and changed
the enabled camera's MJPEG URL automatically, verifying the preview recovery fix.

A temporary single CAM0 pipeline exercised labelled synthetic failed reads for
eight seconds, with no ribbon disconnect. Capture reopen counter advanced
**0 → 3**, and processed frames **3 → 7**; fresh real-MCU/vision health returned
~0.365 s after the read-failure marker was removed. Operator missed this window,
so physical acceptance remains unmeasured. The temporary node stopped, its marker
was removed, and the original production service restarted by cleanup.

The operator explicitly cancelled further automated tests and requested the live
system ready for manual testing. **No more faults, diagnostics, reboot or soak
will run unless requested.** At handover production PID 3935 is active, MCU boot
service active/exited, health ok with 0.01 s vision age, real MCU connected and
fail-safe false. No test heartbeat sender, temporary camera node or failure
marker remains. Dashboard remains accessible through USB forwarding at
`http://127.0.0.1:18000/`, with CAM0 only, preserved calibration and corrected
Grove outputs. White LED stays deferred. Remaining scored camera trials,
corrected-app reboot, persistence trial and 30-minute soak are unmeasured.
Results are committed locally; no push was requested for this phase.

## Camera card brightness: display-only adjustment

Operator clarified that onboard video looked good and requested a fix only for
the app's camera card. No sensor, libcamera tuning, recording, detector, policy
or service settings were changed. Added browser-side preview tone correction
in `dashboard/js/camera-preview.js`, with a separate visible canvas fed by the
existing privacy-blurred MJPEG image. Central/lower-view median luminance drives
a bounded tone curve: large brightness jumps are compensated immediately and
small metering changes are smoothed. Display processing is limited to 8 Hz and
640 pixels wide and stops when Camera is hidden. Browsers unable to process the
image fall back to the original preview. Clipped detail cannot be recovered.

Deployed only three dashboard files while production PID 3935 continued running.
Module syntax checks passed; browser loaded the 632×480 correction canvas with
its source image hidden and no console errors. No fault tests or automated
hardware trials resumed. Operator should reload the existing dashboard and
enable Camera; subjective improvement remains to be confirmed. Previous
libcamera exposure-regression research is a hypothesis about sensor behaviour,
not an established cause of this specifically reported preview-only issue.

## Preview correction rejected and rolled back

Operator reported that the browser tone correction made the image worse, with
additional green/magenta swings. **This adjustment failed user acceptance.**
Restored the dashboard HTML and main module to the preceding committed version
and removed the correction module from tracked source. The deployed old module
file is unreferenced; no camera settings, video recording or inference process
was changed or restarted. The original MJPEG camera card, including its reconnect
fix, is restored. Reload the dashboard to discard the previously loaded canvas
code. The initial brightness issue remains unresolved; the colour cause has
not been established. No further automatic image adjustments are deployed.

## Final restart and preview investigation stopped

At the operator's request, restarted the normal vision service with the original
preview restored. Production PID 4081 became active with zero restarts, fresh
vision (sampled age 0.23 s), real MCU connected and fail-safe false. The operator's
Chrome dashboard still had the old canvas module loaded; reloaded that tab to
remove it. Camera configuration and recording implementation remained unchanged.

Read-only inspection of 24 original MJPEG frames over 7.760 s found central/lower
ROI mean luminance ranging **40.58–252.98** on a 0–255 scale and green/red mean
ratio **0.954–1.824**. Many bright frames had median luminance 252–254. Thus the
preview stream already contains severe brightness variation before browser
rendering; this does not independently prove the raw recorded video has the
same issue or establish the precise camera-stack cause. Only anonymous numeric
metadata was retained in [input statistics](grove_preview_input_stats.json).
No camera frames or video were saved for this inspection.

The operator then cancelled further preview work. No proposed frame-selection
filter or additional correction was implemented. Original live deployment is
left running; brightness remains unresolved. Further hardware acceptance and
soak stay unmeasured. All changes and these final findings are committed and
pushed on `codex/live-board-gpio` at the operator's request. Unrelated untracked
`hardware/` files were preserved and excluded from these commits.
