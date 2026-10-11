"""Persistent, anonymous crossing statistics. SQLite runs on its own worker thread.

Only hourly aggregates and the last 50 safety notices are persisted. Track identities
exist only in memory while a track can still be reclassified or merged. Civil days
and hours use the node's OS timezone; event timestamps are Unix seconds.
"""
from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta
import json
import math
from pathlib import Path
import queue
import sqlite3
import threading
import time

KINDS = ("pedestrian", "bicycle", "micromobility", "vehicle")
LEVELS = ("potential", "serious", "critical")


def civil(ts):
    local = datetime.fromtimestamp(ts).astimezone()
    return local.date().isoformat(), local.hour


class PublicStats:
    def __init__(self, path, node_id, start=None):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False, timeout=2)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS totals (metric TEXT PRIMARY KEY, value REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS hourly (
                day TEXT, hour INTEGER, metric TEXT, value REAL NOT NULL,
                PRIMARY KEY(day, hour, metric));
            CREATE TABLE IF NOT EXISTS hour_profile (
                hour INTEGER, metric TEXT, value REAL NOT NULL, PRIMARY KEY(hour, metric));
            CREATE TABLE IF NOT EXISTS notices (
                id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL, type TEXT, level TEXT,
                detail TEXT, ttc REAL, pet REAL);
        """)
        owner = self.db.execute("SELECT value FROM meta WHERE key='node'").fetchone()
        if owner and owner[0] != node_id:
            self.db.close()
            raise ValueError("statistics database belongs to a different node")
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO meta VALUES ('node', ?)", (node_id,))
            self.db.execute("INSERT OR IGNORE INTO meta VALUES ('since', ?)", (str(time.time() if start is None else start),))
            if not self.db.execute("SELECT 1 FROM meta WHERE key='hour_profile'").fetchone():
                self.db.execute("INSERT INTO hour_profile SELECT hour,metric,SUM(value) FROM hourly GROUP BY hour,metric")
                self.db.execute("INSERT INTO meta VALUES ('hour_profile','1')")
        self.passages = defaultdict(list)
        self.replacements = defaultdict(deque)
        self.conflicts = {}
        self.queue = queue.Queue(maxsize=4096)
        self.error = None
        self.worker = None
        self.closed = False

    def start(self):
        self.worker = threading.Thread(target=self._work, name="public-statistics", daemon=True)
        self.worker.start()

    def submit(self, event, at):
        """Cheap event-bus callback: never wait for disk in the vision loop."""
        if self.error or self.closed:
            return
        try:
            self.queue.put_nowait((dict(event), at))
        except queue.Full:
            self.error = "statistics queue full"

    def _work(self):
        while True:
            item = self.queue.get()
            try:
                if item is None:
                    return
                if not self.error:
                    # One transaction per batch, shared with readers under the lock.
                    batch = [item]
                    stopping = False
                    while len(batch) < 256:
                        try:
                            nxt = self.queue.get_nowait()
                        except queue.Empty:
                            break
                        if nxt is None:
                            self.queue.task_done()
                            stopping = True
                            break
                        batch.append(nxt)
                    try:
                        with self.lock, self.db:
                            for event, at in batch:
                                self._record(event, at)
                    finally:
                        for _ in batch[1:]:
                            self.queue.task_done()
                    if stopping:
                        return
            except Exception as exc:  # a broken statistics store must never stop vision or hang shutdown
                self.error = str(exc)
            finally:
                self.queue.task_done()

    def record(self, event, at):
        """Synchronous ingestion for deterministic evaluation/tests."""
        with self.lock, self.db:
            self._record(event, at)

    def _add(self, slot, metric, delta):
        self.db.execute("""INSERT INTO hourly VALUES (?, ?, ?, ?)
            ON CONFLICT(day,hour,metric) DO UPDATE SET value=MAX(0,value+excluded.value)""",
                        (*slot, metric, delta))
        self.db.execute("""INSERT INTO totals VALUES (?, ?)
            ON CONFLICT(metric) DO UPDATE SET value=MAX(0,value+excluded.value)""", (metric, delta))
        self.db.execute("""INSERT INTO hour_profile VALUES (?, ?, ?)
            ON CONFLICT(hour,metric) DO UPDATE SET value=MAX(0,value+excluded.value)""", (slot[1], metric, delta))

    def _pass(self, slot, kind, direction, delta):
        self._add(slot, kind, delta)
        if direction:
            self._add(slot, f"dir:{kind}:{direction}", delta)

    def _notice(self, event, at):
        return self.db.execute("INSERT INTO notices(at,type,level,detail,ttc,pet) VALUES (?,?,?,?,?,?)",
                               (at, event["type"], event.get("level"),
                                event.get("alert") or event.get("violation"),
                                event.get("ttc"), event.get("pet"))).lastrowid

    def _record(self, e, at):
        typ, kind, track = e.get("type"), e.get("kind"), e.get("track")
        slot = civil(at)
        if typ == "passage" and kind in KINDS:
            direction = e.get("dir")
            key = (track, direction)
            if e.get("corrected") and self.replacements[key]:
                slot = self.replacements[key].popleft()
            self._pass(slot, kind, direction, 1)
            self.passages[track].append((kind, e.get("cls"), direction, slot))
        elif typ == "count_corrected":
            rows = self.passages.get(track, [])
            for i, (k, cls, direction, original) in enumerate(rows):
                if k == kind and cls == e.get("cls") and direction == e.get("dir"):
                    self._pass(original, k, direction, -1)
                    rows.pop(i)
                    if e.get("reason", "").startswith("reclassified_as_"):
                        self.replacements[(track, direction)].append(original)
                    break
        elif typ == "retire":
            for tid in e["tracks"]:
                self.passages.pop(tid, None)
                for key in list(self.replacements):
                    if key[0] == tid:
                        del self.replacements[key]
                for key in list(self.conflicts):
                    if tid in key[:2]:
                        del self.conflicts[key]
            return
        elif typ == "observation":
            # Distribute coverage across hour/day boundaries rather than assigning
            # the entire interval to its end. Stalls never contribute coverage.
            seconds = max(0.0, float(e["seconds"]))
            cursor = at - seconds
            while cursor < at:
                end = min(at, (math.floor(cursor / 60) + 1) * 60)
                self._add(civil(cursor), "observed_s", end - cursor)
                cursor = end
        elif typ == "conflict" and e.get("level") in LEVELS:
            key = (e.get("vru"), e.get("veh"), e.get("episode_t", e.get("t")))
            previous = self.conflicts.get(key)
            if previous:
                old_level, slot, notice = previous
                if LEVELS.index(e["level"]) <= LEVELS.index(old_level):
                    return
                self._add(slot, f"conflict:{old_level}", -1)
                self.db.execute("UPDATE notices SET level=?,ttc=? WHERE id=?", (e["level"], e.get("ttc"), notice))
            else:
                notice = self._notice(e, at)
            self._add(slot, f"conflict:{e['level']}", 1)
            self.conflicts[key] = (e["level"], slot, notice)
        elif typ in ("alert", "violation", "pet"):
            self._add(slot, typ, 1)
            self._notice(e, at)
        elif typ == "yield" and e.get("outcome") in ("yielded", "not_yielded"):
            self._add(slot, f"yield:{e['outcome']}", 1)
        elif typ == "vehicle_pass":
            speed = e.get("speed_kmh")
            if speed is not None and math.isfinite(speed) and speed >= 0:
                self._add(slot, "speed_sum", speed)
                self._add(slot, "speed_n", 1)
            if e.get("speeding"):
                self._add(slot, "speeding", 1)
        elif typ == "crossing" and kind == "pedestrian":
            self._add(slot, "walk_seconds", e["duration"])
            self._add(slot, "walk_n", 1)
        else:
            return
        self.db.execute("DELETE FROM notices WHERE id <= (SELECT MAX(id)-50 FROM notices)")

    @staticmethod
    def summary(metrics):
        counts = {k: int(metrics.get(k, 0)) for k in KINDS}
        near = {k: int(metrics.get(f"conflict:{k}", 0)) for k in LEVELS}
        y, n = metrics.get("yield:yielded", 0), metrics.get("yield:not_yielded", 0)
        observed = metrics.get("observed_s", 0)
        # Screening indicator, not a crash probability or a certified rating.
        weighted = 3 * near["critical"] + 1.5 * near["serious"] + .5 * near["potential"] + n
        score = 100 * math.exp(-4 * weighted / max(20, counts["vehicle"]))
        return {"counts": counts, "total": sum(counts.values()), "near_misses": near,
                "safety_score": round(score, 1) if counts["vehicle"] >= 20 and observed > 0 else None,
                "yield_rate": round(y / (y + n), 3) if y + n else None,
                "yield_observations": int(y + n), "alerts": int(metrics.get("alert", 0)),
                "red_light_flags": int(metrics.get("violation", 0)), "pet_flags": int(metrics.get("pet", 0)),
                "speeding_flags": int(metrics.get("speeding", 0)),
                "vehicle_mean_kmh": round(metrics["speed_sum"] / metrics["speed_n"], 1) if metrics.get("speed_n") else None,
                "ped_mean_crossing_s": round(metrics["walk_seconds"] / metrics["walk_n"], 1) if metrics.get("walk_n") else None,
                "observed_hours": round(observed / 3600, 6), "observed_seconds": round(observed, 3),
                "directions": {k: {m.split(":", 2)[2]: int(v) for m, v in metrics.items()
                                   if m.startswith(f"dir:{k}:")} for k in KINDS}}

    def snapshot(self, now=None):
        now = time.time() if now is None else now
        day, _ = civil(now)
        days = [(datetime.fromisoformat(day).date() - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
        with self.lock:
            mock_row = self.db.execute("SELECT value FROM meta WHERE key='mock_month'").fetchone()
            mock = json.loads(mock_row[0]) if mock_row else None
            history_days = []
            if mock:
                first = datetime.fromisoformat(mock["start_local"]).date()
                last = min(datetime.fromisoformat(mock["end_local"]).date(), datetime.fromisoformat(day).date())
                history_days = [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]
            totals = dict(self.db.execute("SELECT metric,value FROM totals"))
            profile = self.db.execute("SELECT hour,metric,value FROM hour_profile").fetchall()
            rows = self.db.execute("SELECT day,hour,metric,value FROM hourly WHERE day>=? AND day<=?",
                                   (min(days[0], history_days[0]) if history_days else days[0], day)).fetchall()
            notices = [dict(zip(("at", "type", "level", "detail", "ttc", "pet"), row)) for row in
                       self.db.execute("SELECT at,type,level,detail,ttc,pet FROM notices WHERE at<=? ORDER BY at DESC,id DESC LIMIT 20", (now,))]
            since = float(self.db.execute("SELECT value FROM meta WHERE key='since'").fetchone()[0])
        daily = {d: defaultdict(float) for d in set(days + history_days)}
        hours = {h: defaultdict(float) for h in range(24)}
        week_hours = {h: defaultdict(float) for h in range(24)}
        lifetime_hours = {h: defaultdict(float) for h in range(24)}
        for h, metric, value in profile:
            lifetime_hours[h][metric] = value
        week = defaultdict(float)
        for d, h, metric, value in rows:
            if d in daily:
                daily[d][metric] += value
            if d >= days[0]:
                week[metric] += value
                week_hours[h][metric] += value
            if d == day:
                hours[h][metric] += value
        hourly = [{"hour": h, **self.summary(hours[h])} for h in range(24)]
        peak = max(hourly, key=lambda h: h["total"])
        for notice in notices:
            notice["local_time"] = datetime.fromtimestamp(notice["at"]).astimezone().isoformat()
        return {"since": since, "since_local": datetime.fromtimestamp(since).astimezone().isoformat(),
                "timezone": datetime.fromtimestamp(now).astimezone().tzname(),
                "date": day, "lifetime": self.summary(totals), "today": self.summary(daily[day]),
                "week": self.summary(week), "hourly": hourly,
                "hourly_profiles": {"today": hourly,
                                    "week": [{"hour": h, **self.summary(week_hours[h])} for h in range(24)],
                                    "lifetime": [{"hour": h, **self.summary(lifetime_hours[h])} for h in range(24)]},
                "daily": [{"date": d, **self.summary(daily[d])} for d in days],
                "mock_history": mock,
                "daily_history": [{"date": d, **self.summary(daily[d])} for d in history_days],
                "peak_today": {"hour": peak["hour"], "total": peak["total"]} if peak["total"] else None,
                "recent_notices": notices}

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.worker:
            self.queue.put(None)
            self.worker.join()
        with self.lock:
            self.db.close()
