"""Citizen statistics: persistence, corrections, coverage and the public HTTP contract."""
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from crosswalk.config import load_config
from crosswalk.pipeline import Node
from crosswalk.public_stats import PublicStats


def stamp(day=10, hour=12, minute=0, second=0):
    return datetime(2026, 10, day, hour, minute, second).timestamp()


def passage(track=1, kind="pedestrian", direction="A>B", **extra):
    return {"type": "passage", "track": track, "kind": kind, "cls": kind, "dir": direction, **extra}


def test_history_survives_restart_and_operator_reset(tmp_path):
    path = tmp_path / "stats.sqlite3"
    store = PublicStats(path, "crossing-1", stamp())
    store.record(passage(), stamp())
    store.record({"type": "reset"}, stamp())  # operator session reset never clears history
    store.close()
    store = PublicStats(path, "crossing-1", stamp(11))
    try:
        store.record(passage(), stamp(11))  # IDs restart each process; it is a new passage
        data = store.snapshot(stamp(11))
        assert data["lifetime"]["counts"]["pedestrian"] == 2
        assert data["today"]["total"] == 1
        assert data["since"] == stamp()
        assert data["week"]["total"] == 2
    finally:
        store.close()
    with pytest.raises(ValueError, match="different node"):
        PublicStats(path, "different-crossing")


def test_return_crossing_reclassification_stays_in_original_hours():
    store = PublicStats(":memory:", "test", stamp())
    try:
        store.record(passage(), stamp(10, 23, 59))
        store.record(passage(direction="B>A"), stamp(11, 0, 1))
        for direction in ("A>B", "B>A"):
            store.record({"type": "count_corrected", "track": 1, "kind": "pedestrian", "cls": "pedestrian",
                          "dir": direction, "reason": "reclassified_as_bicycle"}, stamp(11, 1))
            store.record(passage(kind="bicycle", direction=direction, corrected=True), stamp(11, 1))
        data = store.snapshot(stamp(11, 2))
        assert data["lifetime"]["counts"] == {"pedestrian": 0, "bicycle": 2, "micromobility": 0, "vehicle": 0}
        assert data["today"]["counts"]["bicycle"] == 1
        assert data["hourly"][0]["counts"]["bicycle"] == 1
        assert data["hourly"][1]["total"] == 0
        assert data["lifetime"]["directions"]["bicycle"] == {"A>B": 1, "B>A": 1}
        store.record({"type": "count_corrected", "track": 1, "kind": "bicycle", "cls": "bicycle",
                      "dir": "A>B", "reason": "merged_duplicate"}, stamp(11, 2))
        assert store.snapshot(stamp(11, 2))["lifetime"]["total"] == 1
    finally:
        store.close()


def test_unknown_correction_cannot_subtract_other_tracks():
    store = PublicStats(":memory:", "test", stamp())
    try:
        store.record(passage(), stamp())
        store.record({"type": "count_corrected", "track": 99, "kind": "pedestrian", "cls": "pedestrian", "dir": "A>B"}, stamp())
        assert store.snapshot(stamp())["lifetime"]["total"] == 1
        store.record({"type": "retire", "tracks": [1]}, stamp())
        assert not store.passages
    finally:
        store.close()


def test_conflict_escalation_is_one_episode_at_highest_severity():
    store = PublicStats(":memory:", "test", stamp())
    try:
        event = {"type": "conflict", "vru": 4, "veh": 5, "episode_t": 1, "t": 2, "level": "potential", "ttc": 2.6,
                 "x": 123, "y": 456, "veh_cls": "car"}
        store.record(event, stamp(10, 23, 59))
        store.record({**event, "t": 3, "level": "critical", "ttc": .5}, stamp(11, 0, 1))
        store.record({**event, "t": 4, "level": "serious"}, stamp(11, 0, 2))
        data = store.snapshot(stamp(11, 1))
        assert data["lifetime"]["near_misses"] == {"potential": 0, "serious": 0, "critical": 1}
        assert sum(data["today"]["near_misses"].values()) == 0
        assert len(data["recent_notices"]) == 1 and data["recent_notices"][0]["ttc"] == .5
        assert not {"vru", "veh", "x", "y", "veh_cls"}.intersection(data["recent_notices"][0])
        store.record({**event, "episode_t": 20}, stamp(11, 1))
        assert len(store.snapshot(stamp(11, 2))["recent_notices"]) == 2
    finally:
        store.close()


