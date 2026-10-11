# Handoff: record real crosswalk footage (tonight)

**Goal:** record footage at the real crosswalk with the board's own camera. Tonight we calibrate, count and iterate
on these videos on the laptop. No live tests are needed beyond what is listed here.

The dashboard now has a **● Rec** button. The running pipeline records the raw camera frames itself (15 fps, 5-minute
`.mp4` parts, stored on the board in `~/occhio/data/recordings/`), so nothing needs stopping or restarting.
**Recordings** in the dashboard lists the files and downloads them.

## Before leaving (venue, ~10 min)

1. **Deploy the current `master`** to `~/occhio`, the same way as before. Keep `.venv` and `models/`.
   - If the autostart services are installed: `sudo systemctl restart occhio`.
   - If not, start it by hand: `libcamerify .venv/bin/python -m crosswalk --config configs/board_imx219.yaml`.
2. **Connect the board to the phone hotspot** we will use outside, and get its IP:
   `sudo nmcli dev wifi connect "<HOTSPOT>" password "<PASSWORD>"`, then `hostname -I`.
   Connect the laptop to the same hotspot and open `http://<BOARD_IP>:8000`.
3. **Dry run:**
   - Press **● Rec**, name it `test`, wait 10 s, then press **■ Stop**.
   - Open **Recordings**, download the file and check that it plays on the laptop.
   - If not, send me the output of `journalctl -u occhio -n 50` (or the console output).
4. **Pack:** power bank (5 V / 3 A, PD), tape measure, something to hold the camera about 3 m high (pole or tripod),
   tape or clamps, laptop, notebook, a bicycle if available.

## On site (~30 min, finish before sunset)

1. **Mount the camera:**
   - On the pavement, about 3 m high, 4–8 m from the zebra.
   - It must see the whole zebra and at least 10 m of road on both sides.
   - Check the framing in the dashboard (**Camera** layer).
   - From now on **do not touch the camera**. If it moves, write down at which recording.
2. **Zebra measurements: already done by Federico.**
   - 11 white stripes, each 0.5 m × 3 m, with 0.5 m gaps.
   - So `W = 3 m` (stripe length, along the road) and `L = 10.5 m` (first to last stripe, across the road).

   **Framing priority:**
   - Try to get **all 11 stripes and both kerbs** in view. Counting uses the zebra's middle line, and waiting
     detection needs both kerbs.
   - Raise the camera, move it back, or turn it more along the zebra if needed.
   - If not all stripes fit, the **middle (6th) stripe must be visible**. Write down **which stripes are fully
     visible, counted from the kerb nearer the camera** (e.g. "stripes 1-8 visible"). We calibrate on the visible
     part and extend it offline.
3. **● Rec `scripted` (~5 min).** The team crosses on purpose. Note in the notebook what happens and roughly when
   (wall-clock time):
   - one person A→B, then B→A (A = the kerb nearer the camera)
   - two people crossing in opposite directions at the same time
   - someone walking along the kerb without crossing
   - someone waiting about 20 s at the kerb, then crossing
   - a slow crossing
   - a bicycle ridden across, then pushed across
   Then **■ Stop**.
4. **● Rec `traffic` (15–20 min)** of real traffic. Everyone stays out of the frame. Then **■ Stop**.
5. **● Rec `dusk` (~10 min)**, optional, as the light drops. Then **■ Stop**.

## Back at the venue

- Open `http://<BOARD_IP>:8000/recordings` and download all files: `scripted_*`, `traffic_*`, `dusk_*`, in 5-minute
  parts.
- Give Federico the files plus a photo of the notebook page (measurements and timeline).

## Rules

- **The recordings are raw**: no pixelation, faces and number plates are visible. Keep them on the board and the team
  laptop only. **Never commit them to Git, or upload them to Devpost or any chat.** The folder is already
  git-ignored.
- Nobody directs traffic or stands in the road while cars are coming. The board's LEDs are only an indicator.
- Recording stops by itself after 1 hour.
