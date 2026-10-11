# Pitch — OCCHIO

**One-liner:** *An Arduino-sized edge node that turns any crosswalk into a smart, privacy-safe safety sensor: it counts,
measures risk, and acts - in real time, without sending a single frame of video anywhere.*

## Numbers for the hook (sources)
- **419 pedestrians killed in Italy in 2025**, 14.6 % of all road deaths (ISTAT, report luglio 2026).
- **~45 % of pedestrian deaths happen on the zebra crossing itself**: 61 of 135 pedestrian deaths Jan–May 2025 (ASAPS-SAPIDATA observatory).
- **Turin 2024: 492 crashes involving pedestrians, 10 fatal** (Polizia Municipale data, Circoscrizioni 3/5 documents).
- Pedestrians die 4× more often per crash than car occupants (ISTAT 2024: 2.5 deaths per 100 pedestrian crashes).
- Accidents are rare, **near-misses are frequent and predictive** → measure near-misses, fix crosswalks before someone dies
  (traffic-conflict technique, used by road-safety engineers).

## Story (5 min)
1. **Hook (30 s)** - photo of a Turin zebra crossing. "Almost half of the pedestrians killed in Italy are killed *on* the
   zebra. Cities don't know which crosswalks are dangerous until somebody dies."
2. **What we built (45 s)** - OCCHIO: camera + Arduino UNO Q. Sees (detect), understands (track in metres, count,
   measure near-misses, driver yielding, speeds), acts (warning beacon, adaptive pedestrian signal). 100 % on-device.
3. **Live demo (2 min)** - see script below.
4. **Engineering (1 min)** - the hard part was making it run on a 4×A53 board with no NPU:
   motion-gated, ROI-cropped nano detector fine-tuned *on our own footage* (teacher-student auto-labelling) →
   X Hz at Y ms; bird's-eye tracker in metres with the camera calibrated **from the zebra stripes themselves**
   (camera height & lens recovered automatically); dual-brain: Linux does vision, the STM32 owns the lamps with a
   **fail-safe watchdog** (flashing amber within 2 s if Linux dies - like real traffic controllers).
5. **Validation (30 s)** - counting accuracy on *our* Turin footage vs. manual ground truth (fill in); simulator with
   ground truth: 91-93 % counting on 1,860 passages under heavy detector noise, adaptive signal cuts pedestrian
   waiting 46 % and, in the same dangerous traffic, serious conflicts from 16 to 0;
   power: Z W; no video stored.
6. **Impact & next (30 s)** - for cities / 5T / road-safety offices: a dashboard of near-misses, yield compliance, V85
   speeds, crossing times, per crosswalk. Privacy by design (GDPR). Scales as a fleet of nodes (2 KB/s each).
   Productisation with rugged edge hardware (GOMA). Ask: pilot on 3 Turin crosswalks.

## Demo script (≈2 min, 2 people)
1. Hand out the QR card → judges open the 3D twin on their phones (board serves it).
2. Teammate walks across the indoor zebra → counter ticks on the LED matrix + dashboard, avatar walks in the twin,
   walking speed and height shown. Push-free crossing: they wait at the curb → the signal turns green by itself.
3. Teammate walks slowly → "Green Man+": clearance extended (toast + lamp keeps flashing).
4. Street footage processed on the board: cars/bikes/pedestrians counted, speeds; a near-miss fires (beacon flashes,
   toast) → click **3D replay** → orbit around the near-miss reconstructed from trajectories only.
5. Pull the plug on the pipeline (Ctrl+C over SSH) → lamps go to flashing amber in 2 s: fail-safe.
Backup: recorded video of the same demo + simulator (`python -m crosswalk --sim dangerous`) on the laptop.

## Slide outline (8-10 slides)
1. Title + one-liner + team
2. Problem (stats above, photo)
3. Solution: sees · understands · acts (3 icons) + photo of the device
4. Architecture (camera → UNO Q Linux: detect → BEV track → count/safety/signal → MCU: lamps/beacon/watchdog; dashboard)
5. Edge AI on a €-class board: benchmark table (model/runtime/ms/fps), duty-cycle graph (compute follows traffic), power
6. Calibration from the zebra + BEV tracking (screenshot of grid overlay + BEV texture)
7. Safety science: TTC / DRAC / PET / yield compliance (one near-miss replay screenshot)
8. Results: accuracy table on real footage + simulator validation + adaptive-signal waiting time
9. Privacy by design + scalability (fleet, 2 KB/s, OTA) + business/next steps
10. Thank you + QR

## Q&A prep
- **Night / rain?** Fine-tuned with photometric augmentation; IR/thermal camera is a drop-in source; evaluation set
  includes what we could record; honest: not validated at night yet.
- **Occlusion?** Track re-identification (same id after a bus passes), multi-camera fusion in the shared ground frame.
- **How accurate are speeds?** Calibration from standard 50 cm stripes; we report V85 like traffic engineers; error
  mainly from calibration (±5 %) - checked against known distances.
- **False alarms?** Near-miss = TTC ≤ 3 s *and* the car would need > 3 m/s² braking (DRAC): a car calmly stopping
  for a pedestrian is not a conflict. Validated against simulator ground truth (in dangerous traffic precision 48 %,
  recall 62 % at heavy noise; in calm traffic ~0.8 false alarms/min, mostly cars still braking to yield: we say it's
  a screening tool, events come with 3D replays for review).
- **Privacy / GDPR?** No frames leave the device or get stored; only anonymous trajectories (no identity, no appearance
  features); debug stream pixelated and only on demand.
- **Why not the cloud?** Latency for actuation, bandwidth (2 KB/s vs Mbit/s video), privacy, works offline.
- **Why the UNO Q?** Linux + real-time MCU on one board: vision and deterministic, fail-safe actuation together.
- **Cost?** Board + webcam + enclosure ≈ low hundreds of euros vs. thousands for commercial counters/radars (check figures).
- **What if Linux crashes?** MCU watchdog → flashing amber (fail-safe state) in 2 s; App/cron restarts the pipeline.
- **Legal?** Yielding: art. 191 Codice della Strada; actuation of real signals needs homologation → we propose
  advisory beacons first, signal integration with the city's controller (5T) as a pilot.