def test_hourly_daily_peaks_and_observation_gaps():
    store = PublicStats(":memory:", "test", stamp())
    try:
        store.record({"type": "observation", "seconds": 2}, stamp(11, 0, 0, 1))
        store.record(passage(), stamp(11, 8))
        store.record(passage(track=2, kind="vehicle", direction="+X"), stamp(11, 8))
        store.record(passage(track=3), stamp(11, 9))
        data = store.snapshot(stamp(11, 10))
        assert len(data["hourly"]) == 24 and len(data["daily"]) == 7
        assert data["peak_today"] == {"hour": 8, "total": 2}
        assert data["today"]["observed_hours"] == pytest.approx(1/3600, abs=.0005)
        assert data["lifetime"]["observed_hours"] == pytest.approx(2/3600, abs=.0005)
        assert data["hourly"][5]["observed_hours"] == 0
        assert data["daily"][-2]["observed_hours"] > 0
        assert data["hourly_profiles"]["lifetime"][23]["observed_hours"] > 0
        assert data["hourly_profiles"]["week"][8]["total"] == 2
    finally:
        store.close()


def test_safety_metrics_require_samples_and_notices_are_bounded():
    store = PublicStats(":memory:", "test", stamp())
    try:
        assert store.snapshot(stamp())["lifetime"]["safety_score"] is None
        assert store.snapshot(stamp())["lifetime"]["yield_rate"] is None
        for tid in range(20):
            store.record(passage(tid, "vehicle", "+X"), stamp())
        store.record({"type": "observation", "seconds": 5}, stamp())
        store.record({"type": "yield", "outcome": "yielded"}, stamp())
        store.record({"type": "yield", "outcome": "not_yielded"}, stamp())
        store.record({"type": "vehicle_pass", "speed_kmh": 42, "speeding": True}, stamp())
        for i in range(70):
            store.record({"type": "alert", "alert": "vehicle_blocking_crosswalk"}, stamp() + i)
        data = store.snapshot(stamp() + 70)
        assert data["lifetime"]["yield_rate"] == .5
        assert data["lifetime"]["vehicle_mean_kmh"] == 42
        assert data["lifetime"]["speeding_flags"] == 1
        assert data["lifetime"]["safety_score"] < 100
        assert data["lifetime"]["alerts"] == 70
        assert len(data["recent_notices"]) == 20
        assert store.db.execute("SELECT COUNT(*) FROM notices").fetchone()[0] == 50
    finally:
        store.close()


def test_worker_drains_on_close_and_reports_storage_failure(tmp_path):
    store = PublicStats(tmp_path / "stats.sqlite3", "test", stamp())
    store.start()
    for tid in range(100):
        store.submit(passage(tid), stamp())
    store.close()
    reopened = PublicStats(tmp_path / "stats.sqlite3", "test")
    assert reopened.snapshot(stamp())["lifetime"]["total"] == 100
    reopened.start()
    def fail(*args):
        raise sqlite3.OperationalError("disk full")
    reopened._record = fail
    reopened.submit(passage(), stamp())
    reopened.queue.join()
    assert reopened.error == "disk full"
    reopened.close()


class FakeSource:
    width, height, live = 64, 48, True
    def __init__(self):
        self.t = 0
        self.seq = 0
    def read(self, *args):
        self.seq += 1
        return np.zeros((48, 64, 3), np.uint8), self.t, self.seq
    def stats(self):
        return {}
    def close(self):
        pass


def make_node(tmp_path, source_type="camera", server=False, server_host="127.0.0.1", mock_month=False, demo=None):
    cfg = load_config(overrides=["detector.backend=sim", "mcu.enabled=false", "log.dir=", "detector.motion_gate=false"])
    cfg.source.type = source_type
    cfg.server.enabled = server
    cfg.server.host = server_host
    cfg.server.port = 0
    cfg.public.stats_dir = str(tmp_path)
    cfg.public.mock_month = mock_month
    cfg.public.demo = demo
    return Node(cfg, source=FakeSource())


@pytest.mark.parametrize("source_type,demo,expected", [
    ("render", None, True), ("render", False, False), ("camera", None, False),
    ("network", True, False), ("sim", None, False), ("video", None, False),
])
def test_mock_month_is_exclusive_to_isolated_render_runs(tmp_path, source_type, demo, expected):
    node = make_node(tmp_path, source_type, mock_month=True, demo=demo)
    try:
        stats = node.public_payload()["statistics"]
        assert bool(stats["mock_history"]) is expected
        assert (stats["lifetime"]["total"] > 0) is expected
        assert node.public_payload()["node"]["brand"] == "òcio"
        assert node.counter.counts["pedestrian"] == 0
    finally:
        node.close()


def test_render_without_mock_option_keeps_only_observed_statistics(tmp_path):
    node = make_node(tmp_path, "render")
    try:
        assert node.public_payload()["statistics"]["mock_history"] is None
        assert node.public_payload()["statistics"]["lifetime"]["total"] == 0
    finally:
        node.close()


