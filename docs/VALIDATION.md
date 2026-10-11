# Validation results (pre-event, simulator)

## Current results - 2026-10-10, merged simulator World

Generated with `tools/sim_eval.py` on master after the `sim-eval` merge (aa23e17): full pipeline (tracker,
counting, safety, signal) on the L1 virtual detector - deliberately noisy (3 % base miss rate, occlusion-dependent
misses, 3 % box jitter, 2 % class flips, false positives, cyclists as separate person + bicycle boxes, e-scooter
riders as 'person'). Ground truth uses the same counting-line definition as the pipeline. 5 simulated minutes x
seeds 0-3 per row. Reports: `runs/sim_eval_20261010-1605*.md`, `runs/sim_eval_20261010-161051.md` (not in Git).

| scenario | lamp mode | GT passages | counting accuracy | by direction | +X vehicles missed |
|---|---|---|---|---|---|
| count_test | beacon (unsignalised zebra) | 477 | 91.0 % | 91.0 % | 21 of 99 |
| count_test | adaptive signal | 489 | 92.2 % | 90.6 % | 16 of 114 |
| dangerous | beacon | 423 | 92.9 % | 92.4 % | 17 of 119 |
| dangerous | adaptive signal | 471 | 92.8 % | 92.8 % | 21 of 132 |

Errors are nearly all missed passages (a handful of +1/+2 overcounts in 16 rows). Most misses are still +X vehicles,
which the virtual camera only sees a few metres before the zebra: **mount the real camera so both approaches are
visible >= 10 m before the zebra.**

**Near-miss detection** (TTC with DRAC gating) against ground-truth serious/critical conflicts:

| scenario | lamp mode | true conflicts | flagged pairs | precision | recall |
|---|---|---|---|---|---|
| dangerous | beacon | 16 | 21 | 48 % | 62 % |
| count_test | beacon | 4 | 17 | 12 % | 50 % |
| count_test | adaptive signal | 0 | 18 | - | - |
| dangerous | adaptive signal | 0 | 15 | - | - |

- In conflict-heavy traffic the detector finds most real conflicts. In calm traffic it raises **~0.8 false alarms per
  minute** under this detector noise, typically a yielding car that is still braking (the track velocity lags the
  deceleration). Treat it as a screening tool with 3D replays for review; persistence/hysteresis on the alert is the
  obvious next improvement.
- **Same dangerous drivers and pedestrians: 16 serious/critical conflicts with the unsignalised zebra + beacon, 0 with
  the adaptive signal.**

**Fixed-time vs vision-adaptive pedestrian signal** (`--compare-signal --minutes 15`, mixed traffic, seeds 0-2):

| mode | ped. cycles | mean ped wait (s) | Green Man+ extensions |
|---|---|---|---|
| fixed | 66 | 23.4 | 0 |
| adaptive | 93 | 12.7 | 33 |

Adaptive cuts the mean pedestrian wait by 46 %.

**Why these differ from the 2026-10-09 numbers below** (which ran `count_test` under the default adaptive signal):
the previous World was unrealistically conflict-heavy (45 serious/critical conflicts in those 20 min, because
careful pedestrians walked in front of cars) and froze in long runs. The merged World only produces conflicts from
careless or hurried pedestrians and non-yielding or speeding drivers, and keeps flowing (see `sim/BEHAVIOUR.md`,
`tools/sim_soak.py`). The same `count_test` + adaptive run now has 0 true conflicts and 18 flagged pairs (was 49):
the detector flags less, but with no real conflicts left every flag is a false alarm, so the old 55 % precision
figure has no current equivalent in normal traffic. Use the `dangerous` row for detection quality.

## Superseded - 2026-10-09, previous World

Generated with `tools/sim_eval.py` on 2026-10-09 22:50. The virtual detector is deliberately noisy: 3 % base miss rate, occlusion-dependent misses, 3 % box jitter, 2 % class flips, false positives, cyclists returned as separate person + bicycle boxes, e-scooter riders returned as 'person'. Ground truth uses the same counting-line definition as the pipeline.

### Run - 2026-10-09 22:47

