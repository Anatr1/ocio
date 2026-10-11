"""Vision-actuated pedestrian signal controller.

Modes
-----
* ``beacon``   - unsignalised zebra: no signal heads, only the active warning beacon (driven by SafetyMonitor)
* ``fixed``    - classic fixed-time cycle (baseline for comparisons)
* ``adaptive`` - demand-actuated by the camera:
    - pedestrian phase only when someone is actually waiting (no button needed)
    - pedestrian green extended while people keep arriving (up to a max)
    - clearance extended while a slow pedestrian is still on the crosswalk ("Green Man+" without a card:
      Singapore's scheme needs elderly users to tap a card - we see them)
    - vehicles get the green back as soon as the crosswalk is empty

The MCU drives the physical lamps and independently falls back to flashing amber if the Linux side stops
sending heartbeats (fail-safe, like real traffic controllers).
"""
from __future__ import annotations

from collections import deque

VEH_GREEN, VEH_YELLOW, ALL_RED_1, PED_GREEN, PED_CLEAR, ALL_RED_2 = (
    "veh_green", "veh_yellow", "all_red_1", "ped_green", "ped_clear", "all_red_2")

# (vehicle lamp, pedestrian lamp) per state
LAMPS = {
    VEH_GREEN: ("green", "red"),
    VEH_YELLOW: ("yellow", "red"),
    ALL_RED_1: ("red", "red"),
    PED_GREEN: ("red", "green"),
    PED_CLEAR: ("red", "flash"),
    ALL_RED_2: ("red", "red"),
}


