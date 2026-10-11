"""Simulator contracts. GPU/real-model checks are opt-in and never use fake detections."""
import functools
from http.server import ThreadingHTTPServer
import math
import os
from pathlib import Path
import re
import sys
import threading
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crosswalk.config import load_config
from crosswalk.counting import Counter
from crosswalk.detectors.base import Detection
from crosswalk.scene import Scene
from sim.behaviour import PARAMETERS, idm, overlaps, social_velocity
from sim.camera import camera_for_config
from sim.detection_eval import DetectionEvaluator, RecordingDetector, match_boxes
from sim.evaluation import check_expectations, evaluate_events
from sim.gt import GroundTrack, line_passage
from sim.render_source import RenderHandler, RenderSource, decode_image, mask_boxes
from sim.repro import file_hash
from sim.runner import run_scenario
from sim.scenarios import catalogue, load_scenario, scenario_hash
from sim.temporal import TemporalEvaluator
from sim.world import Agent, World


@pytest.mark.parametrize("cls,previous,current,direction", [
    ("pedestrian", (0, 0, -1), (1, 0, 1), "A>B"),
    ("pedestrian", (0, 0, 1), (1, 0, -1), "B>A"),
    ("pedestrian", (0, -3, -3.9), (1, 3, -3.9), None),
    ("pedestrian", (0, 5, -1), (1, 5, 1), None),
    ("car", (0, -3, -2), (1, 3, -2), "+X"),
    ("car", (0, 3, 2), (1, -3, 2), "-X"),
    ("bicycle", (0, 0, -1), (1, 0, 1), "A>B"),
    ("bicycle", (0, -2, -3.4), (1, 2, -3.4), "+X"),
    ("bicycle", (0, -1, -3.4), (1, 1, -3.4), None),
    ("e-scooter", (0, 3, 2), (1, -3, 2), "-X"),
])
def test_line_oracle_matches_production(cls, previous, current, direction):
    cfg = load_config()
    scene = Scene(cfg.scene, tracker_cfg=cfg.tracker)
    a = Agent(1, cls, previous[1], previous[2], current[1] - previous[1], current[2] - previous[2])
    tr = GroundTrack(a, previous[0])
    events = []
    counter = Counter(scene, cfg.counting, events.append)
    counter.update(previous[0], [tr], [])
    a.x, a.y = current[1:]
    tr.update(a, current[0])
    counter.update(current[0], [tr], [])
    hit = line_passage(previous, current, a.kind, scene.W, scene.L)
    passages = [e for e in events if e["type"] == "passage"]
    if direction is None:
        assert hit is None and not passages
    else:
        assert hit["dir"] == passages[0]["dir"] == direction
        assert hit["t"] == pytest.approx(passages[0]["t"])
        assert len(passages) == 1


def test_calibrated_camera_preserves_four_corners():
    cfg = load_config()
    camera, scene = camera_for_config(cfg, 640, 480)
    corners = [(-scene.W / 2, -scene.L / 2, 0), (scene.W / 2, -scene.L / 2, 0),
               (scene.W / 2, scene.L / 2, 0), (-scene.W / 2, scene.L / 2, 0)]
    points, _ = camera.project(corners)
    cfg.scene.calibration.update({"H": camera.H_i2w.tolist(), "image_points": points.tolist(),
                                  "image_size": [640, 480], "focal_px": camera.K[0, 0]})
    recovered, scene = camera_for_config(cfg, 640, 480)
    assert scene.calibrated
    assert np.max(np.linalg.norm(points - recovered.project(corners)[0], axis=1)) < 1e-6


def test_idm_free_flow_and_following():
    assert idm(0, 10) > 0
    assert idm(10, 10) == pytest.approx(0)
    assert idm(10, 10, 2, 0) < -8
    assert idm(8, 10, 10, 10) > idm(8, 10, 10, 0)


def test_pedestrian_repels_from_vehicle_surface():
    ped = Agent(1, "pedestrian", 0, 0)
    car = Agent(2, "car", 3, 0)
    free = social_velocity(ped, (5, 0), [ped], 1.35, 0.05, PARAMETERS)
    obstructed = social_velocity(ped, (5, 0), [ped, car], 1.35, 0.05, PARAMETERS)
    assert obstructed[0] < free[0]


