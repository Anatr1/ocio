"""Agent-based crosswalk traffic simulation in the crosswalk world frame (see crosswalk/config.py).

Right-hand traffic: vehicles moving +X use the lane at y = -L/4, vehicles moving -X the lane at y = +L/4.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field, replace

from .behaviour import PARAMETERS, idm, overlaps, penetration, social_velocity
from .scenarios import load_scenario

DIMS = {"pedestrian": (0.5, 0.5, 1.72), "child": (0.4, 0.4, 1.2), "bicycle": (1.8, 0.6, 1.75),
        "e-scooter": (1.0, 0.5, 1.78), "car": (4.4, 1.8, 1.5), "bus": (12.0, 2.55, 3.1),
        "truck": (8.0, 2.5, 3.3), "motorcycle": (2.1, 0.8, 1.5),
        "elderly": (0.5, 0.5, 1.65), "wheelchair": (1.1, 0.7, 1.3),
        "stroller": (1.0, 0.6, 1.6), "van": (5.2, 2.0, 2.2)}
KIND = {"pedestrian": "pedestrian", "child": "pedestrian", "bicycle": "bicycle", "e-scooter": "micromobility",
        "car": "vehicle", "bus": "vehicle", "truck": "vehicle", "motorcycle": "vehicle",
        "elderly": "pedestrian", "wheelchair": "pedestrian", "stroller": "pedestrian", "van": "vehicle"}
DET_CLASS = {"pedestrian": "person", "child": "person", "bicycle": "bicycle", "e-scooter": "person",
             "car": "car", "bus": "bus", "truck": "truck", "motorcycle": "motorcycle",
             "elderly": "person", "wheelchair": "wheelchair", "stroller": "stroller", "van": "car"}


@dataclass
class Agent:
    id: int
    cls: str
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    heading: float = 0.0
    state: str = "walk"
    meta: dict = field(default_factory=dict)
    alive: bool = True
    color: tuple = (200, 200, 200)

    @property
    def kind(self):
        return KIND[self.cls]

    @property
    def dims(self):
        return DIMS[self.cls]

    @property
    def speed(self):
        return math.hypot(self.vx, self.vy)

    @property
    def subclass(self):
        return {"child": "pedestrian", "elderly": "pedestrian", "van": "car"}.get(self.cls, self.cls)


class World:
    def __init__(self, scene_cfg, scenario: dict, seed=0, signal=None, cfg=None):
        self.rng = random.Random(seed)
        cw = scene_cfg["crosswalk"]
        self.W, self.L = float(cw["width"]), float(cw["length"])
        self.D = float(scene_cfg.get("curb_depth", 2.5))
        self.A = float(scene_cfg.get("approach", 25.0))
        self.sw = float(scene_cfg.get("sidewalk_width", 3.0))
        self.sc = load_scenario(scenario)
        self.seed = seed
        self.params = {**PARAMETERS, **self.sc.get("behaviour", {})}
        self.lanes = int(scene_cfg.get("lanes", 2))
        if self.lanes < 2:
            raise ValueError("the bidirectional world requires at least two lanes")
        self.signal = signal  # optional SignalController (signalised mode)
        self.t = 0.0
        self.agents: list[Agent] = []
        self.next_id = 1
        self.gt_events = []
        self.next_spawn = {}
        self.queue = list(self.sc.get("script", []))
        self.pairs_min_ttc = {}
        self.contacts = set()
        self.wait_times = []
        from crosswalk.config import load_config
        from crosswalk.scene import Scene
        from .gt import GroundTruth

        config = cfg or load_config()
        self.truth = GroundTruth(Scene(scene_cfg, tracker_cfg=config.tracker), config.safety, config.counting, signal)
        self.gt_events = self.truth.events
        self.pairs_min_ttc = self.truth.pairs_min_ttc

    # ------------------------------------------------------------------ spawning
    def _rate(self, key):
        return float(self.sc.get("rates", {}).get(key, 0.0)) / 60.0  # per second

    def _schedule(self, key):
        r = self._rate(key)
        if r <= 0:
            self.next_spawn[key] = math.inf
        else:
            self.next_spawn[key] = self.t + self.rng.expovariate(r)

    def spawn(self, cls, **kw):
        if cls not in KIND:
            raise ValueError(f"unknown agent class: {cls}")
        a = Agent(self.next_id, cls, 0.0, 0.0)
        self.next_id += 1
        rng = self.rng
        W, L, D, A = self.W, self.L, self.D, self.A
        route = kw.get("route", "crossing" if a.kind in ("pedestrian", "micromobility") or kw.get("crossing") else "road")
        if route in ("crossing", "sidewalk"):
            side = kw.get("side", rng.choice((-1, 1)))
            jay = kw.get("jaywalk", rng.random() < float(self.sc.get("jaywalk_p", 0.0)))
            a.x = kw.get("x0", rng.uniform(-W / 2 - 10, W / 2 + 10))
            a.y = side * (L / 2 + D + rng.uniform(0.5, self.sw))
            cross_x = rng.uniform(-W / 2 + 0.4, W / 2 - 0.4)
            if jay:
                cross_x = rng.choice((-1, 1)) * rng.uniform(W / 2 + 4, W / 2 + 12)
            a.meta.update({"side": side, "cross_x": kw.get("cross_x", cross_x), "jay": jay,
                           "v": kw.get("v", self._walk_speed(cls)), "impatience": rng.uniform(4, 15),
                           "wait": 0.0, "violator": rng.random() < float(self.sc.get("red_violation_p", 0.03)),
                           "exit_x": rng.uniform(-W / 2 - 12, W / 2 + 12), "route": route,
                           "group": kw.get("group"), "distracted": kw.get("distracted", False),
                           "decision_at": 0.0, "hesitate_s": kw.get("hesitate_s", 0.0),
                           "conspicuity": kw.get("conspicuity", 1.0),
                           # cautious crossers check each lane before stepping into it; scripted agents
                           # default to False so catalogue scenarios keep their exact, designed behaviour
                           "cautious": bool(kw.get("cautious", False))})
            a.state = "to_curb"
            if route == "sidewalk":
                a.y = side * (L / 2 + D / 2)
                a.x = kw.get("x0", -A)
                a.meta["exit_x"] = kw.get("exit_x", A)
                a.state = "sidewalk"
            a.color = tuple(rng.randint(40, 230) for _ in range(3))
        else:
            d = kw.get("dir", rng.choice((-1, 1)))  # +1 -> moves +X
            a.x = -d * (A + 3 + (self.PREROLL_M if kw.get("_rate_spawn") else 0.0))
            lane = int(kw.get("lane", 0))
            a.y = self.lane_y(d, lane)
            if cls in ("bicycle", "e-scooter"):
                a.y = -d * (L / 2 - 0.55)
            v = kw.get("v", self._drive_speed(cls))
            a.vx = d * v
            a.heading = 0.0 if d > 0 else math.pi
            yp = float(self.sc.get("yield_p", 0.8))
            a.meta.update({"dir": d, "v0": v, "yields": kw.get("yields", rng.random() < yp), "stopped_for": None,
                           "reaction": kw.get("reaction", rng.uniform(0.6, 1.4)), "lane": lane,
                           "red_runner": kw.get("red_runner", rng.random() < float(self.sc.get("vehicle_red_p", 0.0))),
                           "conspicuity": kw.get("conspicuity", 1.0)})
            a.state = "drive"
            # never spawn on top of a queued vehicle in the same lane
            for o in self.vehicles():
                if o.meta["dir"] == d and abs(o.y - a.y) < 1.5 and abs(o.x - a.x) < (o.dims[0] + a.dims[0]) / 2 + 6:
                    a.x = o.x - d * ((o.dims[0] + a.dims[0]) / 2 + 8)
                    a.vx = d * min(v, o.speed + 1.0)
            palette = [(30, 30, 200), (200, 200, 200), (40, 40, 40), (180, 50, 30), (30, 140, 200), (240, 240, 240)]
            a.color = rng.choice(palette)
        a.x, a.y = float(kw.get("x", a.x)), float(kw.get("y", a.y))
        a.state = kw.get("state", a.state)
        a.meta.update({k: kw[k] for k in ("stop_at_s", "stop_duration_s", "waypoints", "wrong_way", "blocking") if k in kw})
        a.meta["spawn_t"] = self.t
        if "violator" in kw:
            a.meta["violator"] = bool(kw["violator"])
        if route != "road":
            a.heading = -side * math.pi / 2
        # Ordinary arrivals queue upstream; explicit intersecting initial conditions are invalid.
        for attempt in range(100):
            if not any(overlaps(a, o, 0.02) for o in self.agents):
                break
            if "x" in kw or "y" in kw:
                raise ValueError(f"agent {a.id} starts inside another footprint")
            if route == "road":
                a.x -= a.meta["dir"] * (a.dims[0] + 2)
            else:
                a.x += 0.6
        else:
            if kw.get("_rate_spawn"):
                # a saturated approach: the arrival is not admitted (logged, never a crash)
                self.gt_events.append({"type": "arrival_dropped", "t": self.t, "cls": cls, "reason": "no_space"})
                return None
            raise ValueError("cannot place an arrival without overlap")
        if kw.get("_rate_spawn") and route == "road" and abs(a.x) > self.A + 3 + self.PREROLL_M + self.QUEUE_CAP_M:
            # the queue has spilled back past the previous junction: these drivers take another route
            # (bounds the state of long saturated runs; far beyond anything the camera sees)
            self.gt_events.append({"type": "arrival_dropped", "t": self.t, "cls": cls, "reason": "queue"})
            return None
        if route == "road":
            # A vehicle entering the simulated area has already seen the queue ahead: start no faster than it
            # could stop behind its leader (otherwise boundary spawns cause artificial rear-end crashes).
            d, lead = a.meta["dir"], None
            for o in self.vehicles():
                if o.meta["dir"] != d or abs(o.y - a.y) > 1.5:
                    continue
                gap = (o.x - a.x) * d - (o.dims[0] + a.dims[0]) / 2
                if gap > -1.0 and (lead is None or gap < lead[1]):
                    lead = (o, gap)
            if lead is not None:
                o, gap = lead
                safe = o.speed + math.sqrt(2 * 3.0 * max(0.0, gap - self.params["idm_min_gap_m"]))
                if a.speed > safe:
                    a.vx = d * safe
            if kw.get("_rate_spawn") and self._entry_must_stop(a):
                # The driver has been watching the red lamp / the people on the zebra for the last 100 m:
                # already reacted and slowed so that a comfortable stop at the line is possible.
                a.meta["stop_seen"] = self.t - a.meta["reaction"]
                front = a.x + d * a.dims[0] / 2
                dist_to_stop = (-d * (self.W / 2 + 1.5) - front) * d
                safe = math.sqrt(2 * 3.0 * max(0.0, dist_to_stop - 0.3))
                if a.speed > safe:
                    a.vx = d * safe
        self.agents.append(a)
        return a

    def _entry_must_stop(self, a):
        """Would this vehicle, entering now, already have to stop at the line (as in _veh_step)?"""
        m = a.meta
        sig = self.veh_signal()
        if sig in ("red", "yellow"):
            return not m.get("red_runner")
        if sig is not None or not m["yields"]:
            return False
        for p in self.peds():
            if self._yield_relevant(a, p):
                if "yield_decision" not in m:
                    m["yield_decision"] = self.rng.random() < min(1.0, p.meta.get("conspicuity", 1.0))
                if m["yield_decision"]:
                    m["stopped_for"] = p.id
                    return True
        return False

    # Random vehicle arrivals enter this far beyond the approach (still on the rendered road, which is
    # 60 m long): drivers then react to the crossing, and pedestrians see them coming, as on a real street.
    PREROLL_M = 30.0
    QUEUE_CAP_M = 150.0  # random arrivals queueing further upstream than this are dropped (logged)

    # ------------------------------------------------------------------ curb waiting places
    SLOT_ROWS = 5
    SLOT_DEPTH = 0.7      # row spacing (m) behind the curb
    SLOT_CLAIM_M = 4.0    # claim a place when this close to the curb line

    def _slot_xs(self):
        lo, hi = -self.W / 2 + 0.3, self.W / 2 - 0.3
        if hi <= lo:
            return [0.0]
        n = max(1, int((hi - lo) / 0.6) + 1)
        return [lo + (hi - lo) * i / (n - 1) for i in range(n)] if n > 1 else [0.0]

    def _slot_y(self, a, side, row):
        # crossers face the road while waiting: their length runs across the curb, so long footprints
        # (bicycles 1.8 m, strollers, wheelchairs) wait fully behind the curb instead of poking into the lane
        return side * (self.L / 2 + 0.1 + a.dims[0] / 2 + row * self.SLOT_DEPTH)

    def _claim_slot(self, a):
        """Pick the free waiting place nearest to the preferred crossing point (front rows first)."""
        side = a.meta["side"]
        heading = -side * math.pi / 2
        claimed = [replace(o, x=o.meta["slot_xy"][0], y=o.meta["slot_xy"][1], heading=heading)
                   for o in self.agents if o is not a and o.alive and o.meta.get("slot_xy") is not None
                   and o.meta.get("side") == side]
        best = None
        pref = a.meta["cross_x"]
        for row in range(self.SLOT_ROWS + 8):  # rows beyond SLOT_ROWS: the crowd spills back onto the sidewalk
            y = self._slot_y(a, side, row)
            for x in self._slot_xs():
                probe = replace(a, x=x, y=y, heading=heading)
                if any(overlaps(probe, o, 0.05) for o in claimed):
                    continue
                cost = abs(x - pref) + 1.2 * row
                if best is None or cost < best[0]:
                    best = (cost, x, y)
        if best is None:  # every place taken: queue behind the last row
            x, y = pref, self._slot_y(a, side, self.SLOT_ROWS)
        else:
            _, x, y = best
        a.meta["slot_xy"] = (x, y)
        a.meta["cross_x"] = x  # cross straight ahead from where one waited
        return x, y

    def _release_slot(self, a):
        a.meta.pop("slot_xy", None)

    def lane_y(self, direction, lane=0):
        n = max(1, self.lanes // 2)
        if not 0 <= lane < n:
            raise ValueError(f"lane {lane} outside this direction's {n} lanes")
        return -direction * ((lane + 0.5) * self.L / (2 * n))

    def _walk_speed(self, cls):
        if cls == "e-scooter":
            return self.rng.uniform(4.5, 6.5)
        if cls == "bicycle":
            return self.rng.uniform(3.0, 5.0)
        if cls == "wheelchair":
            return self.rng.uniform(0.7, 1.1)
        if cls == "stroller":
            return self.rng.uniform(0.9, 1.2)
        if cls == "child":
            return self.rng.uniform(1.0, 1.5)
        if cls == "elderly" or self.rng.random() < float(self.sc.get("elderly_p", 0.1)):
            return self.rng.uniform(self.params["elderly_speed_min"], self.params["elderly_speed_max"])
        return max(0.8, self.rng.gauss(self.params["adult_speed_mean"], self.params["adult_speed_sd"]))

    def _drive_speed(self, cls):
        if cls == "bicycle":
            return self.rng.uniform(3.5, 6.5)
        if cls == "bus":
            return self.rng.uniform(8, 11)
        base = float(self.sc.get("car_speed", 12.0))
        if self.rng.random() < float(self.sc.get("speeder_p", 0.1)):
            return base * self.rng.uniform(1.3, 1.6)
        return max(5.0, self.rng.gauss(base, 1.8))

    # ------------------------------------------------------------------ queries
    def peds(self):
        """Everybody who crosses the road (pedestrians, scooters, cyclists using the crosswalk)."""
        return [a for a in self.agents if "side" in a.meta]

    def vehicles(self):
        return [a for a in self.agents if "dir" in a.meta]

    def ped_signal(self):
        return None if self.signal is None or self.signal.mode == "beacon" else self.signal.ped_state()

    def veh_signal(self):
        return None if self.signal is None or self.signal.mode == "beacon" else self.signal.veh_state()

    def _time_to_arrival(self, veh, x_target):
        d = (x_target - veh.x) * veh.meta["dir"]
        if d < -veh.dims[0]:
            return math.inf
        return max(0.0, d) / max(veh.speed, 0.1)

    # ------------------------------------------------------------------ behaviours
    def _ped_step(self, a, dt):
        if a.state == "crashed":
            a.vx = a.vy = 0.0
            return
        W, L = self.W, self.L
        m = a.meta
        side = m["side"]
        elapsed = self.t - m["spawn_t"]
        if elapsed >= m.get("stop_at_s", math.inf) and elapsed < m.get("stop_at_s", math.inf) + m.get("stop_duration_s", math.inf):
            a.vx = a.vy = 0.0
            return
        target = None
        if a.state == "sidewalk":
            target = (m["exit_x"], a.y)
            if abs(a.x - m["exit_x"]) < 0.4:
                a.alive = False
                return
        if a.state == "to_curb":
            if m.get("jay"):
                target = (m["cross_x"], self._slot_y(a, side, 0))
            elif m.get("slot_xy") is not None:
                target = m["slot_xy"]
            elif abs(a.y) - L / 2 < self.SLOT_CLAIM_M:
                target = self._claim_slot(a)
            else:
                target = (m["cross_x"], self._slot_y(a, side, 0))
            if math.hypot(target[0] - a.x, target[1] - a.y) < 0.3:
                a.state = "wait"
        if a.state == "wait":
            m["wait"] += dt
            if self._ped_may_go(a):
                a.state = "cross"
                self._release_slot(a)
                m["t_cross0"] = self.t
                self.wait_times.append({"agent": a.id, "seconds": m["wait"]})
            else:
                a.vx = a.vy = 0.0
                return
        if a.state == "cross":
            target = (m["cross_x"] + 0.3 * math.sin(a.id), -side * (L / 2 + 0.4))
            # Nobody walks into a standing vehicle; only cautious crossers also wait for approaching ones
            # (hurried or careless crossers accepting short gaps is what produces the real conflicts).
            hazard, why = self._lane_hazard(a, target, approaching=bool(m.get("cautious") and not m.get("hurry")))
            if hazard is not None:
                m["held_s"] = m.get("held_s", 0.0) + dt
                m["held_total_s"] = m.get("held_total_s", 0.0) + dt
                if why in ("blocked", "beside") and m["held_s"] > 2.0 and hazard.speed < 1.0:
                    # a vehicle stands across the crossing: walk around it, but stay near the zebra
                    around = [hazard.x + sgn * (hazard.dims[0] / 2 + 0.9) for sgn in (-1, 1)]
                    around = [x for x in around if abs(x) <= self.W / 2 + 3.0]
                    if around:
                        m["cross_x"] = min(around, key=lambda x: abs(x - a.x))
                    m["held_s"] = 0.0
                if m["held_total_s"] > 30.0 and not m.get("aborted"):
                    # give up: cross back to the curb one came from (never wait forever in the road)
                    m["side"] = -side
                    m["aborted"] = True
                    m["held_total_s"] = 0.0
                    m["cross_x"] = a.x
                    self.gt_events.append({"type": "crossing_aborted", "t": self.t, "agent": a.id, "cls": a.cls})
                a.vx = a.vy = 0.0
                return
            m["held_s"] = 0.0
            if math.hypot(target[0] - a.x, target[1] - a.y) < 0.3:
                a.state = "leave"
        if a.state == "leave":
            target = (m["exit_x"], -side * (L / 2 + self.D + 4))
            if math.hypot(target[0] - a.x, target[1] - a.y) < 0.5:
                a.alive = False
                return
        if target is None:
            return
        v = m["v"] * (1.25 if (a.state == "cross" and m.get("hurry")) else 1.0)
        if m.get("distracted"):
            v *= 0.75
        if a.state == "cross" and self.ped_signal() == "flash" and a.cls not in ("elderly", "wheelchair"):
            v *= 1.3
        if a.state == "cross" and elapsed < m.get("hesitate_s", 0.0):
            v = 0.0
        a.vx, a.vy = social_velocity(a, target, self.agents, v, dt, self.params)
        a.x += a.vx * dt
        a.y += a.vy * dt
        if a.state == "leave" and -side * a.y >= L / 2 + max(a.dims[:2]) / 2 + 0.02:
            m["kerb_done"] = True
        self._keep_on_pavement(a)
        if a.speed > 0.1:
            a.heading = math.atan2(a.vy, a.vx)

    def _kerb_side(self, a):
        """The side whose pavement this walker has to stay on now (None while on the carriageway)."""
        if a.state in ("to_curb", "wait", "sidewalk"):
            return a.meta["side"]
        if a.state == "leave" and a.meta.get("kerb_done"):
            return -a.meta["side"]
        return None

    def _keep_on_pavement(self, a):
        """Walking to one's waiting place, waiting, or walking away happens on the pavement: nobody steps
        (or is pushed) off the kerb sideways into the traffic."""
        side = self._kerb_side(a)
        if side is None:
            return
        edge = self.L / 2 + max(a.dims[:2]) / 2 + 0.02
        if side * a.y < edge:
            a.y = side * edge
            if a.vy * side < 0:
                a.vy = 0.0

    def _reliably_stopping(self, v):
        """A vehicle visibly braking for the crossing that can still stop at its stop line. Only such a
        vehicle is trusted as a gap; a driver who has not reacted yet, or cannot stop any more, is not."""
        m = v.meta
        if m.get("stopped_for") is None or self.t - m.get("stop_seen", self.t) < m["reaction"]:
            return False
        d = m["dir"]
        room = (-d * (self.W / 2 + 1.5) - (v.x + d * v.dims[0] / 2)) * d
        return room > -0.5 and v.speed ** 2 / (2 * max(room, 0.1)) <= 4.5

    def _yield_relevant(self, v, p):
        """Zebra rule for a yielding driver: stop for people waiting at the zebra, or on it with this
        driver's lane still ahead of them (or already in or next to it)."""
        if abs(p.x) > self.W / 2 + 2.0:
            return False
        if p.state == "wait":
            return True
        if p.state != "cross":
            return False
        return abs(p.y - v.y) < 3.2 or (v.y - p.y) * -p.meta["side"] > 0

    def _lane_hazard(self, a, target, approaching=True):
        """For a crosser about to step into a lane: the vehicle that makes it unsafe, or None.
        Unsafe = a stopped/slow vehicle body across the path ("beside"/"blocked"), or (approaching=True,
        cautious crossers) a vehicle that arrives before we could clear its lane with 1 s to spare (at least
        lane_check_tta_s), unless it is visibly able to stop at its line before us. Crossers already inside a
        lane keep going to clear it."""
        heading_y = 1.0 if target[1] > a.y else -1.0
        own = max(a.dims[:2]) / 2
        tta_max = float(self.params.get("lane_check_tta_s", 2.0))
        for v in self.vehicles():
            band = v.dims[1] / 2 + own + 0.3
            dy = (v.y - a.y) * heading_y
            dx = a.x - v.x
            if 0 < dy and abs(v.y - a.y) < band and abs(dx) < v.dims[0] / 2 + own + 0.3:
                return v, "beside"  # inside its lane with its body across our path: wait, never walk into it
            if dy <= 0 or dy - band > 1.0 or abs(v.y - a.y) < band:
                continue  # lane behind us, too far ahead, or we are already inside it
            if abs(dx) < v.dims[0] / 2 + own + 0.5 and v.speed < 1.0:
                return v, "blocked"
            along = dx * v.meta["dir"]  # > 0: we are in front of the vehicle
            stop_x = -v.meta["dir"] * (self.W / 2 + 1.5)  # where its front stops when it yields
            protected = self._reliably_stopping(v) and (a.x - stop_x) * v.meta["dir"] > own
            if approaching and along > -v.dims[0] / 2 and v.speed >= 0.3 and not protected:
                clear_s = (dy + band) / max(a.meta["v"], 0.3)  # time to get past the lane's far edge
                if max(0.0, along - v.dims[0] / 2) / v.speed < max(tta_max, clear_s + 1.0):
                    return v, "approaching"
        return None, None

    def _ped_may_go(self, a):
        if self.t < a.meta["decision_at"]:
            return False
        a.meta["decision_at"] = self.t + (1.0 if a.meta.get("distracted") else 0.5)
        sig = self.ped_signal()
        if sig is not None:
            if sig == "green":
                return True
            if a.meta["violator"] and not any(abs(v.x) < 30 for v in self.vehicles()):
                return True
            return False
        # unsignalised: gap acceptance, shrinking with impatience; yielding cars count as a gap
        need = max(2.0, 6.0 - a.meta["wait"] / a.meta["impatience"] * 2.0)
        min_tta = math.inf
        for v in self.vehicles():
            if v.kind != "vehicle" and v.cls != "bicycle":
                continue
            tta = self._time_to_arrival(v, a.x)
            if self._reliably_stopping(v) or v.speed < 0.5:
                front = v.x + v.meta["dir"] * v.dims[0] / 2
                rear = v.x - v.meta["dir"] * v.dims[0] / 2
                if min(abs(front), abs(rear)) < self.W / 2 + 0.3 or (front > 0) != (rear > 0):
                    return False  # a vehicle is on the crosswalk right now
                continue
            min_tta = min(min_tta, tta)
            if tta < 1.0 and abs(v.x) < self.A + 2:
                # brave / distracted pedestrians sometimes go anyway (source of near misses)
                if self.rng.random() < float(self.sc.get("risky_ped_p", 0.002)):
                    a.meta["hurry"] = True
                    return True
                return False
        probability = 1.0 if math.isinf(min_tta) else 1 / (1 + math.exp(max(-30, min(30, -1.4 * (min_tta - need)))))
        return self.rng.random() < probability

    def _veh_step(self, a, dt):
        """Intelligent Driver Model + stop-line logic (yielding / red light) + emergency braking."""
        if a.state == "crashed":
            a.vx = a.vy = 0.0
            return
        m = a.meta
        d = m["dir"]
        W = self.W
        v = a.speed
        v0 = m["v0"]
        stop_line = -d * (W / 2 + 1.5)
        front = a.x + d * a.dims[0] / 2
        dist_to_stop = (stop_line - front) * d  # front bumper to the stop line
        acc = idm(v, v0, params=self.params)
        # car following (same lane)
        leader = None
        for o in self.vehicles():
            if o is a or o.meta["dir"] != d or abs(o.y - a.y) > 1.5:
                continue
            gap = (o.x - a.x) * d - (o.dims[0] + a.dims[0]) / 2
            if gap > -1.0 and (leader is None or gap < leader[1]):
                leader = (o, gap)
        if leader is not None:
            o, gap = leader
            acc = min(acc, idm(v, v0, gap, o.speed, self.params))
        must_stop = False
        sig = self.veh_signal()
        if sig in ("red", "yellow") and dist_to_stop > 0 and not m.get("red_runner"):
            if sig == "red" or v * v / (2 * max(dist_to_stop, 0.1)) < 3.5:
                must_stop = True
        if sig is None and dist_to_stop > -0.5:
            for p in self.peds():
                if p.state not in ("cross", "wait"):
                    continue
                # the duty to yield is at the zebra; people crossing elsewhere get emergency braking only
                if m["yields"] and self._yield_relevant(a, p) and 0 < dist_to_stop < 40:
                    if "yield_decision" not in m:
                        visible = p.meta.get("conspicuity", 1.0)
                        m["yield_decision"] = self.rng.random() < min(1.0, visible)
                    if m["yield_decision"]:
                        must_stop = True
                        m["stopped_for"] = p.id
        # A green lamp is not permission to drive through a stranded road user.
        for p in self.peds():  # crossers, and anybody else on the carriageway (pushed, fallen, leaving)
            if p.kind == "pedestrian" and p.dims[0] == p.dims[1]:
                ext_x = ext_y = p.dims[0] / 2  # walkers are circles
            else:
                c, s = abs(math.cos(p.heading)), abs(math.sin(p.heading))
                ext_x = c * p.dims[0] / 2 + s * p.dims[1] / 2  # crosser's half-extent along the road ...
                ext_y = s * p.dims[0] / 2 + c * p.dims[1] / 2  # ... and across it
            if p.state != "cross" and abs(p.y) - ext_y >= self.L / 2 - 0.05:
                continue  # on the pavement (waiting at the kerb, walking by): not in the way
            gap = (p.x - front) * d - ext_x  # front bumper to the crosser's near edge
            if abs(p.y - a.y) < a.dims[1] / 2 + ext_y + 0.3 and -ext_x < gap < (25 if m["yields"] else 13):
                acc = min(acc, -min(self.params["emergency_brake"], v * v / (2 * max(gap - 1.25, 0.4))))
                if gap < 2.25:  # someone right in front of the bumper: stop, even when creeping
                    acc = min(acc, -self.params["emergency_brake"])
        if must_stop:
            m.setdefault("stop_seen", self.t)
        else:
            m.pop("stop_seen", None)
        reacted = self.t - m.get("stop_seen", self.t) >= m["reaction"]
        if must_stop and reacted and dist_to_stop > 0:
            need = v * v / (2 * max(dist_to_stop - 0.3, 0.1))
            if need > 0.4 or v < 0.5:
                acc = min(acc, -min(8.0, need * 1.15))
            if dist_to_stop < 0.6:
                acc = min(acc, -8.0)
        elif not must_stop:
            m["stopped_for"] = None
        acc = max(-8.0, min(2.0, acc))
        sp = max(0.0, v + acc * dt)
        m["acc"] = (sp - v) / dt
        a.vx = d * sp
        elapsed = self.t - m["spawn_t"]
        if elapsed >= m.get("stop_at_s", math.inf) and elapsed < m.get("stop_at_s", math.inf) + m.get("stop_duration_s", math.inf):
            a.vx = 0.0
        a.x += a.vx * dt
        if m.get("waypoints"):
            target = m["waypoints"][0]
            dx, dy = target[0] - a.x, target[1] - a.y
            dist = math.hypot(dx, dy)
            if dist < 0.4:
                m["waypoints"].pop(0)
            elif dist > 0:
                a.x -= a.vx * dt
                a.vx, a.vy = sp * dx / dist, sp * dy / dist
                a.x += a.vx * dt
                a.y += a.vy * dt
                a.heading = math.atan2(a.vy, a.vx)
        elif self.lanes >= 4 and self.sc.get("lane_changes", True):
            self._lane_change(a, dt, acc)
        if abs(a.x) > self.A + 6 and a.x * d > 0:
            a.alive = False

    def _lane_change(self, a, dt, current_acc):
        m, d = a.meta, a.meta["dir"]
        if "target_lane" not in m and abs(a.x) > self.W / 2 + 6 and self.t >= m.get("next_lane_check", 0):
            m["next_lane_check"] = self.t + 1.0
            for lane in (m["lane"] - 1, m["lane"] + 1):
                if not 0 <= lane < self.lanes // 2:
                    continue
                y = self.lane_y(d, lane)
                neighbours = [o for o in self.vehicles() if o is not a and o.meta["dir"] == d and abs(o.y - y) < 1.5]
                ahead = [(o, (o.x - a.x) * d - (o.dims[0] + a.dims[0]) / 2) for o in neighbours if (o.x - a.x) * d >= 0]
                behind = [(o, (a.x - o.x) * d - (o.dims[0] + a.dims[0]) / 2) for o in neighbours if (o.x - a.x) * d < 0]
                lead, gap = min(ahead, key=lambda q: q[1]) if ahead else (None, math.inf)
                follower, back_gap = min(behind, key=lambda q: q[1]) if behind else (None, math.inf)
                if min(gap, back_gap) < 2.0:
                    continue
                following_acc = idm(follower.speed, follower.meta["v0"], back_gap, a.speed, self.params) if follower else 0
                if following_acc < -self.params["mobil_safe_brake"]:
                    continue
                own_acc = idm(a.speed, m["v0"], gap, lead.speed if lead else 0, self.params)
                old_follow_acc = idm(follower.speed, follower.meta["v0"],
                                     back_gap + a.dims[0] + gap, lead.speed if lead else 0,
                                     self.params) if follower else 0
                gain = own_acc - current_acc + self.params["mobil_politeness"] * (following_acc - old_follow_acc)
                if gain > self.params["mobil_threshold"]:
                    m["target_lane"] = lane
                    break
        if "target_lane" in m:
            y = self.lane_y(d, m["target_lane"])
            delta = y - a.y
            a.vy = max(-0.8, min(0.8, delta / max(dt, 1e-6)))
            a.y += a.vy * dt
            a.heading = math.atan2(a.vy, a.vx)
            if abs(delta) < 0.02:
                m["lane"] = m.pop("target_lane")
                a.vy = 0.0

    # ------------------------------------------------------------------ main step
    def step(self, dt):
        if not math.isfinite(dt) or dt <= 0:
            raise ValueError("step duration must be positive and finite")
        physics_dt = float(self.sc.get("physics_dt", 0.05))
        if not math.isfinite(physics_dt) or physics_dt <= 0:
            raise ValueError("physics_dt must be positive and finite")
        n = max(1, math.ceil(dt / physics_dt))
        for _ in range(n):
            self._step(dt / n)

    def _step(self, dt):
        self.t += dt
        for key in self.sc.get("rates", {}):
            if key not in self.next_spawn:
                self._schedule(key)
            while self.t >= self.next_spawn[key]:
                cautious = self.rng.random() < float(self.sc.get("caution_p", 0.95))
                if key == "sidewalk":
                    self.spawn("pedestrian", route="sidewalk", _rate_spawn=True)
                elif key == "scooter_road":
                    self.spawn("e-scooter", route="road", _rate_spawn=True)
                elif key == "bike_cross":
                    self.spawn("bicycle", crossing=True, v=self.rng.uniform(3.0, 5.0), cautious=cautious,
                               _rate_spawn=True)
                else:
                    self.spawn(key, cautious=cautious, _rate_spawn=True)
                self._schedule(key)
        while self.queue and self.queue[0][0] <= self.t:
            _, cls, kw = self.queue.pop(0)
            count = int(kw.get("n", 1))
            for i in range(count):
                params = {k: v for k, v in kw.items() if k != "n"}
                if count > 1:
                    params.setdefault("group", self.next_id - i)
                    params["x0"] = params.get("x0", 0) + 0.7 * i
                    params["cross_x"] = params.get("cross_x", 0) + 0.7 * (i - (count - 1) / 2)
                    params.setdefault("exit_x", 7.0)
                self.spawn(cls, **params)
        before = {a.id: replace(a) for a in self.agents}
        for a in self.agents:
            if "side" in a.meta:
                self._ped_step(a, dt)
            else:
                self._veh_step(a, dt)
        self._resolve_contacts(before, dt)
        clear_s = float(self.params.get("crash_clear_s", 60.0))
        for a in self.agents:
            if a.state == "crashed" and self.t - a.meta.get("crash_t", self.t) >= clear_s:
                a.alive = False
                self.gt_events.append({"type": "crash_cleared", "t": self.t, "agent": a.id, "cls": a.cls})
        self.agents = [a for a in self.agents if a.alive]
        self.truth.signal = self.signal
        self.truth.safety.signal_mode = self.signal.mode if self.signal else "beacon"
        self.truth.update(self.t, self.agents)

    @staticmethod
    def _pose(previous, current, fraction):
        angle = (current.heading - previous.heading + math.pi) % (2 * math.pi) - math.pi
        return replace(current, x=previous.x + fraction * (current.x - previous.x),
                       y=previous.y + fraction * (current.y - previous.y),
                       heading=previous.heading + fraction * angle)

    def _resolve_contacts(self, before, dt):
        """Vehicles: swept contact test, first touch logged as a collision, participants immobilised (crash).
        People and cyclists: soft contacts - pushed apart to touching with their sliding motion kept, so they
        brush past each other instead of freezing forever. No footprint ever stays interpenetrated."""
        resolved = self._resolve_vehicle_contacts(before, dt)
        if resolved:
            self._separate_soft(dt)
            # Local fallback: rewind only the agents that are still interpenetrating (their previous poses were
            # valid). Rewinding can uncover new overlaps with neighbours, so grow the set until it is clean.
            rewound = set()
            for _ in range(len(self.agents) + 1):
                bad = {o.id for a, b in self._overlapping_pairs() if overlaps(a, b) for o in (a, b)} - rewound
                if not bad:
                    if rewound:
                        self.gt_events.append({"type": "physics_rewind", "t": self.t, "agents": sorted(rewound)})
                    return
                for obj in self.agents:
                    if obj.id in bad:
                        prev = before[obj.id]
                        obj.x, obj.y, obj.heading = prev.x, prev.y, prev.heading
                        obj.vx = obj.vy = 0.0
                rewound |= bad
        # A dense pile-up cannot be advanced safely; retain the last valid world pose.
        for obj in self.agents:
            prev = before[obj.id]
            obj.x, obj.y, obj.heading = prev.x, prev.y, prev.heading
            obj.vx = obj.vy = 0.0
        self.gt_events.append({"type": "physics_guard", "t": self.t})

    def _resolve_vehicle_contacts(self, before, dt):
        # Truncating one trajectory can create another contact: repeat until all are clear.
        for _ in range(max(4, len(self.agents) * 2)):
            changed = False
            for a, b, lo, hi in self._contacts(before):
                if "vehicle" not in (a.kind, b.kind):
                    continue  # soft contact, handled by _separate_soft
                pair = tuple(sorted((a.id, b.id)))
                if pair not in self.contacts:
                    self.contacts.add(pair)
                    self.gt_events.append({"type": "collision" if "vehicle" in (a.kind, b.kind) else "contact",
                                           "t": self.t - dt + hi * dt, "agents": list(pair),
                                           "classes": [a.cls, b.cls], "states": [a.state, b.state],
                                           "relative_speed_mps": math.hypot(a.vx - b.vx, a.vy - b.vy),
                                           "x": (a.x + b.x) / 2, "y": (a.y + b.y) / 2})
                for obj in (a, b):
                    pose = self._pose(before[obj.id], obj, lo)
                    obj.x, obj.y, obj.heading = pose.x, pose.y, pose.heading
                    obj.vx = obj.vy = 0.0
                    obj.state = "crashed"
                    obj.meta.setdefault("crash_t", self.t)
                    self._release_slot(obj)
                changed = True
            if not changed:
                return True
        return False

    def _overlapping_pairs(self):
        """Broad phase (sweep and prune on x) over the current footprints."""
        bounds = []
        for i, a in enumerate(self.agents):
            r = math.hypot(*a.dims[:2]) / 2
            bounds.append((a.x - r, a.x + r, a.y - r, a.y + r, i))
        active = []
        for x0, x1, y0, y1, i in sorted(bounds):
            active = [b for b in active if b[1] >= x0]
            for b in active:
                if b[3] >= y0 and b[2] <= y1:
                    yield self.agents[b[4]], self.agents[i]
            active.append((x0, x1, y0, y1, i))

    def _separate_soft(self, dt, iterations=24):
        """Push overlapping people/cyclists apart (vehicles and wrecks are immovable here). Returns success."""
        for _ in range(iterations):
            moved = False
            for a, b in list(self._overlapping_pairs()):
                if a.kind == "vehicle" and b.kind == "vehicle":
                    continue
                depth, nx, ny = penetration(a, b)
                if depth <= 1e-7:
                    continue
                pair = tuple(sorted((a.id, b.id)))
                if "vehicle" not in (a.kind, b.kind) and pair not in self.contacts:
                    self.contacts.add(pair)
                    self.gt_events.append({"type": "contact", "t": self.t, "agents": list(pair),
                                           "classes": [a.cls, b.cls], "states": [a.state, b.state],
                                           "relative_speed_mps": math.hypot(a.vx - b.vx, a.vy - b.vy),
                                           "x": (a.x + b.x) / 2, "y": (a.y + b.y) / 2})
                fixed_a = a.kind == "vehicle" or a.state == "crashed"
                fixed_b = b.kind == "vehicle" or b.state == "crashed"
                if fixed_a and fixed_b:
                    continue
                # people waiting at the curb hold their place against arrivals, but step aside for people
                # coming off the crossing (who would otherwise be pushed back into the road)
                wa = 0.0 if fixed_a else self._push_weight(a, b)
                wb = 0.0 if fixed_b else self._push_weight(b, a)
                push = depth + 0.005
                for obj, w, sgn in ((a, wa / (wa + wb), 1.0), (b, wb / (wa + wb), -1.0)):
                    if w <= 0:
                        continue
                    obj.x += sgn * nx * push * w
                    obj.y += sgn * ny * push * w
                    if "side" in obj.meta:
                        self._keep_on_pavement(obj)
                    vn = (obj.vx * nx + obj.vy * ny) * sgn
                    if vn < 0:  # remove only the approaching component: keep sliding
                        obj.vx -= sgn * vn * nx
                        obj.vy -= sgn * vn * ny
                moved = True
            if not moved:
                return True
        return not any(overlaps(a, b) for a, b in self._overlapping_pairs())

    @staticmethod
    def _push_weight(o, other):
        off_crossing = ("cross", "leave")
        if o.state == "wait":
            return 0.75 if other.state in off_crossing else 0.25
        if o.state in off_crossing and other.state == "wait":
            return 0.25
        return 1.0

    def _contacts(self, before):
        # Sweep-and-prune bounds contain every interpolated pose, including rotation.
        bounds = []
        for i, a in enumerate(self.agents):
            previous = before[a.id]
            radius = math.hypot(*a.dims[:2]) / 2
            bounds.append((min(previous.x, a.x) - radius, max(previous.x, a.x) + radius,
                           min(previous.y, a.y) - radius, max(previous.y, a.y) + radius, i))
        active, pairs = [], []
        for bound in sorted(bounds):
            x0, x1, y0, y1, i = bound
            active = [b for b in active if b[1] >= x0]
            for b in active:
                if b[3] >= y0 and b[2] <= y1:
                    pairs.append(tuple(sorted((i, b[4]))))
            active.append(bound)
        for i, j in sorted(pairs):
            a, b = self.agents[i], self.agents[j]
            pa, pb = before[a.id], before[b.id]
            rx, ry = pa.x - pb.x, pa.y - pb.y
            vx, vy = a.x - pa.x - b.x + pb.x, a.y - pa.y - b.y + pb.y
            f = max(0.0, min(1.0, -(rx * vx + ry * vy) / max(vx * vx + vy * vy, 1e-12)))
            radius = (math.hypot(*a.dims[:2]) + math.hypot(*b.dims[:2])) / 2
            if math.hypot(rx + f * vx, ry + f * vy) > radius:
                continue
            travel = math.hypot(a.x - pa.x, a.y - pa.y) + math.hypot(b.x - pb.x, b.y - pb.y)
            rotation = abs(a.heading - pa.heading) * max(a.dims[:2]) / 2 + abs(b.heading - pb.heading) * max(b.dims[:2]) / 2
            steps = max(1, math.ceil((travel + rotation) / 0.15))
            contact = None
            for k in range(1, steps + 1):
                f = k / steps
                qa, qb = self._pose(pa, a, f), self._pose(pb, b, f)
                if overlaps(qa, qb):
                    contact = ((k - 1) / steps, f)
                    break
            if contact is None:
                continue
            lo, hi = contact
            for _ in range(16):
                f = (lo + hi) / 2
                qa, qb = self._pose(pa, a, f), self._pose(pb, b, f)
                if overlaps(qa, qb):
                    hi = f
                else:
                    lo = f
            yield a, b, lo, hi