## Counting (count_test, 5 min x 4 seeds)

| scenario | seed | kind | ground truth | counted | error |
|---|---|---|---|---|---|
| count_test | 0 | pedestrian | 45 | 41 | -4 |
| count_test | 0 | bicycle | 15 | 15 | +0 |
| count_test | 0 | micromobility | 8 | 6 | -2 |
| count_test | 0 | vehicle | 48 | 46 | -2 |
| count_test | 1 | pedestrian | 59 | 57 | -2 |
| count_test | 1 | bicycle | 19 | 18 | -1 |
| count_test | 1 | micromobility | 4 | 4 | +0 |
| count_test | 1 | vehicle | 49 | 45 | -4 |
| count_test | 2 | pedestrian | 47 | 46 | -1 |
| count_test | 2 | bicycle | 28 | 26 | -2 |
| count_test | 2 | micromobility | 4 | 3 | -1 |
| count_test | 2 | vehicle | 50 | 47 | -3 |
| count_test | 3 | pedestrian | 45 | 42 | -3 |
| count_test | 3 | bicycle | 18 | 17 | -1 |
| count_test | 3 | micromobility | 6 | 5 | -1 |
| count_test | 3 | vehicle | 56 | 51 | -5 |

**Overall counting accuracy: 93.6%** (1 - sum|error| / sum(ground truth), 501 passages)

## Near-miss detection (TTC with DRAC gating)

- precision 55% (27 of 49 flagged pairs are real conflicts, TTC <= 3 s)
- recall 60% (27 of 45 serious/critical ground-truth conflicts flagged)
- seed 0: detected {'critical': 10, 'serious': 1, 'potential': 0}, ground truth {'critical': 5, 'serious': 13, 'potential': 13}, PET measurements 123, yield {'yielded': 11, 'not_yielded': 10}
- seed 1: detected {'critical': 10, 'serious': 3, 'potential': 2}, ground truth {'critical': 5, 'serious': 11, 'potential': 11}, PET measurements 118, yield {'yielded': 16, 'not_yielded': 10}
- seed 2: detected {'critical': 5, 'serious': 1, 'potential': 1}, ground truth {'critical': 6, 'serious': 8, 'potential': 10}, PET measurements 118, yield {'yielded': 15, 'not_yielded': 12}
- seed 3: detected {'critical': 12, 'serious': 4, 'potential': 0}, ground truth {'critical': 6, 'serious': 13, 'potential': 13}, PET measurements 141, yield {'yielded': 20, 'not_yielded': 12}

### Run - 2026-10-09 22:48

## Fixed-time vs vision-adaptive pedestrian signal

| mode | ped. cycles | mean ped wait (s) | Green Man+ extensions |
|---|---|---|---|
| fixed | 36 | 23.2 | 0 |
| adaptive | 50 | 12.3 | 21 |

Real-footage results: fill in from `tools/eval_counts.py` on site.

## Update 2026-10-10 - counting by direction

`tools/sim_eval.py --scenario count_test --minutes 5 --seeds 0 1 2 3` now also checks the direction of every passage
against ground truth: **direction-resolved counting accuracy 93.0 %** vs 93.4 % overall - i.e. the remaining errors are
missed passages, not wrong directions. Most misses are +X vehicles that enter the virtual camera's view only a few
metres before the crosswalk (they come from behind the pole): **mount the real camera so both approaches are visible
>= 10 m before the zebra.**


## Additional intersection mode — 2026-10-11

The optional four-arm intersection mode is independent of the crosswalk vision
pipeline. The figures above are unchanged. New experiments use perfect ground-truth
observations, protected left/through/right phases, an exclusive pedestrian phase,
and identical generated arrival streams for fixed/adaptive policies. Each row is
five simulated minutes x seeds 0, 1, 2, without warm-up.

