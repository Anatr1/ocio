# Crosswalk MCU: original and Grove profiles

The production RPC contract is shared by both wiring profiles. Directly copying
this folder retains the original D2-D10 wiring from `docs/HARDWARE.md`, with an
active buzzer and no external OLED dependency.

For Federico's current hardware, use the **Grove** profile with the green/yellow swap
reported during physical testing on 2026-10-11. Build a self-contained App Lab folder on the laptop or board:

```bash
python tools/prepare_mcu_app.py --profile grove --out runs/crosswalk_grove_live
```

The output contains the shared sketch, `hardware.h`, U8g2 2.36.5 dependency,
an App Lab Python stub that never opens the camera, and `occhio-build.json`
with revision and content hashes. No installed app is overwritten or flashed.
Copy the generated folder to a new path inside `~/ArduinoApps/` on the board,
then follow [the live GPIO handoff](../../docs/HANDOFF_LIVE_GPIO.md).

Grove outputs: vehicle green D3, yellow D2, red D6; white alert D7; passive
buzzer D4; OLED on I2C. There are no separate pedestrian LEDs, red warning
LED or physical button. Pedestrian states appear on the OLED; the white alert
blinks slowly for B1 and quickly for B2. This is a bench demonstrator and does
not reproduce the original warning colours or accessible signal certification.

The OLED shows the effective vehicle/pedestrian state, warning level and a copy
of the matrix page. During fail-safe it displays `FAILSAFE`. All values come
from production RPC commands/watchdog state; no random numbers or timer-based
traffic cycles are generated. The passive buzzer services one waveform cycle
per loop; I2C display updates are deferred during beeps. Frequency, loudness,
I2C latency and target-board timing remain unmeasured.

`--no-oled` builds a GPIO-only diagnostic version when I2C is the blocker.
`--profile original` builds the previous wiring. Never run a profile on the
other profile's wiring.

Additional read-only RPC: `get_status()` returns eight integers:

| Index | Meaning |
|---|---|
| 0 | Schema version (1) |
| 1 | Grove profile (1) or original (0) |
| 2 | Effective watchdog fail-safe (1/0) |
| 3 | Effective vehicle code (same encoding as `set_signal`) |
| 4 | Effective pedestrian code |
| 5 | Effective warning level |
| 6 | Audio enabled (1/0) |
| 7 | Milliseconds since last heartbeat, or -1 before any heartbeat |

Reading this RPC does not keep the watchdog alive. It reports firmware state,
not electrically measured GPIOs or confirmation that a lamp emitted light.
