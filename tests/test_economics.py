from copy import deepcopy
import json
import math

import numpy as np
import pytest

from economics.model import DATA, DEFAULTS, defaults, deployment_count, financials, load_dataset, run_scenario, validate
from economics.simulation import PROFILE, arrivals, optimized_experiment, paired_experiment, policy_run


@pytest.fixture
def dataset():
    return {"type": "FeatureCollection", "features": [
        {"properties": {"id": "001272", "name": "Torino", "population": 10000,
                        "signalized_crossings": 8, "traffic_vph": None}},
        {"properties": {"id": "001001", "name": "Other", "population": 20000,
                        "signalized_crossings": None, "traffic_vph": 200}},
    ]}


def test_primary_demographics_and_inventory():
    d = load_dataset("metropolitan")
    rows = [f["properties"] for f in d["features"]]
    assert len(rows) == len({r["id"] for r in rows}) == 312
    assert sum(r["population"] for r in rows) == 2204276
    assert {r["zone"] for r in rows} == set(range(1, 12))
    assert next(r for r in rows if r["id"] == "001272")["population"] == 853196
    for r in rows:
        assert r["commuters_work"] + r["commuters_study"] == r["commuters_total"]
        assert r["commuters_internal"] + r["commuters_outbound"] == r["commuters_total"]
        assert 0 <= r["signalized_crossings"] <= r["mapped_crossings"]


def test_city_scope_has_only_eight_official_districts():
    d = load_dataset()
    rows = [f["properties"] for f in d["features"]]
    assert len(rows) == 8
    assert {r["id"] for r in rows} == {f"C{i}" for i in range(1, 9)}
    assert sum(r["population"] for r in rows) == 858874
    assert {r["population_year"] for r in rows} == {2025}
    assert sum(r["signalized_crossings"] for r in rows) == 4009
    assert all(0 <= r["signalized_crossings"] <= r["mapped_crossings"] for r in rows)
    with pytest.raises(ValueError, match="Unknown district"):
        validate({"areas": ["001272"]}, d)


@pytest.mark.parametrize("parameters", [
    {"uptime": math.nan}, {"recall": 2}, {"seed": 1.5}, {"vehicle_vph": True},
    {"baseline": "imaginary"}, {"inventory_mode": "imaginary"}, {"gdp_increase": 1},
    {"use_observed_traffic": 1}, {"horizon_years": 0},
    {"traffic_level": "custom"}, {"traffic_level": []}, {"cost_profile": []},
    {"cost_profile": "free"}, {"baseline": []}, {"inventory_mode": []},
    {"replacement_schedule": []}, {"replacement_schedule": "yearly10percent"},
    {"spending_time_fraction": 1, "work_time_fraction": .1},
    {"spending_eur_h": math.nan}, {"spending_additionality": 2},
    {"priority": "money"}, {"priority": []},
])
def test_invalid_parameters_rejected(dataset, parameters):
    with pytest.raises(ValueError):
        validate({"municipalities": ["001272"], "parameters": parameters}, dataset)


@pytest.mark.parametrize("traffic", ["light", "medium", "peak"])
def test_co2_priority_and_time_guardrail_are_real_timing_choices(traffic):
    co2 = run_scenario({"areas": ["C1"], "parameters": {"priority": "co2", "traffic_level": traffic}})
    time = run_scenario({"areas": ["C1"], "parameters": {"priority": "time", "traffic_level": traffic}})
    carbon = co2["optimization"][0]
    travel = time["optimization"][0]
    assert len(carbon["candidates"]) == 626
    feasible = [c for c in travel["candidates"] if c["net_co2_kg_per_year"] >= 0 and c["person_hours_saved_per_day"] >= 0]
    assert feasible
    assert carbon["selected"]["net_co2_kg_per_year"] == max(c["net_co2_kg_per_year"] for c in feasible)
    assert travel["selected"]["person_hours_per_day"] == min(c["person_hours_per_day"] for c in feasible)
    assert co2["totals"]["net_co2_tonnes"] >= time["totals"]["net_co2_tonnes"] >= 0
    assert time["totals"]["person_hours"] >= co2["totals"]["person_hours"] > 0
    assert carbon["selected"]["period_timings"] != travel["selected"]["period_timings"]
    assert not carbon["shared_optimum"] and not travel["shared_optimum"]
    assert co2["id"] != time["id"]
    for result in (co2, time):
        totals = result["totals"]
        assert totals["baseline_idle_fuel_litres"] - totals["adaptive_idle_fuel_litres"] == pytest.approx(totals["fuel_litres"])
        assert result["optimization"][0]["selected"]["net_co2_kg_per_year"] * totals["sites"] / 1000 == pytest.approx(totals["net_co2_tonnes"])
        assert result["optimization"][0]["selected"]["person_hours_saved_per_day"] * totals["sites"] * result["parameters"]["active_days"] * result["parameters"]["uptime"] == pytest.approx(totals["person_hours"])


