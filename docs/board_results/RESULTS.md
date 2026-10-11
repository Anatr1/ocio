# Board bring-up results — Arduino UNO Q + ZED Mini / IMX219

> Tested on 2026-10-10 by the electronics colleague + agent on branch `board-bringup`, following `docs/HANDOFF_BOARD.md`.
> Hardware updates: IMX219 tested first; operator subsequently connected a ZED Mini over USB, which provided live capture. CAM0 IMX219 also enumerated and streamed after the latest operator reboot; it is the current live source. External LEDs/buzzer/button tests remain deferred.
> Push after every phase. Keep raw outputs in code blocks; put large artefacts (CSV, bench JSON, images) next to this
> file and link them. Status legend: ✅ pass · ⚠️ partial / workaround · ❌ fail · ⏳ not done yet.

## Status overview
| Phase | Status | Key result (one line) | Updated |
|---|---|---|---|
| 0 Facts | ✅ | Board verified; initially missing IMX219 now binds after latest operator reboot | 2026-10-10 |
| 1 Deploy | ✅ | Online install; all eight required modules import; models/videos deployed | 2026-10-10 |
| 2 Camera | ✅ | Both tested: ZED USB 3 and CAM0 IMX219; current live source is IMX219 via libcamerify | 2026-10-10 |
| 3 Benchmark | ✅ | NCNN YOLO11n 320/t4: 91.8 ms burst, 9.07 Hz median sustained; no observed frequency throttling | 2026-10-10 |
| 4 Live pipeline | ⚠️ | CAM0: median 5.1 Hz / 155.9 ms inference / 35.6 capture fps; calibrated empty/busy trials pending | 2026-10-10 |
| 5 Calibration | ⚠️ | Live IMX219 available; operator has no marked rectangle yet | 2026-10-10 |
| 6 Functional | ⚠️ | Four call cycles total; 8 vehicle counts on board video; physical crossings pending | 2026-10-10 |
| 7a MCU (matrix, watchdog) | ⚠️ | Compiles/flashes; boot fail-safe fixed and visually verified; RPC RTT 5.3 ms; timing pending | 2026-10-10 |
| 7b MCU (LEDs, buzzer, button, power) | ⚠️ | External outputs deferred by operator; power meter unavailable | 2026-10-10 |
| 8 Robustness | ⚠️ | Recovered 30-minute monitor: camera state froze for final 70 s while MCU heartbeat continued; no clean soak pass | 2026-10-10 |

## Blockers / open questions for the main team
- Network access restored at 14:41 UTC (16:41 Rome) after the operator's reboot; old timeout no longer blocks access.
- Operator confirms no marked floor rectangle for now: phase 5 and scored physical crossings remain pending.
- Earlier IMX219 chip-ID failure is resolved in the latest boot; the exact physical cause is not established. Driver warnings and unavailable FPS control remain; see current capture evidence in §2.
- Initial SSH authentication with the suggested `vivic` account failed: `Permission denied, please try again.` The documented `arduino` account works. Credentials are not recorded.
- Initial sandboxed `git pull` failed with `ssh: Could not resolve hostname github.com: Temporary failure in name resolution`. Retried with network permission: successful; branch already up to date.

## 0. Board facts — initial inventory
Latest camera state is in §2; the inventory below records conditions before either camera successfully streamed.
Full raw output: [phase0_facts.txt](phase0_facts.txt), [camera_inventory.txt](camera_inventory.txt).

- Python: 3.13.5; OS: Debian 13 trixie; architecture: aarch64; cores: 4 (Qualcomm Kryo-V2, max 2016 MHz).
- RAM: 3667 MiB total, 3034 MiB available at first check. Root filesystem: 2.7 GiB free; `/home/arduino`: 17 GiB free.
- Router socket: present and world-accessible; `arduino-router.service` active.
- Camera: Qualcomm CAMSS `/dev/video0`–`/dev/video7`; these are capture nodes, **not proof of an attached sensor**. `/dev/video8` and `/dev/video9` are hardware codecs. No camera discovered by libcamera v0.4.0.
- USB camera speed: not applicable to the CSI IMX219. `lsusb` and `lsusb -t` returned no devices.
- CPU thermal zones: zone3 `cpuss0-thermal` (37.6 °C), zone4 `cpuss1-thermal` (36.6 °C). Ambient temperature unknown; operator confirms no heatsink and no fan.
- SSH login: `arduino@10.34.93.148`; board hostname: `VIVIC`. Board clock uses UTC; user-facing date here is Europe/Rome.

## 1. Deploy
- Method: online PyPI install in `~/occhio/.venv` with system site packages. Code deployed with tar over SSH; models and public sample videos transferred afterward. Setup plus missing OS prerequisites took approximately 8 minutes (no precise stopwatch measurement).
- First attempt failed because Python's venv support was missing; full output: [deploy.log](deploy.log).
```
The virtual environment was not created successfully because ensurepip is not
available.  On Debian/Ubuntu systems, you need to install the python3-venv
package using the following command.

    apt install python3.13-venv

You may need to use sudo with that command.  After installing the python3-venv
package, recreate your virtual environment.

Failing command: /home/arduino/occhio/.venv/bin/python3

need: sudo apt install python3-venv
```
- Recovery: `sudo apt-get update`, `sudo apt-get install -y python3-venv python3-pip`, recreate `.venv`, rerun setup. Apt also installed recommended build packages and upgraded Python/libc dependencies; no kernel upgrade or reboot. Full setup output: [deploy_retry.log](deploy_retry.log).
- Imports verified: numpy **2.5.3**, cv2 **5.0.0**, onnxruntime **1.31.0**, msgpack **1.2.3**, yaml **6.0.3**, scipy **1.18.1**, ncnn **1.0.20260526**, segno **1.6.6**. Segno checked explicitly because setup's import loop omits it.
- Camera check: `camera read FAILED` (consistent with Phase 2 sensor probe failure). MCU ping succeeds.
- Laptop checkout initially had no model binaries or videos. Created isolated export venv, installed CPU-only PyTorch, fetched public sample videos, ran `tools/fetch_assets.py --models`: 12 ONNX fp32/int8 models + 2 NCNN models. Export environment, calibration inputs and transferred model/video checksums: [asset_provenance.json](asset_provenance.json). No raw camera footage was fetched or committed.

## 2. Camera — CAM0 IMX219 now working; earlier attempts below

### Latest CAM0 check — 14:41–14:46 UTC (16:41–16:46 Rome)
After the operator's latest reboot/reconnection, `cam -l` lists **`imx219`** at `/base/soc@0/cci@5c1b000/i2c-bus@0/sensor@10`; `/sys/bus/i2c/devices/0-0010/driver` points to the IMX219 driver. CAM0 current/next settings are still **`type1-2lanes`**. No overlay or GPIO changes were made during this check. The prior chip-ID failure is absent; this establishes recovery but does not identify its physical cause. [Current inventory/kernel evidence](imx219_detected_recheck.txt).

