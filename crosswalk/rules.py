"""The explicit light-signal rules - single source of truth for the code, the dashboard and docs/RULES.md.

Every lamp change made by the node carries the id of the rule that caused it and a plain-language "why" with the
live values (who, where, how fast, how many seconds). Thresholds come from the config, so what is displayed is
exactly what is executed.

    python -m crosswalk.rules            # print the rule table (markdown) with the default config
    python -m crosswalk.rules > docs/RULES.md
"""
from __future__ import annotations

# group: beacon = driver warning light at the zebra (works with or without a traffic signal)
#        signal = vision-actuated pedestrian traffic light (modes adaptive / fixed)
#        mcu    = executed by the STM32 independently of Linux
RULES = [
    {"id": "B0", "group": "beacon", "name": "Beacon off",
     "when": "no condition of B1/B2 holds (and the {hold:g} s hold time has expired)",
     "then": "amber beacon off",
     "it": "Nessuna condizione B1/B2 attiva (trascorsi {hold:g} s): lampeggiante spento."},
    {"id": "B1", "group": "beacon", "name": "Caution - people at the crossing",
     "when": "a pedestrian, cyclist or e-scooter is ON the crosswalk, or WAITING at / WALKING UP TO the curb, "
             "AND a vehicle is approaching with time-to-arrival < {tta:g} s",
     "then": "amber beacon slow blink + walking icon on the LED matrix, held {hold:g} s after the condition ends",
     "it": "Se un pedone/ciclista è sulle strisce, in attesa o in avvicinamento al marciapiede E un veicolo arriva entro "
           "{tta:g} s: lampeggiante giallo lento + icona pedone, mantenuto per {hold:g} s."},
    {"id": "B2", "group": "beacon", "name": "Danger - imminent conflict",
     "when": "a vehicle is on a collision course with a person on the carriageway: time-to-collision <= {ttc2:g} s "
             "AND the vehicle would need > {drac:g} m/s2 braking to stop (DRAC)",
     "then": "beacon turns RED, fast blink + buzzer + warning icon (overrides B1)",
     "it": "Se un veicolo è in rotta di collisione con una persona in carreggiata (TTC ≤ {ttc2:g} s e frenata "
           "necessaria > {drac:g} m/s²): lampeggiante ROSSO rapido + cicalino + icona di pericolo."},
    {"id": "S0", "group": "signal", "name": "Rest on vehicle green",
     "when": "nobody is waiting to cross",
     "then": "vehicles GREEN, pedestrians RED (no useless stops for traffic)",
     "it": "Nessuno in attesa: verde ai veicoli, rosso ai pedoni."},
    {"id": "S1", "group": "signal", "name": "Pedestrian call (by camera or button)",
     "when": "someone waits at a curb for >= {wait:g} s (or presses the button) AND vehicles have had green "
             "for >= {min_veh:g} s AND no vehicle is about to cross (< 3 s away) - or vehicle green reached {max_veh:g} s",
     "then": "vehicles YELLOW {yellow:g} s -> ALL RED {allred:g} s -> pedestrians GREEN",
     "it": "Persona in attesa ≥ {wait:g} s (o pulsante) e verde veicoli da ≥ {min_veh:g} s senza veicoli a meno di 3 s "
           "(o verde veicoli ≥ {max_veh:g} s): giallo {yellow:g} s, tutto rosso {allred:g} s, verde pedoni."},
    {"id": "S2", "group": "signal", "name": "Walk phase",
     "when": "pedestrian green has lasted >= {min_ped:g} s and nobody else is waiting - or it reached {max_ped:g} s",
     "then": "pedestrians FLASHING (clearance)",
     "it": "Verde pedoni per almeno {min_ped:g} s, prolungato finché arrivano altre persone (max {max_ped:g} s), "
           "poi lampeggiante di sgombero."},
    {"id": "S3", "group": "signal", "name": "Clearance + Green Man+ extension",
     "when": "clearance lasts L / {walk:g} m/s = {clear:.1f} s; if someone is still on the crosswalk, it is extended "
             "by their measured time to reach the curb (max +{ext:g} s)",
     "then": "pedestrians FLASHING until everyone is off the crosswalk, then ALL RED",
     "it": "Sgombero di {clear:.1f} s (L / {walk:g} m/s), prolungato di quanto serve a chi è ancora sulle strisce "
           "(max +{ext:g} s): nessuno resta in mezzo alla strada."},
    {"id": "S4", "group": "signal", "name": "Return to traffic",
     "when": "all red has lasted >= {allred:g} s AND the crosswalk is empty (or 6 s have passed)",
     "then": "vehicles GREEN, pedestrians RED",
     "it": "Tutto rosso ≥ {allred:g} s e strisce libere (o 6 s): verde ai veicoli."},
    {"id": "SF", "group": "signal", "name": "Fixed-time baseline",
     "when": "signal mode = fixed (used only to compare against the adaptive rules)",
     "then": "fixed cycle: vehicles green {fixed:g} s, yellow, all red, pedestrians green, clearance, all red",
     "it": "Modalità a tempo fisso (solo come confronto): ciclo fisso indipendente da chi c'è."},
    {"id": "F1", "group": "mcu", "name": "Fail-safe",
     "when": "the STM32 receives no heartbeat from the vision side for 2 s (crash, reboot, cable)",
     "then": "vehicle lamp FLASHING AMBER, pedestrian lamps off, '!' on the LED matrix - like a real controller fault",
     "it": "Se il microcontrollore non riceve segnali dalla parte di visione per 2 s: giallo lampeggiante, "
           "pedonali spente, '!' sulla matrice LED."},
]


