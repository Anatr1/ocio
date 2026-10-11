"""Continuous-traffic contracts of the World: no gridlock, no simulator-made collisions, bounded state.

These guard the behaviours that long unscripted runs depend on (rate-spawned traffic for minutes): a
regression here shows up as traffic that slowly freezes, or as careful road users being run over."""
import math
from pathlib import Path
import random
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crosswalk.config import load_config
from crosswalk.scene import Scene
from crosswalk.signal import SignalController
from sim.behaviour import overlaps, penetration
from sim.world import Agent, World


def run_traffic(scenario, mode, minutes, seed=1):
    """Run a rate-driven scenario like the dashboard does; return the world and 'careful' collisions."""
    cfg = load_config(None, [f"signal.mode={mode}"])
    world = World(cfg.scene, scenario, seed, cfg=cfg)
    signal = SignalController(cfg.signal, Scene(cfg.scene, tracker_cfg=cfg.tracker), lambda e: None)
    world.signal = signal
    careful = []
    for _ in range(int(minutes * 60 * 15)):
        n = len(world.gt_events)
        world.step(1 / 15)
        signal.update(world.t, waiting=sum(a.state == "wait" for a in world.agents),
                      crossing=sum(a.state == "cross" for a in world.agents), time_to_clear=3.0)
        for e in world.gt_events[n:]:
            if e["type"] != "collision":
                continue
            for agent in (a for a in world.agents if a.id in e["agents"]):
                if "side" in agent.meta and agent.meta.get("cautious") and not agent.meta.get("hurry"):
                    careful.append(e)
    return world, careful


@pytest.mark.parametrize("scenario,mode,minutes", [
    ("count_test", "beacon", 6), ("count_test", "adaptive", 6), ("mixed", "beacon", 6),
    ("dangerous", "beacon", 5), ("rush_hour", "beacon", 4), ("rush_hour", "adaptive", 3),
])
def test_continuous_traffic_keeps_flowing_without_simulator_made_crashes(scenario, mode, minutes):
    world, careful = run_traffic(scenario, mode, minutes)
    passages = [e["t"] for e in world.gt_events if e["type"] == "passage"]
    per_minute = [sum(1 for t in passages if 60 * k <= t < 60 * (k + 1)) for k in range(minutes)]
    assert min(per_minute[1:]) >= 5, f"traffic froze: passages per minute {per_minute}"
    assert not [e for e in world.gt_events if e["type"] == "physics_guard"], "global physics reset needed"
    assert not careful, f"a cautious, unhurried road user was run over: {careful[0]}"
    assert not any(overlaps(a, b) for i, a in enumerate(world.agents) for b in world.agents[i + 1:])


def test_penetration_agrees_with_overlaps_and_its_normal_separates():
    rng = random.Random(7)
    shapes = [("pedestrian", 0), ("bicycle", 0), ("car", 0), ("bus", 0)]
    checked = 0
    for i in range(3000):
        a = Agent(1, rng.choice(shapes)[0], 0.0, 0.0)
        b = Agent(2, rng.choice(shapes)[0], rng.uniform(-6, 6), rng.uniform(-3, 3))
        a.heading, b.heading = rng.uniform(-math.pi, math.pi), rng.uniform(-math.pi, math.pi)
        depth, nx, ny = penetration(a, b)
        if abs(depth) < 1e-6:
            continue  # touching: either answer is fine
        assert overlaps(a, b) == (depth > 0), (a, b, depth)
        if depth > 0:
            a.x += nx * (depth + 0.005)
            a.y += ny * (depth + 0.005)
            assert not overlaps(a, b), (a, b, depth)
            checked += 1
    assert checked > 300


def test_saturated_approach_drops_random_arrivals_instead_of_crashing():
    cfg = load_config()
    world = World(cfg.scene, {"rates": {}}, cfg=cfg)
    placed = [world.spawn("car", dir=1, v=0.0, _rate_spawn=True) for _ in range(200)]
    assert None in placed and len(world.agents) < 60, "the stationary queue must be capped"
    assert any(e["type"] == "arrival_dropped" for e in world.gt_events)
    limit = world.A + 3 + world.PREROLL_M + world.QUEUE_CAP_M
    assert max(abs(a.x) for a in world.agents) <= limit
    assert not any(overlaps(a, b) for i, a in enumerate(world.agents) for b in world.agents[i + 1:])
    world.spawn("car", dir=-1, x=0.0)
    with pytest.raises(ValueError, match="footprint"):  # scripted initial conditions still fail loudly
        world.spawn("pedestrian", x=0.0, y=2.0)


def test_wrecks_are_cleared_so_one_crash_does_not_block_the_road_forever():
    cfg = load_config()
    world = World(cfg.scene, {"rates": {}}, cfg=cfg)
    car = world.spawn("car", dir=1, x=-2.0, v=0.0)
    car.state, car.meta["crash_t"] = "crashed", 0.0
    for _ in range(int((world.params["crash_clear_s"] + 1) / 0.05)):
        world.step(0.05)
    assert car not in world.agents
    assert any(e["type"] == "crash_cleared" and e["agent"] == car.id for e in world.gt_events)


def test_people_at_the_kerb_are_never_pushed_into_the_road():
    cfg = load_config()
    world = World(cfg.scene, {"rates": {}}, cfg=cfg)
    edge = world.L / 2 + 0.25 + 0.02
    waiting = world.spawn("pedestrian", side=1, x=0.0, y=edge + 0.01, state="wait")
    arriving = world.spawn("pedestrian", side=1, x=0.0, y=edge + 0.6, state="to_curb")
    arriving.y = waiting.y + 0.3  # pressed into the waiting person from the pavement side
    world._separate_soft(0.05)
    assert waiting.y >= edge - 1e-9 and arriving.y >= edge - 1e-9
    assert not overlaps(waiting, arriving)


def test_driver_brakes_for_a_waiting_cyclists_front_wheel():
    cfg = load_config()
    world = World(cfg.scene, {"rates": {}}, cfg=cfg)
    lane = world.lane_y(-1)
    # a cyclist on the zebra, pointing across the road, front wheel 0.15 m into the lane's swept band
    bike = world.spawn("bicycle", crossing=True, side=1, x=0.0, y=lane + 0.9 + 0.9 - 0.15, state="cross",
                       stop_at_s=0.0, stop_duration_s=60.0)
    car = world.spawn("car", dir=-1, x=20.0, v=8.0, yields=False)
    for _ in range(200):
        world.step(0.05)
    assert not [e for e in world.gt_events if e["type"] == "collision"]
    assert car.speed < 0.1 and car.x - car.dims[0] / 2 > bike.x


def test_a_yielding_driver_is_only_trusted_once_visibly_able_to_stop():
    cfg = load_config()
    world = World(cfg.scene, {"rates": {}}, cfg=cfg)
    car = world.spawn("car", dir=1, x=-14.0, v=12.0, yields=True, reaction=1.0)
    car.meta.update(stopped_for=99, stop_seen=world.t)
    assert not world._reliably_stopping(car)  # has not reacted yet
    world.t += 1.0
    assert not world._reliably_stopping(car)  # reacted, but 12 m/s cannot stop in the ~9 m left
    car.vx = 6.0
    assert world._reliably_stopping(car)