Standalone `timeout --signal=INT 20 cam -c 1 --stream role=viewfinder,width=640,height=480,pixelformat=RGB888 --capture=60` exited **0**, with all **60 frames** delivered. Request adjusted to **632×480 RGB888**, approximately **59.93 fps** after the first frame. No camera images written. [Exact capture log](imx219_capture_recheck.log).

Existing project `CameraSource` through **`libcamerify`**: 20.006 s, **1,188 reads / 59.38 Hz**, **0 missing reads**, actual array shape **480×632×3**, source statistics **59.4 camera fps**. Capture process CPU **82.8% of one core** (about 20.7% across four cores); includes lightweight intensity-statistics sampling. [Helper](check_imx219_capture.py), [JSON metadata](imx219_opencv_capture.json), [stdout](imx219_opencv_capture.log).

Known warnings are retained: recommended V4L2 control `0x009a0922` not supported, camera location/rotation missing, missing `imx219.yaml` ISP tuning falls back to `uncalibrated.yaml`, and **`Camera does not support FrameDurationLimits`**. The requested **30 fps is not enforced**; observed capture is about 60 fps. These warnings did not prevent streaming. Image quality/tuning and physical orientation still require a properly aimed scene.

Started the real node using `libcamerify .venv/bin/python -u -m crosswalk --config configs/board_imx219.yaml`. Browser shows a live close-up under the desk, IMX219 node name, NCNN model and connected STM32 (~6–7 ms RTT). Updated config calibration image size to actual **632×480**; no homography/rectangle invented. Restarted the existing MCU app after this reboot because `ping` again returned `[2, 'method ping not available']`; compile/flash succeeded, then ping/live RPC succeeded. [MCU restart log](mcu_after_camera_reboot.log), [live state](imx219_live_state.json). Completed five-minute pipeline measurements are recorded separately in §4c. Dashboard: `http://10.34.93.148:8000/`.

### Earlier probe failures — historical evidence

**Earlier check, 2026-10-10 13:42–13:47 UTC (15:42–15:47 Rome): blocked at that time.** Operator reseated the ribbon with power disconnected and powered the board back on. This boot exposed sensor `1-0010`, but the same `-ENXIO` chip-ID failure persisted; I²C bus numbers changed across boots, so use the device name/tree rather than assuming a fixed bus number. [Post-reseat output](camera_after_reseat.txt).

