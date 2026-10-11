"""Contracts for the optional intersection mode; existing crosswalk behaviour stays separate."""
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sim.behaviour import overlaps
from sim.intersection.controller import IntersectionController, PHASES
from sim.intersection.geometry import ARMS, IntersectionGeometry
from sim.intersection.world import IntersectionWorld, User


def test_concurrent_protected_paths_have_disjoint_vehicle_footprints():
    geometry = IntersectionGeometry()
    for phase in PHASES:
        for i, movement in enumerate(phase.movements):
            route = geometry.routes[movement]
            for other_id in phase.movements[i + 1:]:
                other = geometry.routes[other_id]
                if route.origin == other.origin:
                    continue  # shared lane branches are separated by following distance
                for k in range(31):
                    a = User(1, "car", 0, 11, route_id=movement)
                    a.x, a.y, a.heading = route.pose(route.entry_s - 3 + (route.exit_s-route.entry_s+6)*k/30)
                    for j in range(31):
                        b = User(2, "car", 0, 11, route_id=other_id)
                        b.x, b.y, b.heading = other.pose(other.entry_s - 3 + (other.exit_s-other.entry_s+6)*j/30)
                        assert not overlaps(a, b, .1), (phase.id, movement, other_id)


def test_all_twelve_routes_are_continuous_and_exit_in_the_right_lane():
    geometry = IntersectionGeometry()
    assert len(geometry.routes) == 12
    for route in geometry.routes.values():
        assert route.stop_s < route.entry_s < route.exit_s < route.clear_s < route.length
        last = route.pose(0)
        for k in range(1, 401):
            pose = route.pose(route.length*k/400)
            assert math.dist(last[:2], pose[:2]) < .5
            # Tight right turns have ~1.75 m radius: a .33 m sample can
            # legitimately change heading by about eleven degrees.
            assert abs((pose[2]-last[2]+math.pi) % (2*math.pi)-math.pi) < .35
            last = pose


def test_clearance_never_releases_conflicting_green_while_occupied():
    controller = IntersectionController("fixed", fixed_green=1.)
    controller.update(1., {}, {}, False)
    assert controller.state == "yellow"
    controller.update(4., {}, {}, True)
    assert controller.state == "all_red"
    for t in range(6, 30):
        controller.update(float(t), {}, {}, True)
        assert controller.state == "all_red"
        assert all(v == "red" for v in controller.payload()["vehicles"].values())
    controller.update(30., {}, {}, False)
    assert controller.state == "green" and controller.phase.id == "NS_LEFT"


def test_slow_walker_holds_clearance_until_completion():
    world = IntersectionWorld("empty", "fixed")
    world.controller.phase = PHASES[-1]
    walker = world.spawn_pedestrian("N", speed=.55)
    world.run(20)
    assert walker.admitted and walker.alive
    assert world.controller.state == "all_red"
    assert all(v == "red" for v in world.controller.payload()["vehicles"].values())
    world.run(20)
    assert world.metrics["pedestrians_completed"] == 1
    assert not world.occupied()


def test_all_turns_and_all_crosswalks_are_counted_once():
    world = IntersectionWorld("empty", "adaptive")
    for arm in ARMS:
        for turn in ("straight", "left", "right"):
            while any(u.route_id for u in world.users):
                world.step()
            car = world.spawn_vehicle(arm, turn)
            for _ in range(1800):
                world.step()
                if not car.alive:
                    break
            assert not car.alive, (arm, turn)
            assert world.movements[f"{arm}_{turn}"] == 1
    assert world.metrics["vehicles_completed"] == 12
    assert world.report()["vehicle_speed_kmh"]["sample_count"] == 12
    for arm in ARMS:
        walker = world.spawn_pedestrian(arm)
        for _ in range(1500):
            world.step()
            if not walker.alive:
                break
        assert world.crossings[arm]["pedestrian"] == 1
        assert world.crossings[arm]["A>B"] == 1
        assert world.report()["pedestrian_crossing_duration_s"][arm]["sample_count"] == 1
    assert world.report()["counts"] == {"vehicle":12, "pedestrian":4, "bicycle":0}


def test_paired_policies_receive_identical_demand():
    worlds = [IntersectionWorld("commute", policy, 12) for policy in ("fixed", "adaptive")]
    for world in worlds:
        world.run(120)
    assert worlds[0].arrival_log == worlds[1].arrival_log
    for world in worlds:
        assert sum(world.movements.values()) == world.metrics["vehicles_completed"]
        assert world.metrics["requested_arrivals_vehicle"] == world.metrics["admitted_arrivals_vehicle"] + world.metrics["dropped_vehicles"]


