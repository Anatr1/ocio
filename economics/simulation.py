"""Paired isolated-crossing queue experiment using the production controller.

No network routing or calibrated citywide traffic assignment is implied. Every
policy receives the same arrivals, walking speeds, and visibility draws.
"""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from functools import lru_cache
from itertools import product
from types import SimpleNamespace

import numpy as np

from crosswalk.config import DEFAULTS
from crosswalk.signal import SignalController

# A provisional 24-hour profile, not an observed Turin hourly distribution.
PROFILE = (("Night", 6, 0.08), ("Off peak", 10, 0.45),
           ("Shoulder", 4, 0.7), ("Peak", 4, 1.0))
MODEL_VERSION = "isolated-queue-1.3"


def arrivals(vehicle_vph, pedestrian_pph, seconds, seed, recall):
    rng = np.random.default_rng(seed)
    vehicles = rng.poisson(vehicle_vph / 7200, (seconds, 2))
    pedestrians = rng.poisson(pedestrian_pph / 3600, seconds)
    total = int(pedestrians.sum())
    visible = rng.random(total) < recall
    walking = rng.uniform(0.8, 1.6, total)
    return vehicles, pedestrians, visible, walking


def policy_run(data, mode, fixed_green, button_delay, length, warmup=300,
               capacity_vph_lane=1800, adaptive_min_green_s=None):
    vehicles, pedestrians, visible, walking = data
    cfg = deepcopy(DEFAULTS["signal"])
    cfg.update(mode="fixed" if mode == "fixed" else "adaptive",
               fixed_cycle_veh_green_s=fixed_green)
    if mode == "adaptive" and adaptive_min_green_s is not None:
        cfg.update(veh_min_green_s=adaptive_min_green_s,
                   veh_max_green_s=max(cfg["veh_max_green_s"], adaptive_min_green_s))
    signal = SignalController(cfg, SimpleNamespace(L=length), lambda _: None)
    vq = [deque(), deque()]
    pq, crossing = deque(), []
    credit = [0.0, 0.0]
    ped_index = 0
    metrics = dict(vehicle_wait_s=0.0, pedestrian_wait_s=0.0,
                   vehicle_arrivals=0, pedestrian_arrivals=0,
                   vehicle_departures=0, pedestrian_departures=0,
                   maximum_queue=0, residual_vehicles=0, residual_pedestrians=0)
    trace = []
    last_vehicle = -100
    for t in range(len(pedestrians)):
        for lane in (0, 1):
            for _ in range(int(vehicles[t, lane])):
                vq[lane].append(t)
                last_vehicle = t
        for _ in range(int(pedestrians[t])):
            pq.append((t, bool(visible[ped_index]), length / walking[ped_index]))
            ped_index += 1
        crossing = [finish for finish in crossing if finish > t]
        if mode == "button":
            demand = sum(t - at >= button_delay for at, _, _ in pq)
        else:
            # Both policies retain the same manual button. Vision only adds an
            # earlier request; missed detections must not erase this fallback.
            demand = sum(seen or t - at >= button_delay for at, seen, _ in pq)
        signal.update(t, waiting=demand, crossing=len(crossing),
                      time_to_clear=max(crossing, default=t) - t,
                      vehicle_close=t - last_vehicle < 2)
        if signal.ped_state() == "green":
            for _ in range(min(3, len(pq))):
                _, _, duration = pq.popleft()
                crossing.append(t + duration)
                if t >= warmup:
                    metrics["pedestrian_departures"] += 1
        for lane in (0, 1):
            # Queues discharge at an assumed saturation flow, only on green and
            # after the crossing clears. Unused service is never banked on red.
            if signal.veh_state() == "green" and not crossing:
                credit[lane] = min(1.0, credit[lane] + capacity_vph_lane / 3600)
                if vq[lane] and credit[lane] >= 1:
                    vq[lane].popleft()
                    credit[lane] -= 1
                    if t >= warmup:
                        metrics["vehicle_departures"] += 1
            else:
                credit[lane] = 0.0
        if t >= warmup:
            # Queue integrals include unfinished travellers; there is no completed-
            # only selection bias. These seconds are stationary idling, not a
            # speed/acceleration-resolved fuel model.
            metrics["vehicle_wait_s"] += sum(map(len, vq))
            metrics["pedestrian_wait_s"] += len(pq)
            metrics["vehicle_arrivals"] += int(vehicles[t].sum())
            metrics["pedestrian_arrivals"] += int(pedestrians[t])
            metrics["maximum_queue"] = max(metrics["maximum_queue"], sum(map(len, vq)))
            if (t - warmup) % 60 == 0:
                trace.append({"minute": (t - warmup) // 60,
                              "vehicle_queue": sum(map(len, vq)), "pedestrian_queue": len(pq)})
    metrics["residual_vehicles"] = sum(map(len, vq))
    metrics["residual_pedestrians"] = len(pq)
    metrics["cycles"] = signal.cycles
    metrics["extensions"] = signal.extensions
    measured_s = len(pedestrians) - warmup
    metrics["vehicle_wait_s_per_hour"] = metrics["vehicle_wait_s"] * 3600 / measured_s
    metrics["pedestrian_wait_s_per_hour"] = metrics["pedestrian_wait_s"] * 3600 / measured_s
    metrics["mean_vehicle_wait_s"] = metrics["vehicle_wait_s"] / max(1, metrics["vehicle_arrivals"])
    metrics["mean_pedestrian_wait_s"] = metrics["pedestrian_wait_s"] / max(1, metrics["pedestrian_arrivals"])
    metrics["trace"] = trace
    return metrics