def test_node_demo_isolation_and_public_projection(tmp_path, monkeypatch):
    node = make_node(tmp_path)
    try:
        node.step()
        node.bus.emit(passage())
        node.public_stats.queue.join()
        data = node.public_payload()
        assert data["statistics"]["lifetime"]["total"] == 1
        assert data["data_mode"] == "live" and data["live"]["healthy"]
        assert not {"tracks", "record", "perf", "scene", "source", "bbox"}.intersection(data)
        node.reset_counts()
        node.public_stats.queue.join()
        assert node.public_payload()["statistics"]["lifetime"]["total"] == 1
        monkeypatch.setattr(node.mcu, "vision_age", lambda: 99)
        assert not node.public_payload()["live"]["healthy"]
        assert node.public_payload()["live"]["visible"] is None
        node.public_stats.error = "disk full"
        assert not node.public_payload()["statistics_available"]
        assert node.public_payload()["statistics"] is None
        assert node.step()  # statistics failure does not stop the vision pipeline
    finally:
        node.close()
    demo = make_node(tmp_path, "video")
    try:
        assert demo.public_demo
        assert demo.public_payload()["statistics"]["lifetime"]["total"] == 0
        assert demo.public_stats.db.execute("PRAGMA database_list").fetchone()[2] == ""
    finally:
        demo.close()


def test_node_coverage_excludes_stall_and_keeps_partial_interval_in_original_day(tmp_path):
    node = make_node(tmp_path, "video")
    node._public_epoch = stamp(10, 23, 59, 59)
    try:
        for t in (0, .6, 10, 10.6, 11.2):
            node.source.t = t
            node.step()
        node.public_stats.queue.join()
        data = node.public_payload()["statistics"]
        assert data["lifetime"]["observed_seconds"] == pytest.approx(1.8)
        assert data["today"]["observed_seconds"] == pytest.approx(1.2)
        assert data["daily"][-2]["observed_seconds"] == pytest.approx(.6)
    finally:
        node.close()


@pytest.mark.parametrize("listen_host", ["127.0.0.1", "0.0.0.0"])
def test_share_url_respects_listening_interface(tmp_path, monkeypatch, listen_host):
    node = make_node(tmp_path, server=True, server_host=listen_host)
    node.server.start()
    base = f"http://localhost:{node.server.httpd.server_port}"
    monkeypatch.setattr("crosswalk.server.lan_ip", lambda: "192.168.1.20")
    try:
        with urlopen(base + "/api/share") as response:
            data = json.load(response)
        if listen_host == "127.0.0.1":
            assert data["url"] == base + "/public/"
            # Following the advertised URL must actually reach the citizen page.
            with urlopen(data["url"]) as response:
                assert response.status == 200
                assert b"public.js" in response.read()
        else:
            assert data["url"] == f"http://192.168.1.20:{node.server.httpd.server_port}/public/"
    finally:
        node.close()
        node.server.httpd.server_close()


def test_public_http_and_qr_use_only_public_routes(tmp_path, monkeypatch):
    node = make_node(tmp_path, server=True)
    node.server.start()
    base = f"http://127.0.0.1:{node.server.httpd.server_port}"
    monkeypatch.setattr("crosswalk.server.lan_ip", lambda: "192.168.1.20")
    try:
        for suffix in ("/public/", "/public/public.js", "/public/public.css", "/public/theme.css", "/public/fonts/manrope-latin.woff2"):
            with urlopen(base + suffix) as response:
                assert response.status == 200
        with urlopen(base + "/public/api/stats") as response:
            data = json.load(response)
            assert data["schema_version"] == 1
            assert response.headers["Cache-Control"] == "no-store"
        for suffix in ("/public/api/reset", "/public/api/state", "/public/video.mjpg", "/public/recordings"):
            with pytest.raises(HTTPError) as error:
                urlopen(base + suffix)
            assert error.value.code == 404
        with pytest.raises(HTTPError) as error:
            urlopen(Request(base + "/public/api/mode", data=b'{"mode":"beacon"}', headers={"Content-Type": "application/json"}))
        assert error.value.code == 405 and node.signal.mode == "adaptive"
        with urlopen(base + "/api/share") as response:
            assert json.load(response)["url"] == base + "/public/"
        node.cfg.public.url = "https://crossing.example/public/"
        with urlopen(base + "/api/share") as response:
            assert json.load(response)["url"] == "https://crossing.example/public/"
        node.cfg.public.url = "javascript:alert(1)"
        with pytest.raises(HTTPError) as error:
            urlopen(base + "/api/share")
        assert error.value.code == 400
        node.cfg.public.enabled = False
        with pytest.raises(HTTPError) as error:
            urlopen(base + "/public/api/stats")
        assert error.value.code == 404
    finally:
        node.close()
        node.server.httpd.server_close()