def test_no_demand_keeps_baseline_without_fabricating_savings():
    # Zero pedestrians leave the baseline and every adaptive timing identical.
    result = run_scenario({"areas": ["C1"], "parameters": {"pedestrian_pph": 0}})
    assert result["totals"]["person_hours"] == 0
    assert result["totals"]["net_co2_tonnes"] < 0
    assert result["optimization"][0]["shared_optimum"]
    assert result["optimization"][0]["time_guardrail_met"]


@pytest.mark.parametrize("priority", ["co2", "time"])
def test_time_regressing_schedules_revert_to_baseline(monkeypatch, priority):
    rows = [[{"name": name, "hours": hours, "factor": factor,
              "baseline": {"vehicle_wait_s_per_hour": 3600, "pedestrian_wait_s_per_hour": 3600},
              "adaptive": {"vehicle_wait_s_per_hour": 0, "pedestrian_wait_s_per_hour": 14400}}
             for name, hours, factor in PROFILE] for _ in range(4)]
    monkeypatch.setattr("economics.simulation.paired_experiment", lambda *args, **kwargs: rows)
    experiment, choice = optimized_experiment(107, 60, "button", 20, 8, 8, .85, 42,
                                              priority, 1.3, device_kg_year=10)
    assert choice["selected"]["baseline_fallback"]
    assert choice["selected"]["person_hours_saved_per_day"] == 0
    assert choice["selected"]["net_co2_kg_per_year"] == -10
    assert not choice["co2_guardrail_met"]
    assert choice["shared_optimum"]
    assert all(row["adaptive"] == row["baseline"] for periods in experiment for row in periods)


def test_impossible_co2_target_is_not_fabricated():
    result = run_scenario({"areas": ["C1"], "parameters": {"priority": "time", "active_days": 0}})
    assert not result["optimization"][0]["co2_guardrail_met"]
    assert result["totals"]["net_co2_tonnes"] < 0
    assert any("CO2 savings cannot be claimed" in message for message in result["warnings"])


def test_idle_reference_is_litres_per_engine_on_hour_not_per_minute():
    p = defaults()
    assert p["idle_lph"] == .62
    result = financials(1, {"pedestrian_hours": 0, "vehicle_hours": 30 / 3600}, p)
    assert result["fuel_litres"] == pytest.approx(.62 * 30 / 3600 * p["ice_fraction"] * p["engine_running_fraction"])


def test_ids_and_explicit_site_overrides(dataset):
    p, areas, overrides = validate({"municipalities": ["001272", "001272"],
                                   "site_overrides": {"001272": 7}}, dataset)
    assert len(areas) == 1
    assert deployment_count(areas[0], p, overrides) == 7
    for payload in ({"municipalities": []}, {"municipalities": ["bad"]},
                    {"municipalities": ["001272"], "site_overrides": {"001001": 3}},
                    {"municipalities": ["001272"], "site_overrides": {"001272": 2.5}}):
        with pytest.raises(ValueError):
            validate(payload, dataset)


def test_node_count_is_not_installation_count(dataset):
    area = dataset["features"][0]["properties"]
    p = {**DEFAULTS, "inventory_mode": "mapped", "installations_per_node": .25}
    assert deployment_count(area, p, {}) == 2
    with pytest.raises(ValueError):
        deployment_count(dataset["features"][1]["properties"], p, {})


