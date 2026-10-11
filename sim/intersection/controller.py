"""Protected movement phases with a demand scheduler and independent clearance gate."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .geometry import ARMS


@dataclass(frozen=True)
class Phase:
    id: str
    label: str
    movements: tuple
    pedestrian: bool = False


PHASES = (
    Phase("NS", "North / south · straight & right", tuple(f"{a}_{t}" for a in ("N", "S") for t in ("straight", "right"))),
    Phase("NS_LEFT", "North / south · protected left", ("N_left", "S_left")),
    Phase("EW", "East / west · straight & right", tuple(f"{a}_{t}" for a in ("E", "W") for t in ("straight", "right"))),
    Phase("EW_LEFT", "East / west · protected left", ("E_left", "W_left")),
    Phase("PED", "All four pedestrian crossings", (), True),
)
BY_ID = {p.id: p for p in PHASES}
# Legal concurrent signal groups. Shared entry-lane routes can diverge under one green.
COMPATIBLE = {frozenset((a, b)) for p in PHASES for a in p.movements for b in p.movements}


class IntersectionController:
    def __init__(self, policy="adaptive", min_green=12., max_green=35., fixed_green=18., max_wait=70.):
        if policy not in ("fixed", "adaptive"):
            raise ValueError("policy must be fixed or adaptive")
        if not 0 < min_green <= max_green or fixed_green <= 0 or max_wait <= 0:
            raise ValueError("invalid phase timing")
        self.policy = policy
        self.min_green, self.max_green = min_green, max_green
        self.fixed_green, self.max_wait = fixed_green, max_wait
        self.phase = PHASES[0]
        self.state = "green"
        self.since = 0.
        self.t = 0.
        self.next_phase = None
        self.calls = set()
        self.history = deque(maxlen=30)
        self.reason = "Initial north / south phase"
        self.scores = {}
        self.phase_changes = 0
        self.clearance_holds = 0

    def request(self, crossing):
        if crossing not in ARMS:
            raise ValueError("unknown crossing")
        if self.pedestrian_state(crossing) != "green":
            self.calls.add(crossing)

    def set_policy(self, policy):
        if policy not in ("fixed", "adaptive"):
            raise ValueError("unknown policy")
        self.policy = policy

    def allows(self, movement):
        return self.state == "green" and movement in self.phase.movements

    def pedestrian_state(self, crossing):
        if crossing not in ARMS:
            raise ValueError("unknown crossing")
        if not self.phase.pedestrian:
            return "red"
        return "green" if self.state == "green" else "flash" if self.state == "clearance" else "red"

    def lamp(self, movement):
        if movement not in self.phase.movements:
            return "red"
        return "green" if self.state == "green" else "yellow" if self.state == "yellow" else "red"

    def _transition(self, state, t, reason):
        self.state, self.since, self.reason = state, t, reason
        self.history.appendleft({"t": round(t, 2), "phase": self.phase.id, "state": state, "reason": reason})

    def _activate(self, phase, t):
        self.phase, self.next_phase = phase, None
        if phase.pedestrian:
            self.calls.clear()
        self.phase_changes += 1
        self._transition("green", t, f"Serve {phase.label}")

    def update(self, t, demands, pedestrians, occupied=False):
        self.t = t
        elapsed = t - self.since
        self.scores = {}
        ages = {}
        for phase in PHASES:
            rows = list(pedestrians.values()) if phase.pedestrian else [demands.get(m, {}) for m in phase.movements]
            count = sum(r.get("count", 0) for r in rows)
            age = max((r.get("oldest_s", 0.) for r in rows), default=0.)
            if phase.pedestrian and self.calls:
                count += len(self.calls)
            ages[phase.id] = age
            self.scores[phase.id] = (count * (1.3 if phase.pedestrian else 1.) + age * .10) if count else 0.
        if self.state in ("yellow", "clearance"):
            if elapsed >= (4. if self.state == "clearance" else 3.):
                self._transition("all_red", t, "Clear committed road users before conflicting green")
            return
        if self.state == "all_red":
            if elapsed >= 2. and not occupied:
                target = self.next_phase
                if self.policy == "adaptive":
                    candidates = [p for p in PHASES if p != self.phase and self.scores[p.id] > 0]
                    if candidates:
                        target = max(candidates, key=lambda p: (ages[p.id] >= self.max_wait,
                                                                ages[p.id] if ages[p.id] >= self.max_wait else self.scores[p.id],
                                                                -PHASES.index(p)))
                self._activate(target or self.phase, t)
            elif elapsed >= 2.:
                self.clearance_holds += 1
                self.reason = "Clearance held: junction or crossing still occupied"
            return
        duration = (10. if self.phase.pedestrian else self.fixed_green) if self.policy == "fixed" else (
            8. if self.phase.pedestrian else self.max_green)
        if self.policy == "fixed":
            if elapsed < duration:
                return
            target = PHASES[(PHASES.index(self.phase) + 1) % len(PHASES)]
            why = "Fixed phase duration elapsed"
        else:
            candidates = [p for p in PHASES if p != self.phase and self.scores[p.id] > 0]
            if not candidates or elapsed < (6. if self.phase.pedestrian else self.min_green):
                return
            target = max(candidates, key=lambda p: (ages[p.id] >= self.max_wait,
                                                    ages[p.id] if ages[p.id] >= self.max_wait else self.scores[p.id],
                                                    -PHASES.index(p)))
            urgent = ages[target.id] >= self.max_wait
            if not urgent and elapsed < duration and self.scores[self.phase.id] > 0:
                # Switching has a real yellow/all-red/clearance cost. Do not
                # oscillate for small queue differences; batch current demand.
                if not self.phase.pedestrian and (elapsed < 18. or
                        self.scores[target.id] <= self.scores[self.phase.id] * 2.5 + 2):
                    return
            why = "Oldest demand priority" if urgent else "Queue / waiting pressure" if elapsed < duration else "Maximum green reached"
        self.next_phase = target
        self._transition("clearance" if self.phase.pedestrian else "yellow", t, why + f" → {target.label}")

    def payload(self):
        return {"policy": self.policy, "phase": self.phase.id, "label": self.phase.label, "state": self.state,
                "elapsed_s": round(self.t - self.since, 1), "reason": self.reason,
                "next": self.next_phase.id if self.next_phase else None,
                "vehicles": {f"{a}_{turn}": self.lamp(f"{a}_{turn}") for a in ARMS for turn in ("straight", "left", "right")},
                "pedestrians": {a: self.pedestrian_state(a) for a in ARMS},
                "calls": sorted(self.calls), "scores": self.scores, "history": list(self.history),
                "phase_changes": self.phase_changes}