@lru_cache(maxsize=128)
def paired_experiment(vehicle_vph, pedestrian_pph, baseline, fixed_green,
                      button_delay, length, recall, seed, replications=4,
                      adaptive_min_green_s=None):
    rows = []
    for replication in range(replications):
        periods = []
        for period_index, (name, hours, factor) in enumerate(PROFILE):
            data = arrivals(vehicle_vph * factor, pedestrian_pph * factor,
                            2100, seed + replication * 100 + period_index, recall)
            base = policy_run(data, baseline, fixed_green, button_delay, length)
            adaptive = policy_run(data, "adaptive", fixed_green, button_delay, length,
                                  adaptive_min_green_s=adaptive_min_green_s)
            periods.append({"name": name, "hours": hours, "factor": factor,
                            "baseline": base, "adaptive": adaptive})
        rows.append(periods)
    return rows


def optimized_experiment(vehicle_vph, pedestrian_pph, baseline, fixed_green,
                         button_delay, length, recall, seed, priority, occupancy,
                         fuel_kg_per_idle_hour=1, active_days=365, uptime=1,
                         device_kg_year=0):
    """Choose the best tested timing on paired samples, not a citywide optimum."""
    candidates, experiments = [], []
    # With no vision in button mode, keep the existing controller fallback.
    greens = (8,) if recall == 0 and baseline == "button" else (8, 15, 30, 45, 60)
    for green in greens:
        rows = paired_experiment(vehicle_vph, pedestrian_pph, baseline, fixed_green,
                                 button_delay, length, recall, seed,
                                 adaptive_min_green_s=green)
        experiments.append(rows)

    def daily_hours(rows, policy):
        return np.array([[np.mean([periods[j][policy][f"{kind}_wait_s_per_hour"]
                                   for periods in rows]) * hours / 3600
                          for kind in ("vehicle", "pedestrian")]
                         for j, (_, hours, _) in enumerate(PROFILE)])

    base_vehicle, base_pedestrian = daily_hours(experiments[0], "baseline").sum(axis=0)
    base_person = base_pedestrian + occupancy * base_vehicle
    period_hours = [daily_hours(rows, "adaptive") for rows in experiments]
    schedules = list(product(range(len(greens)), repeat=len(PROFILE)))
    # Periods are independent paired experiments. Recombine their measured
    # outcomes to test demand-period schedules without rerunning 625 simulations.
    for schedule in schedules + [None]:
        vehicle, pedestrian = (np.array([base_vehicle, base_pedestrian]) if schedule is None else
                               sum(period_hours[i][j] for j, i in enumerate(schedule)))
        person = float(pedestrian + occupancy * vehicle)
        net_co2 = float((base_vehicle - vehicle) * active_days * uptime * fuel_kg_per_idle_hour - device_kg_year)
        timings = [{"name": name, "hours": hours, "vehicle_min_green_s": greens[schedule[j]]}
                   for j, (name, hours, _) in enumerate(PROFILE)] if schedule is not None else []
        candidates.append({"vehicle_min_green_s": timings[0]["vehicle_min_green_s"]
                           if timings and len({t["vehicle_min_green_s"] for t in timings}) == 1 else None,
                           "period_timings": timings, "baseline_fallback": schedule is None,
                           "vehicle_hours_per_day": float(vehicle),
                           "pedestrian_hours_per_day": float(pedestrian),
                           "person_hours_per_day": person,
                           "person_hours_saved_per_day": float(base_person - person),
                           "net_co2_kg_per_year": net_co2})
    # Both priorities prohibit increasing aggregate road-user waiting. The
    # baseline fallback guarantees an honest zero-time-benefit option, but still
    # charges device electricity; it cannot fabricate a CO2 saving.
    time_safe = [i for i, c in enumerate(candidates) if c["person_hours_saved_per_day"] >= 0]
    feasible = [i for i in time_safe if candidates[i]["net_co2_kg_per_year"] >= 0]
    carbon_winner = min(feasible or time_safe, key=lambda i: (-candidates[i]["net_co2_kg_per_year"],
                        candidates[i]["person_hours_per_day"], i))
    time_winner = min(feasible, key=lambda i: (candidates[i]["person_hours_per_day"],
                      -candidates[i]["net_co2_kg_per_year"], i)) if feasible else carbon_winner
    winner = time_winner if priority == "time" else carbon_winner
    schedule = (schedules + [None])[winner]
    selected_rows = [[{**experiments[0][r][j],
                       "adaptive": experiments[schedule[j]][r][j]["adaptive"] if schedule is not None
                       else experiments[0][r][j]["baseline"]}
                      for j in range(len(PROFILE))] for r in range(len(experiments[0]))]
    choice = candidates[winner]
    return selected_rows, {"priority": priority, "selected": choice,
                           "candidates": candidates, "co2_guardrail_met": choice["net_co2_kg_per_year"] >= 0,
                           "time_guardrail_met": choice["person_hours_saved_per_day"] >= 0,
                           "shared_optimum": carbon_winner == time_winner,
                           "co2_saving_target_met": choice["net_co2_kg_per_year"] > 0,
                           "status": "Best tested demand-period schedule with no extra road-user waiting" if feasible else
                           "No jointly CO2-neutral and time-neutral schedule found; least-emitting time-safe option selected"}
