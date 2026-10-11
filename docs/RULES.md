# OCCHIO - explicit light-signal rules

Generated from `crosswalk/rules.py` with the thresholds of the running config (`python -m crosswalk.rules`). Every lamp change logged by the node carries the rule id and the live values that triggered it (dashboard "Rules" card, `signal` / `beacon` events).

## Rules

| id | rule | WHEN | THEN |
|---|---|---|---|
| **B0** | Beacon off | no condition of B1/B2 holds (and the 1.5 s hold time has expired) | amber beacon off |
| **B1** | Caution - people at the crossing | a pedestrian, cyclist or e-scooter is ON the crosswalk, or WAITING at / WALKING UP TO the curb, AND a vehicle is approaching with time-to-arrival < 6 s | amber beacon slow blink + walking icon on the LED matrix, held 1.5 s after the condition ends |
| **B2** | Danger - imminent conflict | a vehicle is on a collision course with a person on the carriageway: time-to-collision <= 2 s AND the vehicle would need > 3 m/s2 braking to stop (DRAC) | beacon turns RED, fast blink + buzzer + warning icon (overrides B1) |
| **S0** | Rest on vehicle green | nobody is waiting to cross | vehicles GREEN, pedestrians RED (no useless stops for traffic) |
| **S1** | Pedestrian call (by camera or button) | someone waits at a curb for >= 0.8 s (or presses the button) AND vehicles have had green for >= 8 s AND no vehicle is about to cross (< 3 s away) - or vehicle green reached 40 s | vehicles YELLOW 3 s -> ALL RED 1.5 s -> pedestrians GREEN |
| **S2** | Walk phase | pedestrian green has lasted >= 5 s and nobody else is waiting - or it reached 20 s | pedestrians FLASHING (clearance) |
| **S3** | Clearance + Green Man+ extension | clearance lasts L / 1.2 m/s = 6.7 s; if someone is still on the crosswalk, it is extended by their measured time to reach the curb (max +8 s) | pedestrians FLASHING until everyone is off the crosswalk, then ALL RED |
| **S4** | Return to traffic | all red has lasted >= 1.5 s AND the crosswalk is empty (or 6 s have passed) | vehicles GREEN, pedestrians RED |
| **SF** | Fixed-time baseline | signal mode = fixed (used only to compare against the adaptive rules) | fixed cycle: vehicles green 20 s, yellow, all red, pedestrians green, clearance, all red |
| **F1** | Fail-safe | the STM32 receives no heartbeat from the vision side for 2 s (crash, reboot, cable) | vehicle lamp FLASHING AMBER, pedestrian lamps off, '!' on the LED matrix - like a real controller fault |

## Regole (italiano)

- **B0 - Beacon off**: Nessuna condizione B1/B2 attiva (trascorsi 1.5 s): lampeggiante spento.
- **B1 - Caution - people at the crossing**: Se un pedone/ciclista è sulle strisce, in attesa o in avvicinamento al marciapiede E un veicolo arriva entro 6 s: lampeggiante giallo lento + icona pedone, mantenuto per 1.5 s.
- **B2 - Danger - imminent conflict**: Se un veicolo è in rotta di collisione con una persona in carreggiata (TTC ≤ 2 s e frenata necessaria > 3 m/s²): lampeggiante ROSSO rapido + cicalino + icona di pericolo.
- **S0 - Rest on vehicle green**: Nessuno in attesa: verde ai veicoli, rosso ai pedoni.
- **S1 - Pedestrian call (by camera or button)**: Persona in attesa ≥ 0.8 s (o pulsante) e verde veicoli da ≥ 8 s senza veicoli a meno di 3 s (o verde veicoli ≥ 40 s): giallo 3 s, tutto rosso 1.5 s, verde pedoni.
- **S2 - Walk phase**: Verde pedoni per almeno 5 s, prolungato finché arrivano altre persone (max 20 s), poi lampeggiante di sgombero.
- **S3 - Clearance + Green Man+ extension**: Sgombero di 6.7 s (L / 1.2 m/s), prolungato di quanto serve a chi è ancora sulle strisce (max +8 s): nessuno resta in mezzo alla strada.
- **S4 - Return to traffic**: Tutto rosso ≥ 1.5 s e strisce libere (o 6 s): verde ai veicoli.
- **SF - Fixed-time baseline**: Modalità a tempo fisso (solo come confronto): ciclo fisso indipendente da chi c'è.
- **F1 - Fail-safe**: Se il microcontrollore non riceve segnali dalla parte di visione per 2 s: giallo lampeggiante, pedonali spente, '!' sulla matrice LED.

## Definitions

- **On the crosswalk**: ground position inside the painted zebra (+0.5 m tolerance along the road).
- **Waiting**: in the curb area (2.5 m deep, zebra width + 1 m each side) and slower than 0.6 m/s for >= 0.8 s.
- **Walking up to the curb (approaching)**: in the curb area or on the sidewalk within 8 m of the zebra, moving towards the zebra; time-to-arrival = distance / speed towards it.
- **Approaching vehicle**: on the carriageway, within 40 m of the zebra, moving towards it; time-to-arrival = distance to the zebra edge / speed along the road.
- **TTC / DRAC**: constant-velocity time-to-collision between the person (0.35 m disc) and the vehicle (oriented rectangle of its class size); DRAC = v^2 / 2d, the braking needed to stop before the person.

