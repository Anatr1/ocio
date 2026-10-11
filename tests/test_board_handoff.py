import json

import pytest

from crosswalk.config import load_config
from tools.prepare_mcu_app import prepare
from tools.board_acceptance import checks, progress_checks


def test_package_is_self_contained_and_cannot_overwrite_an_app(tmp_path):
    path = tmp_path / "app"
    manifest = prepare(path)
    assert manifest["profile"] == "grove" and manifest["oled"]
    assert "OCCHIO_GROVE_PROFILE 1" in (path / "sketch/sketch.ino").read_text()
    assert (path / "sketch/hardware.h").exists()
    assert "U8g2 (2.36.5)" in (path / "sketch/sketch.yaml").read_text()
    assert "subprocess" not in (path / "python/main.py").read_text()
    before = (path / "occhio-build.json").read_bytes()
    with pytest.raises(FileExistsError):
        prepare(path)
    assert (path / "occhio-build.json").read_bytes() == before
    recorded = json.loads(before)
    import hashlib
    for name, digest in recorded["files_sha256"].items():
        assert hashlib.sha256((path / name).read_bytes()).hexdigest() == digest


def test_original_and_gpio_only_packages_keep_dependencies_separate(tmp_path):
    for profile, oled in (("original", True), ("grove", False)):
        path = tmp_path / profile
        manifest = prepare(path, profile, oled)
        assert not manifest["oled"]
        assert "U8g2" not in (path / "sketch/sketch.yaml").read_text()
        assert "OCCHIO_HAS_OLED 0" in (path / "sketch/sketch.ino").read_text()


def test_live_config_is_camera_nn_and_required_hardware():
    cfg = load_config("configs/board_grove_live.yaml")
    assert cfg.source.type == "camera" and cfg.detector.backend == "ncnn"
    assert cfg.detector.imgsz == 320 and cfg.mcu.enabled is True
    assert cfg.public.demo is False and cfg.public.mock_month is False
    assert cfg.scene.calibration.image_points is None  # never borrow the site's old viewpoint


def sample():
    config = {"source": {"type": "camera"}, "detector": {"backend": "ncnn", "model": "yolo11n_320_ncnn_model"},
              "mcu": {"virtual": False}, "scene": {"calibrated": True}}
    health = {"ok": True, "failsafe": False}
    state = {"mcu": {"connected": True, "failsafe": False, "error": None},
             "perf": {"infer_ms": 140, "det_runs": 20, "frames": 21}}
    return config, health, state, [1, 1, 0, 3, 1, 0, 1, 100]


def test_healthy_sample_and_progress_are_software_evidence_only():
    cfg, health, state, status = sample()
    assert not checks(cfg, 200, health, state, status)
    assert not progress_checks([{"perf": {"frames": 1, "det_runs": 1}}, {"perf": {"frames": 3, "det_runs": 2}}])
    assert progress_checks([state, state])


@pytest.mark.parametrize("fault", ["replay", "mock", "virtual", "uncalibrated", "stale", "rpc", "old_sketch", "wrong_profile", "watchdog"])
def test_collector_rejects_false_deployment_success(fault):
    cfg, health, state, status = sample()
    if fault == "replay": cfg["source"]["type"] = "video"
    if fault == "mock": cfg["detector"]["backend"] = "sim"
    if fault == "virtual": cfg["mcu"]["virtual"] = True
    if fault == "uncalibrated": cfg["scene"]["calibrated"] = False
    if fault == "stale": health["ok"] = False
    if fault == "rpc": state["mcu"]["error"] = "method ping not available"
    if fault == "old_sketch": status = None
    if fault == "wrong_profile": status[1] = 0
    if fault == "watchdog": status[2] = 1
    assert checks(cfg, 200, health, state, status)


@pytest.mark.parametrize("healthy", [True, False])
def test_collector_writes_evidence_without_sending_heartbeats(tmp_path, monkeypatch, healthy):
    from tools import board_acceptance as collector
    cfg, health, state, status = sample()
    health["ok"] = healthy
    sequence = [0]

    def fetch(url, path):
        if path == "/api/config": return 200, cfg
        if path == "/api/health": return (200 if healthy else 503), health
        assert path == "/api/state"
        sequence[0] += 1
        return 200, {**state, "perf": {**state["perf"], "frames": sequence[0], "det_runs": sequence[0]}}

    class ReadOnlyClient:
        def __init__(self, *args): self.alive = False
        def connect(self): self.alive = True
        def close(self): self.alive = False
        def call(self, method):
            assert method == "get_status"  # any heartbeat or actuation command fails the test
            return status

    monkeypatch.setattr(collector, "fetch", fetch)
    monkeypatch.setattr(collector, "RouterClient", ReadOnlyClient)
    output = tmp_path / "evidence.jsonl"
    monkeypatch.setattr(collector.sys, "argv", ["board_acceptance", "--seconds", ".1", "--every", ".02", "--out", str(output)])
    assert collector.main() == (0 if healthy else 1)
    summary = json.loads(output.with_suffix(".summary.json").read_text())
    assert summary["software_checks_passed"] is healthy
    assert summary["functional_acceptance"] is False
    assert summary["samples"] >= 2
    assert output.read_text().count("firmware_status") >= 2
