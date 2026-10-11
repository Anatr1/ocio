"""Transparent screening appraisal of a proposed OCCHIO rollout."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np

from .simulation import MODEL_VERSION, PROFILE, optimized_experiment

DATA = Path(__file__).parent / "data"
DEFAULTS = {
    "traffic_level": "medium", "cost_profile": "pilot", "priority": "co2",
    "inventory_mode": "mapped", "sites_per_10k": 3.0, "coverage_pct": 100.0,
    "installations_per_node": 0.25,
    "baseline": "button", "vehicle_vph": 600.0, "pedestrian_pph": 60.0,
    "use_observed_traffic": False, "fixed_green_s": 20.0, "button_delay_s": 8.0,
    "crossing_length_m": 8.0, "recall": 0.85, "uptime": 0.90,
    "active_days": 365.0, "occupancy": 1.3, "seed": 42,
    "installed_cost_eur": 2800.0, "annual_maintenance_eur": 180.0,
    "platform_cost_eur": 20000.0, "power_watts": 10.0,
    "electricity_eur_kwh": 0.30, "grid_kg_kwh": 0.2692,
    "idle_lph": 0.62, "fuel_eur_l": 2.028, "combustion_kg_l": 2.45,
    "ice_fraction": 0.95, "engine_running_fraction": 0.60,
    "vot_eur_h": 10.0, "carbon_eur_t": 100.0,
    "discount_rate": 0.03, "horizon_years": 10,
    "replacement_fraction": 0.10, "replacement_year": 5, "replacement_schedule": "spread",
    "work_time_fraction": 0.15, "productivity_realization": 0.25,
    "labour_value_eur_h": 25.0,
    "spending_time_fraction": 0.20, "spending_eur_h": 10.0,
    "spending_additionality": 0.0, "domestic_value_added_fraction": 0.50,
    "supplier_gross_margin": 0.20, "supplier_setup_cost_eur": 100000.0,
    "supplier_discount_rate": 0.10,
}
LIMITS = {
    "sites_per_10k": (0, 100), "coverage_pct": (0, 100), "installations_per_node": (0, 1),
    "vehicle_vph": (0, 2400), "pedestrian_pph": (0, 1200),
    "fixed_green_s": (8, 180), "button_delay_s": (0, 120),
    "crossing_length_m": (4, 30), "recall": (0, 1), "uptime": (0, 1),
    "active_days": (0, 365), "occupancy": (1, 5), "seed": (0, 100000),
    "installed_cost_eur": (0, 100000), "annual_maintenance_eur": (0, 10000),
    "platform_cost_eur": (0, 10000000), "power_watts": (0, 1000),
    "electricity_eur_kwh": (0, 5), "grid_kg_kwh": (0, 2),
    "idle_lph": (0, 10), "fuel_eur_l": (0, 10), "combustion_kg_l": (0, 5),
    "ice_fraction": (0, 1), "engine_running_fraction": (0, 1),
    "vot_eur_h": (0, 200), "carbon_eur_t": (0, 1000),
    "discount_rate": (0, 0.3), "horizon_years": (1, 30),
    "replacement_fraction": (0, 1), "replacement_year": (1, 30),
    "work_time_fraction": (0, 1), "productivity_realization": (0, 1),
    "labour_value_eur_h": (0, 200),
    "spending_time_fraction": (0, 1), "spending_eur_h": (0, 1000),
    "spending_additionality": (0, 1), "domestic_value_added_fraction": (0, 1),
    "supplier_gross_margin": (0, 0.75), "supplier_setup_cost_eur": (0, 10000000),
    "supplier_discount_rate": (0, 0.50),
}
INTEGER_KEYS = {"seed", "horizon_years", "replacement_year"}


def load_dataset(scope="city"):
    filename = "districts.geojson" if scope == "city" else "municipalities.geojson"
    return json.loads((DATA / filename).read_text(encoding="utf-8"))


def defaults():
    values = dict(DEFAULTS)
    path = DATA / "costs.json"
    if path.exists():
        cost_values = json.loads(path.read_text(encoding="utf-8")).get("defaults", {})
        values.update({k: v for k, v in cost_values.items() if k in values})
    profiles = json.loads((DATA / "cost_profiles.json").read_text(encoding="utf-8"))
    values.update(profiles["profiles"][values["cost_profile"]]["parameters"])
    traffic_file = DATA / "traffic_presets.json"
    if traffic_file.exists():
        traffic = json.loads(traffic_file.read_text(encoding="utf-8"))
        values["vehicle_vph"] = traffic["presets"][values["traffic_level"]]["vehicle_vph"]
    return values


def validate(payload, dataset):
    if not isinstance(payload, dict):
        raise ValueError("The scenario must be an object.")
    raw = payload.get("parameters", {})
    if not isinstance(raw, dict) or set(raw) - set(DEFAULTS):
        raise ValueError("Unknown scenario parameter.")
    profiles = json.loads((DATA / "cost_profiles.json").read_text(encoding="utf-8"))["profiles"]
    profile = raw.get("cost_profile", "pilot")
    if not isinstance(profile, str) or profile not in profiles:
        raise ValueError("Choose pilot or production deployment cost.")
    p = defaults()
    p.update(profiles[profile]["parameters"])
    p.update(raw)
    for key, (lo, hi) in LIMITS.items():
        value = p[key]
        if isinstance(value, bool) or not isinstance(value, (float, int)):
            raise ValueError(f"{key} must be numeric.")
        if not math.isfinite(value) or not lo <= value <= hi:
            raise ValueError(f"{key} must be between {lo} and {hi}.")
        if key in INTEGER_KEYS and value != int(value):
            raise ValueError(f"{key} must be an integer.")
        if key in INTEGER_KEYS:
            p[key] = int(value)
    if not isinstance(p["baseline"], str) or p["baseline"] not in {"fixed", "button", "beacon"}:
        raise ValueError("Unknown baseline.")
    if not isinstance(p["priority"], str) or p["priority"] not in {"co2", "time"}:
        raise ValueError("Choose CO2 or time priority.")
    if not isinstance(p["inventory_mode"], str) or p["inventory_mode"] not in {"planning", "mapped"}:
        raise ValueError("Unknown inventory mode.")
    if not isinstance(p["use_observed_traffic"], bool):
        raise ValueError("use_observed_traffic must be boolean.")
    if not isinstance(p["replacement_schedule"], str) or p["replacement_schedule"] not in {"spread", "one_off"}:
        raise ValueError("Unknown replacement schedule.")
    if p["work_time_fraction"] + p["spending_time_fraction"] > 1 + 1e-9:
        raise ValueError("Work and spending time shares must total no more than 100%.")
    traffic = json.loads((DATA / "traffic_presets.json").read_text(encoding="utf-8"))
    if not isinstance(p["traffic_level"], str) or p["traffic_level"] not in traffic["presets"]:
        raise ValueError("Choose peak, medium or light Turin traffic.")
    p["vehicle_vph"] = traffic["presets"][p["traffic_level"]]["vehicle_vph"]
    p["use_observed_traffic"] = False
    selected = payload.get("areas", payload.get("municipalities", []))
    if not isinstance(selected, list) or not selected or any(not isinstance(i, str) for i in selected):
        raise ValueError("Select district identifiers from the available city boundaries.")
    if len(set(selected)) > len(dataset["features"]):
        raise ValueError("Select at least one district from the available city boundaries.")
    by_id = {str(f["properties"]["id"]): f["properties"] for f in dataset["features"]}
    if any(not isinstance(i, str) or i not in by_id for i in selected):
        raise ValueError("Unknown district.")
    selected = sorted(set(selected))
    overrides = payload.get("site_overrides", {})
    if not isinstance(overrides, dict) or set(overrides) - set(selected):
        raise ValueError("Site overrides must refer to selected districts.")
    for key, count in overrides.items():
        if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 10000:
            raise ValueError(f"Invalid site count for {key}.")
    return p, [by_id[i] for i in selected], overrides


def deployment_count(area, p, overrides):
    if area["id"] in overrides:
        return overrides[area["id"]]
    if p["inventory_mode"] == "mapped":
        mapped = area.get("signalized_crossings")
        if mapped is None:
            raise ValueError(f"No mapped inventory for {area['name']}; use a planning quota or site override.")
        potential = mapped * p["installations_per_node"]
    else:
        potential = area["population"] / 10000 * p["sites_per_10k"]
    return int(math.floor(potential * p["coverage_pct"] / 100 + 0.5))


def financials(n, physical, p):
    ped_h, veh_h = physical["pedestrian_hours"], physical["vehicle_hours"]
    person_h = ped_h + veh_h * p["occupancy"]
    fuel_l = veh_h * p["idle_lph"] * p["ice_fraction"] * p["engine_running_fraction"]
    electricity = n * p["power_watts"] * 8760 / 1000
    co2_t = (fuel_l * p["combustion_kg_l"] - electricity * p["grid_kg_kwh"]) / 1000
    time_value = person_h * p["vot_eur_h"]
    fuel_value = fuel_l * p["fuel_eur_l"]
    carbon_value = co2_t * p["carbon_eur_t"]
    gross = time_value + fuel_value + carbon_value
    price = p["installed_cost_eur"] / (1 - p["supplier_gross_margin"])
    service_fee = p["annual_maintenance_eur"] / (1 - p["supplier_gross_margin"])
    opex = n * service_fee + electricity * p["electricity_eur_kwh"]
    capital = n * price + (p["platform_cost_eur"] if n else 0)
    spread_replacements = p.get("replacement_schedule", "spread") == "spread"
    expected_replaced_units = n * p["replacement_fraction"] if spread_replacements or p["replacement_year"] <= p["horizon_years"] else 0.0
    replacement_budget = expected_replaced_units * price
    annual_replacement = replacement_budget / p["horizon_years"]
    cashflows = [{"year": 0, "benefit": 0, "cost": capital, "net": -capital,
                  "cumulative": -capital, "discounted_cumulative": -capital}]
    discounted_cost, discounted_benefit = capital, 0.0
    cumulative, discounted_cumulative, payback = -capital, -capital, None
    for year in range(1, p["horizon_years"] + 1):
        replacement = annual_replacement if spread_replacements else (replacement_budget if year == p["replacement_year"] else 0)
        cost = opex + replacement
        net = gross - cost
        discount = (1 + p["discount_rate"]) ** year
        discounted_cost += cost / discount
        discounted_benefit += gross / discount
        cumulative += net
        discounted_cumulative += net / discount
        cashflows.append({"year": year, "benefit": gross, "cost": cost, "maintenance_eur": n * service_fee,
                          "electricity_eur": electricity * p["electricity_eur_kwh"], "replacement_eur": replacement, "net": net,
                          "cumulative": cumulative, "discounted_cumulative": discounted_cumulative})
    # Report durable discounted payback, not a temporary crossing before replacement.
    for i, row in enumerate(cashflows[1:], 1):
        if row["discounted_cumulative"] >= 0 and all(r["discounted_cumulative"] >= 0 for r in cashflows[i:]):
            payback = row["year"]
            break
    annuity = sum((1 + p["discount_rate"]) ** -y for y in range(1, p["horizon_years"] + 1))
    replacement_pv_fraction = (p["replacement_fraction"] * annuity / p["horizon_years"] if spread_replacements else
                               (p["replacement_fraction"] / (1 + p["discount_rate"]) ** p["replacement_year"]
                                if p["replacement_year"] <= p["horizon_years"] else 0))
    affordable = ((discounted_benefit - opex * annuity - (p["platform_cost_eur"] if n else 0)) /
                  (n * (1 + replacement_pv_fraction))) if n else None
    supplier_annuity = sum((1 + p["supplier_discount_rate"]) ** -y for y in range(1, p["horizon_years"] + 1))
    unit_margin = price - p["installed_cost_eur"]
    annual_service_margin = service_fee - p["annual_maintenance_eur"]
    contribution_per_site_pv = unit_margin + annual_service_margin * supplier_annuity
    productive_hours = person_h * p["work_time_fraction"] * p["productivity_realization"]
    work_value_added = productive_hours * p["labour_value_eur_h"]
    spending_hours = person_h * p["spending_time_fraction"]
    gross_spending = spending_hours * p["spending_eur_h"]
    net_spending = gross_spending * p["spending_additionality"]
    spending_value_added = net_spending * p["domestic_value_added_fraction"]
    supplier_npv = n * contribution_per_site_pv - p["supplier_setup_cost_eur"]
    return {
        "sites": n, "pedestrian_hours": ped_h, "vehicle_hours": veh_h,
        "person_hours": person_h, "fuel_litres": fuel_l, "electricity_kwh": electricity,
        "traffic_co2_tonnes": fuel_l * p["combustion_kg_l"] / 1000,
        "device_co2_tonnes": electricity * p["grid_kg_kwh"] / 1000,
        "net_co2_tonnes": co2_t, "time_value_eur": time_value,
        "fuel_saving_eur": fuel_value, "carbon_value_eur": carbon_value,
        "annual_gross_benefit_eur": gross, "annual_opex_eur": opex,
        "annual_social_net_eur": gross - opex - annual_replacement, "capital_eur": capital,
        "annual_maintenance_cost_eur": n * service_fee,
        "annual_electricity_cost_eur": electricity * p["electricity_eur_kwh"],
        "replacement_budget_eur": replacement_budget, "average_annual_replacement_eur": annual_replacement,
        "expected_replaced_units": expected_replaced_units,
        "average_annual_running_cost_eur": opex + annual_replacement,
        "npv_eur": discounted_benefit - discounted_cost,
        "benefit_cost_ratio": discounted_benefit / discounted_cost if discounted_cost else None,
        "municipal_cost_pv_eur": discounted_cost, "municipal_cash_saving_eur": 0,
        "payback_years": payback, "affordable_installed_price_eur": affordable,
        "productivity_potential_eur": max(0, person_h) * p["work_time_fraction"] * p["productivity_realization"] * p["labour_value_eur_h"],
        "productive_hours_delta": productive_hours, "work_value_added_eur": work_value_added,
        "spending_hours_delta": spending_hours, "gross_spending_delta_eur": gross_spending,
        "net_new_spending_delta_eur": net_spending, "spending_value_added_eur": spending_value_added,
        "gdp_scenario_eur": work_value_added + spending_value_added,
        "installed_sale_price_eur": price, "annual_service_fee_eur": service_fee,
        "supplier_initial_revenue_eur": n * price, "supplier_initial_delivery_cost_eur": n * p["installed_cost_eur"],
        "supplier_annual_service_revenue_eur": n * service_fee,
        "supplier_annual_service_contribution_eur": n * annual_service_margin,
        "supplier_contribution_npv_eur": supplier_npv,
        "supplier_break_even_sites": math.ceil(p["supplier_setup_cost_eur"] / contribution_per_site_pv) if contribution_per_site_pv > 0 else None,
        "gdp_increase_eur": None, "safety_benefit_eur": 0,
        "cashflows": cashflows,
    }


def annual_deltas(experiment, p):
    out = []
    for periods in experiment:
        ped_h = veh_h = 0.0
        for row in periods:
            factor = row["hours"] * p["active_days"] * p["uptime"] / 3600
            ped_h += (row["baseline"]["pedestrian_wait_s_per_hour"] - row["adaptive"]["pedestrian_wait_s_per_hour"]) * factor
            veh_h += (row["baseline"]["vehicle_wait_s_per_hour"] - row["adaptive"]["vehicle_wait_s_per_hour"]) * factor
        out.append({"pedestrian_hours": ped_h, "vehicle_hours": veh_h})
    return out


def run_scenario(payload, dataset=None, progress=lambda *_: None):
    dataset = dataset or load_dataset()
    p, areas, overrides = validate(payload, dataset)
    counts = {a["id"]: deployment_count(a, p, overrides) for a in areas}
    sites = sum(counts.values())
    if sites > 20000:
        raise ValueError("Maximum scenario size is 20,000 sites.")
    cohorts, experiments, optimization, warnings = {}, {}, {}, []
    for a in areas:
        flow = p["vehicle_vph"]
        observed = a.get("traffic_vph")
        if p["use_observed_traffic"] and observed is not None:
            # A sensor arc is directional; the factor of two is an explicit
            # bidirectional approximation, not an observed crossing total.
            flow = min(2400, max(0, round(observed * 2 / 100) * 100))
        cohorts[a["id"]] = float(flow)
    active_flows = sorted({cohorts[a["id"]] for a in areas if counts[a["id"]]})
    # Bound work if observed counts create many distinct cohorts. Nearest 200 vph
    # is exposed in the result; independent jobs per geographical area are unnecessary.
    if len(active_flows) > 12:
        cohorts = {k: round(v / 200) * 200.0 for k, v in cohorts.items()}
        active_flows = sorted(set(cohorts[a["id"]] for a in areas if counts[a["id"]]))
    for i, flow in enumerate(active_flows):
        progress(i / max(1, len(active_flows)), f"Paired crossing experiment {i + 1}/{len(active_flows)}")
        if p["baseline"] == "beacon":
            experiments[flow] = []
        else:
            experiments[flow], optimization[flow] = optimized_experiment(flow, p["pedestrian_pph"], p["baseline"],
                p["fixed_green_s"], p["button_delay_s"], p["crossing_length_m"], p["recall"], p["seed"],
                p["priority"], p["occupancy"],
                fuel_kg_per_idle_hour=p["idle_lph"] * p["ice_fraction"] * p["engine_running_fraction"] * p["combustion_kg_l"],
                active_days=p["active_days"], uptime=p["uptime"],
                device_kg_year=p["power_watts"] * 8760 / 1000 * p["grid_kg_kwh"])
            if not optimization[flow]["co2_guardrail_met"]:
                warnings.append("No tested schedule achieves net CO2 neutrality without increasing road-user waiting at this demand and energy use. The least-emitting time-safe option is shown; CO2 savings cannot be claimed. Reduce device power, reconsider placement, or collect site data before deployment.")
    replications = 4
    samples = [{"pedestrian_hours": 0.0, "vehicle_hours": 0.0} for _ in range(replications)]
    area_rows = []
    saturated = False
    for a in areas:
        n, flow = counts[a["id"]], cohorts[a["id"]]
        ex = experiments.get(flow, [])
        deltas = annual_deltas(ex, p) if ex else [{"pedestrian_hours": 0.0, "vehicle_hours": 0.0} for _ in samples]
        mean = {k: float(np.mean([r[k] for r in deltas])) * n for k in samples[0]}
        for j, sample in enumerate(samples):
            for k in sample:
                sample[k] += deltas[j][k] * n
        if ex and n:
            saturated |= any(r["baseline"]["maximum_queue"] > 100 or r["adaptive"]["maximum_queue"] > 100 for periods in ex for r in periods)
        area_p = {**p, "platform_cost_eur": 0}
        result = financials(n, mean, area_p)
        area_rows.append({"id": a["id"], "name": a["name"], "population": a["population"],
                          "zone": a.get("zone"), "sites": n, "vehicle_vph": flow,
                          "traffic_observed": bool(p["use_observed_traffic"] and a.get("traffic_vph") is not None),
                          "signalized_crossings": a.get("signalized_crossings"),
                          "pedestrian_hours": mean["pedestrian_hours"], "vehicle_hours": mean["vehicle_hours"],
                          "net_co2_tonnes": result["net_co2_tonnes"],
                          "work_value_added_eur": result["work_value_added_eur"],
                          "spending_value_added_eur": result["spending_value_added_eur"],
                          "gdp_scenario_eur": result["gdp_scenario_eur"],
                          "annual_maintenance_cost_eur": result["annual_maintenance_cost_eur"],
                          "replacement_budget_eur": result["replacement_budget_eur"],
                          "annual_social_net_eur": result["annual_social_net_eur"], "capital_eur": result["capital_eur"]})
    physical = {k: float(np.mean([r[k] for r in samples])) for k in samples[0]}
    total = financials(sites, physical, p)
    baseline_idle_hours = sum(counts[a["id"]] * p["active_days"] * float(np.mean([
        sum(row["hours"] * row["baseline"]["vehicle_wait_s_per_hour"] / 3600 for row in periods)
        for periods in experiments[cohorts[a["id"]]]])) for a in areas
        if counts[a["id"]] and experiments.get(cohorts[a["id"]]))
    fuel_factor = p["idle_lph"] * p["ice_fraction"] * p["engine_running_fraction"]
    total.update(baseline_idle_fuel_litres=baseline_idle_hours * fuel_factor if experiments and p["baseline"] != "beacon" else None,
                 adaptive_idle_fuel_litres=(baseline_idle_hours - physical["vehicle_hours"]) * fuel_factor
                 if experiments and p["baseline"] != "beacon" else None,
                 fuel_saved_per_crossing_litres=total["fuel_litres"] / sites if sites else 0,
                 engine_on_idle_ml_per_minute=p["idle_lph"] * 1000 / 60)
    population = sum(a["population"] for a in areas)
    total.update(population=population, area_count=len(areas),
                 capital_per_resident_eur=total["capital_eur"] / population if population else None)
    # Correlated scenario sensitivities, not a statistical confidence interval.
    rng = np.random.default_rng(p["seed"] + 9876)
    sensitivity = []
    for _ in range(256):
        physical_draw = samples[int(rng.integers(replications))]
        physical_draw = {k: v * rng.uniform(0.5, 1.5) for k, v in physical_draw.items()}
        uncertain = dict(p)
        for key, spread in (("installed_cost_eur", .30), ("annual_maintenance_eur", .30),
                            ("vot_eur_h", .50), ("idle_lph", .30)):
            uncertain[key] *= rng.uniform(1 - spread, 1 + spread)
        sensitivity.append(financials(sites, physical_draw, uncertain))
    bands = {k: {"p10": float(np.percentile([r[k] for r in sensitivity], 10)),
                 "p90": float(np.percentile([r[k] for r in sensitivity], 90))}
             for k in ("npv_eur", "annual_social_net_eur", "net_co2_tonnes", "person_hours")}
    scale = []
    for fraction in (0, .1, .25, .5, .75, 1):
        count = round(sites * fraction)
        scaled = {k: v * count / sites if sites else 0 for k, v in physical.items()}
        values = financials(count, scaled, p)
        scale.append({"sites": count, "capital_eur": values["capital_eur"], "npv_eur": values["npv_eur"],
                      "annual_social_net_eur": values["annual_social_net_eur"]})
    warnings.extend([
        "Timing optimization tests five vehicle minimum-green settings (8, 15, 30, 45, 60 seconds) separately in each of four independent demand periods, comparing 625 schedules plus baseline fallback on the same four simulated seeds. Both priorities prohibit an increase in combined pedestrian plus occupancy-weighted vehicle waiting. CO2 maximizes net stationary-combustion savings after device electricity under that constraint. Time minimizes combined waiting among CO2-neutral or better schedules; if none exist, the least-emitting time-safe option is shown with an unmet-target warning. Identical results are possible when both objectives select the same schedule. With zero vision recall in button mode, baseline timing is retained. Yellow, all-red and clearance timings are unchanged. Period transitions are not simulated; the 24-hour demand profile is provisional, not observed Turin hourly data. This is an in-sample isolated-crossing choice, not a validated network optimum or deployment-approved controller setting. All districts share assumed demand; no evidence-based geographical priority is claimed.",
        "This is an isolated-crossing queue simulation scaled to selected Turin city districts, not a calibrated city traffic network.",
        "Hourly demand, pedestrian arrivals, controller baseline, detection recall and uptime are scenario assumptions. Confirm them with field measurements.",
        "Road-user passages across sites can repeat. Hours are local delay changes, not unique travellers or total journey-time changes; network spillback/rebound is excluded.",
        "GDP contribution is a conditional gross-value-added proxy, not measured GDP growth. Work/spending allocations, realization, additional spending and domestic value-added shares are unmeasured assumptions. It excludes net product taxes, multipliers, network effects and overlap between productive output and consumption. Spending additionality must remove shifted spending and output already counted in the work channel. GDP is excluded from social NPV to avoid counting time twice. Crash reduction is not causally estimated.",
        "CO2 covers stationary combustion and device operational electricity only; acceleration, manufacturing, installation and infrastructure emissions are excluded.",
        "Gross consumer prices are used as a screening convention. Tax transfers, VAT recovery and formal transport appraisal adjustments are not modelled.",
        "The assumed supplier gross margin is applied to site delivery and annual service budgets; municipal costs include these estimated sale prices. Supplier contribution deducts the separate assumed product setup budget, but is not audited profit: sales, legal, insurance, taxes, financing, replacement sales and shared-platform contracts are excluded.",
        "Sensitivity p10-p90 varies effects +/-50%, installed/maintenance cost +/-30%, time value +/-50%, idling +/-30% and paired seeds; it is not an empirical confidence interval.",
    ])
    traffic_evidence = json.loads((DATA / "traffic_presets.json").read_text(encoding="utf-8"))
    warnings.append(traffic_evidence["caveat"])
    profile_evidence = json.loads((DATA / "cost_profiles.json").read_text(encoding="utf-8"))["profiles"][p["cost_profile"]]
    warnings.extend(profile_evidence["conditions"])
    warnings.append(f"Routine maintenance is separate from major device replacement. Replacement allowance is {p['replacement_fraction'] * 100:g}% of equipped units across the {p['horizon_years']}-year appraisal, at the entered installed price per replacement, not that percentage every year. Schedule: {p['replacement_schedule']}. Fractional replacement counts are expected budgeting values, not partial devices.")
    if p["inventory_mode"] == "planning":
        warnings.append("Site counts are a population-based planning quota, not a surveyed crossing inventory. Selection is a circoscrizione boundary, not individual road approvals.")
    else:
        warnings.append(f"OpenStreetMap counts mapped nodes, not unique crossings or certified installation locations. This scenario assumes {p['installations_per_node']} equipped crossings per signalized node; grouping and controller compatibility are unverified. Coverage is applied before rounding each district.")
    if p["use_observed_traffic"]:
        warnings.append("5T counts are a single five-minute directional sensor snapshot, doubled and rounded into two-direction demand cohorts. Missing areas use the manual rate; no annual representativeness is claimed.")
    if p["baseline"] == "beacon":
        warnings.append("Beacon-only deployment has no validated causal time/CO2/safety benefit. Modelled traffic benefit is zero; energy and costs remain. Installing NEW traffic signals requires a different civil-works appraisal.")
    if saturated:
        warnings.append("A simulated approach queue exceeds 100 vehicles. Treat this scenario as capacity-constrained and unsuitable for simple city-scale extrapolation.")
    if p["uptime"] < 1:
        warnings.append("During assumed downtime the site reverts to its baseline controller. Device electricity is conservatively charged for 24/7 operation.")
    canonical = {"scope": "turin-city-districts", "parameters": p, "areas": sorted(a["id"] for a in areas), "site_overrides": overrides}
    dataset_hash = hashlib.sha256(json.dumps(dataset, sort_keys=True).encode()).hexdigest()
    code_hash = hashlib.sha256(Path(__file__).read_bytes() + Path(__file__).with_name("simulation.py").read_bytes()
                               + (Path(__file__).parents[1] / "crosswalk/signal.py").read_bytes()).hexdigest()
    digest = hashlib.sha256(json.dumps(canonical, sort_keys=True).encode() + dataset_hash.encode() + code_hash.encode()).hexdigest()[:16]
    experiment = experiments[active_flows[0]] if active_flows else []
    progress(1, "Complete")
    return {"id": digest, "model_version": MODEL_VERSION, "dataset_sha256": dataset_hash,
            "code_sha256": code_hash, "scenario": canonical, "parameters": p, "totals": total,
            "areas": area_rows, "sensitivity": bands, "scale": scale,
            "optimization": [{"vehicle_vph": flow, **choice} for flow, choice in optimization.items()],
            "inventory": {"basis": p["inventory_mode"], "coverage_pct": p["coverage_pct"],
                          "estimated_crossings_at_100_pct": sum(deployment_count(a, {**p, "coverage_pct": 100}, {}) for a in areas),
                          "mapped_signalized_nodes": sum(a.get("signalized_crossings") or 0 for a in areas),
                          "crossings_per_node_assumption": p["installations_per_node"],
                          "count_status": "Provisional estimate, not a surveyed or certified inventory",
                          "legacy_field": "sites means estimated equipped crossings"},
            "experiment": experiment[0] if experiment else [],
            "benchmark_vehicle_vph": active_flows[0] if active_flows else None,
            "profile": [{"name": n, "hours": h, "factor": f} for n, h, f in PROFILE],
            "warnings": warnings, "replications": replications, "measurement_seconds_per_period": 1800}
