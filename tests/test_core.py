"""Core regression tests:  python -m pytest -q"""
import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crosswalk import msgpack_lite  # noqa: E402
from crosswalk.config import load_config  # noqa: E402
from crosswalk.counting import Counter  # noqa: E402
from crosswalk.detectors.base import Detection, decode_yolo, nms  # noqa: E402
from crosswalk.geometry import Camera, apply_h, homography_dlt  # noqa: E402
from crosswalk.safety import drac, ttc_box  # noqa: E402
from crosswalk.scene import Scene  # noqa: E402
from crosswalk.tracker import Track, Tracker  # noqa: E402


# ------------------------------------------------------------------ geometry
def test_homography_roundtrip():
    src = [(0, 0), (100, 0), (100, 50), (0, 50), (30, 20)]
    H = homography_dlt(src[:4], [(0, 0), (4, 0), (4, 2), (0, 2)])
    p = apply_h(H, [(50, 25)])[0]
    assert np.allclose(p, (2, 1), atol=1e-6)


def test_camera_pose_from_homography():
    cam = Camera.look_at([-7, -7, 5.5], [3, 0.5, 0], 640, 480, hfov_deg=78)
    est, info = Camera.from_ground_homography(cam.H_i2w, 640, 480)
    assert info["focal_source"] == "estimated"
    assert abs(info["hfov_deg"] - 78) < 1.0
    assert abs(est.center[2] - 5.5) < 0.05
    # height of a 1.75 m person from its box
    foot = cam.project([(2, 1, 0)])[0][0]
    head = cam.project([(2, 1, 1.75)])[0][0]
    h = est.height_from_box(foot, head[1])
    assert abs(h - 1.75) < 0.05


def test_scene_sign_normalisation():
    cam = Camera.look_at([-7, -7, 5.5], [3, 0.5, 0], 640, 480, hfov_deg=78)
    cfg = load_config(None)
    W, L = cfg.scene.crosswalk.width, cfg.scene.crosswalk.length
    pts = cam.project([(-W / 2, -L / 2, 0), (W / 2, -L / 2, 0), (W / 2, L / 2, 0), (-W / 2, L / 2, 0)])[0]
    cfg.scene.calibration.image_points = pts.tolist()
    sc = Scene(cfg.scene, (640, 480), cfg.tracker)
    Hinv = np.linalg.inv(sc.H)
    assert (Hinv @ np.array([0, 0, 1.0]))[2] > 0  # visible ground point has positive w
    assert abs(sc.cal_info["camera_height_m"] - 5.5) < 0.1


# ------------------------------------------------------------------ detector post-processing
def test_decode_v8_and_end2end():
    nc = 80
    out = np.zeros((1, 4 + nc, 3), np.float32)
    out[0, :4, 0] = [100, 100, 20, 40]
    out[0, 4 + 0, 0] = 0.9            # person
    out[0, :4, 1] = [102, 101, 20, 40]
    out[0, 4 + 0, 1] = 0.8            # duplicate -> suppressed
    out[0, :4, 2] = [200, 200, 50, 30]
    out[0, 4 + 2, 2] = 0.7            # car
    det = decode_yolo(out, 0.25, 0.5, None, 320, nc=80)
    assert len(det) == 2
    e2e = np.array([[[90, 80, 110, 120, 0.9, 0], [10, 10, 20, 20, 0.1, 2]]], np.float32)
    det = decode_yolo(e2e, 0.25, 0.5, None, 320, nc=80)
    assert len(det) == 1 and int(det[0, 5]) == 0


def test_nms_basic():
    b = np.array([[0, 0, 10, 10], [1, 1, 11, 11], [50, 50, 60, 60]], np.float32)
    s = np.array([0.9, 0.8, 0.7], np.float32)
    assert sorted(nms(b, s, 0.5).tolist()) == [0, 2]


# ------------------------------------------------------------------ tracking + counting on synthetic ground tracks
def _det(x, y, cls="person", score=0.9):
    d = Detection(0, 0, 10, 20, score, cls)
    d.kind = {"person": "pedestrian", "car": "vehicle", "bicycle": "bicycle"}[cls]
    d.world = (x, y)
    d.cov = np.eye(2) * 0.05
    return d


