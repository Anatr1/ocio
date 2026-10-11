# World Model Parameters

These are literature-informed starting values, not a calibrated Turin population.
G4 remains unassessed: no site speed/gap/yield distribution or KS test is available.

| Model / parameter | Current default | Basis / limitation |
|---|---|---|
| Adult walking | mean 1.35 m/s, SD 0.2 | FHWA-informed typical adult magnitude; not a fitted population |
| Slow older/mobility-limited walking | 0.6-0.9 m/s | Handoff's slow-walker subset; not the mean for all older people |
| Social force | relaxation 0.5 s, strength 2, range 0.3 m | Helbing-style desired velocity and repulsion; simplified, with right-side passing/group attraction |
| IDM | a=1.6 m/s2, b=2.2 m/s2, T=1.2 s, gap=2 m | Standard IDM structure; emergency braking capped at 8 m/s2 |
| MOBIL-like lane changes | politeness 0.3, benefit 0.2 m/s2, safe brake 4 m/s2 | Simplified incentive/safety check, not the full old/new-follower model |
| Gap acceptance | logit; decisions every 0.5 s | Waiting-dependent acceptance; probabilities not site-fitted |
| Driver compliance/yield | scenario probabilities, reaction delay | Vehicle emergency braking still applies to stranded crossers under green |

Scenarios may deliberately override defaults (e.g. the 0.4 m/s S3 extension case).
Scripted stopped agents are abrupt stops; they are not a medical fall model.
Turning uses waypoints, not a general intersection-routing engine.

Physics substeps are <=0.05 s. Circular walkers/oriented vehicle footprints,
swept collision tests and last-safe-pose truncation prevent penetration. Vehicle
contact is logged as a collision and immobilises the participants (wrecks are
removed after `crash_clear_s` = 60 s, `crash_cleared`). Contacts between people,
cyclists and scooters are soft: they are pushed apart (`contact`, once per pair)
instead of freezing. Remaining overlaps are rewound locally (`physics_rewind`);
only a dense unsolvable case falls back to the global `physics_guard`.

## Continuous traffic (rate-spawned scenarios)

Rules added so that minutes of unscripted traffic neither freeze nor produce
crashes nobody caused. They are plausible heuristics, **not calibrated behaviour**.

| Behaviour | Rule |
|---|---|
| Waiting places | Arrivals claim a free place in up to 5 rows behind the kerb (sized to their footprint) instead of piling up on one point |
| Pavement | People walking to the kerb, waiting, or walking away never step or get pushed off the kerb sideways |
| Crowd | Waiting people hold their place against arrivals but step aside for people coming off the crossing |
| Lane check | Nobody walks into a standing vehicle. Cautious crossers (`caution_p`, default 0.95; `dangerous` 0.6) also wait at each lane for an approaching vehicle unless they can clear the lane with 1 s to spare (at least `lane_check_tta_s`), or the vehicle is visibly braking and able to stop at its line before them |
| Blocked zebra | A vehicle stopped across the path is walked around within 3 m of the zebra; after 30 s held in the road the crosser goes back |
| Zebra rule | Yielding drivers stop for people waiting at the zebra, or on it with the driver's lane still ahead of them; there is no duty to yield away from the zebra |
| Emergency braking | Every driver brakes for anyone on the carriageway in front of the bumper, using the oriented footprint (a cyclist's front wheel counts) |
| Arrivals | Random vehicles enter 30 m beyond the approach (still on the 60 m rendered road), so drivers react to a red lamp or a busy zebra and walkers see them coming; entry speed is limited by the queue ahead |
| Saturation | Arrivals that cannot be placed, or would queue more than 150 m upstream, are dropped and logged (`arrival_dropped`) |

Soak evidence (`tools/sim_soak.py`, 10 simulated minutes each, `count_test`,
`mixed`, `rush_hour`, `dangerous` x beacon/adaptive x seeds 0-2): no run's
passages collapse, no `physics_guard`, and no collision involves a cautious,
unhurried crosser. The few collisions left come from careless or hurried crossers
and non-yielding drivers, which is what `dangerous` is for. Unsignalised
`rush_hour` saturates (long vehicle queues behind drivers yielding to a steady
stream of pedestrians), which is expected behaviour and not a deadlock.
`tests/test_sim_continuous.py` keeps shorter versions of these runs as regressions.
`near_miss_late_braking` is currently the **collision** variant (expected collision=1),
not evidence of a full noncolliding TTC 0.5-2 s sweep.

Pure-World stress benchmark after broad-phase pruning: 100 simulated seconds in
4.64 wall seconds (~21.5x), peak 82 agents, board geometry, rush_hour seed 0.
The >=50x crowded headless target is not yet met.

Definitions: independent interpolated counting-line GT is tested against the
production Counter. Perfect tracks reuse production TTC/DRAC/PET definitions
and SafetyMonitor; that establishes consistency, **not independent proof that
the safety implementation is correct**. Rule GT additionally evaluates raw
World conditions before production debounce/hold. F1 requires the real MCU.

Primary references: [IDM](https://traffic-simulation.de/info/info_IDM.html),
[MOBIL](https://mtreiber.de/publications/MOBIL.pdf),
[Helbing and Molnar social-force model](https://journals.aps.org/pre/abstract/10.1103/PhysRevE.51.4282),
[FHWA aging-road-user handbook](https://highways.dot.gov/safety/other/older-road-user/handbook-designing-roadways-aging-population/chapter-7-intersections).
