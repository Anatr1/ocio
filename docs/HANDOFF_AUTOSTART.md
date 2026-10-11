# Handoff: autostart + camera fail-safe on the UNO Q

Two issues from `docs/board_results/RESULTS.md` are fixed in code on `master`. They need a run on the real board.

1. **The MCU app did not start after a reboot**, so someone had to run `arduino-app-cli app start` by hand.
   There are now boot services in `deploy/`.
2. **A frozen camera kept the MCU heartbeat going**: in the 30-minute run, vision was stale for 70 s while the lamps
   stayed "normal". Now:
   - The heartbeat is sent only while fresh frames arrive (`mcu.vision_timeout_s`, default 1.5 s).
   - When frames stop, the firmware watchdog (2 s) switches the lamps to flashing amber, as if Linux were dead.
   - A camera with no frames for 2 s is closed and reopened (`source.reopen_s`).
   - `/api/health` now reports `vision_age_s` and answers **HTTP 503** when vision is stale.

   No firmware change is needed: the existing watchdog does the work.

Reminder: the ZED is not used. The camera is the IMX219 on CAM0, through `libcamerify`.

## Steps (on the board, user `arduino`, code in `~/occhio`)

1. **Deploy the current `master`** to `~/occhio`, the same way you did before (tar over SSH). Keep `.venv` and `models/`.
2. **Stop any pipeline you started by hand.** Then install the services:
   `cd ~/occhio && sudo sh deploy/install_autostart.sh`
   This writes `/etc/default/occhio` with the config, the `libcamerify` wrapper and the MCU app path. Check that the app
   path matches where `crosswalk_mcu` lives on this board.
3. **Check that both services run:**
   `systemctl status occhio-mcu occhio` and `curl -s localhost:8000/api/health`.
   Expect `"ok": true`, a small `vision_age_s` and `"mcu_connected": true`.
4. **Reboot test:** `sudo reboot`, touch nothing, and time it.
   - Expect the matrix to show blinking `!` at boot.
   - Then expect normal pages once the pipeline runs, with the dashboard at `http://<board-ip>:8000`.
   - Record the time from power-on until health is `ok`.
   - If `arduino-app-cli` fails when started from systemd, send me `journalctl -u occhio-mcu -b` (it may need a
     different user or environment).
5. **Fail-safe tests.** Film the matrix with a phone in slow motion so the reaction time can be measured:
   - **Vision frozen:** `sudo kill -STOP $(pgrep -f "crosswalk --config")`. Expect flashing amber / `!` within about
     2 s, and health no longer answering. Then `sudo kill -CONT <pid>`: normal again within a few seconds.
   - **Pipeline crash:** `sudo kill -9 <pid>`. Expect amber within 2 s, then systemd restarts the node after 3 s and the
     lamps return to normal.
   - **Do not unplug the CSI ribbon while powered.** If you have any USB webcam, a run with it plus unplug/replug
     exercises the camera reopen path. Look for `camera_reopens` in `/api/state` → `perf`, or in the logs.
6. **30-minute soak again** on the IMX219 with `tools/soak_monitor.py`, as before. Report the 503/stale samples, if any.

## Report

Add a section **"9. Autostart + fail-safe"** to `docs/board_results/RESULTS.md`, with:
- boot-to-healthy time
- the three fail-safe reaction times from the video
- the soak table
- any errors, quoted exactly

Push to a new branch `board-failsafe`; I'll review and merge it.
