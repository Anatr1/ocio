"""Metric lane routes and crossings for a right-hand-traffic four-arm junction."""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from functools import cached_property
import math

ARMS = ("N", "E", "S", "W")
TURNS = ("straight", "left", "right")
FORWARD = {"N": (0., -1.), "E": (-1., 0.), "S": (0., 1.), "W": (1., 0.)}


def right(vector):
    x, y = vector
    return y, -x


def add(a, b, scale=1.):
    return a[0] + b[0] * scale, a[1] + b[1] * scale


@dataclass
class Route:
    id: str
    origin: str
    destination: str
    turn: str
    lane: str
    points: list
    distances: list
    entry_s: float
    exit_s: float
    stop_s: float
    clear_s: float

    @property
    def length(self):
        return self.distances[-1]

    def pose(self, distance):
        distance = min(self.length, max(0., distance))
        i = min(len(self.points) - 2, max(0, bisect_right(self.distances, distance) - 1))
        a, b = self.points[i:i + 2]
        span = self.distances[i + 1] - self.distances[i]
        f = (distance - self.distances[i]) / max(span, 1e-9)
        return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f,
                math.atan2(b[1] - a[1], b[0] - a[0]))


@dataclass
class IntersectionGeometry:
    lane_width: float = 3.5
    approach: float = 65.
    crosswalk_width: float = 3.

    def __post_init__(self):
        if not 3 <= self.lane_width <= 4.5 or self.approach < 35:
            raise ValueError("intersection requires lane width 3–4.5 m and approach >= 35 m")

    @property
    def half_road(self):
        return 2 * self.lane_width

    @property
    def crossing_radius(self):
        return self.half_road + 3.5

    @property
    def stop_radius(self):
        return self.crossing_radius + self.crosswalk_width / 2 + 2.

    @cached_property
    def routes(self):
        result = {}
        h = self.half_road
        for arm in ARMS:
            forward = FORWARD[arm]
            lateral = right(forward)
            index = ARMS.index(arm)
            for turn in TURNS:
                destination = ARMS[(index + {"straight": 2, "left": 1, "right": -1}[turn]) % 4]
                outward = tuple(-v for v in FORWARD[destination])
                offset = self.lane_width * (.5 if turn == "left" else 1.5)
                start = add(tuple(-v * self.approach for v in forward), lateral, offset)
                entry = add(tuple(-v * h for v in forward), lateral, offset)
                exit_point = add(tuple(v * h for v in outward), right(outward), offset)
                finish = add(tuple(v * self.approach for v in outward), right(outward), offset)
                if turn == "straight":
                    curve = [entry, exit_point]
                else:
                    # Turn on the near side of the junction centre. A deeper arc
                    # intersects the opposing protected-left vehicle footprint.
                    tangent = 3. if turn == "left" else (h - offset) * .55228475
                    c1 = add(entry, forward, tangent)
                    c2 = add(exit_point, outward, -tangent)
                    curve = []
                    for k in range(41):
                        t, u = k / 40, 1 - k / 40
                        curve.append(tuple(u**3 * entry[j] + 3*u*u*t*c1[j] +
                                           3*u*t*t*c2[j] + t**3*exit_point[j] for j in (0, 1)))
                points = [start, *curve, finish]
                distances = [0.]
                for a, b in zip(points, points[1:]):
                    distances.append(distances[-1] + math.dist(a, b))
                entry_s, exit_s = distances[1], distances[-2]
                rid = f"{arm}_{turn}"
                result[rid] = Route(rid, arm, destination, turn, "left" if turn == "left" else "through",
                                    points, distances, self.approach - h,
                                    exit_s, self.approach - self.stop_radius,
                                    exit_s + self.stop_radius - h + 3.)
        return result

    def crossing(self, arm, direction=1, offset=0.):
        f = FORWARD[arm]
        center = tuple(-v * self.crossing_radius for v in f)
        lateral = right(f)
        extent = self.half_road + 1.5
        start = add(add(center, f, offset), lateral, -direction * extent)
        finish = add(add(center, f, offset), lateral, direction * extent)
        return start, finish

    def payload(self):
        return {"lane_width": self.lane_width, "half_road": self.half_road, "approach": self.approach,
                "crosswalk_width": self.crosswalk_width, "crossing_radius": self.crossing_radius,
                "stop_radius": self.stop_radius,
                "crosswalks": {a: {"start": self.crossing(a)[0], "end": self.crossing(a)[1]} for a in ARMS},
                "routes": {k: {"points": r.points, "origin": r.origin, "destination": r.destination,
                                "turn": r.turn, "lane": r.lane} for k, r in self.routes.items()}}