@pytest.mark.parametrize("scenario", ["opposing_groups", "queue_two_lanes", "near_miss_late_braking"])
def test_world_never_penetrates_footprints(scenario):
    cfg = load_config()
    spec = load_scenario(scenario)
    if spec.get("scene"):
        from crosswalk.config import Cfg, deep_merge
        cfg.scene = Cfg.wrap(deep_merge(cfg.scene, spec["scene"]))
    world = World(cfg.scene, spec, 0, cfg=cfg)
    for _ in range(600):
        world.step(0.05)
        assert not any(overlaps(a, b) for i, a in enumerate(world.agents) for b in world.agents[i + 1:])
    if scenario == "near_miss_late_braking":
        collisions = [e for e in world.gt_events if e["type"] == "collision"]
        assert len(collisions) == 1
        assert all(a.state == "crashed" and a.speed == 0 for a in world.agents)


def test_explicit_overlapping_spawn_is_rejected():
    cfg = load_config()
    world = World(cfg.scene, {"rates": {}}, cfg=cfg)
    world.spawn("car", x=0, y=-2)
    with pytest.raises(ValueError, match="footprint"):
        world.spawn("pedestrian", x=0, y=-2)


def test_seeded_events_and_scenario_hash_are_repeatable():
    a = run_scenario("group_a_b", "L0", seed=2)
    b = run_scenario("group_a_b", "L0", seed=2)
    assert a["events"] == b["events"]
    assert a["ground_truth"] == b["ground_truth"]
    assert a["scenario_hash"] == b["scenario_hash"]
    assert all(c["passed"] for c in a["checks"])
    assert scenario_hash(load_scenario("single_a_b")) != scenario_hash(load_scenario("single_b_a"))


def test_empty_world_has_no_spurious_lamps_or_counts():
    result = run_scenario("empty_street", "L0", duration=3)
    assert result["metrics"]["passages"] == 0
    assert not any(e.get("rule") in ("B1", "B2") for e in result["events"])
    assert result["ground_truth"] == []


def test_s1_and_s3_timing_expectations():
    result = run_scenario("slow_walker_extension", "L0")
    assert all(c["passed"] for c in result["checks"])
    assert result["temporal"]["rules"]["S1"]["missed_onsets"] == 0
    assert result["temporal"]["rules"]["S1"]["onset_latency_s"]["p95"] < 1
    assert result["signal"]["extension_s"] >= 3


@pytest.mark.parametrize("extra", [
    {"duration_s": 0}, {"duration_s": float("inf")}, {"physics_dt": 0}, {"yield_p": 2},
    {"name": "../escape"}, {"rates": {"car": -1}}, {"script": [{"cls": "car", "dir": 0}]},
    {"script": [{"cls": "car", "n": -1}]}, {"script": [{"cls": "car", "n": 1.5}]},
    {"script": [{"cls": "pedestrian", "x": float("nan")}]},
])
def test_invalid_scenario_inputs(extra):
    with pytest.raises(ValueError):
        load_scenario(extra)


def test_catalogue_has_exact_scripted_direction_expectations():
    assert len(catalogue()) >= 40
    for name in catalogue():
        spec = load_scenario(name)
        assert spec["expected"]
        if spec["script"] and not spec["rates"]:
            assert "counts" in spec["expected"] and "directions" in spec["expected"], name


def test_visible_instance_boxes_and_hidden_agents():
    mask = np.zeros((8, 10, 3), np.uint8)
    mask[2:6, 3:7] = (1, 2, 3)
    boxes = mask_boxes(mask, [{"id": 0x010203, "det_class": "person", "kind": "pedestrian"},
                             {"id": 2, "det_class": "car", "kind": "vehicle"}])
    assert boxes[0]["box"] == [3, 2, 7, 6] and boxes[0]["pixels"] == 16
    assert boxes[1]["box"] is None and boxes[1]["pixels"] == 0