class SignalController:
    def __init__(self, cfg, scene, emit):
        self.cfg = cfg
        self.mode = cfg.get("mode", "adaptive") if cfg.get("enabled", True) else "beacon"
        self.scene = scene
        self.emit = emit
        self.state = VEH_GREEN
        self.t_state = None
        self.t = 0.0
        self.demand_since = None
        self.manual_request = False
        self.extension_used = 0.0
        self.waits = deque(maxlen=500)
        self.cycles = 0
        self.extensions = 0
        L = scene.L if scene is not None else 8.0
        self.clearance = float(cfg.get("ped_clearance_s") or (L / float(cfg.get("design_walk_speed", 1.2))))
        self.rule = {"id": "S0" if self.mode == "adaptive" else ("SF" if self.mode == "fixed" else None),
                     "why": "nobody waiting to cross", "t": 0.0}
        self.history = deque(maxlen=20)   # last rule firings (id, why, t, lamps)

    # ------------------------------------------------------------------ public API
    def veh_state(self):
        return "off" if self.mode == "beacon" else LAMPS[self.state][0]

    def ped_state(self):
        return "off" if self.mode == "beacon" else LAMPS[self.state][1]

    def time_in_state(self):
        return 0.0 if self.t_state is None else self.t - self.t_state

    def request(self):
        """Manual pedestrian call (physical button / dashboard)."""
        self.manual_request = True

    def _go(self, st, t, rule="", why=""):
        prev = self.state
        self.state = st
        self.t_state = t
        self.rule = {"id": rule, "why": why, "t": round(t, 2)}
        self.history.appendleft({"id": rule, "why": why, "t": round(t, 2), "veh": LAMPS[st][0], "ped": LAMPS[st][1]})
        if st == PED_GREEN:
            self.cycles += 1
            if self.demand_since is not None:
                self.waits.append(t - self.demand_since)
            self.demand_since = None
            self.manual_request = False
            self.extension_used = 0.0
        self.emit({"type": "signal", "t": t, "from": prev, "to": st, "veh": LAMPS[st][0], "ped": LAMPS[st][1],
                   "rule": rule, "why": why, "log_only": True})

    def update(self, t, waiting=0, crossing=0, time_to_clear=0.0, vehicle_close=False):
        self.t = t
        if self.t_state is None:
            self.t_state = t
        if self.mode == "beacon":
            return
        c = self.cfg
        dt_state = t - self.t_state
        demand = waiting > 0 or self.manual_request
        if demand and self.demand_since is None and self.state in (VEH_GREEN, VEH_YELLOW, ALL_RED_1):
            self.demand_since = t

        if self.mode == "fixed":
            seq = [(VEH_GREEN, float(c.get("fixed_cycle_veh_green_s", 20.0))), (VEH_YELLOW, float(c["veh_yellow_s"])),
                   (ALL_RED_1, float(c["all_red_s"])), (PED_GREEN, float(c["ped_min_green_s"]) + 3.0),
                   (PED_CLEAR, self.clearance), (ALL_RED_2, float(c["all_red_s"]))]
            durations = dict(seq)
            order = [s for s, _ in seq]
            if dt_state >= durations[self.state]:
                nxt = order[(order.index(self.state) + 1) % len(order)]
                self._go(nxt, t, "SF", f"fixed cycle: {self.state} lasted {durations[self.state]:.0f} s")
            return

        # ---------------- adaptive
        if self.state == VEH_GREEN:
            if not demand and self.rule.get("id") != "S0":
                self.rule = {"id": "S0", "why": "nobody waiting to cross", "t": round(t, 2)}
            if demand:
                min_ok = dt_state >= float(c["veh_min_green_s"])
                # small gap-seeking: hold a little if a vehicle is about to cross, up to max green
                if min_ok and (not vehicle_close or dt_state >= float(c["veh_max_green_s"])):
                    who = f"{waiting} waiting at the curb" if waiting else "push button"
                    extra = "max vehicle green reached" if vehicle_close else "no vehicle about to cross"
                    self._go(VEH_YELLOW, t, "S1", f"{who} for {t - self.demand_since:.1f} s; vehicles green "
                                                  f"for {dt_state:.0f} s; {extra}")
                elif self.rule.get("id") != "S1":
                    self.rule = {"id": "S1", "t": round(t, 2),
                                 "why": "call registered - " + ("waiting for a gap in traffic" if min_ok
                                                                else f"vehicle minimum green {c['veh_min_green_s']:g} s")}
        elif self.state == VEH_YELLOW:
            if dt_state >= float(c["veh_yellow_s"]):
                self._go(ALL_RED_1, t, "S1", f"yellow {c['veh_yellow_s']:g} s elapsed")
        elif self.state == ALL_RED_1:
            if dt_state >= float(c["all_red_s"]):
                self._go(PED_GREEN, t, "S1", f"all-red {c['all_red_s']:g} s elapsed - walk")
        elif self.state == PED_GREEN:
            min_g, max_g = float(c["ped_min_green_s"]), float(c["ped_max_green_s"])
            if dt_state >= max_g or (dt_state >= min_g and waiting == 0):
                why = (f"max walk {max_g:g} s reached" if dt_state >= max_g
                       else f"walk {dt_state:.0f} s, nobody else waiting")
                self._go(PED_CLEAR, t, "S2", why)
        elif self.state == PED_CLEAR:
            need = self.clearance
            if crossing > 0 and dt_state >= self.clearance - 0.5:
                # Green Man+: somebody is still on the crosswalk -> extend clearance
                ext_max = float(c.get("max_clearance_extension_s", 8.0))
                want = min(ext_max, max(0.0, dt_state + time_to_clear - self.clearance))
                if want > self.extension_used + 0.05:
                    if self.extension_used == 0.0:
                        self.extensions += 1
                        self.emit({"type": "ped_extension", "t": t, "seconds": round(want, 1),
                                   "crossing": crossing, "replay": True})
                    self.extension_used = want
                    self.rule = {"id": "S3", "t": round(t, 2),
                                 "why": f"{crossing} still on the crosswalk, needs {time_to_clear:.1f} s "
                                        f"to the curb -> clearance +{want:.1f} s"}
                    if not self.history or self.history[0].get("id") != "S3":
                        self.history.appendleft({**self.rule, "veh": "red", "ped": "flash"})
                need = self.clearance + self.extension_used
            if dt_state >= need:
                why = f"clearance {self.clearance:.1f} s" + (f" + {self.extension_used:.1f} s Green Man+" if self.extension_used else "") + " elapsed"
                self._go(ALL_RED_2, t, "S3", why)
        elif self.state == ALL_RED_2:
            if dt_state >= float(c["all_red_s"]) and (crossing == 0 or dt_state >= 6.0):
                self._go(VEH_GREEN, t, "S4", "crosswalk empty" if crossing == 0 else "6 s all-red limit")

    def to_dict(self):
        w = list(self.waits)
        return {
            "mode": self.mode,
            "state": self.state,
            "veh": self.veh_state(),
            "ped": self.ped_state(),
            "t_in_state": round(self.time_in_state(), 1),
            "demand": self.demand_since is not None,
            "extension_s": round(self.extension_used, 1),
            "cycles": self.cycles,
            "extensions": self.extensions,
            "mean_ped_wait_s": None if not w else round(sum(w) / len(w), 1),
            "rule": self.rule,
            "history": list(self.history)[:8],
        }
