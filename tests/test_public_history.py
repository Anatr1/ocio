"""Mock history remains coherent, calendar-based and separate from measured data."""
from datetime import datetime
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from crosswalk.public_stats import PublicStats
from sim.public_history import month_before, populate


@pytest.mark.parametrize("end,start", [("2026-10-11T10:30:00", "2026-09-11T10:30:00"),
    ("2026-03-31T12:00:00", "2026-02-28T12:00:00"),
    ("2024-03-31T12:00:00", "2024-02-29T12:00:00"),
    ("2026-01-05T09:00:00", "2025-12-05T09:00:00")])
def test_previous_calendar_month(end, start):
    assert month_before(datetime.fromisoformat(end).timestamp()) == datetime.fromisoformat(start).timestamp()


def test_month_is_coherent_repeatable_and_has_realistic_daily_patterns(tmp_path):
    now = datetime(2026, 10, 11, 10, 30).timestamp()
    path = tmp_path / "demo.sqlite3"
    store = PublicStats(path, "same-crosswalk", now)
    try:
        populate(store, now, 8, 50)
        data = store.snapshot(now)
        assert data["since"] == month_before(now)
        assert data["mock_history"]["synthetic"]
        days = data["daily_history"]
        assert len(days) == 31
        assert days[0]["date"] == "2026-09-11" and days[-1]["date"] == "2026-10-11"
        assert sum(d["total"] for d in days) == data["lifetime"]["total"]
        assert sum(d["total"] for d in data["daily"]) == data["week"]["total"]
        assert data["week"]["total"] < data["lifetime"]["total"]
        assert data["today"] == {k: v for k, v in days[-1].items() if k != "date"}
        lifetime = data["lifetime"]
        for kind, count in lifetime["counts"].items():
            assert sum(lifetime["directions"][kind].values()) == count
        assert 100_000 < lifetime["counts"]["vehicle"] < 200_000
        assert .90 < lifetime["yield_rate"] < .99
        assert 20 < lifetime["vehicle_mean_kmh"] < 50
        assert 5 < lifetime["ped_mean_crossing_s"] < 8
        assert .94 * (now - data["since"]) <= lifetime["observed_seconds"] <= now - data["since"]
        hours = data["hourly_profiles"]["lifetime"]
        assert hours[8]["total"] > hours[3]["total"] * 3
        assert hours[18]["total"] > hours[3]["total"] * 3
        assert all(h["total"] == 0 for h in data["hourly"][11:])
        weekdays = [d["total"] for d in days[1:-1] if datetime.fromisoformat(d["date"]).weekday() < 5]
        weekends = [d["total"] for d in days[1:-1] if datetime.fromisoformat(d["date"]).weekday() >= 5]
        assert sum(weekdays) / len(weekdays) > sum(weekends) / len(weekends) * 1.2
        assert len(data["recent_notices"]) == 20
        assert all(data["since"] <= n["at"] <= now for n in data["recent_notices"])
        assert store.db.execute("SELECT COUNT(*) FROM notices").fetchone()[0] <= 50
        assert not store.passages and not store.conflicts
        populate(store, now, 8, 50)
        assert store.snapshot(now) == data  # seeding is idempotent
    finally:
        store.close()
    reopened = PublicStats(path, "same-crosswalk", now)
    fresh = PublicStats(":memory:", "same-crosswalk", now)
    try:
        assert reopened.snapshot(now) == data
        populate(fresh, now, 8, 50)
        assert fresh.snapshot(now) == data
        # Live events add to today's and monthly history without changing session semantics.
        reopened.record({"type": "passage", "track": 1, "kind": "pedestrian", "dir": "A>B"}, now)
        live = reopened.snapshot(now)
        assert live["lifetime"]["total"] == lifetime["total"] + 1
        assert live["daily_history"][-1]["total"] == days[-1]["total"] + 1
    finally:
        reopened.close()
        fresh.close()


def test_seeder_refuses_to_overwrite_observed_data():
    store = PublicStats(":memory:", "real-data")
    try:
        store.record({"type": "passage", "track": 1, "kind": "vehicle", "dir": "+X"}, datetime(2026, 10, 11).timestamp())
        with pytest.raises(ValueError, match="empty demo"):
            populate(store, datetime(2026, 10, 11).timestamp(), 8, 50)
        assert store.snapshot()["lifetime"]["total"] == 1
        assert store.snapshot()["mock_history"] is None
    finally:
        store.close()
