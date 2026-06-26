from __future__ import annotations

import os
import pickle
import subprocess
from pathlib import Path

import pandas as pd

from heavy_bulky.capacity import reconcile_capacity_with_route_pool
from heavy_bulky.contracts import validate_route_candidates
from heavy_bulky.optimization import (
    PlanResult,
    _solver_worker_environment,
    greedy_plan,
    solve_plan,
    validate_plan,
)


def test_route_contract_partitions_every_station_strategy(route_bundle, smoke_config):
    routes, members, orders = route_bundle
    result = validate_route_candidates(routes, members, orders, smoke_config["routing"])
    assert result["passed"] is True
    assert result["partition_checks"] == len(smoke_config["stations"]) * len(
        smoke_config["routing"]["strategies"]
    )
    assert result["singleton_time_exceptions"] == 0


def test_route_generation_uses_only_planning_safe_features(route_bundle):
    routes, _, orders = route_bundle
    forbidden = {"actual_duration", "failed_attempt", "failure_probability_true"}
    assert forbidden.isdisjoint(orders.columns)
    assert not routes.empty
    assert set(routes["strategy"]) == {
        "nearest",
        "sweep",
        "risk_first",
        "balanced",
        "skill_clustered",
    }


def test_route_pool_reconciliation_closes_resource_floor(
    route_bundle, capacity_bundle, data_bundle, smoke_config
):
    routes, _, _ = route_bundle
    reconciled = reconcile_capacity_with_route_pool(
        capacity_bundle, routes, data_bundle.vehicles, data_bundle.crews, smoke_config
    )
    for row in reconciled.capacity_plan.itertuples(index=False):
        assert row.planned_vehicles >= min(row.route_pool_min_routes, row.available_vehicles)
        assert row.planned_crews >= min(row.route_pool_min_routes, row.available_crews)
    assert reconciled.metrics["route_pool_reconciled"] is True


def test_reserve_shortfall_does_not_block_operational_feasibility(
    route_bundle, capacity_bundle, data_bundle, smoke_config
):
    routes, _, _ = route_bundle
    reconciled = reconcile_capacity_with_route_pool(
        capacity_bundle, routes, data_bundle.vehicles, data_bundle.crews, smoke_config
    )
    assert reconciled.metrics["total_capacity_shortfall"] == 0
    assert reconciled.metrics["total_reserve_shortfall"] >= 0
    for row in reconciled.capacity_plan.itertuples(index=False):
        assert row.vehicle_shortfall == max(
            0, row.minimum_required_vehicles - row.available_vehicles
        )
        assert row.crew_shortfall == max(0, row.minimum_required_crews - row.available_crews)
        assert row.reserve_vehicle_shortfall == max(
            0, row.requested_vehicles - row.available_vehicles
        )
        assert row.reserve_crew_shortfall == max(0, row.requested_crews - row.available_crews)


def test_cp_sat_plan_is_feasible(route_bundle, capacity_bundle, smoke_config):
    routes, members, orders = route_bundle
    plan = solve_plan(
        routes,
        members,
        orders,
        capacity_bundle.vehicles,
        capacity_bundle.crews,
        smoke_config,
    )
    validation = validate_plan(
        plan,
        members,
        orders,
        capacity_bundle.vehicles,
        capacity_bundle.crews,
    )
    assert plan.status in {"OPTIMAL", "FEASIBLE"}
    assert validation["hard_constraint_violations"] == 0
    assert len(plan.unserved_orders) == 0
    assert plan.relative_gap is None or plan.relative_gap <= 0.2


def test_impossible_resource_pool_produces_explicit_unserved(route_bundle, smoke_config):
    routes, members, orders = route_bundle
    empty_vehicles = pd.DataFrame(
        columns=["vehicle_id", "station_id", "cube_capacity", "weight_capacity", "available"]
    )
    empty_crews = pd.DataFrame(
        columns=["crew_id", "station_id", "skill", "crew_size", "max_minutes", "available"]
    )
    plan = solve_plan(routes, members, orders, empty_vehicles, empty_crews, smoke_config)
    assert set(plan.unserved_orders) == set(orders["order_id"])
    assert plan.status in {"OPTIMAL", "FEASIBLE", "FALLBACK_GREEDY"}


