"""Generated presentation history for the photoreal dashboard, never validation evidence."""
from __future__ import annotations

import calendar
from datetime import datetime, timedelta
import hashlib
import json
import math
import random

from crosswalk.public_stats import civil


def month_before(now):
    """Same local time in the preceding calendar month, clamped at month end."""
    current = datetime.fromtimestamp(now)
    year, month = (current.year - 1, 12) if current.month == 1 else (current.year, current.month - 1)
    return current.replace(year=year, month=month, day=min(current.day, calendar.monthrange(year, month)[1])).timestamp()


def _bump(hour, center, width):
    return math.exp(-.5 * ((hour - center) / width) ** 2)


def _profile(kind, hour, weekend):
    if weekend:
        return .025 + _bump(hour, 13, 3.5) + .6 * _bump(hour, 19, 2.5)
    if kind == "vehicle":
        return .10 + _bump(hour, 8, 1.5) + 1.15 * _bump(hour, 18, 1.8) + .4 * _bump(hour, 13, 3)
    return .015 + _bump(hour, 8, 1.1) + 1.1 * _bump(hour, 18, 1.5) + .65 * _bump(hour, 13, 2)


def _poisson(rng, mean):
    limit, product, n = math.exp(-mean), 1.0, 0
    while product > limit:
        product *= rng.random()
        n += 1
    return max(0, n - 1)


def populate(store, now, length_m, speed_limit_kmh):
    """Seed an empty run store once, using hourly aggregates rather than fake tracks.

    The caller must enforce render-only, isolated demo storage. No changes are made
    to session counts, safety decisions, renderer ground truth or detector input.
    """
    with store.lock, store.db:
        existing = store.db.execute("SELECT value FROM meta WHERE key='mock_month'").fetchone()
        if existing:
            return json.loads(existing[0])
        if store.db.execute("SELECT 1 FROM totals LIMIT 1").fetchone():
            raise ValueError("mock history requires an empty demo statistics store")
        start = month_before(now)
        node_id = store.db.execute("SELECT value FROM meta WHERE key='node'").fetchone()[0]
        seed = int(hashlib.sha256(str(node_id).encode()).hexdigest()[:16], 16)
        metadata = {"synthetic": True, "model": "urban-month-v1", "start": start, "end": now,
                    "start_local": datetime.fromtimestamp(start).astimezone().isoformat(),
                    "end_local": datetime.fromtimestamp(now).astimezone().isoformat(),
                    "description": "Generated month of urban traffic; not measured observations or validation evidence."}
        cursor = start
        while cursor < now:
            local = datetime.fromtimestamp(cursor)
            hour_end = (local.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)).timestamp()
            end = min(now, hour_end)
            day, hour = civil(cursor)
            rng = random.Random(seed ^ (int(day.replace("-", "")) * 100 + hour))
            day_rng = random.Random(seed ^ int(day.replace("-", "")))
            weekend = local.weekday() >= 5
            daily_factor = day_rng.uniform(.86, 1.14)
            # Occasional brief outages and ordinary small gaps in coverage.
            coverage = rng.uniform(.965, .998)
            if day_rng.random() < .15 and hour == 3:
                coverage = 0
            observed = (end - cursor) * coverage
            slot = (day, hour)
            store._add(slot, "observed_s", observed)
            counts = {}
            for kind, daily in (("pedestrian", 1250 if weekend else 1550),
                                ("bicycle", 180 if weekend else 260),
                                ("vehicle", 3400 if weekend else 5200)):
                weight = _profile(kind, hour + .5, weekend)
                normalization = sum(_profile(kind, h + .5, weekend) for h in range(24))
                count = round(daily * daily_factor * weight / normalization * observed / 3600 * rng.uniform(.90, 1.10))
                counts[kind] = count
                # Morning/evening commuting changes the directional balance.
                outward = .62 if hour < 12 else .40
                first = round(count * rng.uniform(outward - .07, outward + .07))
                directions = ("+X", "-X") if kind == "vehicle" else ("A>B", "B>A")
                for direction, number in zip(directions, (first, count - first)):
                    store._pass(slot, kind, direction, number)
            vehicles, pedestrians = counts["vehicle"], counts["pedestrian"]
            opportunities = round(pedestrians * rng.uniform(.12, .20))
            yielded = round(opportunities * rng.uniform(.90, .98))
            mean_speed = max(8, min(speed_limit_kmh, speed_limit_kmh * (.56 if hour in (8, 17, 18) else .70) + rng.uniform(-3, 3)))
            for metric, value in {"yield:yielded": yielded, "yield:not_yielded": opportunities - yielded,
                                  "speed_n": vehicles, "speed_sum": vehicles * mean_speed,
                                  "speeding": round(vehicles * rng.uniform(.008, .025)),
                                  "walk_n": pedestrians, "walk_seconds": pedestrians * length_m / rng.uniform(1.15, 1.50)}.items():
                store._add(slot, metric, value)
            notice_types = (("conflict:potential", .0012, {"type": "conflict", "level": "potential", "ttc": 2.5}),
                            ("conflict:serious", .0002, {"type": "conflict", "level": "serious", "ttc": 1.3}),
                            ("conflict:critical", .000012, {"type": "conflict", "level": "critical", "ttc": .6}),
                            ("pet", .0005, {"type": "pet", "pet": 1.6}),
                            ("alert", .0003, {"type": "alert", "alert": "vehicle_blocking_crosswalk"}))
            for metric, rate, event in notice_types:
                amount = _poisson(rng, vehicles * rate)
                store._add(slot, metric, amount)
                for _ in range(amount):
                    store._notice(event, rng.uniform(cursor, end))
            store._add(slot, "violation", _poisson(rng, pedestrians * .0015))
            cursor = end
        store.db.execute("DELETE FROM notices WHERE id NOT IN (SELECT id FROM notices ORDER BY at DESC,id DESC LIMIT 50)")
        store.db.execute("UPDATE meta SET value=? WHERE key='since'", (str(start),))
        store.db.execute("INSERT INTO meta VALUES ('mock_month', ?)", (json.dumps(metadata),))
        return metadata
