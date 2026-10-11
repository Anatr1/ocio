"""Transport/validation contract fixtures are synthetic test data, not real-site evidence."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import sys
import threading

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from crosswalk.config import load_config
from crosswalk.sources import NetworkSource, read_mjpeg_part
from sim.cache_source import CacheSource
from sim.detection_eval import DetectionEvaluator
from sim.evaluation import write_html
from sim.noise import fit_noise
from sim.repro import file_hash
from sim.source import SimSource
from sim.validation import compare_detection, decision_transfer
from tools.detector_eval import load_yolo_labels
from tools.report import real_result


def cache_fixture(path, **extra):
    path.mkdir(exist_ok=True)
    metadata = {"complete": True, "scenario_complete": True, "frame_count": 2, "fps": 5,
                "scenario": {"name": "fixture", "conditions": {"time_of_day": "day", "weather": "clear"}},
                "calibration": {"image_size": [40, 30]}, **extra}
    (path / "manifest.json").write_text(json.dumps(metadata))
    for seq in (1, 2):
        image = path / f"{seq:06d}.jpg"
        assert cv2.imwrite(str(image), np.full((30, 40, 3), seq * 50, np.uint8))
        image.with_suffix(".json").write_text(json.dumps({"seq": seq, "t": seq / 5, "boxes": [],
                                                        "sha256": {"jpg": file_hash(image)}}))
    return path


def test_cached_pixels_timestamps_end_and_integrity(tmp_path):
    path = cache_fixture(tmp_path)
    source = CacheSource(path)
    a, t, seq = source.read()
    assert t == 0.2 and seq == 1 and a.shape == (30, 40, 3)
    b, t, seq = source.read(seq)
    assert t == 0.4 and seq == 2 and b.mean() > a.mean()
    assert source.read(seq) == (None, None, seq)
    assert not hasattr(source, "detections") and source.verified_payload_hashes
    source.close()
    assert cv2.imwrite(str(path / "000001.jpg"), np.zeros((30, 40, 3), np.uint8))
    with pytest.raises(ValueError, match="pixels changed"):
        CacheSource(path)


@pytest.mark.parametrize("extra", [{"complete": False}, {"frame_count": 0}, {"presentation_mode": True}])
def test_replay_rejects_invalid_caches(tmp_path, extra):
    with pytest.raises(ValueError):
        CacheSource(cache_fixture(tmp_path, **extra))


def test_partial_cache_is_not_scenario_certification(tmp_path):
    path = cache_fixture(tmp_path, scenario_complete=False)
    CacheSource(path).close()
    with pytest.raises(ValueError, match="scenario prefix"):
        CacheSource(path, require_scenario_complete=True)


def test_mjpeg_part_headers_payload_and_bounds():
    payload = b"pixels\r\n--frame-not-a-boundary"
    stream = BytesIO(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(payload)).encode() +
                     b"\r\nX-Timestamp: 1.25\r\nX-Sequence: 7\r\n\r\n" + payload + b"\r\n--frame--\r\n")
    headers, data = read_mjpeg_part(stream, b"frame")
    assert data == payload and headers["X-Timestamp"] == "1.25" and headers["X-Sequence"] == "7"
    assert read_mjpeg_part(stream, b"frame") is None
    for invalid in (b"", b"100000000", b"-1"):
        with pytest.raises(ValueError):
            read_mjpeg_part(BytesIO(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + invalid + b"\r\n\r\n"), b"frame")


def test_network_source_uses_sender_time_and_rejects_reordered_frames():
    ok, jpeg = cv2.imencode(".jpg", np.full((30, 40, 3), 100, np.uint8))
    assert ok
    payload = jpeg.tobytes()
    served = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            served.append(1)
            if len(served) > 1:  # one stream only: the reconnect must not race the assertions below
                self.send_error(503)
                return
            self.send_response(200)
            self.send_header("Content-Type", 'multipart/x-mixed-replace; boundary="frame"')
            self.end_headers()
            try:
                for seq, t in ((1, 10), (2, 10.2), (1, 9), (5, 10.4)):
                    head = (f"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: {len(payload)}\r\n"
                            f"X-Timestamp: {t}\r\nX-Sequence: {seq}\r\n\r\n").encode()
                    self.wfile.write(head + payload + b"\r\n")
                self.wfile.write(b"--frame--\r\n")
            except OSError:
                pass
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    source = NetworkSource({"url": f"http://127.0.0.1:{server.server_port}/video.mjpg", "width": 40, "height": 30})
    try:
        with source.condition:
            assert source.condition.wait_for(lambda: source.sender_seq == 5, 3)
        frame, t, seq = source.read()
        assert frame.mean() == pytest.approx(100, abs=1) and t == 10.4 and seq == 3
        assert source.dropped == 2 and source.rejected >= 1
        assert not hasattr(source, "detections")
    finally:
        source.close()
        server.shutdown()
        server.server_close()
        thread.join()
    assert not source.thread.is_alive()


def test_network_source_rebases_a_sender_that_restarts_after_reconnect():
    ok, jpeg = cv2.imencode(".jpg", np.full((30, 40, 3), 100, np.uint8))
    assert ok
    payload = jpeg.tobytes()
    served = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            served.append(1)
            if len(served) > 2:
                self.send_error(503)
                return
            self.send_response(200)
            self.send_header("Content-Type", 'multipart/x-mixed-replace; boundary="frame"')
            self.end_headers()
            try:
                for seq, t in ((1, 0.0), (2, 0.2), (3, 0.4)):  # every connection restarts the sender clock
                    head = (f"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: {len(payload)}\r\n"
                            f"X-Timestamp: {t}\r\nX-Sequence: {seq}\r\n\r\n").encode()
                    self.wfile.write(head + payload + b"\r\n")
                self.wfile.write(b"--frame--\r\n")
            except OSError:
                pass
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    source = NetworkSource({"url": f"http://127.0.0.1:{server.server_port}/video.mjpg", "width": 40, "height": 30})
    try:
        with source.condition:
            assert source.condition.wait_for(lambda: source.seq == 6, 5), "frames after the reconnect were rejected"
        frame, t, seq = source.read()
        assert seq == 6 and source.rebases == 1 and source.rejected == 0 and source.dropped == 0
        assert t > 0.4 + 0.25  # continues after the first stream's last frame plus the reconnect pause
    finally:
        source.close()
        server.shutdown()
        server.server_close()
        thread.join()


def detection_fixture():
    cfg = load_config()
    scorer = DetectionEvaluator(cfg.detector.conf)
    for i in range(40):
        scorer.observe((i + 1) / 5, [{"cls": "person", "box": [1, 1, 11, 21]}],
                       [{"cls": "person", "box": [1, 1, 11, 21], "score": 0.9}], "day:clear", [100, 100])
    return {"domain": "real", "label_policy": "visible", "sampling": {"representative": True}, "model_hash": "test-fixture-only",
            "config": cfg.to_plain(), "detection": scorer.summarize(8)}


def test_g2_missing_bins_and_model_mismatch_are_not_passes():
    real = detection_fixture()
    sim = {**real, "domain": "synthetic", "level": "L2"}
    assert compare_detection(sim, real)["status"] == "PASS"
    assert compare_detection(sim, real, 41)["status"] == "UNASSESSED"
    for other in ({**sim, "model_hash": "changed"}, {**sim, "render": {"presentation_mode": True}}):
        with pytest.raises(ValueError):
            compare_detection(other, real)
    with pytest.raises(ValueError):
        compare_detection(sim, real, 0)
    assert compare_detection(sim, {**real, "detection": {**real["detection"], "frames": 100}})["status"] == "UNASSESSED"


def test_fitted_noise_requires_real_representative_visible_labels():
    report = detection_fixture()
    noise = fit_noise(report)
    assert noise["bins"]["person:small:day:clear"]["miss"] == 0
    assert noise["bins"]["person:small:day:clear"]["scores"] == [0.9] * 40
    for bad in ({**report, "domain": "synthetic"}, {**report, "sampling": {}}, {**report, "label_policy": "amodal"}):
        with pytest.raises(ValueError):
            fit_noise(bad)


def test_noise_config_and_unobserved_bins_are_rejected(tmp_path):
    model = tmp_path / "fixture.onnx"
    model.write_bytes(b"not-a-real-model; never loaded")
    cfg = load_config()
    cfg.detector.model = str(model)
    report = detection_fixture()
    report.update(config=cfg.to_plain(), model_hash=file_hash(model))
    noise = fit_noise(report)
    cfg.setdefault("sim", {})["noise"] = noise
    source = SimSource(cfg, "single_a_b", realtime=False, render=False)
    source.read()
    with pytest.raises(ValueError, match="no fitted observations"):
        source.detections()
    cfg.detector.imgsz += 1
    with pytest.raises(ValueError, match="configuration differs"):
        SimSource(cfg, "single_a_b", render=False)


def test_g6_requires_provenance_and_variable_finite_ranks():
    rows = [{"config_hash": str(i), "sim_accuracy": i / 10, "real_accuracy": i / 10} for i in range(3)]
    assert decision_transfer(rows)["status"] == "UNASSESSED"
    verified = [{**r, "sim_report_hash": "fixture", "real_report_hash": "fixture"} for r in rows]
    assert decision_transfer(verified)["status"] == "UNASSESSED"
    assert decision_transfer(verified)["criterion_met"]
    assert decision_transfer([{**r, "real_accuracy": 1} for r in verified])["status"] == "UNASSESSED"
    with pytest.raises(ValueError):
        decision_transfer([{**r, "real_accuracy": float("nan")} for r in verified])


def test_real_count_csv_uses_the_same_event_scorer_and_report(tmp_path):
    events, gt = tmp_path / "events.jsonl", tmp_path / "counts.gt.csv"
    events.write_text(json.dumps({"type": "passage", "t": 1, "track": 1, "kind": "pedestrian", "dir": "A>B"}))
    gt.write_text("t,kind,cls\n1,pedestrian,pedestrian\n")
    result = real_result(events, gt)
    assert result["metrics"]["count_accuracy"] == 1 and result["metrics"]["direction_accuracy"] is None
    write_html(tmp_path / "report.html", [result])
    assert "unlabelled" in (tmp_path / "report.html").read_text()


@pytest.mark.parametrize("label", ["-1 .5 .5 .2 .2", "2 .5 .5 .2 .2", "0 .5 .5 0 .2", "0 nan .5 .2 .2"])
def test_invalid_real_label_coordinates_or_classes(tmp_path, label):
    path = tmp_path / "label.txt"
    path.write_text(label)
    with pytest.raises(ValueError):
        load_yolo_labels(path, ["person"], 640, 480)
