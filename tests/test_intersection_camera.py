"""Camera projection and RGB-only observation contracts for optional photoreal mode."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

import cv2
import numpy as np
import pytest

from crosswalk.config import load_config
from crosswalk.detectors.base import Detection
from crosswalk.tracker import Tracker
from sim.intersection.render_source import CAMERAS,IntersectionRenderer,camera_for_view
from sim.intersection.world import IntersectionWorld
from sim.detection_eval import DetectionEvaluator


@pytest.mark.parametrize("view",CAMERAS)
def test_camera_ground_plane_round_trip(view):
    camera=camera_for_view(view)
    points=np.asarray([[0,0,0],[-7,10.5,0],[7,10.5,0],[10.5,7,0],[10.5,-7,0]])
    pixels,depth=camera.project(points)
    assert np.all(depth>0)
    assert np.max(np.abs(camera.ground_from_pixel(pixels)-points[:,:2]))<1e-8


def test_nn_receives_rgb_only_and_tracker_uses_camera_projection(monkeypatch):
    import sim.intersection.render_source as module
    renderer=IntersectionRenderer.__new__(IntersectionRenderer)
    renderer.width,renderer.height=640,480
    renderer.camera_name="overview";renderer.camera=camera_for_view("overview")
    renderer.last_detections={};renderer.generation=0;renderer.condition="day";renderer.frames=0;renderer.elapsed=0
    renderer.errors=[];renderer.info={};renderer.projection_error=0.
    renderer.cfg=load_config(None,[]);renderer.tracker=Tracker(renderer.cfg.tracker)
    renderer.scorers={name:DetectionEvaluator() for name in CAMERAS}
    image=np.full((480,640,3),73,np.uint8)
    monkeypatch.setattr(module,"decode_image",lambda data:image.copy())
    ground=np.array([[5.,4.,0]])
    pixels,_=renderer.camera.project(ground)
    x,y=pixels[0]
    def detector(frame):
        assert frame.shape==(480,640,3) and np.all(frame==73)
        return [Detection(x-15,y-50,x+15,y,.9,"person",kind="pedestrian")]
    renderer.detector=detector
    class Page:
        def evaluate(self,expression,snapshot):
            # Deliberately unrelated simulator identity/location: it must not
            # become a tracker measurement through a ground-truth shortcut.
            return {"rgb":"unused","boxes":[{"id":9999,"cls":"person","kind":"pedestrian",
                       "box":[10,10,20,30],"pixels":200}],"errors":[]}
    renderer.page=Page()
    snapshot=IntersectionWorld("empty").snapshot()
    snapshot["t"]=1.
    overlay,raw,stats,_=renderer.capture(snapshot)
    assert stats["detector"]=="real" and len(stats["predictions"])==1
    assert stats["tracks"] and stats["tracks"][0]["id"]!=9999
    assert stats["tracks"][0]["x"]==5. and stats["tracks"][0]["y"]==4.
    assert cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR).shape==(480,640,3)
    assert overlay!=raw


def test_photoreal_cli_is_optional_and_real_detector_requires_pixels(monkeypatch):
    from crosswalk.__main__ import main
    from sim.intersection import app
    captured=[]
    monkeypatch.setattr(app,"run",lambda args:captured.append(args))
    with pytest.raises(SystemExit):
        main(["--intersection","--intersection-detector","real"])
    main(["--intersection","--intersection-render","photoreal","--intersection-detector","real","--intersection-camera","E"])
    assert captured[0].intersection_render=="photoreal" and captured[0].intersection_camera=="E"


def test_camera_controls_are_isolated_and_validated():
    from sim.intersection.app import IntersectionApp
    app=IntersectionApp("empty")
    try:
        with pytest.raises(ValueError):app.control({"action":"camera","camera":"N"})
        app.render_mode="photoreal"
        app.control({"action":"camera","camera":"W"})
        assert app.camera_name=="W"
        with pytest.raises(ValueError):app.control({"action":"camera","camera":"bad"})
        app.control({"action":"reset"})
        assert app.generation==1
    finally:app.close()