def test_validate_plan_detects_reused_resources(route_bundle, capacity_bundle):
    routes, members, orders = route_bundle
    chosen = routes[routes["strategy"].eq("nearest")].head(2).copy()
    if len(chosen) < 2:
        return
    vehicle = capacity_bundle.vehicles.iloc[0]
    crew = capacity_bundle.crews.iloc[0]
    chosen["vehicle_id"] = vehicle["vehicle_id"]
    chosen["crew_id"] = crew["crew_id"]
    plan = PlanResult(
        selected_routes=chosen,
        unserved_orders=sorted(
            set(orders["order_id"]) - {o for r in chosen["route_id"] for o in members[r]}
        ),
        status="TEST",
        objective=0.0,
        best_bound=None,
        fallback_used=False,
        solve_time_seconds=0.0,
        relative_gap=None,
    )
    validation = validate_plan(
        plan,
        members,
        orders,
        capacity_bundle.vehicles,
        capacity_bundle.crews,
    )
    assert validation["reused_vehicles"] >= 1
    assert validation["reused_crews"] >= 1
    assert validation["hard_constraint_violations"] >= 2


def test_greedy_fallback_is_deterministic(route_bundle, capacity_bundle, smoke_config):
    routes, members, orders = route_bundle
    first = greedy_plan(
        routes, members, orders, capacity_bundle.vehicles, capacity_bundle.crews, smoke_config
    )
    second = greedy_plan(
        routes, members, orders, capacity_bundle.vehicles, capacity_bundle.crews, smoke_config
    )
    pd.testing.assert_frame_equal(first.selected_routes, second.selected_routes)
    assert first.unserved_orders == second.unserved_orders


def test_invalid_solver_worker_plan_falls_back_to_validated_incumbent(
    route_bundle, capacity_bundle, smoke_config, monkeypatch
):
    routes, members, orders = route_bundle
    chosen = routes[routes["strategy"].eq("nearest")].head(2).copy()
    assert len(chosen) == 2
    chosen["vehicle_id"] = capacity_bundle.vehicles.iloc[0]["vehicle_id"]
    chosen["crew_id"] = capacity_bundle.crews.iloc[0]["crew_id"]
    served = {order for route_id in chosen["route_id"] for order in members[route_id]}
    invalid = PlanResult(
        selected_routes=chosen,
        unserved_orders=sorted(set(orders["order_id"]) - served),
        status="FEASIBLE",
        objective=1.0,
        best_bound=1.0,
        fallback_used=False,
        relative_gap=0.0,
    )

    def fake_run(args, **kwargs):
        response_path = args[-1]
        with open(response_path, "wb") as handle:
            pickle.dump(invalid, handle)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr("heavy_bulky.optimization.subprocess.run", fake_run)
    plan = solve_plan(
        routes,
        members,
        orders,
        capacity_bundle.vehicles,
        capacity_bundle.crews,
        smoke_config,
    )
    validation = validate_plan(
        plan, members, orders, capacity_bundle.vehicles, capacity_bundle.crews
    )
    assert plan.status == "FALLBACK_GREEDY"
    assert plan.fallback_reason.startswith("cp_sat_worker_invalid_plan")
    assert validation["hard_constraint_violations"] == 0


def test_malformed_solver_worker_plan_falls_back_safely(
    route_bundle, capacity_bundle, smoke_config, monkeypatch
):
    routes, members, orders = route_bundle
    malformed = PlanResult(
        selected_routes=pd.DataFrame({"unexpected": [1]}),
        unserved_orders=[],
        status="FEASIBLE",
        objective=1.0,
        best_bound=1.0,
        fallback_used=False,
        relative_gap=0.0,
    )

    def fake_run(args, **kwargs):
        response_path = args[-1]
        with open(response_path, "wb") as handle:
            pickle.dump(malformed, handle)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr("heavy_bulky.optimization.subprocess.run", fake_run)
    plan = solve_plan(
        routes,
        members,
        orders,
        capacity_bundle.vehicles,
        capacity_bundle.crews,
        smoke_config,
    )
    validation = validate_plan(
        plan, members, orders, capacity_bundle.vehicles, capacity_bundle.crews
    )
    assert plan.status == "FALLBACK_GREEDY"
    assert plan.fallback_reason == "cp_sat_worker_validation_error:KeyError"
    assert validation["hard_constraint_violations"] == 0


def test_solver_worker_environment_supports_source_checkout(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "")
    environment = _solver_worker_environment()
    source_root = Path(__file__).resolve().parents[1] / "src"
    assert environment["PYTHONPATH"].split(os.pathsep)[0] == str(source_root)
    assert environment["PYTHONHASHSEED"] == "0"