def test_raw_detector_observer_never_receives_ground_truth():
    image = np.zeros((30, 40, 3), np.uint8)
    class RealDetector:
        backend = "onnx"
        def __call__(self, pixels):
            assert pixels is image
            return [Detection(5, 5, 15, 25, 0.9, "person")]
    source = SimpleNamespace(world=SimpleNamespace(t=1), spec={"conditions": {"time_of_day": "day", "weather": "clear"}},
                             frame_meta={"boxes": [{"cls": "person", "box": [5, 5, 15, 25]}]}, width=40, height=30)
    scorer = DetectionEvaluator()
    detector = RecordingDetector(RealDetector(), source, scorer)
    assert detector.backend == "onnx" and len(detector(image)) == 1
    assert scorer.summarize(1)["bins"]["person:small:day:clear"]["recall"] == 1
    assert not hasattr(RenderSource, "detections")


def test_box_assignment_maximizes_valid_matches(monkeypatch):
    scores = {(0, 0): 0.60, (0, 1): 0.51, (1, 0): 0.51, (1, 1): 0.49}
    monkeypatch.setattr("sim.detection_eval.iou", lambda a, b: scores[(a[0], b[0])])
    boxes = [{"cls": "person", "box": [i, 0, i + 1, 1]} for i in range(2)]
    assert len(match_boxes(boxes, boxes)) == 2


def test_detector_bins_and_false_positive_rate():
    scorer = DetectionEvaluator()
    scorer.observe(1, [{"cls": "person", "box": [1, 1, 11, 21]}],
                   [{"cls": "person", "box": [1, 1, 11, 21], "score": 0.9},
                    {"cls": "car", "box": [20, 20, 40, 40], "score": 0.8}], "night:rain", [100, 100])
    report = scorer.summarize(30)
    assert report["fp_per_minute"] == 2
    assert report["bins"]["person:small:night:rain"]["recall"] == 1
    assert len(report["bins"]["car:small:night:rain"]["fp_samples"]) == 1


def test_temporal_overlap_latency_and_hold():
    cfg = load_config()
    evaluator = TemporalEvaluator(Scene(cfg.scene, tracker_cfg=cfg.tracker), cfg.safety)
    ground = []
    for i in range(1, 11):
        t = i / 10
        ground.append({"t": t, "rules": {"B1": 2 <= i <= 5, "B2": False}, "users": []})
        evaluator.observe(t, [], SimpleNamespace(warning_level=1 if 3 <= i <= 7 else 0), {})
    row = evaluator.evaluate(ground, 1)["rules"]["B1"]
    assert row["onset_latency_s"]["median"] == pytest.approx(0.1)
    assert row["tp_s"] == pytest.approx(0.3)
    assert row["fn_s"] == pytest.approx(0.1)
    assert row["fp_s"] == pytest.approx(0.2)
    assert row["hold_adjusted_fp_s"] == 0


def test_unlabelled_real_directions_are_unassessed():
    pred = [{"type": "passage", "track": 1, "t": 1, "kind": "pedestrian", "dir": "A>B"}]
    gt = [{"type": "passage", "t": 1, "kind": "pedestrian"}]
    assert evaluate_events(pred, gt)["direction_accuracy"] is None


def test_unexpected_direction_fails_even_with_correct_total():
    r = run_scenario("single_a_b", "L0")
    r["metrics"]["directions"] = {"pedestrian:B>A": 1}
    checks = check_expectations(r, load_scenario("single_a_b")["expected"])
    assert any(not c["passed"] for c in checks if c["name"].startswith("direction:"))


def test_ncnn_directory_hash_includes_names_and_contents(tmp_path):
    (tmp_path / "model.param").write_bytes(b"parameters")
    (tmp_path / "model.bin").write_bytes(b"weights")
    first = file_hash(tmp_path)
    assert file_hash(tmp_path) == first
    (tmp_path / "model.bin").write_bytes(b"new weights")
    assert file_hash(tmp_path) != first