| Scenario | Vehicle delay change | Pedestrian wait change | Road passages fixed → adaptive | Dropped arrivals fixed → adaptive |
|---|---:|---:|---:|---:|
| balanced | -13.1% | -26.1% | 274 → 283 | 63 → 47 |
| commute | -15.3% | -33.4% | 242 → 286 | 126 → 73 |
| pedestrian | -0.4% | -48.8% | 222 → 207 | 24 → 14 |
| turning | -14.1% | -31.7% | 283 → 284 | 20 → 15 |
| saturated | +5.2% | -0.5% | 376 → 361 | 527 → 521 |

Negative changes mean less accumulated delay/wait. Vehicle delay integrates
`max(0, 1-speed/desired_speed)` over active users; pedestrian waiting and residual
queues include unfinished users. **Dropped/diverted boundary arrivals are excluded
from delay**; inspect them and throughput alongside these percentages. Under heavy
saturation vehicle delay increases: this scheduler is a heuristic with a fairness/
throughput tradeoff, not a universally optimal policy. No accident reduction,
field calibration, intersection detector precision or board performance is claimed.

Compact results: [intersection_results.json](intersection_results.json). Reproduce
with `tools/intersection_eval.py --scenario <name> --minutes 5 --seeds 0 1 2`.
The full JSON/Markdown run reports were saved locally in ignored `runs/`.

Continuous checks: fifteen simulated minutes each for commute/saturated/pedestrian,
seed 17, adaptive: 321/380/243 road passages. All user footprints were sampled
once per second (900 samples per scenario); no overlap found, and at least five
road passages in every minute after the first. Full tests: 185 passed, 1 skipped.
Desktop and 390px/320px Chrome checks passed, including the paired comparison and
JSON download. See [INTERSECTION.md](INTERSECTION.md) for model boundaries.

Photoreal extension: five staged day-camera frames (overview/N/E/S/W) using the
existing verified L2 assets and YOLO11n 416 on the RTX 3060 Laptop GPU. Projection
errors were <1 px in every view; visible mask IDs 16/11/11/11/11 and raw NN
detections 7/11/5/2/5 (confidence >=0.15). Camera switching, raw/overlay selection,
mobile layouts and JSON downloads passed in Chrome without JS/HTTP errors. These
are execution checks, not calibrated accuracy results. The actual detector sees
only RGB. This initial diagnostic path was subsequently extended to four-camera
perception-driven twin and control (see below). Reproduce with `tools/intersection_render_check.py` and
`tools/intersection_smoke.py --photoreal`.
The original crosswalk L2 renderer/real detector also completed a three-frame
`driver_yields` smoke run after the extension; this is compatibility evidence,
not a replacement for its existing scenario validation.


### Four-camera perception reconstruction — 2026-10-11

The real-detector intersection mode now samples N/E/S/W RGB at a common physical
world timestamp, fuses projected NN detections and updates one metric tracker.
Its public twin, demands and observed passage/wait metrics use model tracks.
Signal clearance uses observed conflict-zone occupancy, with all red for stale
camera observations; there is no simulator-truth fallback. Physical drivers still
use collision/following logic as part of the synthetic reality being rendered.
The policy comparison above remains a **perfect-observation benchmark**, not a
measurement of this vision controller.

Chrome QA passed the separate camera/twin views, all four sensors, selecting N,
raw/boxes/visibility toggles, persistent main twin, pause/resume, policies, crossing
call, slow walker, reset, comparison/report downloads and 390px/320px layouts.
No JavaScript or HTTP errors were observed. Artifacts are in ignored
`runs/intersection-four-camera-qa/`. A live snapshot at 13.4 simulated seconds
contained 6 physical users and 4 reconstructed tracks, with 2 physical versus 1
observed road passage. This illustrates model misses rather than a measured
accuracy score. Per-camera localization and cross-camera identities are
approximate; safe real-world signal control is not established.

A regression reproduced an observed curb user incorrectly blocking clearance;
the conflict zone now excludes curb queues while including zebra users. Unit
coverage explicitly checks both, alongside cross-camera fusion, no truth leakage,
false positives, perceived demands, stale observations and identity/reset behavior.

Final full suite: **195 passed, 1 skipped**. A regression also covers the
configured freshness budget for slow cameras. The final Chrome run repeated all
checks without JS/HTTP errors; artifacts: `runs/intersection-four-camera-final-qa/`.