@pytest.mark.parametrize("scenario", ["balanced", "commute", "pedestrian", "turning", "saturated"])
def test_continuous_intersection_keeps_flowing_and_vehicle_footprints_separate(scenario):
    world = IntersectionWorld(scenario, seed=9)
    per_minute = []
    previous = 0
    for minute in range(4):
        for tick in range(600):
            world.step()
            if tick % 10 == 0:
                cars = [u for u in world.users if u.route_id]
                assert not any(overlaps(a, b) for i, a in enumerate(cars) for b in cars[i+1:])
                if world.controller.phase.pedestrian and world.controller.state == "green":
                    assert all(value == "red" for value in world.controller.payload()["vehicles"].values())
        current = world.metrics["vehicles_completed"]
        per_minute.append(current - previous)
        previous = current
    assert min(per_minute[1:]) >= 5, per_minute
    assert len(world.events) <= 150
    assert len(world.users) < 250
    assert all(sum(world.movements[f"{arm}_{turn}"] for turn in ("straight", "left", "right")) > 0 for arm in ARMS)


def test_downstream_queue_blocks_new_admission():
    world = IntersectionWorld("empty")
    route = world.geometry.routes["N_straight"]
    blocking = world.spawn_vehicle("N", "straight", s=route.clear_s+1, parked_until=100)
    blocking.speed = 0
    car = world.spawn_vehicle("N", "straight", s=route.stop_s-3)
    assert not world._exit_available(car)
    for _ in range(30):
        world.step()
    assert not car.admitted
    assert car.s + car.dims[0]/2 <= route.stop_s


def test_manual_call_is_served_and_green_call_does_not_repeat():
    world = IntersectionWorld("empty")
    world.controller.request("W")
    world.run(25)
    assert world.controller.phase.pedestrian
    assert not world.controller.calls
    if world.controller.state == "green":
        world.controller.request("W")
        assert not world.controller.calls


def test_live_controls_and_comparison_do_not_modify_other_modes():
    from sim.intersection.app import IntersectionApp
    app = IntersectionApp("empty")
    try:
        app.control({"action": "slow_walker", "crossing": "S"})
        app.control({"action": "call", "crossing": "S"})
        app.control({"action": "pause", "paused": True})
        app.control({"action": "speed", "speed": 12})
        assert app.snapshot()["paused"] and app.speed == 12
        assert app.world.controller.calls == {"S"}
        assert len(app.world.users) == 1
        app.control({"action": "policy", "policy": "fixed"})
        assert app.world.controller.policy == "fixed"
        app.control({"action": "reset", "scenario": "turning", "seed": 3})
        assert not app.world.users and app.world.seed == 3 and app.world.scenario == "turning"
        for bad in ({"action":"speed", "speed":float("nan")}, {"action":"call", "crossing":"bad"},
                    {"action":"reset", "seed":True}, {"action":"pause", "paused":"yes"}):
            with pytest.raises(ValueError):
                app.control(bad)
    finally:
        app.close()


def test_cli_dispatch_is_opt_in_and_rejects_camera_combinations(monkeypatch):
    from crosswalk.__main__ import main
    from sim.intersection import app
    captured = []
    monkeypatch.setattr(app, "run", lambda args: captured.append(args))
    main(["--intersection", "--intersection-scenario", "turning", "--intersection-policy", "fixed", "--seed", "7"])
    assert captured[0].seed == 7 and captured[0].intersection_policy == "fixed"
    with pytest.raises(SystemExit):
        main(["--intersection", "--sim", "mixed"])


def test_http_assets_controls_and_private_paths():
    import json
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError
    from sim.intersection.app import IntersectionApp, serve
    app = IntersectionApp("empty")
    server, thread = serve(app, 0)
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        for path in ("/", "/js/intersection.js", "/js/avatars.js", "/vendor/OrbitControls.js", "/api/config", "/api/state", "/api/report"):
            with urlopen(base+path) as response:
                assert response.status == 200 and response.read()
        for path in ("/../README.md", "/vendor/../../crosswalk/config.py", "/api/frame.jpg"):
            with pytest.raises(HTTPError) as error:
                urlopen(base+path)
            assert error.value.code == 404
        request = Request(base+"/api/control", json.dumps({"action":"pause", "paused":True}).encode(),
                          {"Content-Type":"application/json"})
        assert json.loads(urlopen(request).read())["ok"] and app.paused
        request = Request(base+"/api/control", b'{}', {"Content-Type":"application/json", "Origin":"http://elsewhere.example"})
        with pytest.raises(HTTPError) as error:
            urlopen(request)
        assert error.value.code == 403
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        app.close()


def test_opposing_walkers_and_riders_do_not_stack_or_overlap():
    world = IntersectionWorld("empty")
    world.controller.phase = PHASES[-1]
    for i in range(12):
        world.spawn_pedestrian("N", direction=1 if i % 2 else -1,
                               speed=.8+i*.04, cls="bicycle" if i % 5 == 0 else "pedestrian")
    for _ in range(600):
        assert not any(overlaps(a,b) for i,a in enumerate(world.users) for b in world.users[i+1:])
        world.step()
    assert world.metrics["pedestrians_completed"] == 12