def test_render_http_cannot_read_outside_asset_directories(tmp_path):
    (tmp_path / "sim/render").mkdir(parents=True)
    (tmp_path / "sim/render/public.txt").write_text("public")
    (tmp_path / "secret.txt").write_text("private")
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(RenderHandler, directory=str(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        assert urlopen(base + "/sim/render/public.txt").read() == b"public"
        for path in ("/secret.txt", "/sim/render/../../secret.txt", "/sim/render/%2e%2e/%2e%2e/secret.txt"):
            for method in ("GET", "HEAD"):
                with pytest.raises(HTTPError) as error:
                    urlopen(Request(base + path, method=method))
                assert error.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_render_http_serves_twin_module_dependencies():
    root = Path(__file__).resolve().parents[1]
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(RenderHandler, directory=str(root)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    pending = [root / "dashboard/js/twin.js"]
    visited = set()
    try:
        while pending:
            module = pending.pop().resolve()
            if module in visited:
                continue
            visited.add(module)
            path = module.relative_to(root).as_posix()
            with urlopen(base + "/" + path) as response:
                assert response.read() == module.read_bytes(), path
            source = module.read_text(encoding="utf-8")
            pending.extend(module.parent / dependency for dependency in
                           re.findall(r'''\bfrom\s*["'](\.[^"']+)["']''', source))
        # Serving renderer dependencies must not expose the rest of the app.
        for path in ("/dashboard/js/main.js", "/crosswalk/config.py"):
            with pytest.raises(HTTPError) as error:
                urlopen(base + path)
            assert error.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_evaluation_rejects_presentation_mode():
    with pytest.raises(ValueError, match="presentation_mode"):
        run_scenario("single_a_b", "L0", overrides=["sim.presentation_mode=true"])


@pytest.mark.skipif(os.environ.get("SIM_RENDER_TEST") != "1", reason="opt-in GPU and downloaded assets")
def test_three_geometry_mask_pixels_motion_and_mobile(tmp_path):
    cfg = load_config(overrides=[f"sim.browser={os.environ.get('SIM_BROWSER', 'chromium')}"])
    cfg.setdefault("sim", {})["render_cache"] = str(tmp_path)
    scenario = {"name": "render_contract", "script": [
        {"t": 0, "cls": "pedestrian", "side": -1, "x": -2, "y": -5, "cross_x": -2, "state": "cross", "v": 1.35},
        {"t": 0, "cls": "bicycle", "side": 1, "crossing": True, "x": 1.2, "y": 5,
         "cross_x": 1.2, "state": "cross", "v": 3.5},
        {"t": 0, "cls": "car", "dir": -1, "x": 18, "v": 7, "yields": True},
        {"t": 0, "cls": "car", "dir": 1, "x": -20, "v": 7, "yields": True},
    ]}
    source = RenderSource(cfg, scenario, fps=5)
    try:
        context_path = "sim/render/context.js"
        assert source.cache_metadata["bundle_code"][context_path] == file_hash(Path(__file__).resolve().parents[1] / context_path)
        for name in ("avatars.js", "streetscape.js", "visual-geometry.js"):
            path = "dashboard/js/" + name
            assert source.cache_metadata["bundle_code"][path] == file_hash(Path(__file__).resolve().parents[1] / path)
        first, _, _ = source.read()
        assert source.geometry_error_px < 1
        assert first.std() > 10 and source.mask.max() > 0
        source.read()
        source.read()
        # Instance IDs must follow the current pose after RGB shadow/sky passes.
        repeated = source.page.evaluate("state => provingGround.render(state)", source.snapshot())
        assert np.array_equal(decode_image(repeated["mask"]), source.mask)
        for _ in range(5):
            second, _, _ = source.read()
        assert np.abs(first.astype(float) - second).mean() > 0.1
        source.page.screenshot(path=str(tmp_path / "desktop.png"))
        source.page.set_viewport_size({"width": 390, "height": 844})
        source.page.screenshot(path=str(tmp_path / "mobile.png"))
        bounds = source.page.locator("canvas").bounding_box()
        assert bounds["width"] == 390 and bounds["height"] == 844
        assert not source.page_errors
    finally:
        source.close()