def _run(tracks_fn, seconds, hz=8.0):
    cfg = load_config(None)
    cfg.scene.calibration.image_points = None
    sc = Scene(cfg.scene, (640, 480), cfg.tracker)
    Track._next_id = 1
    tr = Tracker(cfg.tracker, sc, conf_high=0.35)
    events = []
    cnt = Counter(sc, cfg.counting, events.append)
    t = 0.0
    while t < seconds:
        dets = tracks_fn(t)
        live = tr.update(t, dets)
        cnt.update(t, live, tr.ended_now)
        t += 1.0 / hz
    return tr, cnt, events


def test_pedestrian_crossing_counted_once():
    rng = np.random.default_rng(0)
    tr, cnt, ev = _run(lambda t: [_det(0.3 + rng.normal(0, 0.05), -6 + 1.3 * t + rng.normal(0, 0.05))], 9.5)
    assert cnt.counts["pedestrian"] == 1
    assert any(e["type"] == "crossing" for e in ev)


def test_stationary_pedestrian_at_curb_not_counted():
    rng = np.random.default_rng(1)
    tr, cnt, ev = _run(lambda t: [_det(0.5 + rng.normal(0, 0.15), -4.4 + rng.normal(0, 0.15))], 20)
    assert cnt.counts["pedestrian"] == 0


def test_vehicle_pass_with_speed():
    tr, cnt, ev = _run(lambda t: [_det(-20 + 12.0 * t, -2.0, "car")], 3.5)
    assert cnt.counts["vehicle"] == 1
    vp = [e for e in ev if e["type"] == "vehicle_pass"]
    assert vp and abs(vp[0]["speed_kmh"] - 43.2) < 4


def test_fast_person_without_bike_box_is_counted_as_bicycle():
    # the board detector often finds the rider but not the thin bicycle: a 'person' crossing at 5 m/s
    tr, cnt, ev = _run(lambda t: [_det(0.3, -6 + 5.0 * t)], 3.0)
    assert cnt.counts["bicycle"] == 1 and cnt.counts["pedestrian"] == 0


def test_person_crossing_back_is_counted_again():
    # site recording: people crossed, turned around beyond the zebra and crossed back on the same track
    def f(t):
        y = -6 + 1.3 * t if t < 9 else 5.7 - 1.3 * (t - 9)
        return [_det(0.3, y)]
    tr, cnt, ev = _run(f, 18.5)
    passages = [e for e in ev if e["type"] == "passage"]
    assert cnt.counts["pedestrian"] == 2 and [p["dir"] for p in passages] == ["A>B", "B>A"]


def test_hesitating_in_the_middle_is_counted_once():
    def f(t):  # steps past the midline, turns back before the far side, returns to the start
        y = -6 + 1.3 * t if t < 5 else 0.5 - 1.3 * (t - 5)
        return [_det(0.3, y)]
    tr, cnt, ev = _run(f, 10)
    assert cnt.counts["pedestrian"] == 1


def test_implausibly_short_person_boxes_are_dropped():
    # site recording: hanging leaves detected as a 0.5-0.6 m "person" for the whole clip
    from types import SimpleNamespace
    from crosswalk.pipeline import Node
    node = SimpleNamespace(cfg=load_config(None))
    leaves, person, rider_bike = _det(-3.2, -1.9), _det(0.0, 0.0), _det(0.0, 0.0, "bicycle")
    leaves.height_m, person.height_m, rider_bike.height_m = 0.55, 1.78, 0.55
    assert Node._plausible(node, [leaves, person, rider_bike]) == [person, rider_bike]


def test_occlusion_reidentified_same_id():
    def f(t):
        if 3.0 < t < 5.5:  # 2.5 s occlusion (longer than the track max age)
            return []
        return [_det(0.0, -6 + 1.3 * t)]

    tr, cnt, ev = _run(f, 9.5)
    assert cnt.counts["pedestrian"] == 1
    assert tr.revived >= 1