def test_zero_deployment_zero_cost(dataset):
    r = run_scenario({"municipalities": ["001272"], "parameters": {"coverage_pct": 0}}, dataset)
    t = r["totals"]
    assert t["capital_eur"] == t["npv_eur"] == t["annual_opex_eur"] == 0
    assert t["benefit_cost_ratio"] is None
    assert t["gdp_increase_eur"] is None


def test_beacon_does_not_invent_benefits(dataset):
    r = run_scenario({"municipalities": ["001272"], "parameters": {"baseline": "beacon"}}, dataset)
    t = r["totals"]
    assert t["pedestrian_hours"] == t["vehicle_hours"] == t["fuel_saving_eur"] == 0
    assert t["net_co2_tonnes"] < 0
    assert t["npv_eur"] < 0
    assert t["payback_years"] is None
    assert t["municipal_cash_saving_eur"] == t["safety_benefit_eur"] == 0


def test_financial_accounting_and_no_double_counted_productivity():
    p = {**DEFAULTS, "installed_cost_eur": 1000, "platform_cost_eur": 100,
         "annual_maintenance_eur": 50, "power_watts": 0, "horizon_years": 2,
         "discount_rate": 0, "vot_eur_h": 10, "idle_lph": 0,
         "replacement_fraction": .5, "replacement_year": 2, "supplier_gross_margin": 0}
    t = financials(2, {"pedestrian_hours": 100, "vehicle_hours": 0}, p)
    assert t["capital_eur"] == 2100
    assert t["annual_gross_benefit_eur"] == 1000
    assert t["npv_eur"] == 2000 - (2100 + 2*100 + 1000)
    assert t["cashflows"][-1]["discounted_cumulative"] == t["npv_eur"]
    changed = financials(2, {"pedestrian_hours": 100, "vehicle_hours": 0},
                         {**p, "productivity_realization": 1, "labour_value_eur_h": 200})
    assert changed["npv_eur"] == t["npv_eur"]
    assert changed["productivity_potential_eur"] > t["productivity_potential_eur"]


def test_more_cost_cannot_improve_npv_and_losses_remain_negative():
    physical = {"pedestrian_hours": -100, "vehicle_hours": -200}
    t = financials(1, physical, DEFAULTS)
    costly = financials(1, physical, {**DEFAULTS, "installed_cost_eur": 20000})
    assert costly["npv_eur"] < t["npv_eur"] < 0
    assert t["net_co2_tonnes"] < 0 and t["fuel_saving_eur"] < 0
    assert t["person_hours"] < 0 and t["productivity_potential_eur"] == 0


def test_supplier_margin_separate_from_social_value():
    p = {**DEFAULTS, "installed_cost_eur": 1000, "annual_maintenance_eur": 80,
         "supplier_gross_margin": .2, "supplier_setup_cost_eur": 1000,
         "supplier_discount_rate": 0, "horizon_years": 1, "power_watts": 0,
         "platform_cost_eur": 0}
    t = financials(4, {"pedestrian_hours": 0, "vehicle_hours": 0}, p)
    assert t["installed_sale_price_eur"] == 1250
    assert t["annual_service_fee_eur"] == 100
    assert t["capital_eur"] == 5000
    assert t["annual_opex_eur"] == 400
    assert t["supplier_contribution_npv_eur"] == 80
    assert t["supplier_break_even_sites"] == 4
    assert t["npv_eur"] < 0  # a supplier can earn contribution while society loses


def test_zero_visibility_matches_button_policy_and_arrivals_are_identical():
    data = arrivals(600, 60, 900, 42, 0)
    copied = deepcopy(data)
    base = policy_run(data, "button", 20, 8, 8)
    vision = policy_run(data, "adaptive", 20, 8, 8)
    assert base == vision
    for old, new in zip(copied, data):
        np.testing.assert_array_equal(old, new)
    assert base["vehicle_wait_s"] >= 0 and base["pedestrian_wait_s"] >= 0


def test_empty_demand_zero_delay():
    data = arrivals(0, 0, 900, 1, 1)
    for mode in ("fixed", "button", "adaptive"):
        r = policy_run(data, mode, 20, 8, 8)
        assert r["vehicle_wait_s"] == r["pedestrian_wait_s"] == 0
        assert r["vehicle_arrivals"] == r["pedestrian_arrivals"] == 0