def params(cfg) -> dict:
    s, g, sc = cfg["safety"], cfg["signal"], cfg["scene"]
    L = float(sc["crosswalk"]["length"])
    walk = float(g.get("design_walk_speed", 1.2))
    return {
        "tta": float(s.get("beacon_tta_s", 6.0)), "hold": float(s.get("warning_hold_s", 1.5)),
        "ttc2": float(s.get("ttc_levels_s", [1.0, 2.0, 3.0])[1]), "drac": float(s.get("drac_min", 3.0)),
        "wait": float(s.get("waiting_min_s", 0.8)), "min_veh": float(g["veh_min_green_s"]),
        "max_veh": float(g["veh_max_green_s"]), "yellow": float(g["veh_yellow_s"]), "allred": float(g["all_red_s"]),
        "min_ped": float(g["ped_min_green_s"]), "max_ped": float(g["ped_max_green_s"]), "walk": walk,
        "clear": float(g.get("ped_clearance_s") or L / walk), "ext": float(g.get("max_clearance_extension_s", 8.0)),
        "fixed": float(g.get("fixed_cycle_veh_green_s", 20.0)),
    }


def describe(cfg) -> list[dict]:
    """Rules with thresholds filled in from the config."""
    p = params(cfg)
    out = []
    for r in RULES:
        out.append({"id": r["id"], "group": r["group"], "name": r["name"], "when": r["when"].format(**p),
                    "then": r["then"].format(**p), "it": r["it"].format(**p)})
    return out


def markdown(cfg) -> str:
    lines = ["# OCCHIO - explicit light-signal rules", "",
             "Generated from `crosswalk/rules.py` with the thresholds of the running config "
             "(`python -m crosswalk.rules`). Every lamp change logged by the node carries the rule id and the live "
             "values that triggered it (dashboard \"Rules\" card, `signal` / `beacon` events).", "",
             "## Rules", "", "| id | rule | WHEN | THEN |", "|---|---|---|---|"]
    for r in describe(cfg):
        lines.append(f"| **{r['id']}** | {r['name']} | {r['when']} | {r['then']} |")
    lines += ["", "## Regole (italiano)", ""]
    for r in describe(cfg):
        lines.append(f"- **{r['id']} - {r['name']}**: {r['it']}")
    lines += ["", "## Definitions", "",
              "- **On the crosswalk**: ground position inside the painted zebra (+0.5 m tolerance along the road).",
              "- **Waiting**: in the curb area (2.5 m deep, zebra width + 1 m each side) and slower than 0.6 m/s for >= 0.8 s.",
              "- **Walking up to the curb (approaching)**: in the curb area or on the sidewalk within 8 m of the zebra, "
              "moving towards the zebra; time-to-arrival = distance / speed towards it.",
              "- **Approaching vehicle**: on the carriageway, within 40 m of the zebra, moving towards it; "
              "time-to-arrival = distance to the zebra edge / speed along the road.",
              "- **TTC / DRAC**: constant-velocity time-to-collision between the person (0.35 m disc) and the vehicle "
              "(oriented rectangle of its class size); DRAC = v^2 / 2d, the braking needed to stop before the person.",
              ""]
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    from .config import load_config

    print(markdown(load_config(sys.argv[1] if len(sys.argv) > 1 else None)))
