from __future__ import annotations

import pandas as pd
import pytest

from heavy_bulky.optimization import greedy_plan
from heavy_bulky.simulation import (
    generate_scenario_bank,
    paired_policy_comparison,
    simulate_plan,
    simulation_summary,
    validate_scenario_bank,
    vv_checks,
)


def _plans(route_bundle, capacity_bundle, smoke_config):
    """Create deterministic feasible plans without re-testing the native solver.

    CP-SAT lifecycle and feasibility are covered in routing/optimization tests. Simulation tests
    should isolate replay, common-random-number, and cost-reconciliation behavior rather than
    repeatedly starting native solver subprocesses.
    """
    routes, members, orders = route_bundle
    candidate = greedy_plan(
        routes,
        members,
        orders,
        capacity_bundle.vehicles,
        capacity_bundle.crews,
        smoke_config,
    )
    baseline = greedy_plan(
        routes,
        members,
        orders,
        capacity_bundle.vehicles,
        capacity_bundle.crews,
        smoke_config,
    )
    return candidate, baseline, members, orders


def test_scenario_bank_is_complete_and_reproducible(
    route_bundle, capacity_bundle, data_bundle, smoke_config
):
    _, _, orders = route_bundle
    first = generate_scenario_bank(
        data_bundle.planning_orders,
        data_bundle.vehicles,
        data_bundle.crews,
        smoke_config,
    )
    second = generate_scenario_bank(
        data_bundle.planning_orders,
        data_bundle.vehicles,
        data_bundle.crews,
        smoke_config,
    )
    assert all(validate_scenario_bank(first, smoke_config).values())
    pd.testing.assert_frame_equal(first.order_events, second.order_events)
    pd.testing.assert_frame_equal(first.station_events, second.station_events)


def test_common_scenario_replay_and_cost_reconciliation(
    route_bundle, capacity_bundle, data_bundle, service_bundle, smoke_config
):
    optimized, greedy, members, _ = _plans(route_bundle, capacity_bundle, smoke_config)
    _, planning, _, _ = service_bundle
    bank = generate_scenario_bank(planning, data_bundle.vehicles, data_bundle.crews, smoke_config)
    a = simulate_plan(
        optimized,
        members,
        planning,
        smoke_config,
        bank,
        vehicles=data_bundle.vehicles,
        crews=data_bundle.crews,
    )
    repeated = simulate_plan(
        optimized,
        members,
        planning,
        smoke_config,
        bank,
        vehicles=data_bundle.vehicles,
        crews=data_bundle.crews,
    )
    baseline = simulate_plan(
        greedy,
        members,
        planning,
        smoke_config,
        bank,
        vehicles=data_bundle.vehicles,
        crews=data_bundle.crews,
    )
    assert a.equals(repeated)
    components = [
        "minute_cost",
        "overtime_cost",
        "unserved_cost",
        "failed_attempt_cost",
        "vehicle_failure_cost",
        "crew_absence_cost",
    ]
    assert (a[components].sum(axis=1) - a["total_cost"]).abs().max() < 1e-8
    summary = simulation_summary(a)
    assert summary["cvar95_cost"] >= summary["expected_cost"]
    comparison = paired_policy_comparison(a, baseline, smoke_config["seed"], bootstrap_samples=200)
    assert comparison["bootstrap_ci95_low"] <= comparison["bootstrap_ci95_high"]


def test_paired_comparison_requires_matching_replications():
    candidate = pd.DataFrame({"replication": [0, 1], "total_cost": [1.0, 2.0]})
    baseline = pd.DataFrame({"replication": [0, 2], "total_cost": [1.0, 2.0]})
    with pytest.raises(ValueError, match="identical"):
        paired_policy_comparison(candidate, baseline, 1)


def test_vv_checks_discriminate_pathological_policy():
    base = pd.DataFrame(
        {
            "replication": [0, 1],
            "minute_cost": [10.0, 11.0],
            "overtime_cost": [0.0, 0.0],
            "unserved_cost": [0.0, 0.0],
            "failed_attempt_cost": [0.0, 0.0],
            "vehicle_failure_cost": [0.0, 0.0],
            "crew_absence_cost": [0.0, 0.0],
            "total_cost": [10.0, 11.0],
            "total_minutes": [10.0, 11.0],
            "overtime_minutes": [0.0, 0.0],
        }
    )
    pathological = base.copy()
    pathological["minute_cost"] += 100
    pathological["total_cost"] += 100
    checks = vv_checks(base, base.copy(), pathological, {"complete": True})
    assert all(checks.values())