def test_determinism_and_aggregate_conservation(dataset):
    payload = {"municipalities": ["001272", "001001"], "parameters": {"baseline": "button", "recall": 0, "inventory_mode": "planning"}}
    first, second = run_scenario(payload, dataset), run_scenario(payload, dataset)
    assert first == second
    t = first["totals"]
    for key in ("sites", "population", "pedestrian_hours", "vehicle_hours", "net_co2_tonnes", "annual_social_net_eur"):
        assert sum(r[key] for r in first["areas"]) == pytest.approx(t[key])
    assert t["pedestrian_hours"] == t["vehicle_hours"] == 0
    assert t["npv_eur"] < 0


def test_three_traffic_levels_reproduce_primary_hourly_profile():
    data = json.loads((DATA / "traffic_presets.json").read_text())
    assert set(data["presets"]) == {"peak", "medium", "light"}
    day = data["observations"][0]
    assert day["date"] == "2026-10-09"
    values = day["hourly_mean_arc_vph"]
    assert len(values) == 24
    assert data["presets"]["peak"]["vehicle_vph"] == 2 * max(values) == 1128
    assert data["presets"]["medium"]["vehicle_vph"] == 2 * day["daily_mean_arc_vph"] == 626
    assert data["presets"]["light"]["vehicle_vph"] == round(2 * sum(values[:6]) / 6) == 107


@pytest.mark.parametrize("level, expected", [("peak", 1128), ("medium", 626), ("light", 107)])
def test_traffic_choice_resolves_authoritative_flow(dataset, level, expected):
    p, _, _ = validate({"areas": ["001272"], "parameters": {
        "traffic_level": level, "vehicle_vph": 100, "use_observed_traffic": True}}, dataset)
    assert p["vehicle_vph"] == expected
    assert p["use_observed_traffic"] is False


def test_pilot_and_production_cost_profiles(dataset):
    p = defaults()
    assert p["traffic_level"] == "medium" and p["vehicle_vph"] == 626
    assert p["inventory_mode"] == "mapped"
    assert p["replacement_fraction"] == .1 and p["horizon_years"] == 10
    assert p["replacement_schedule"] == "spread"
    assert p["installed_cost_eur"] == 908.31 and p["platform_cost_eur"] == 2000
    profiles = json.loads((DATA / "cost_profiles.json").read_text())["profiles"]
    costs = json.loads((DATA / "costs.json").read_text())
    hardware = sum(b["cost_eur"] * b["quantity"] for b in costs["bom"])
    pilot = profiles["pilot"]
    assert hardware == pytest.approx(455.74)
    assert pilot["hardware_eur"] == profiles["production"]["hardware_eur"] == pytest.approx(hardware)
    labour = sum(b["cost_eur"] * b["quantity"] for b in pilot["installation"])
    assert p["installed_cost_eur"] == round((hardware + labour) * 1.1, 2)
    price = financials(1, {"pedestrian_hours": 0, "vehicle_hours": 0}, p)
    assert price["installed_sale_price_eur"] == pytest.approx(1135.3875)
    assert price["annual_service_fee_eur"] == 100
    production, _, _ = validate({"areas": ["001272"], "parameters": {"cost_profile": "production"}}, dataset)
    assert production["installed_cost_eur"] == costs["defaults"]["installed_cost_eur"]
    assert production["platform_cost_eur"] == 50000
    assert production["annual_maintenance_eur"] == 120


def test_percentage_applies_to_selected_signalized_inventory():
    data = load_dataset()
    area = data["features"][0]["properties"]
    p = defaults()
    for percentage in (0, 1, 25, 50, 100):
        expected = math.floor(area["signalized_crossings"] * .25 * percentage / 100 + .5)
        assert deployment_count(area, {**p, "coverage_pct": percentage}, {}) == expected
    r = run_scenario({"areas": [area["id"]], "parameters": {"coverage_pct": 25, "baseline": "beacon"}})
    assert r["totals"]["sites"] == deployment_count(area, {**p, "coverage_pct": 25}, {})
    assert r["inventory"]["estimated_crossings_at_100_pct"] == deployment_count(area, p, {})
    assert r["inventory"]["coverage_pct"] == 25


