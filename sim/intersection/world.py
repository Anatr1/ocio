"""Route-based, deterministic intersection traffic with measured ground-truth metrics.

This is the physical synthetic world, with exact states for rendering/scoring.
Its controller accepts either the default perfect observations or an injected
perception provider. Driver following/admission belongs to physical behaviour.
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
import hashlib
import math
import random

from sim.behaviour import idm, overlaps
from sim.world import DIMS

from .controller import COMPATIBLE, IntersectionController
from .geometry import ARMS, FORWARD, IntersectionGeometry

SCENARIOS = {
    "balanced": {"vehicles": (420, 420, 420, 420), "pedestrians": (45, 45, 45, 45), "left": .20, "right": .20},
    "commute": {"vehicles": (760, 220, 650, 180), "pedestrians": (25, 60, 35, 70), "left": .18, "right": .18},
    "pedestrian": {"vehicles": (300, 280, 300, 280), "pedestrians": (150, 180, 150, 180), "left": .15, "right": .20},
    "turning": {"vehicles": (380, 380, 380, 380), "pedestrians": (40, 40, 40, 40), "left": .45, "right": .35},
    "saturated": {"vehicles": (1200, 900, 1200, 900), "pedestrians": (80, 80, 80, 80), "left": .25, "right": .20},
    "empty": {"vehicles": (0, 0, 0, 0), "pedestrians": (0, 0, 0, 0), "left": .2, "right": .2},
}


@dataclass
class User:
    id: int
    cls: str
    arrived: float
    desired: float
    route_id: str | None = None
    crossing: str | None = None
    direction: int = 1
    offset: float = 0.
    s: float = 0.
    speed: float = 0.
    x: float = 0.
    y: float = 0.
    heading: float = 0.
    admitted: bool = False
    wait: float = 0.
    delay: float = 0.
    alive: bool = True
    counted: set = field(default_factory=set)
    parked_until: float = 0.
    entered_at: float | None = None

    @property
    def kind(self):
        return "vehicle" if self.route_id else "bicycle" if self.cls == "bicycle" else "pedestrian"

    @property
    def dims(self):
        return DIMS[self.cls]

    @property
    def pos(self):
        return self.x, self.y

    @property
    def vel(self):
        return self.speed * math.cos(self.heading), self.speed * math.sin(self.heading)


class IntersectionWorld:
    dt = .1

    def __init__(self, scenario="balanced", policy="adaptive", seed=0, geometry=None):
        if scenario not in SCENARIOS:
            raise ValueError("unknown intersection scenario")
        self.scenario, self.seed = scenario, seed
        self.geometry = geometry or IntersectionGeometry()
        self.controller = IntersectionController(policy)
        self.t = 0.
        self.users = []
        self.next_id = 1
        self.events = deque(maxlen=150)
        self.metrics = Counter()
        self.movements = Counter()
        self.crossings = {a: Counter() for a in ARMS}
        self.wait_samples = {"vehicle": deque(maxlen=10000), "pedestrian": deque(maxlen=10000)}
        self.wait_sum = Counter()
        self.wait_n = Counter()
        self.delay_sum = Counter()
        self.delay_n = Counter()
        self.speed_samples = deque(maxlen=10000)
        self.crossing_times = {arm: deque(maxlen=2000) for arm in ARMS}
        self.active_conflicts = set()
        self.conflict_notices = deque(maxlen=20)
        self.rngs, self.arrivals = {}, {}
        self.last_demand = {}
        self.observation_provider = None
        self.max_wait = Counter()
        spec = SCENARIOS[scenario]
        for kind, rates in (("vehicle", spec["vehicles"]), ("pedestrian", spec["pedestrians"])):
            for arm, rate in zip(ARMS, rates):
                key = (kind, arm)
                digest = hashlib.sha256(f"{seed}:{kind}:{arm}".encode()).digest()
                self.rngs[key] = random.Random(int.from_bytes(digest[:8], "big"))
                self.arrivals[key] = self.rngs[key].expovariate(rate / 3600) if rate else math.inf
        self.arrival_log = deque(maxlen=5000)

    def _event(self, typ, **fields):
        self.events.append({"type": typ, "t": round(self.t, 2), **fields})

    def spawn_vehicle(self, arm="N", turn="straight", speed=11., cls="car", s=0., parked_until=0.):
        route_id = f"{arm}_{turn}"
        if route_id not in self.geometry.routes or cls not in ("car", "bicycle") or speed <= 0:
            raise ValueError("invalid vehicle route/class/speed")
        user = User(self.next_id, cls, self.t, speed, route_id=route_id, s=s, parked_until=parked_until)
        self.next_id += 1
        self._locate(user)
        if any(overlaps(user, other, .3) for other in self.users):
            self.metrics["dropped_vehicles"] += 1
            self._event("arrival_dropped", arm=arm, reason="approach full")
            return None
        self.users.append(user)
        gap, leader_speed = self._leader(user)
        user.speed = min(speed, leader_speed + math.sqrt(4.4 * max(0., gap - 2.))) if math.isfinite(gap) else speed
        self.metrics["admitted_arrivals_vehicle"] += 1
        return user

    def spawn_pedestrian(self, crossing="N", direction=1, speed=1.3, cls="pedestrian", offset=0.):
        if crossing not in ARMS or direction not in (-1, 1) or not .3 <= speed <= 5 or cls not in ("pedestrian", "bicycle"):
            raise ValueError("invalid pedestrian crossing/class/speed")
        # Two narrow walking lanes in each direction. Separate opposing flows
        # and queue longitudinally using actual walker/rider footprints.
        waiting = [u for u in self.users if u.crossing == crossing and u.direction == direction and not u.admitted]
        slot = len(waiting)
        if slot >= 50:
            self.metrics["dropped_pedestrians"] += 1
            return None
        lane_offset = offset + direction * .75 + ((slot % 2) - .5) * .6
        peers = [u for u in self.users if u.crossing == crossing and u.direction == direction
                 and abs(u.offset-lane_offset) < .25 and u.s < 2.]
        start_s = min([0., *[u.s-(u.dims[0]+DIMS[cls][0])/2-.2 for u in peers]])
        user = User(self.next_id, cls, self.t, speed, crossing=crossing, direction=direction,
                    offset=lane_offset, s=start_s)
        self.next_id += 1
        self._locate(user)
        self.users.append(user)
        self.metrics["admitted_arrivals_pedestrian"] += 1
        return user

    def _locate(self, user):
        if user.route_id:
            user.x, user.y, user.heading = self.geometry.routes[user.route_id].pose(user.s)
        else:
            a, b = self.geometry.crossing(user.crossing, user.direction, user.offset)
            length = math.dist(a, b)
            fraction = user.s / length
            user.x, user.y = a[0] + (b[0] - a[0]) * fraction, a[1] + (b[1] - a[1]) * fraction
            user.heading = math.atan2(b[1] - a[1], b[0] - a[0])

    def _arrive(self):
        spec = SCENARIOS[self.scenario]
        for key, next_t in list(self.arrivals.items()):
            kind, arm = key
            rate = spec["vehicles" if kind == "vehicle" else "pedestrians"][ARMS.index(arm)]
            rng = self.rngs[key]
            while self.t + 1e-8 >= next_t:
                if kind == "vehicle":
                    draw = rng.random()
                    turn = "left" if draw < spec["left"] else "right" if draw < spec["left"] + spec["right"] else "straight"
                    speed = rng.uniform(9, 12.5)
                    # Riding bicycles use the same protected road movements, at lower speed.
                    cls = "bicycle" if rng.random() < .04 else "car"
                    if cls == "bicycle":
                        speed = rng.uniform(4, 6)
                    self.spawn_vehicle(arm, turn, speed, cls)
                    detail = (turn, round(speed, 5), cls)
                else:
                    direction, speed = rng.choice((-1, 1)), rng.uniform(.8, 1.6)
                    cls = "bicycle" if rng.random() < .06 else "pedestrian"
                    if cls == "bicycle":
                        speed = rng.uniform(2.5, 3.5)
                    self.spawn_pedestrian(arm, direction, speed, cls)
                    detail = (direction, round(speed, 5), cls)
                self.metrics[f"requested_arrivals_{kind}"] += 1
                self.arrival_log.append((round(next_t, 5), key, detail))
                next_t += rng.expovariate(rate / 3600)
            self.arrivals[key] = next_t

    def demands(self):
        vehicles = {r: {"count": 0, "oldest_s": 0., "queued": 0} for r in self.geometry.routes}
        pedestrians = {a: {"count": 0, "oldest_s": 0.} for a in ARMS}
        for user in self.users:
            if user.admitted:
                continue
            if user.route_id:
                route = self.geometry.routes[user.route_id]
                if user.s < route.stop_s - 25:
                    continue
                row = vehicles[user.route_id]
                row["queued"] += int(user.speed < 1.)
            else:
                row = pedestrians[user.crossing]
            row["count"] += 1
            row["oldest_s"] = max(row["oldest_s"], user.wait)
        return vehicles, pedestrians

    def occupied(self):
        for user in self.users:
            if not user.admitted:
                continue
            if user.route_id:
                if user.s < self.geometry.routes[user.route_id].clear_s:
                    return True
            elif user.s < 2 * (self.geometry.half_road + 1.5):
                return True
        return False

    def _exit_available(self, user):
        route = self.geometry.routes[user.route_id]
        for other in self.users:
            if other is user or not other.route_id:
                continue
            o = self.geometry.routes[other.route_id]
            if o.destination == route.destination and o.lane == route.lane and o.exit_s <= other.s < o.clear_s + 5:
                if other.speed < 1:
                    return False
        return True

    def _can_enter(self, user):
        if not self.controller.allows(user.route_id) or not self._exit_available(user):
            return False
        for other in self.users:
            if other is user or not other.admitted:
                continue
            if other.crossing:
                return False
            o = self.geometry.routes[other.route_id]
            if other.s < o.clear_s and frozenset((user.route_id, other.route_id)) not in COMPATIBLE:
                return False
        return True

    def _leader(self, user):
        route = self.geometry.routes[user.route_id]
        nearest = (math.inf, 0.)
        for other in self.users:
            if other is user or not other.route_id:
                continue
            o = self.geometry.routes[other.route_id]
            distance = None
            if route.id == o.id:
                distance = other.s - user.s
            elif route.origin == o.origin and route.lane == o.lane and user.s <= route.entry_s and other.s <= o.entry_s + 2:
                distance = other.s - user.s
            elif route.destination == o.destination and route.lane == o.lane and user.s >= route.exit_s and other.s >= o.exit_s:
                distance = (other.s - o.exit_s) - (user.s - route.exit_s)
            if distance is not None and distance > 0:
                gap = distance - (user.dims[0] + other.dims[0]) / 2
                if gap < nearest[0]:
                    nearest = gap, other.speed
        return nearest

    def _vehicle_step(self, user, dt):
        route = self.geometry.routes[user.route_id]
        gap, lead_speed = self._leader(user)
        stop_center = route.stop_s - user.dims[0] / 2
        gate = user.admitted or self._can_enter(user)
        if not gate:
            stop_gap = max(0., stop_center - user.s)
            if stop_gap < gap:
                gap, lead_speed = stop_gap, 0.
        desired = min(user.desired, 4. if route.turn == "right" else 5.5) if route.entry_s - 8 < user.s < route.exit_s + 2 and route.turn != "straight" else user.desired
        acceleration = max(-8., min(1.6, idm(user.speed, desired, gap, lead_speed)))
        if self.t < user.parked_until:
            speed = 0.
        else:
            speed = max(0., min(desired, user.speed + acceleration * dt))
        advance = speed * dt
        if math.isfinite(gap):
            advance = min(advance, max(0., gap - .15))
        if not gate:
            advance = min(advance, max(0., stop_center - user.s))
        previous = user.s
        user.s += advance
        self._locate(user)
        # Footprint admission check handles curved followers/merges, where scalar gaps alone are insufficient.
        if any(overlaps(user, o, .05) for o in self.users if o is not user and o.route_id):
            user.s = previous
            advance = 0.
            self._locate(user)
            self.metrics["geometry_holds"] += 1
        user.speed = advance / dt
        if not user.admitted and gate and user.s >= stop_center - .1:
            user.admitted = True
            user.entered_at = self.t
            self._event("vehicle_enter", track=user.id, movement=route.id)
        if not user.admitted and user.speed < 1:
            user.wait += dt
        if "complete" not in user.counted:
            user.delay += max(0., 1 - user.speed / user.desired) * dt
            self.metrics["vehicle_delay_s"] += max(0., 1 - user.speed / user.desired) * dt
            self.metrics["vehicle_stopped_s"] += dt if user.speed < .5 else 0.
        for arm, crossing_s in ((route.origin, self.geometry.approach - self.geometry.crossing_radius),
                                 (route.destination, route.exit_s + self.geometry.crossing_radius - self.geometry.half_road)):
            key = "crossing:" + arm
            if previous < crossing_s <= user.s and key not in user.counted:
                user.counted.add(key)
                self.crossings[arm][user.kind if user.cls != "bicycle" else "bicycle"] += 1
        if user.s >= route.clear_s and "complete" not in user.counted:
            user.counted.add("complete")
            self.metrics["vehicles_completed"] += 1
            self.metrics["road_bicycles_completed"] += int(user.cls == "bicycle")
            self.movements[route.id] += 1
            if user.cls == "car":
                self.speed_samples.append(user.speed * 3.6)
            self._complete(user, "vehicle")
            self._event("passage", track=user.id, movement=route.id, kind="bicycle" if user.cls == "bicycle" else "vehicle", wait_s=round(user.wait, 1))
        if user.s >= route.length:
            user.alive = False

    def _complete(self, user, kind):
        self.wait_samples[kind].append(user.wait)
        self.wait_sum[kind] += user.wait
        self.wait_n[kind] += 1
        self.delay_sum[kind] += user.delay
        self.delay_n[kind] += 1
        self.max_wait[kind] = max(self.max_wait[kind], user.wait)

    def _pedestrian_step(self, user, dt):
        if not user.admitted:
            if self.controller.pedestrian_state(user.crossing) != "green":
                user.wait += dt
                user.delay += dt
                self.metrics["pedestrian_wait_s"] += dt
                user.speed = 0.
                return
        previous = user.s
        advance = user.desired * dt
        for other in self.users:
            if other is user or other.crossing != user.crossing or other.direction != user.direction or abs(other.offset-user.offset) > .4:
                continue
            if other.s > user.s:
                gap = other.s-user.s-(other.dims[0]+user.dims[0])/2-.1
                advance = min(advance, max(0.,gap))
        user.s += advance
        user.speed = advance / dt
        if not user.admitted and user.s >= 0:
            user.admitted = True
            user.entered_at = self.t
        if not user.admitted and user.speed < .3:
            user.wait += dt
            user.delay += dt
            self.metrics["pedestrian_wait_s"] += dt
        self._locate(user)
        length = 2 * (self.geometry.half_road + 1.5)
        if previous < length / 2 <= user.s and "count" not in user.counted:
            user.counted.add("count")
            self.crossings[user.crossing][user.kind] += 1
            self.crossings[user.crossing]["A>B" if user.direction == 1 else "B>A"] += 1
            self._event("crossing", track=user.id, crosswalk=user.crossing, direction=user.direction, kind=user.kind)
        if user.s >= length:
            user.alive = False
            self.metrics["pedestrians_completed"] += 1
            self.metrics["crossing_bicycles_completed"] += int(user.cls == "bicycle")
            self._complete(user, "pedestrian")
            if user.cls == "pedestrian" and user.entered_at is not None:
                self.crossing_times[user.crossing].append(self.t-user.entered_at)

    def _safety(self):
        # A short constant-velocity screening check, including vehicle–vehicle pairs.
        # Turning paths make this approximate; report indicators, not accident probabilities.
        from crosswalk.safety import ttc_box
        active = set()
        moving = [u for u in self.users if u.admitted and u.speed > .5]
        for i, a in enumerate(moving):
            for b in moving[i + 1:]:
                if a.kind != "vehicle" and b.kind != "vehicle":
                    continue
                if math.dist(a.pos, b.pos) > 20:
                    continue
                if a.route_id and b.route_id:
                    ra, rb = self.geometry.routes[a.route_id], self.geometry.routes[b.route_id]
                    if ra.origin == rb.origin and ra.lane == rb.lane or ra.destination == rb.destination and ra.lane == rb.lane:
                        continue
                ttc = ttc_box(a, b, 2., .3)
                if ttc is None:
                    continue
                pair = tuple(sorted((a.id, b.id)))
                active.add(pair)
                if pair not in self.active_conflicts:
                    self.metrics["possible_conflicts"] += 1
                    self.conflict_notices.append({"t": round(self.t, 1), "agents": pair, "ttc": round(ttc, 2)})
        self.active_conflicts = active

    def step(self, dt=.1):
        if not 0 < dt <= .2:
            raise ValueError("intersection timestep must be in (0, .2]")
        self.t = round(self.t + dt, 9)
        self._arrive()
        if self.observation_provider is None:
            vehicles, pedestrians = self.demands()
            occupied, fresh = self.occupied(), True
        else:
            vehicles, pedestrians, occupied, fresh = self.observation_provider(self.t)
        if fresh:
            self.controller.update(self.t, vehicles, pedestrians, occupied)
        else:
            self.controller.t = self.t
            if self.controller.state != "all_red":
                self.controller.next_phase = self.controller.phase
                self.controller._transition("all_red", self.t, "Waiting for fresh camera observations")
            self.controller.reason = "Waiting for fresh camera observations"
        self.last_demand = {"vehicles": vehicles, "pedestrians": pedestrians}
        # Leaders move first; stable ID ordering makes tied positions reproducible.
        road_users = sorted((u for u in self.users if u.route_id), key=lambda u: (-u.s, u.id))
        for user in road_users:
            self._vehicle_step(user, dt)
        for user in sorted((u for u in self.users if u.crossing), key=lambda u: -u.s):
            self._pedestrian_step(user, dt)
        self.users = [u for u in self.users if u.alive]
        queued = sum(u.route_id is not None and not u.admitted and u.speed < 1 for u in self.users)
        self.metrics["max_queue"] = max(self.metrics["max_queue"], queued)
        self.metrics["queue_integral_s"] += queued * dt
        if int(round(self.t / dt)) % 5 == 0:
            self._safety()

    def run(self, seconds):
        if seconds < 0 or not math.isfinite(seconds):
            raise ValueError("duration must be finite and nonnegative")
        steps = int(round(seconds / self.dt))
        for _ in range(steps):
            self.step(self.dt)
        return self.report()

    def report(self):
        means = {kind: round(self.wait_sum[kind] / self.wait_n[kind], 2) if self.wait_n[kind] else None
                 for kind in ("vehicle", "pedestrian")}
        delays = {kind: round(self.delay_sum[kind] / self.delay_n[kind], 2) if self.delay_n[kind] else None
                  for kind in ("vehicle", "pedestrian")}
        speeds = sorted(self.speed_samples)
        return {"scenario": self.scenario, "seed": self.seed, "seconds": round(self.t, 1),
                "policy": self.controller.policy, "observation_mode": "perfect simulator ground truth",
                "counts": {"vehicle": self.metrics["vehicles_completed"]-self.metrics["road_bicycles_completed"],
                           "pedestrian": self.metrics["pedestrians_completed"]-self.metrics["crossing_bicycles_completed"],
                           "bicycle": self.metrics["road_bicycles_completed"]+self.metrics["crossing_bicycles_completed"]},
                "vehicle_speed_kmh": {"sample_count": len(speeds),
                                      "mean": round(sum(speeds)/len(speeds),2) if speeds else None,
                                      "v85": round(speeds[int(.85*(len(speeds)-1))],2) if speeds else None},
                "pedestrian_crossing_duration_s": {arm: {"sample_count": len(values),
                    "mean": round(sum(values)/len(values),2) if values else None} for arm,values in self.crossing_times.items()},
                "metrics": {k: round(v, 3) for k, v in self.metrics.items()},
                "mean_completed_wait_s": means, "mean_completed_delay_s": delays,
                "max_completed_wait_s": dict(self.max_wait),
                "residual": {"vehicles": sum(u.route_id is not None and "complete" not in u.counted for u in self.users),
                             "pedestrians": sum(u.crossing is not None for u in self.users)},
                "movement_counts": {k: self.movements[k] for k in self.geometry.routes},
                "crosswalk_counts": {a: dict(self.crossings[a]) for a in ARMS},
                "phase_changes": self.controller.phase_changes,
                "notes": ["Completed-trip averages exclude users still waiting; integrated delays and residual queues include them.",
                          "Four-arm ground-truth simulation, protected turns and an exclusive pedestrian phase.",
                          "TTC flags use constant-velocity screening and are approximate on turning paths.",
                          "Signal control uses provided perception observations." if self.observation_provider else
                          "Signal control uses simulator ground truth; optional camera diagnostics are reported separately.",
                          "No board integration, calibrated field traffic or emission model in this mode."]}

    def snapshot(self):
        vehicles, pedestrians = self.demands()
        return {"t": round(self.t, 2), "scenario": self.scenario, "seed": self.seed,
                "signal": self.controller.payload(), "demands": {"vehicles": vehicles, "pedestrians": pedestrians},
                "agents": [{"id": u.id, "kind": "bicycle" if u.cls == "bicycle" else u.kind, "cls": u.cls,
                            "x": round(u.x, 3), "y": round(u.y, 3), "heading": round(u.heading, 4),
                            "speed": round(u.speed, 2), "dims": u.dims,
                            "movement": u.route_id, "crosswalk": u.crossing, "wait_s": round(u.wait, 1),
                            "state": "crossing" if u.crossing and u.admitted else "waiting" if u.speed < .5 else "moving"}
                           for u in self.users],
                "statistics": self.report(), "events": list(self.events)[-12:],
                "conflicts": list(self.conflict_notices)}
