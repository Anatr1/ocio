"""Perception must remain a reconstruction, including misses and false positives."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

import numpy as np
import pytest
from crosswalk.detectors.base import Detection
from sim.intersection.geometry import IntersectionGeometry
from sim.intersection.perception import IntersectionPerception, fuse_observations
from sim.intersection.app import IntersectionApp


def detection(x,y,cls="person",score=.9):
    return Detection(0,0,20,40,score,cls,world=(x,y),cov=np.eye(2)*.25,extra={"gt":9999})


def test_four_camera_duplicate_is_one_measurement_without_gt_identity():
    observations={a:[detection(2+i*.05,3)] for i,a in enumerate("NESW")}
    fused=fuse_observations(observations)
    assert len(fused)==1 and fused[0].world==pytest.approx((2.075,3))
    assert fused[0].extra=={"cameras":["E","N","S","W"]}
    # Correlated cameras must not divide localization covariance by four.
    assert fused[0].cov==pytest.approx(np.eye(2)*.25)
    perception=IntersectionPerception(IntersectionGeometry())
    for t in (0.,.2,.4):perception.update(t,observations)
    assert len(perception.snapshot(.4)["agents"])==1
    assert perception.snapshot(.4)["agents"][0]["id"]!=9999


def test_same_camera_close_people_are_not_fused_and_views_match_once():
    fused=fuse_observations({"N":[detection(0,0),detection(.6,0)],
                             "E":[detection(.05,0),detection(.65,0)]})
    assert len(fused)==2
    assert sorted(d.world[0] for d in fused)==pytest.approx([.025,.625])


def test_perception_twin_does_not_copy_unseen_simulator_users():
    app=IntersectionApp("empty")
    try:
        app.enable_perception()
        user=app.world.spawn_vehicle("E")
        app.perception.update(0.,{a:[] for a in "NESW"})
        assert app.world.snapshot()["agents"]
        state=app.snapshot()
        assert state["agents"]==[] and state["events"]==[] and state["conflicts"]==[]
        assert state["statistics"]["observation_mode"]=="four-camera NN perception"
        app.world.step()
        assert sum(row["count"] for row in app.world.last_demand["vehicles"].values())==0
        assert user.alive
    finally:app.close()


def test_false_positive_becomes_twin_track_even_with_empty_physical_world():
    app=IntersectionApp("empty")
    try:
        app.enable_perception()
        for t in (0.,.2,.4):app.perception.update(t,{"N":[detection(-5.25,20,"car")]})
        app.world.t=.4
        state=app.snapshot()
        assert not app.world.users and len(state["agents"])==1
        assert state["demands"]["vehicles"]["N_straight"]["queued"]==1
        app.world.step()
        assert app.world.last_demand["vehicles"]["N_straight"]["count"]==1
    finally:app.close()


def test_stale_vision_holds_all_red_and_reset_starts_with_no_tracks():
    app=IntersectionApp("empty")
    try:
        app.enable_perception()
        app.world.step()
        assert app.world.controller.state=="all_red"
        for t in (0.,.2,.4):app.perception.update(t,{"N":[detection(0,0)]})
        assert app.perception.control_observations(.5)[2:] == (True,True)
        app.world.t=2.
        app.world.step()
        assert app.world.controller.state=="all_red"
        assert app.world.controller.reason=="Waiting for fresh camera observations"
        app.control({"action":"reset"})
        assert app.snapshot()["agents"]==[] and app.perception.frame_t is None
        assert app.world.observation_provider is not None
    finally:app.close()


def test_display_camera_switch_keeps_shared_track_identity():
    app=IntersectionApp("empty")
    try:
        app.render_mode="photoreal";app.enable_perception()
        for t in (0.,.2,.4):app.perception.update(t,{"N":[detection(0,0)]})
        ids=[a["id"] for a in app.snapshot()["agents"]]
        app.control({"action":"camera","camera":"W"})
        assert [a["id"] for a in app.snapshot()["agents"]]==ids
    finally:app.close()


def test_perceived_curb_queue_does_not_block_clearance_but_zebra_user_does():
    perception=IntersectionPerception(IntersectionGeometry())
    for t in (0.,.2,.4):perception.update(t,{"N":[detection(-8.5,10.5)]})
    assert perception.control_observations(.4)[2] is False
    assert perception.demands(.4)[1]["N"]["count"]==1
    crossing=IntersectionPerception(IntersectionGeometry())
    for t in (0.,.2,.4):crossing.update(t,{"N":[detection(-5.,10.5)]})
    assert crossing.control_observations(.4)[2] is True


def test_turn_counts_require_observed_origin_and_exit_once():
    from crosswalk.tracker import Track
    perception=IntersectionPerception(IntersectionGeometry())
    tr=Track(detection(-1.75,20,"car"),0.,perception.tracker.cfg)
    tr.state="confirmed"
    perception._describe(tr,0.)
    assert tr.meta["movement"]=="N_left"
    # A north-approach origin that departs east is an observed protected left.
    tr.x=np.array([20.,-1.75,6.,0.]);tr.t_last=2.
    perception._describe(tr,2.);perception._describe(tr,2.2)
    assert perception.report()["movement_counts"]["N_left"]==1
    assert perception.report()["counts"]["vehicle"]==1
    assert tr.meta["turn_uncertain"] is False


def test_four_sensor_batch_has_common_timestamp_and_no_mask_observations():
    from sim.intersection.render_source import IntersectionRenderer
    renderer=IntersectionRenderer.__new__(IntersectionRenderer)
    renderer.last_detections={}
    calls=[]
    def capture(snapshot,camera,generation):
        calls.append((camera,snapshot["t"],generation))
        renderer.last_detections[camera]=[detection(0,0)]
        return b"jpeg",b"raw",{"frame_t":snapshot["t"]},[{"gt_id":9999}]
    renderer.capture=capture
    feeds,observations=renderer.capture_all({"t":12.},3)
    assert calls==[(arm,12.,3) for arm in "NESW"]
    assert set(feeds)==set(observations)==set("NESW")
    assert all(isinstance(rows[0],Detection) for rows in observations.values())


def test_slow_camera_cadence_has_configured_freshness_budget():
    perception=IntersectionPerception(IntersectionGeometry(),max_frame_age=2.2)
    perception.update(0.,{a:[] for a in "NESW"})
    assert perception.control_observations(2.)[3] is True
    assert perception.control_observations(2.3)[3] is False