# ------------------------------------------------------------------ safety
class _T:
    def __init__(self, pos, vel, dims=(4.4, 1.8, 1.5)):
        self.pos, self.vel, self.dims = pos, vel, dims
        self.heading = math.atan2(vel[1], vel[0]) if math.hypot(*vel) > 0 else 0.0


def test_ttc_and_drac():
    ped = _T((0.0, 0.0), (0.0, 0.0), (0.5, 0.5, 1.7))
    car = _T((-10.0, 0.0), (10.0, 0.0))
    assert ttc_box(ped, car, 4.0, 0.35) == pytest.approx(0.745, abs=0.01)
    assert drac(ped, car, 0.35) == pytest.approx(100 / (2 * 7.45), rel=0.01)
    side = _T((0.0, 3.0), (0.0, 0.0), (0.5, 0.5, 1.7))  # on the curb next to the lane
    assert ttc_box(side, car, 4.0, 0.35) is None


# ------------------------------------------------------------------ MCU protocol
def test_msgpack_lite_roundtrip():
    obj = [0, 12345, "set_signal", [3, 1, -5, 3.25, True, None, b"\x00\x07" * 52, {"a": [1, 2]}]]
    data = msgpack_lite.packb(obj)
    up = msgpack_lite.Unpacker()
    up.feed(data[:7])
    assert list(up) == []
    up.feed(data[7:])
    out = list(up)
    assert out == [obj]
    try:
        import msgpack

        assert msgpack.unpackb(data, raw=False) == obj
    except ImportError:
        pass


# ------------------------------------------------------------------ directions, approach, explicit rules
def test_direction_assigned_at_count():
    tr, cnt, ev = _run(lambda t: [_det(0.2, 6 - 1.3 * t)], 9.5)          # curb B -> curb A
    p = [e for e in ev if e["type"] == "passage"]
    assert len(p) == 1 and p[0]["dir"] == "B>A"
    assert cnt.dir_counts["pedestrian"]["B>A"] == 1
    tr, cnt, ev = _run(lambda t: [_det(20 - 12.0 * t, 2.0, "car")], 3.5)  # vehicle towards -X
    assert [e["dir"] for e in ev if e["type"] == "passage"] == ["-X"]


def test_walking_along_curb_is_not_a_passage():
    tr, cnt, ev = _run(lambda t: [_det(-6 + 1.3 * t, -4.3)], 10)          # along curb A, across x = 0
    assert cnt.counts["pedestrian"] == 0


def test_vehicle_eta_and_classify():
    from crosswalk.approach import vehicle_eta

    cfg = load_config(None)
    cfg.scene.calibration.image_points = None
    sc = Scene(cfg.scene, (640, 480), cfg.tracker)
    d, eta = vehicle_eta((-22.0, -2.0), (10.0, 0.0), sc)
    assert d == pytest.approx(20.0) and eta == pytest.approx(2.0)
    assert vehicle_eta((-22.0, -2.0), (-10.0, 0.0), sc) is None           # driving away


def test_signal_rules_tagged():
    from crosswalk.signal import SignalController

    cfg = load_config(None)
    cfg.scene.calibration.image_points = None
    sc = Scene(cfg.scene, (640, 480), cfg.tracker)
    ev = []
    sig = SignalController(cfg.signal, sc, ev.append)
    t = 0.0
    while t < 40:
        waiting = 1 if 10 <= t < 14 else 0
        crossing = 1 if 14 <= t < 30 else 0
        sig.update(t, waiting=waiting, crossing=crossing, time_to_clear=2.0 if crossing else 0.0)
        t += 0.1
    rules = [e["rule"] for e in ev if e["type"] == "signal"]
    assert rules[:3] == ["S1", "S1", "S1"] and "S2" in rules and "S4" in rules
    assert all(e["why"] for e in ev if e["type"] == "signal")


def test_rules_doc_matches_config():
    from crosswalk.rules import describe, markdown

    cfg = load_config(None)
    ids = [r["id"] for r in describe(cfg)]
    assert ids[:3] == ["B0", "B1", "B2"] and "F1" in ids
    assert f"< {cfg.safety.beacon_tta_s:g} s" in describe(cfg)[1]["when"]
    assert "| **S3** |" in markdown(cfg)
