# Hardware: wiring, shopping list, mounting

For the current Grove bench deployment, **setup-GPIO-app wiring takes priority**.
Use the packaged Grove profile and [live hardware handoff](HANDOFF_LIVE_GPIO.md).
The pin table below describes the retained original profile, not the Grove wiring.

## Block diagram

```
 USB webcam ──┐                         ┌──────────── Arduino UNO Q ────────────┐
              ├─ powered USB-C hub (PD) ─┤ QRB2210 (4x A53, Debian)               │
 5V/3A PD ────┘                         │   vision pipeline + web server (:8000)  │
                                        │        │ arduino-router (msgpack-RPC)   │
                                        │ STM32U585 (Zephyr)                      │
                                        │   lamps · beacon · buzzer · button ·    │
                                        │   8x13 LED matrix · fail-safe watchdog  │
                                        └──────┬──────────────────────────────────┘
                                               │ D2..D9
                     vehicle R/Y/G · pedestrian R/G · amber beacon · piezo · push button
```

## MCU wiring (default pins - change at the top of `firmware/crosswalk_mcu/sketch/sketch.ino`)

| Pin | Function | Part |
|---|---|---|
| D2 | vehicle RED | LED + 330 Ω to GND |
| D3 | vehicle YELLOW | LED + 330 Ω |
| D4 | vehicle GREEN | LED + 220 Ω (green LEDs need more voltage at 3.3 V) |
| D5 | pedestrian RED | LED + 330 Ω |
| D6 | pedestrian GREEN | LED + 220 Ω |
| D7 | warning beacon (amber) | LED + 330 Ω, or logic-level N-MOSFET (e.g. IRLZ44N / AO3400) gate for a 12 V lamp/LED strip (+ 10 kΩ pull-down) |
| D8 | buzzer (accessible pedestrian signal) | **active** 3.3–5 V buzzer by default; for a passive piezo set `USE_TONE 1` in the sketch (needs `tone()` in the Zephyr core) |
| D9 | pedestrian push button | button to GND (internal pull-up) |
| D10 | danger beacon (red, rule B2) | LED + 330 Ω (or MOSFET for a big red lamp) |
| GND | common ground | |

UNO Q GPIOs are **3.3 V logic**: keep each LED ≤ ~8 mA (220–330 Ω); drive anything bigger through a transistor.
Real traffic lamps are 230 V / 40 V: never connect them directly - use a relay board only if the organisers allow it.

## Camera placement (matters more than the model!)
- Height 2.5–4 m, looking **along** the crosswalk diagonally so both curbs and ~10–15 m of each approach are visible;
  avoid looking straight across (occlusion by the near lane).
- The crosswalk should cover a good part of the image; use `detector.roi` to crop away sky/buildings.
- Avoid backlight (sun in the frame) and windscreen reflections; 640×480 MJPG is enough (the detector runs at 256–416 px).
- Lock exposure if the webcam hunts: `v4l2-ctl -d /dev/video0 -c auto_exposure=1 -c exposure_time_absolute=150`.

## Shopping / packing list
- [ ] Powered USB-C hub **with PD pass-through** (USB-A port for the webcam) — the UNO Q docs say a powered hub is required
- [ ] USB-C PD charger ≥ 5 V/3 A (+ a second one) and a power bank with USB-C PD (street recording)
- [ ] USB webcam(s), UVC + MJPG, wide FOV (≥ 78°), 720p+ (e.g. Logitech C920/C930e); a spare
- [ ] Travel router (GL.iNet or any) → our own Wi-Fi for board + laptop + judges' phones
- [ ] Tripod / light stand reaching 2.5–3 m + clamp with 1/4" screw; zip ties; gaffer tape
- [ ] Tape measure (≥ 10 m), white + black gaffer tape 5 cm (indoor zebra), marker
- [ ] LEDs R/Y/G ×2, 220/330 Ω, push button, active buzzer, breadboard, M-F + M-M jumpers, (MOSFET + 12 V LED strip for a big beacon)
- [ ] Inline USB-C power meter (for the "X W" number), small heatsink or 5 V fan for the QRB2210
- [ ] USB stick: `hackturin-offline/wheels-aarch64-cp313` (160 MB) + `models/` + recordings
- [ ] Extension cord + multi-socket, USB-C/USB-A cables, USB-C-to-Ethernet adapter

## Power budget (fill in on site)
| State | Current @5 V | Power |
|---|---|---|
| idle (pipeline stopped) | | |
| pipeline, empty street (motion-gated) | | |
| pipeline, busy (detector at max rate) | | |
| + LEDs/beacon | | |