Discovered CAM0 was configured as **`type1-4lanes`**. Operator identified module **CAM8MPXRPI5**; its [supplier specification](https://futuranet.it/prodotto/modulo-fotocamera-8mp-imx219-per-raspberry-pi-5/) states IMX219, **two CSI lanes**. The supplier links Waveshare, whose [Pi5-IMX219 product](https://www.waveshare.com/pi5-imx219.htm) matches the listed optics and dimensions; exact PCB identity still needs visual confirmation. Supplier's Wiki link points to a different camera family, so it was not used as wiring evidence.

Backed up the existing boot DTB and carrier state on the board under `~/occhio/board_backups/20261010-camera/`, then used the official [Arduino Linux Config CLI](https://github.com/arduino/arduino-linux-config):
```sh
sudo arduino-linux-config carrier enable media-carrier camera0=type1-2lanes camera1=none display=none
sudo reboot
```
After reboot, `carrier show` confirms both current and next CAM0 settings **`type1-2lanes`**. Sensor `0-0010` still fails chip-ID read and `cam -l` returns no cameras. Manual bind retry at 13:47:26 UTC fails identically. PCA9555 GPIO expander is bound; read-only `gpioget --as-is` of its reset line succeeds before/after bind. This does not verify the camera's supply voltage or rule out a module-specific power/reset issue. No manual reset/power GPIO writes or custom boot-overlay changes performed. [Carrier inventory](carrier_after_reseat.txt), [stock two-lane overlay, command/state + DTB hashes](camera_lane_config.txt), [post-two-lane probe/GPIO/MCU checks](camera_after_2lanes.txt).

The earlier suggested hardware checks were not sufficient to establish a root cause. Streaming is now verified above; physical calibration remains pending.

**Blocked before streaming.** Operator confirms IMX219 on Arduino UNO Media Carrier CAM0, setup not previously tested. A driver bind retry at 13:25:37 UTC reproduced the same chip-ID error (`sh: 1: echo: echo: I/O error` from the bind write); libcamera still enumerates no camera. Sensor is declared on I²C bus 0, address 0x10, but is not detected:

```text
imx219 0-0010: Error reading reg 0x0000: -6
imx219 0-0010: error -ENXIO: failed to read chip id 219
No sensor found for /dev/media0
```

`/sys/bus/i2c/devices/0-0010/name` = `imx219`; `modalias` = `of:NsensorT(null)Csony,imx219`; the device has no `driver` symlink. This is a hardware probe failure, before OpenCV or pipeline execution. No resolution/fps/CPU or visual result can be measured yet. The following handoff rows are inapplicable because the ZED has been removed:
| Requested mode | Obtained | fps | Notes |
|---|---|---|---|
| 1344x376 YUYV | | | |
| 2560x720 YUYV | | | |
| 672x376 YUYV | | | |
- USB link speed / left-eye crop: not applicable. Capture-only CPU %, orientation: unmeasured.
- **Chosen mode at this earlier stage:** not available before sensor discovery. The later verified IMX219 mode is recorded at the start of §2.

### ZED Mini connected afterward — working live camera
Operator connected ZED Mini over USB at approximately 13:50 UTC; IMX219 still does not enumerate on the second cold boot. ZED camera `2b03:f682` is **USB 3 / 5000M**, while its HID interface `2b03:f681` uses a separate slower link. The working UVC capture is `/dev/video0`; CSI nodes shifted to `/dev/video2`–9. Config uses stable `/dev/v4l/by-id/usb-Technologies__Inc._ZED-M-video-index0` rather than the transient node number. [USB/video inventory](zed_inventory.txt).

Short benchmark (`tools/bench.py --camera 0 --camera-modes ... --models`, three seconds per mode, requested 30 fps):

| Requested YUYV stereo mode | Obtained raw mode | measured raw fps | Result |
|---|---|---|---|
| 1344×376 | 1344×376 | 30.3 | pass |
| 2560×720 | 2560×720 | 29.0 | pass |
| 672×376 | **1344×376** | 29.3 | unsupported request coerced; not a single-eye mode |

[Raw camera benchmark](zed_camera_bench.log). The regular threaded `CameraSource` uses a one-frame capture buffer and postprocessing, so raw benchmark fps is not sufficient for selecting a pipeline mode. Separate 20-second source tests, no vision pipeline or dashboard active, same lighting, MCU stub active:

| Requested raw | Left-eye output | actual capture fps | process CPU % of one core | missing reads |
|---|---|---|---|---|
| 1344×376 @30 | 672×376, no resize | **29.7** | 46.4 | 0 |
| 2560×720 @30 | 640×360 after crop/resize | **15.1** | 54.8 | 0 |

Process CPU normalized across four cores is approximately 11.6% / 13.7%; this is capture plus crop/resize, not system CPU. [Reproduction helper](check_zed_capture.py), [metadata/telemetry](zed_capture.json), [stdout](zed_capture.log). Images were not saved.

A live high-resolution trial with NCNN 320/t4 fell to **12.8 camera fps** (instantaneous detector 7.2 Hz / inference 125.9 ms). Thus selected **1344×376 YUYV @30, left eye 672×376**, no additional resize. A subsequent low-mode snapshot gave camera 15.3 fps / detector 7.8 Hz / inference 109.2 ms under load; sustained figures belong in §4. [High-mode trial state](zed_high_mode_state.json), [startup log](zed_high_mode.log). `configs/board_zed.yaml` now contains this mode and the measured NCNN winner. Browser visual check: one eye, correct aspect and upright, visible desk/people scene; no floor rectangle. No rotation applied. No camera images committed.

## 3. Detector benchmark
Conditions: UNO Q aarch64, Python 3.13.5, CPU-only inference, ONNX Runtime 1.31.0 / NCNN 1.0.20260526. Ambient temperature is **unknown**. Operator confirms **no heatsink and no fan**; camera on UNO Media Carrier **CAM0**, setup not previously tested. Initial board CPU temperature was 37.6 °C; immediately before the sweep, highest thermal zone was 44.5 °C after deployment/compilation, not a controlled cold-idle measurement. No camera or vision pipeline active. MCU App Lab stub/router remained running.

Input: 20 evenly spaced frames from public `data/videos/vtest.avi`, resized to 640×480; 30 measured iterations + 5 warmups per model/thread combination. First 10 frames therefore occur twice in the measured 30. `conf=0.35`, `conf_low=0.25`. Requested camera mode: not applicable. Bench `total_ms` is the sum of separate preprocessing/inference/postprocessing medians; it is not end-to-end lamp latency. `dets/frame` is a quality proxy, not counting accuracy.

Full sweep: **42 combinations, no failures**. Raw reports: [ONNX JSON](bench_20261010-131757.json), [ONNX table](bench_20261010-131757.md), [YOLO11n NCNN JSON](bench_20261010-131820.json), [table](bench_20261010-131820.md), [YOLO26n NCNN JSON](bench_20261010-131840.json), [table](bench_20261010-131840.md). [Complete stdout](benchmarks.log), [reproduction commands](run_benchmarks.sh).

| model | backend | imgsz | threads | pre ms | infer ms | post ms | total ms | fps | dets/frame | conf |
|---|---|---|---|---|---|---|---|---|---|---|
| yolo11n_320_ncnn_model | ncnn | 320 | 4 | 3.8 | 83.2 | 4.8 | 91.8 | 10.9 | 8.3 | 0.559 |
| yolo26n_320_ncnn_model | ncnn | 320 | 4 | 3.9 | 85.1 | 5.0 | 94.0 | 10.6 | 5.07 | 0.55 |
| yolo26n_256_int8.onnx | onnx | 256 | 4 | 3.3 | 89.9 | 4.3 | 97.5 | 10.3 | 6.03 | 0.512 |
| yolo26n_256.onnx | onnx | 256 | 4 | 3.3 | 91.6 | 4.2 | 99.1 | 10.1 | 6.07 | 0.52 |
| yolo11n_256_int8.onnx | onnx | 256 | 4 | 3.3 | 96.1 | 4.3 | 103.7 | 9.6 | 6.53 | 0.533 |
| yolo26n_256_int8.onnx | onnx | 256 | 3 | 2.9 | 100.2 | 4.2 | 107.3 | 9.3 | 6.03 | 0.512 |
| yolo26n_256.onnx | onnx | 256 | 3 | 2.9 | 107.8 | 4.2 | 114.9 | 8.7 | 6.07 | 0.52 |
| yolo11n_256.onnx | onnx | 256 | 4 | 3.4 | 107.2 | 4.4 | 115.0 | 8.7 | 6.37 | 0.556 |
| yolo11n_256_int8.onnx | onnx | 256 | 3 | 2.9 | 108.2 | 4.3 | 115.4 | 8.7 | 6.53 | 0.533 |
| yolo26n_320_ncnn_model | ncnn | 320 | 3 | 3.8 | 108.9 | 5.2 | 118.0 | 8.5 | 5.07 | 0.55 |
| yolo26n_256_int8.onnx | onnx | 256 | 2 | 2.7 | 120.2 | 4.3 | 127.1 | 7.9 | 6.03 | 0.512 |
| yolo11n_256.onnx | onnx | 256 | 3 | 2.9 | 125.7 | 4.3 | 132.8 | 7.5 | 6.37 | 0.556 |
| yolo11n_256_int8.onnx | onnx | 256 | 2 | 2.7 | 131.5 | 4.3 | 138.5 | 7.2 | 6.53 | 0.533 |
| yolo26n_320_ncnn_model | ncnn | 320 | 2 | 4.0 | 130.8 | 5.5 | 140.3 | 7.1 | 5.07 | 0.55 |
| yolo26n_256.onnx | onnx | 256 | 2 | 2.7 | 134.3 | 4.2 | 141.2 | 7.1 | 6.07 | 0.52 |
| yolo26n_320_int8.onnx | onnx | 320 | 4 | 4.8 | 131.3 | 5.3 | 141.5 | 7.1 | 5.0 | 0.547 |
| yolo11n_320_int8.onnx | onnx | 320 | 4 | 4.7 | 135.3 | 5.7 | 145.7 | 6.9 | 7.2 | 0.558 |
| yolo26n_320.onnx | onnx | 320 | 4 | 4.8 | 144.3 | 5.4 | 154.5 | 6.5 | 5.07 | 0.55 |
| yolo11n_320_ncnn_model | ncnn | 320 | 3 | 4.0 | 149.1 | 5.7 | 158.8 | 6.3 | 8.3 | 0.559 |
| yolo26n_320_int8.onnx | onnx | 320 | 3 | 4.2 | 149.5 | 5.3 | 159.0 | 6.3 | 5.0 | 0.547 |
| yolo11n_256.onnx | onnx | 256 | 2 | 2.7 | 159.4 | 4.4 | 166.5 | 6.0 | 6.37 | 0.556 |
| yolo11n_320_ncnn_model | ncnn | 320 | 2 | 4.0 | 157.2 | 5.8 | 166.9 | 6.0 | 8.3 | 0.559 |
| yolo11n_320_int8.onnx | onnx | 320 | 3 | 4.2 | 158.1 | 5.8 | 168.1 | 5.9 | 7.2 | 0.558 |
| yolo26n_320.onnx | onnx | 320 | 3 | 4.2 | 166.3 | 5.4 | 175.8 | 5.7 | 5.07 | 0.55 |
| yolo11n_320.onnx | onnx | 320 | 4 | 4.8 | 168.8 | 5.7 | 179.3 | 5.6 | 8.3 | 0.559 |
| yolo26n_320_int8.onnx | onnx | 320 | 2 | 4.2 | 183.1 | 5.3 | 192.6 | 5.2 | 5.0 | 0.547 |
| yolo11n_320.onnx | onnx | 320 | 3 | 4.2 | 193.7 | 5.6 | 203.4 | 4.9 | 8.3 | 0.559 |
| yolo11n_320_int8.onnx | onnx | 320 | 2 | 4.0 | 197.9 | 6.0 | 207.9 | 4.8 | 7.2 | 0.558 |
| yolo26n_416_int8.onnx | onnx | 416 | 4 | 7.0 | 202.8 | 7.2 | 217.0 | 4.6 | 7.43 | 0.585 |
| yolo26n_320.onnx | onnx | 320 | 2 | 4.0 | 211.3 | 5.4 | 220.7 | 4.5 | 5.07 | 0.55 |
| yolo11n_416_int8.onnx | onnx | 416 | 4 | 7.0 | 209.7 | 7.9 | 224.6 | 4.5 | 8.73 | 0.638 |
| yolo26n_416.onnx | onnx | 416 | 4 | 6.7 | 230.2 | 7.7 | 244.6 | 4.1 | 7.4 | 0.591 |
| yolo26n_416_int8.onnx | onnx | 416 | 3 | 6.4 | 233.8 | 7.7 | 247.8 | 4.0 | 7.43 | 0.585 |
| yolo11n_320.onnx | onnx | 320 | 2 | 4.0 | 248.3 | 5.7 | 258.0 | 3.9 | 8.3 | 0.559 |
| yolo11n_416_int8.onnx | onnx | 416 | 3 | 6.3 | 245.9 | 7.8 | 260.0 | 3.8 | 8.73 | 0.638 |
| yolo26n_416.onnx | onnx | 416 | 3 | 6.4 | 266.3 | 7.6 | 280.3 | 3.6 | 7.4 | 0.591 |
| yolo11n_416.onnx | onnx | 416 | 4 | 7.0 | 273.5 | 7.8 | 288.4 | 3.5 | 8.73 | 0.643 |
| yolo26n_416_int8.onnx | onnx | 416 | 2 | 6.1 | 298.4 | 7.6 | 312.2 | 3.2 | 7.43 | 0.585 |
| yolo11n_416.onnx | onnx | 416 | 3 | 6.4 | 309.6 | 7.9 | 323.8 | 3.1 | 8.73 | 0.643 |
| yolo11n_416_int8.onnx | onnx | 416 | 2 | 6.2 | 317.6 | 7.8 | 331.6 | 3.0 | 8.73 | 0.638 |
| yolo26n_416.onnx | onnx | 416 | 2 | 6.1 | 349.1 | 7.7 | 362.9 | 2.8 | 7.4 | 0.591 |
| yolo11n_416.onnx | onnx | 416 | 2 | 6.1 | 403.4 | 7.9 | 417.4 | 2.4 | 8.73 | 0.643 |

- **Winner:** NCNN / `models/yolo11n_320_ncnn_model` / imgsz 320 / threads 4 → **91.8 ms total, 10.9 fps**, 8.30 dets/frame, mean confidence 0.559. The fp32 ONNX YOLO11n 320 reference also gives 8.30 dets/frame and 0.559 confidence, but takes 179.3 ms at four threads. NCNN three threads gives 158.8 ms in this sweep.
- Selection: reject candidates more than 5% below the reference detection-count proxy; among the remaining candidates choose minimum total ms. This conservative guard implements the handoff's instruction not to trade an obvious detection loss for speed. The fast 256-pixel models yield only 6.03–6.53 dets/frame; YOLO26n 320 yields 5.07. This does not prove YOLO26 is less accurate overall; it is the observed result on this particular sample.
- Sustained **300 s**: first 10-second window **9.54 Hz**, last recorded window at 292 s **8.93 Hz**, median **9.07 Hz**, min **8.84**, max **9.68**. First/last benchmark temperature samples **60.2 → 66.1 °C**; pre-run maximum **44.8 °C**. The independent named-zone monitor reached **cpuss0 70.2 °C / cpuss1 68.6 °C**, and ended inference near 68.9/68.0 °C. Bench sampling every ~10 s misses faster peaks; its `temp_c` is the maximum across all zones. At every 5-second sample during sustained inference, all four core frequencies were **2,016,000 kHz** (schedutil governor): **no frequency throttling observed**, though throughput drifted ~6.4%. Once inference stopped, temperature fell to ~51 °C and idle frequency to 614,400 kHz. No heatsink/fan; ambient unknown. Logs: [sustained stdout](sustained.log), [report](bench_20261010-132520.md), [JSON + time series](bench_20261010-132520.json), [named CPU temperatures/frequencies](sustained_cpu.csv). Sustained uses detector defaults (`conf_low=0.15`), whereas timed sweep uses 0.25; report both conditions rather than equating the two FPS calculations.
- **Committed configs:** `configs/board_imx219.yaml` requests unverified CSI 640×480@30 with no stereo crop. Updated `configs/board_zed.yaml` uses the measured NCNN detector and verified UVC mode described in §2. Real floor calibration is still pending.

## 4. Live ZED pipeline — uncontrolled desk scene
`configs/board_zed.yaml`: ZED Mini USB 3, raw 1344×376 YUYV @30 requested, left-eye output 672×376; NCNN YOLO11n 320, four threads, conf 0.35/conf_low 0.15, max_hz 10, motion gating enabled. No heatsink/fan, ambient unknown. No ground calibration: operator confirms no rectangle yet. Visible indoor desk/people scene; **not a controlled empty or 2–3-person trial**. One laptop dashboard with Camera layer enabled for part of the interval; five additional localhost SSE clients during part of it; two virtual Call cycles.

First five minutes of the live monitor, 13:55:33–14:00:31 UTC, 60 samples at ~5 s:

| Metric | min | median | max |
|---|---|---|---|
| detector Hz | 7.0 | **7.4** | 7.8 |
| inference ms | 109.1 | **114.4** | 123.5 |
| decision ms | 124.2 | **130.65** | 139.9 |
| loop fps (EMA) | 7.1 | 7.5 | 9.9 |
| camera fps (cumulative average) | 15.2 | **15.3** | 15.4 |
| detector duty | 0.889 | 0.963 | 0.978 |
| system CPU % | 84.1 | 85.6 | 88.6 |
| maximum thermal-zone °C | 64.2 | 68.0 | 69.6 |
| system used RAM MiB | 709 | 740 | 751 |
| MCU RTT ms | 6.0 | 7.25 | **126.5** |

No MCU error in these samples; all connected. A single RTT spike is retained rather than reporting only the median. Named CPU sampler reached 70.8 °C in this interval; all four frequencies remained 2,016,000 kHz. Process RSS around 178 MiB late in the interval, no process swap. Detector target ≥6 Hz is met in this scene, but capture falls from 29.7 fps alone to ~15.3 fps with the full pipeline. Duty stays high: **motion gating has not been validated on an empty scene**. Counting/approach remain unverified without ground coordinates.

[Five-minute CSV](zed_uncontrolled_5min.csv), [live state](zed_low_mode_state.json), [startup stdout](zed_live.log), [two Call cycles](zed_live_calls.jsonl). Browser verified real live camera, one eye/aspect/upright, NCNN name, nonzero detector timing and STM32 router status, with no browser console errors. Two actual UI Call clicks each completed S1 yellow → all-red → walk → S2 → S3 → S4. These validate button-to-controller transitions/RPC on the live node; they do not validate camera-triggered waiting or physical lamp timing.

Thirty-minute uncalibrated live monitor completed and was recovered after the latest reboot: 356 samples, zero HTTP errors, but the final 14 samples had frozen camera/source time. **This is not a clean 30-minute pipeline pass**; see §8. Viewer-load and offline checks completed below. No raw camera frames committed.

## 4b. Public-video fallback before ZED was connected
**IMX219 was unavailable during these fallback tests. ZED connected afterward and provides the separate live measurements in §4a.** Controlled empty/busy live-scene trials have not been performed. The following are measured **public-video** results, not camera performance or real-crosswalk accuracy. All compute and MCU RPC ran on the UNO Q. Input: Intel public parking-lot sample, 768×432, realtime loop, approximate virtual crosswalk; no heatsink/fan, ambient unknown. Dashboard open on one laptop, Camera layer enabled during part of the baseline. API pedestrian-call cycle included; no phone verified.

Default `configs/video_demo.yaml`: ONNX YOLO11n 416, threads 4, conf 0.35/conf_low 0.2, max_hz 12. Run `--max-seconds 370`; five-minute monitor recorded **150 samples, 0 failed requests**. [Pipeline stdout](video_default.log), [CSV](video_default_5min.csv), [monitor stdout](video_default_soak.log).

| Metric | min | median | max |
|---|---|---|---|
| detector Hz | 1.2 | 2.2 | 2.9 |
| inference ms | 284.9 | 306.8 | 410.3 |
| decision ms | 315.8 | 339.7 | 446.7 |
| loop fps | 4.9 | 9.3 | 11.4 |
| decoded video fps (`camera_fps` field) | 11.5 | 11.9 | 12.0 |
| detector duty fraction | 0.23 | 0.30 | 0.51 |
| system CPU % (all cores normalized to 100%) | 37.6 | 56.1 | 100.0 |
| maximum thermal-zone °C | 48.6 | 59.2 | 63.9 |
| system used RAM MiB | 820.0 | 877.5 | 886.0 |
| MCU RTT ms | 5.5 | 7.0 | 14.0 |

All 150 MCU samples connected, no RPC errors. System RAM is not process RSS. `decision_ms` measures the loop up to dispatch to the MCU worker, not physical lamp-edge latency. `camera_fps` here counts decoded public-video frames, not IMX219 capture. No pipeline tracebacks.

Browser verified live updates, real model/backend, vehicle counter/direction, 3D twin, Camera layer, STM32 status, and Share QR generation. A temporary stale dropdown after API mode change resolved on reload; proposed UI synchronization below. Actual hardware matrix behavior was confirmed by operator (§7a).

NCNN fallback reproduction: `configs/board_video.yaml` (same public video, YOLO11n 320, threads 4, max_hz 10). A 30-minute soak was started, but operator requested power-off/ribbon inspection shortly afterward. **The saved checkpoint is only 12 samples over 55 s**, not a completed 30-minute pass: detector median 4.55 Hz, inference 124.8 ms, decision 150.55 ms; MCU connected throughout. Files: [partial CSV](video_ncnn_30min.csv), [partial stdout](video_ncnn_soak.log), [pipeline startup](video_ncnn.log), [process RSS / CPU monitor checkpoint](video_ncnn_cpu.csv). Longer run must be repeated after hardware work.

## 4c. Live CAM0 IMX219 pipeline
Five-minute monitor: **147 samples, zero failed requests**, **14:46:46–14:51:45 UTC** (16:46–16:51 Rome). All sampled source times advanced; no consecutive stale states. MCU connected throughout, no RPC errors. This is a short pipeline pass, not a 30-minute endurance test.

Conditions: `libcamerify` + `configs/board_imx219.yaml`, IMX219 CAM0 type1-2lanes, requested 640×480@30 → actual **632×480** with unavailable FPS control; NCNN YOLO11n 320/t4; uncalibrated close-up under-desk scene, one laptop Camera viewer. No heatsink/fan; ambient unknown. Scene was not established as controlled empty/busy; physical counting/approach is unverified.

| Metric | min | median | max |
|---|---|---|---|
| detector Hz | 1.1 | 5.1 | 6.0 |
| inference ms | 139.9 | 155.9 | 246.3 |
| decision ms | 157.6 | 174.4 | 264.8 |
| loop fps EMA | 8.6 | 53.7 | 77.1 |
| cumulative capture fps | 32.0 | 35.6 | 40.0 |
| detector duty fraction | 0.17 | 0.33 | 0.74 |
| system CPU % | 40.0 | 74.9 | 85.9 |
| maximum reported thermal-zone °C | 49.5 | 58.3 | 62.4 |
| system used RAM MiB | 776.0 | 792.0 | 800.0 |
| MCU RTT ms | 5.6 | 7.0 | 152.7 |

Median detector rate **5.1 Hz** is below the 6 Hz live target in this scene; motion gating reduced the duty/rate at times, so it is not a controlled saturated-detector capacity test. Median inference **155.9 ms**, decision **174.4 ms**. `camera_fps` is cumulative capture throughput; loop fps is a per-loop EMA and must not be interpreted as sustained capture throughput. Capture remains above the 15 fps target in this trial. All category counts stayed zero because ground calibration is absent; these are not detection-accuracy results.

cpuss0 temperature °C: min/median/max **49.8 / 59.2 / 63.6**, first/last **59.2 / 54.8**. cpuss1 temperature °C: min/median/max **49.5 / 58.0 / 62.7**, first/last **58.3 / 54.5**. process RSS MiB: min/median/max **181.3 / 181.4 / 181.8**, first/last **181.3 / 181.8**. No process swap observed. Process RSS includes viewer/JPEG allocation; five minutes does not establish leak freedom. Sampled frequencies were 1420.8, 1612.8, 1804.8 and 2016 MHz as workload varied; no controlled thermal-throttling conclusion is made. MCU RTT median was 7.0 ms with one maximum of 152.7 ms; the spike is retained in the table.

[Pipeline CSV](imx219_live_5min.csv), [monitor stdout](imx219_live_soak.log), [process/thermal CSV](imx219_live_cpu.csv), [pipeline stdout](imx219_live.log). Browser verified an actual camera image and active MCU; pipeline remains running on `http://10.34.93.148:8000/`. No raw camera media committed. Configuration loaded successfully on laptop; no production pipeline logic changed.

## 5. Calibration
**Pending physical setup:** both ZED and IMX219 have provided live images, but operator confirms **no marked rectangle for now**. No measured lens height, grid alignment or ±15% height comparison has been verified. The video's pre-existing approximate fixture reports height 17.98 m / tilt 90° / HFOV 60°; these are software fixture outputs, **not physical camera measurements**. No calibration image committed.

## 6. Functional tests
| # | Test | Repetitions | Observed result | Status |
|---|---|---|---|---|
| F1 | A→B / B→A crossings | 0 | No calibrated rectangle | blocked |
| F2 | walk along edge | 0 | No calibrated rectangle | blocked |
| F3 | two people opposite | 0 | No calibrated rectangle | blocked |
| F4 | approach + wait | 0 | Camera approach/wait not tested without a calibrated rectangle; call cycle below uses virtual button | blocked |
| F5 | slow walker extension | 0 | No physical walk test | blocked |
| F6 | bicycle / e-scooter | 0 | No physical ride/push test | blocked |
| F7 | empty 5 min | 0 | Public video includes actors; cannot substitute for empty live scene | blocked |
| F8 | pedestrian call | 4 | Two video cycles (API + UI), plus two actual UI clicks on the live ZED node: all completed S1 → S2 → S3 → S4 without RPC errors | controller/UI pass; physical lamps deferred |
| F9 | offline 2 min | 1 network trial, 0 scored walks | Wi-Fi carrier 0 for 24 local samples; capture/inference/MCU continued and same profile reconnected automatically | capture/MCU pass; counting unverified without rectangle |
| F10 | public video on board | 1 | ONNX baseline: median 2.2 Hz; final 8 vehicles, all −X, 0 pedestrians/bikes/micromobility; B0/B2 seen | partial: vehicle counting demonstrated; person counting not demonstrated |

Event log: [video_default_events.jsonl](video_default_events.jsonl). API evidence: [video_api.json](video_api.json), [helper](check_video_api.py). First cycle 13:26:49–13:27:09 UTC; dashboard cycle 13:31:47 onward, also completed all four rules. No ground-truth counting accuracy can be asserted for the eyeballed virtual crosswalk. Five conflict events and two violation events occurred on that fixture; these do not validate physical collision estimates.

Verification helper initially raised `TypeError: '<' not supported between instances of 'str' and 'NoneType'` in its final summary print, **after saving the full JSON and restoring beacon mode**; [exact log](video_api.log). Corrected the helper's optional rule-ID formatting; this was not a pipeline exception or production-code change.

## 7a. MCU — firmware, matrix, watchdog
- App Lab CLI compile/upload: **successful**, using `arduino-app-cli app start ~/ArduinoApps/crosswalk_mcu`, then `app restart` after the fix. Core **arduino:zephyr 1.0.0**, Arduino_RouterBridge **0.4.3**, Arduino_LED_Matrix **0.1.3**. Flash: **99,968 B / 786,432 B**; globals: **40,160 B / 262,144 B**. No compilation errors, no RPC signature changes, `USE_TONE=0`. Logs: [initial](firmware_initial.log), [fixed/reflashed](firmware_fixed.log).
- Initial boot fail-safe **failed visually**: operator reported no blinking `!`. Root cause: `frameDirty=false` plus initial `failsafe=true` means the first loop never loads `FAILSAFE_FRAME`. Minimal fix: initialize `frameDirty=true`. Recompiled and reflashed successfully; operator then confirmed **blinking `!` before heartbeats**.
- Smoke test: `timeout --signal=INT 40 .venv/bin/python -u tools/mcu_test.py --watchdog`. Ping RTT **5.3 ms** (one sample, no inference pipeline active). All signal/warning/draw/heartbeat RPCs completed without error; operator saw the various matrix icons and later the blinking `!` after test shutdown. Exact page-by-page correspondence was not individually scored. Log: [mcu_smoke.log](mcu_smoke.log).
- Exit **124** is the deliberate timeout ending the tool's otherwise infinite button-monitor loop, after the complete sequence, six-second heartbeat pause, and heartbeat resumption. No external lamps/button/buzzer were verified.
- Watchdog reaction time: **unmeasured** (no slow-motion recording); do not claim ≤2 s from firmware timeout alone. Boot behavior and eventual fail-safe after heartbeats stop are visually confirmed. Operator subsequently confirmed that the physical matrix changed to count/walk/warning pages during the public-video pipeline and returned to blinking `!` after it stopped. Pipeline startup recovered normal pages. Exact physical correspondence and ≤2 s reaction were not timed.

- Latest MCU check with live CAM0: all 147 five-minute samples connected, no RPC errors; median RTT **7.0 ms**, maximum **152.7 ms** (§4c). The app required manual restart after the latest operator reboot (§2).

## 7b. MCU — LEDs, buzzer, button, power
External LEDs are available, but the operator explicitly deferred using them. External lamps, buzzer, physical button, wiring photo and full physical signal-cycle video were **not tested**. No USB power meter measurement was available; idle/empty/busy/LED current and power are unmeasured.

## 8. Robustness
| # | Test | Result |
|---|---|---|
| R1 | ZED unplug/replug | Uncontrolled loss of frames observed near the end of the previous run: V4L2 timeout, frozen source state, ongoing MCU heartbeat. No timed unplug/replug or automatic recovery trial was performed. CAM0 now works after operator reboot. |
| R2 | 30-min soak | Monitor completed: 356 samples / zero failed HTTP requests; fresh source time through 14:24:19, then 70 s of stale states. Fail for uninterrupted capture; cause of camera loss not isolated. Memory was steady after initialization. |
| R3 | reboot | Operator cold boots and agent reboot completed. Agent reboot issued ~13:44:10 UTC; first sampled SSH banner 13:45:03 (~53 s; polling adds ≤7 s uncertainty). Router active, but MCU app stopped and ping unavailable. `arduino-app-cli app start ~/ArduinoApps/crosswalk_mcu` successfully compiled/flashed/restarted it; live ZED run confirms MCU connected with ~7 ms RTT. No automatic startup configured. |
| R4 | 5 phones | Five extra localhost SSE consumers for 120 s: 879–880 state events each, max gap 0.505 s, no errors; median CPU 85.65% baseline vs 85.6% loaded. This is server-data load, **not five physical phones/Wi-Fi/rendering**. |

### Recovered 30-minute ZED monitor — stale camera state at end
The board-local monitor continued despite SSH loss: **356 samples**, 13:55:33–14:25:29 UTC, **zero failed HTTP requests**. Camera time stopped advancing at **t=1782.874 s**, last new state sampled **14:24:19**. The final **14 samples / 70 s** repeated the same time/performance state. MCU RTT still varied (~6.2–6.4 ms) while `connected=True` and no errors were reported. Thus server availability and MCU heartbeat continued after fresh vision stopped; neither proves camera health. The exact hardware action/cause was not isolated. No controlled reconnect was performed before the operator reboot.

[Full CSV](zed_uncalibrated_30min.csv), [monitor stdout](zed_uncalibrated_soak.log), [pipeline stdout](zed_live.log), [stability plot](zed_live_soak_plot.png) ([plot source](plot_zed_soak.py)). Pipeline logged repeated:
```
[ WARN:0@1794.725] global cap_v4l.cpp:1049 tryIoctl VIDEOIO(V4L2:/dev/v4l/by-id/usb-Technologies__Inc._ZED-M-video-index0): select() timeout.
```
This substantiates the heartbeat/freshness concern below. Physical matrix fail-safe during this stall was not observed, so no physical watchdog claim is made. **R2 is not a clean 30-minute pass.**

Conditions: ZED 1344×376 YUYV @30 requested → 672×376 left eye; NCNN YOLO11n 320/t4; uncalibrated desk scene, laptop Camera viewer, extra SSE load and a two-minute Wi-Fi interruption as detailed below; no heatsink/fan, ambient unknown. Metrics below exclude consecutive stale states (**342 distinct samples**, 28 min 46 s between first/last fresh monitor samples):

| Metric | min | median | max |
|---|---|---|---|
| detector Hz | 3.2 | 7.5 | 8.8 |
| inference ms | 95.0 | 114.1 | 382.8 |
| decision ms | 109.5 | 129.6 | 401.1 |
| cumulative capture fps | 14.9 | 15.2 | 15.4 |
| system CPU % | 84.1 | 86.1 | 89.4 |
| maximum reported thermal-zone °C | 64.2 | 70.2 | 73.3 |
| MCU RTT ms | 5.7 | 7.1 | 126.5 |

[Process/thermal monitor](zed_low_cpu.csv): after startup RSS was steady around **178.7–178.8 MiB**, no process swap observed; this does not assert long-term leak freedom. Named CPU temperature maxima **75.2 °C cpuss0 / 74.0 °C cpuss1**. Frequencies were **2016 MHz** until the sample at **14:24:17**, then **614.4 MHz** while temperatures fell rapidly and camera state ceased advancing. This is consistent with reduced workload after capture loss, not evidence establishing thermal throttling. The temperatures during the active run did not establish a sufficiently long plateau.

Recovered process CSV and pipeline log contained respectively **534 / 142 trailing NUL bytes**. Readable copies omit those bytes; originals are preserved byte-for-byte in [raw CSV gzip](zed_low_cpu_raw.csv.gz) and [raw log gzip](zed_live_raw.log.gz), with SHA-256 and normalization details in [artifact audit](zed_recovered_artifacts.json). The source of the trailing zeros is not established; they do not affect earlier complete rows.

### Viewer-load and offline evidence
Viewer reproduction: [check_viewers.py](check_viewers.py), [JSON](zed_viewer_load.json), [stdout](zed_viewer_load.log). One laptop viewer with Camera layer active, plus **five localhost SSE consumers**, uncontrolled uncalibrated desk scene. Sequential baseline 60 s / extra consumers 120 s / recovery 30 s:

| Period | median system CPU % | detector Hz | inference ms | cumulative camera fps |
|---|---|---|---|---|
| baseline | 85.65 | 7.5 | 114.2 | 15.4 |
| five extra SSE clients | 85.6 | 7.3 | 115.8 | 15.4 |
| recovery | 86.2 | 7.3 | 119.7 | 15.3 |

No MCU errors in these measurements. Each extra client received 879–880 state events; maximum state gap 0.505 s, no errors. CPU delta **−0.05 percentage points** between sequential windows is effectively no measured increase, not a controlled causal estimate: scene and temperature were not held constant. This excludes five-phone rendering, wireless traffic and five concurrent camera streams.

Offline reproduction: [check_offline.py](check_offline.py), [JSON](zed_offline.json), [stdout](zed_offline.log). Root-run `nohup` helper disconnected wlan0 for 120 s and restored the same active NetworkManager profile in `finally`; no Wi-Fi names, UUIDs or credentials saved. **24 samples, 14:03:24–14:05:21 UTC, all carrier=0**. Camera/inference/MCU continued on localhost; Wi-Fi restored automatically and SSH returned. Source time 530.517 → 658.909 s and pipeline frames 3863 → 4835 (includes disconnect/reconnection overhead). Offline detector min/median/max **6.1 / 7.7 / 8.3 Hz**, inference **103.7 / 110.65 / 262.6 ms**, decision **118 / 126.5 / 278.6 ms**, cumulative camera fps **14.9 / 15.0 / 15.0**; CPU max 91%, hottest zone max 71.1 °C. MCU connected throughout, no errors. The capture target of 15 fps is therefore borderline under full load; don't promise ≥15 fps in all conditions from capture-only data. No physical crossings or counting accuracy measured.

## Code changes made on this branch
| File | Change | Why |
|---|---|---|
| `firmware/crosswalk_mcu/sketch/sketch.ino` | Initialize `frameDirty=true` | Actual board boot had no fail-safe icon. Load the existing `FAILSAFE_FRAME` on the first loop; RPC names/semantics and timeout unchanged. Fixed firmware compiled, flashed, and boot icon confirmed by operator. |

Laptop baseline validation: `python3 -m pytest -q tests` → **16 passed in 0.55 s** before any code changes.
After firmware initialization fix: **16 passed in 0.35 s** on the laptop; actual board firmware compile/upload also passed.

## Proposed changes (not done)
- Fix camera-loss fail-safe and recovery. **Observed uncontrolled stall in recovered ZED run, plus source inspection; controlled reconnect still pending:** `CameraSource._loop` retries the same failed capture without reopening it; `Node.run` continues on a missing live frame before checking `max_seconds`; MCU `_worker` sends heartbeat independently of new vision frames; `/api/health` always reports HTTP-server liveness. The recovered ZED run did leave a stale state and ongoing MCU heartbeat. Test removal/reconnection, then consider capture reopen, frame-age health reporting and heartbeat gating on fresh vision. Production logic was not changed under this handoff.
- Define MCU app startup/recovery on reboot. Post-boot router is active but `ping` returns `[2, 'method ping not available']` and `crosswalk_mcu` app is stopped; do not assume firmware RPC is ready just because the router socket exists.
- Investigate capture throughput under inference: raw/cropped capture alone ~30 fps but live pipeline ~15 fps. Consider cropping raw YUYV before RGB conversion and evaluating buffer/thread contention; no source logic changed.
- Validate motion gating under fixed lighting and a verified empty scene; the uncontrolled desk scene had ~96% duty.
- Synchronize the signal-mode dropdown when the backend mode changes through the API; a reload currently brings it back into agreement.
- Mark public-video sources explicitly in the live header so “LIVE · on-device” cannot be mistaken for live camera capture.
- Validate IMX219 image tuning, exposure and orientation in the intended scene; the current simple ISP uses `uncalibrated.yaml` and does not expose FrameDurationLimits. `libcamerify` capture is now verified; do not claim requested 30 fps is controlled.

## 9. Autostart + fail-safe

Tested 2026-10-10 UTC on master **82a2c71**, results branch **board-failsafe**, following `docs/HANDOFF_AUTOSTART.md`. **CAM0 IMX219 only**; USB was not used. Deployed master into `~/occhio`, preserved its virtualenv/models, installed `deploy/install_autostart.sh`, and selected `configs/board_imx219.yaml`, `libcamerify`, and `/home/arduino/ArduinoApps/crosswalk_mcu` in `/etc/default/occhio`. Both units are enabled; `occhio-mcu` is a successful oneshot (active/exited), and `occhio` is active. The previous Grove app was stopped and its source preserved. Crosswalk firmware compiled/flashed successfully. No production code or firmware logic was changed in this results branch. The master's freshness gating, health response and service installation address the earlier proposed heartbeat/startup changes; the observations below define what was verified.

Evidence: [installation log](autostart_install.log), [installed configuration](autostart_installed.txt), [boot service journal](autostart_boot_services.log), [final service status](autostart_final_status.txt). Final check at **16:14:47 UTC**: CAM0 node `cw-01-imx219`, HTTP 200 / `ok=true`, vision age **0.16 s**, MCU connected, failsafe false, normal service PID **2254**, no injected camera fault. The normal service remains running for video recording. The temporary boot observer was removed; the temporary camera hook is not active.

### Reboot and faults

Reboot was issued at 16:02:04 UTC. No manual MCU/pipeline start followed it. A board-local monotonic observer recorded the first fully healthy response at **40.68 s after kernel boot** (16:02:43 UTC), with MCU connected and vision age 0.21 s. Last failed sample was at 40.43 s; sampling brackets the transition within about 0.26 s. This is not a measured physical power-on delay. [Boot samples](autostart_boot.jsonl), [network samples](autostart_reboot_network.jsonl).

| Test | Observed software result | Physical matrix reaction time |
|---|---|---|
| Boot | Both services started automatically; healthy at 40.68 s after kernel boot. | Unmeasured: operator unavailable. |
| SIGSTOP / SIGCONT | PID 1660 frozen for 8.52 s; five health requests timed out. After CONT, a transient 503 then healthy response; same PID, recovery **0.44 s after CONT**. | Unmeasured: operator unavailable. |
| SIGKILL | systemd restarted PID 1660 as 1989; healthy response **6.30 s after KILL**, including configured restart delay and initialization. | Unmeasured: operator unavailable. |
| Synthetic CAM0 read failure | Test-only OpenCV wrapper returned failed reads for about 8 s. First unhealthy HTTP 503 **~1.57 s after injection**; 26 HTTP 503 samples, stale vision, `failsafe=true`, MCU connected. Healthy response **0.37 s after release**. | Unmeasured; no physical CSI disconnect performed. |

[Freeze evidence](autostart_freeze.jsonl), [crash evidence](autostart_crash.jsonl), [camera failure evidence](autostart_cam0_fault.jsonl), [camera test node log](autostart_cam0_fault_node.log). The freeze recovery response still had an old performance snapshot (`frame_age_s=8.68`); its reported recovery time measures health/MCU response, not complete capture recovery. The synthetic camera trial ended before a new performance snapshot confirmed `camera_reopens`; **capture reopen-counter verification remains incomplete**. It verifies unhealthy response and software failsafe state, not physical camera reconnection. The helper now includes an additional counter check for a future repeat; that updated camera check was not run. No ≤2 s physical watchdog claim is made.

Exact recorded errors: successful app discovery emitted `Stopped decode loop: EOF` for `builtin:serial-discovery` and `builtin:mdns-discovery`. Frozen health clients recorded `TimeoutError: timed out`; their disconnects produced `BrokenPipeError: [Errno 32] Broken pipe` in the server after resume. The intentional crash produced `ConnectionResetError: [Errno 104] Connection reset by peer` and connection-refused requests before restart. These intentional test interruptions are recorded in the linked raw logs.

### CAM0 soak — partial, stopped for filming

The requested 30-minute monitor was **stopped at the user's request to prioritize sunset videos**. Files retain their originally planned `30min` names, but this is **not a 30-minute pass**. Pipeline samples cover **16:09:07–16:11:55 UTC (168 s, 34 rows)**; health samples cover 164 s (33 rows). Every health sample was HTTP 200, fresh vision (age max 0.67 s), MCU connected, failsafe false, no request/MCU errors, PID 2254, camera reopen count 0. Source frames progressed. RSS stayed around 170 MiB, with no process swap observed.

Conditions: CAM0 632×480 via libcamerify; NCNN YOLO11n 320 / four threads, uncontrolled scene, no heatsink/fan, ambient temperature unknown. No calibrated crossing accuracy or thermal plateau claim.

| Metric | min | median | max |
|---|---|---|---|
| detector Hz | 4.1 | 6.2 | 6.5 |
| inference ms | 135.6 | 144.05 | 154.6 |
| decision ms | 152.3 | 160.9 | 171.5 |
| cumulative camera fps | 29.9 | 31.55 | 33.0 |
| system CPU % | 44.5 | 84.25 | 86.4 |
| reported thermal-zone °C | 54.5 | 64.9 | 65.8 |
| MCU RTT ms | 6.0 | 6.95 | 654.3 |
| process RSS MiB (health monitor) | 170.01 | 170.52 | 170.53 |

Separate CPU thermal monitor reached **68.0 °C cpuss0 / 66.7 °C cpuss1**. The 654.3 ms MCU RTT was the first pipeline sample; subsequent samples returned to single-digit milliseconds. [Pipeline CSV](autostart_imx219_30min.csv), [health CSV](autostart_health_30min.csv), [CPU/RSS CSV](autostart_cpu_30min.csv), [monitor log](autostart_imx219_soak.log).

Laptop validation: full suite **85 passed, 4 failed, 1 skipped**. Three failures were sandbox socket permissions; rerun with socket access **3 passed** ([log](autostart_network_tests.log)). Remaining failure is the laptop's SciPy 1.8.0 compatibility in `sim/validation.py`: `AttributeError: 'SpearmanrResult' object has no attribute 'statistic'`. Both new failsafe tests passed. Board SciPy is 1.18.1. The unrelated simulator compatibility issue was left outside this deployment task.

Remaining acceptance evidence: physical boot/freeze/crash LED timing, confirmed capture reopen counter/real camera recovery, and a complete 30-minute CAM0 soak. Extended tests were stopped for filming; autostart and the measured software fault responses are recorded above.