def test_gdp_scenario_accounts_for_work_and_net_new_domestic_spending():
    p = {**DEFAULTS, "work_time_fraction": .6, "productivity_realization": .5,
         "labour_value_eur_h": 30, "spending_time_fraction": .4, "spending_eur_h": 10,
         "spending_additionality": .25, "domestic_value_added_fraction": .5}
    physical = {"pedestrian_hours": 1000, "vehicle_hours": 0}
    result = financials(1, physical, p)
    assert result["productive_hours_delta"] == 300
    assert result["work_value_added_eur"] == 9000
    assert result["gross_spending_delta_eur"] == 4000
    assert result["net_new_spending_delta_eur"] == 1000
    assert result["spending_value_added_eur"] == 500
    assert result["gdp_scenario_eur"] == 9500
    assert result["gdp_increase_eur"] is None  # causal GDP change remains unidentified
    no_additionality = financials(1, physical, {**p, "spending_additionality": 0})
    assert no_additionality["spending_value_added_eur"] == 0
    assert no_additionality["gdp_scenario_eur"] == 9000
    assert no_additionality["npv_eur"] == result["npv_eur"]
    assert no_additionality["annual_social_net_eur"] == result["annual_social_net_eur"]
    imports = financials(1, physical, {**p, "domestic_value_added_fraction": 0})
    assert imports["spending_value_added_eur"] == 0
    loss = financials(1, {"pedestrian_hours": -1000, "vehicle_hours": 0}, p)
    assert loss["gdp_scenario_eur"] == -9500
    zero = financials(1, {"pedestrian_hours": 0, "vehicle_hours": 0}, p)
    assert zero["gdp_scenario_eur"] == 0


def test_gdp_metadata_matches_unmeasured_defaults():
    metadata = json.loads((DATA / "gdp_assumptions.json").read_text())
    p = defaults()
    for key, item in metadata["parameter_metadata"].items():
        assert p[key] == item["default"]
    assert p["spending_additionality"] == 0


def test_ten_percent_replacement_is_cumulative_over_ten_years():
    p = {**DEFAULTS, "installed_cost_eur": 300, "supplier_gross_margin": 0,
         "annual_maintenance_eur": 20, "platform_cost_eur": 0, "power_watts": 0,
         "horizon_years": 10, "discount_rate": 0, "replacement_fraction": .1,
         "replacement_schedule": "spread"}
    result = financials(100, {"pedestrian_hours": 0, "vehicle_hours": 0}, p)
    assert result["expected_replaced_units"] == 10
    assert result["replacement_budget_eur"] == 3000
    assert result["average_annual_replacement_eur"] == 300
    assert result["annual_maintenance_cost_eur"] == 2000
    assert result["average_annual_running_cost_eur"] == 2300
    assert result["npv_eur"] == -53000
    assert all(row["replacement_eur"] == 300 for row in result["cashflows"][1:])
    assert sum(row["replacement_eur"] for row in result["cashflows"][1:]) == 3000
    assert result["cashflows"][-1]["discounted_cumulative"] == result["npv_eur"]
    discounted = financials(100, {"pedestrian_hours": 0, "vehicle_hours": 0}, {**p, "discount_rate": .03})
    annuity = sum(1 / 1.03**year for year in range(1, 11))
    assert discounted["npv_eur"] == pytest.approx(-30000 - 2300 * annuity)
    zero = financials(0, {"pedestrian_hours": 0, "vehicle_hours": 0}, p)
    assert zero["replacement_budget_eur"] == zero["expected_replaced_units"] == 0


def test_legacy_one_off_replacement_schedule():
    p = {**DEFAULTS, "replacement_schedule": "one_off", "replacement_year": 5,
         "installed_cost_eur": 100, "supplier_gross_margin": 0}
    result = financials(10, {"pedestrian_hours": 0, "vehicle_hours": 0}, p)
    assert [r["replacement_eur"] for r in result["cashflows"][1:]] == [0, 0, 0, 0, 100, 0, 0, 0, 0, 0]
