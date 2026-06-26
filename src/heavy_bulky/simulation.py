from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .optimization import PlanResult


@dataclass(frozen=True)
class ScenarioBank:
    order_events: pd.DataFrame
    station_events: pd.DataFrame
    vehicle_events: pd.DataFrame
    crew_events: pd.DataFrame


def generate_scenario_bank(
    orders: pd.DataFrame,
    vehicles: pd.DataFrame,
    crews: pd.DataFrame,
    cfg: dict,
) -> ScenarioBank:
    rng = np.random.default_rng(int(cfg["seed"]) + 1000)
    replications = int(cfg["simulation"]["replications"])
    order_rows: list[dict] = []
    station_rows: list[dict] = []
    vehicle_rows: list[dict] = []
    crew_rows: list[dict] = []

    for replication in range(replications):
        for order_id in sorted(orders["order_id"]):
            order_rows.append(
                {
                    "replication": replication,
                    "order_id": order_id,
                    "duration_multiplier": float(
                        rng.lognormal(0.0, float(cfg["simulation"]["service_overrun_sigma"]))
                    ),
                    "failure_uniform": float(rng.random()),
                }
            )
        for station_id in sorted(orders["station_id"].unique()):
            station_rows.append(
                {
                    "replication": replication,
                    "station_id": station_id,
                    "traffic_multiplier": float(0.90 + 0.25 * rng.random()),
                }
            )
        for vehicle_id in sorted(vehicles["vehicle_id"]):
            vehicle_rows.append(
                {
                    "replication": replication,
                    "vehicle_id": vehicle_id,
                    "failure_uniform": float(rng.random()),
                }
            )
        for crew_id in sorted(crews["crew_id"]):
            crew_rows.append(
                {
                    "replication": replication,
                    "crew_id": crew_id,
                    "absence_uniform": float(rng.random()),
                }
            )
    return ScenarioBank(
        order_events=pd.DataFrame(order_rows),
        station_events=pd.DataFrame(station_rows),
        vehicle_events=pd.DataFrame(vehicle_rows),
        crew_events=pd.DataFrame(crew_rows),
    )


def validate_scenario_bank(bank: ScenarioBank, cfg: dict) -> dict[str, bool]:
    replications = int(cfg["simulation"]["replications"])
    unique_replications = set(range(replications))
    tables = [bank.order_events, bank.station_events, bank.vehicle_events, bank.crew_events]
    correct_replications = all(set(table["replication"]) == unique_replications for table in tables)
    no_duplicate_events = bool(
        not bank.order_events.duplicated(["replication", "order_id"]).any()
        and not bank.station_events.duplicated(["replication", "station_id"]).any()
        and not bank.vehicle_events.duplicated(["replication", "vehicle_id"]).any()
        and not bank.crew_events.duplicated(["replication", "crew_id"]).any()
    )
    complete_entity_grids = bool(
        len(bank.order_events) == replications * bank.order_events["order_id"].nunique()
        and len(bank.station_events) == replications * bank.station_events["station_id"].nunique()
        and len(bank.vehicle_events) == replications * bank.vehicle_events["vehicle_id"].nunique()
        and len(bank.crew_events) == replications * bank.crew_events["crew_id"].nunique()
    )
    probabilities_in_range = bool(
        bank.order_events["failure_uniform"].between(0, 1).all()
        and bank.vehicle_events["failure_uniform"].between(0, 1).all()
        and bank.crew_events["absence_uniform"].between(0, 1).all()
    )
    positive_multipliers = bool(
        bank.order_events["duration_multiplier"].gt(0).all()
        and bank.station_events["traffic_multiplier"].gt(0).all()
    )
    return {
        "correct_replications": bool(correct_replications),
        "no_duplicate_events": no_duplicate_events,
        "complete_entity_grids": complete_entity_grids,
        "probabilities_in_range": probabilities_in_range,
        "positive_multipliers": positive_multipliers,
    }


def simulate_plan(
    plan: PlanResult,
    route_members: dict[str, list[str]],
    orders: pd.DataFrame,
    cfg: dict,
    scenario_bank: ScenarioBank | None = None,
    *,
    vehicles: pd.DataFrame | None = None,
    crews: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Replay a plan over common random scenarios using vectorized joins.

    The event bank is policy independent. Route/order assignments are joined to the same order,
    station, vehicle, and crew draws so paired policy comparisons remain valid.
    """
    if scenario_bank is None:
        if vehicles is None or crews is None:
            selected = plan.selected_routes
            vehicles = pd.DataFrame(
                {"vehicle_id": sorted(selected.get("vehicle_id", pd.Series(dtype=str)).unique())}
            )
            crews = pd.DataFrame(
                {"crew_id": sorted(selected.get("crew_id", pd.Series(dtype=str)).unique())}
            )
        scenario_bank = generate_scenario_bank(orders, vehicles, crews, cfg)

    replications = pd.DataFrame({"replication": range(int(cfg["simulation"]["replications"]))})
    selected = plan.selected_routes.copy()
    if selected.empty:
        aggregate = replications.assign(
            service_minutes=0.0,
            travel_minutes=0.0,
            disruption_minutes=0.0,
            overtime_minutes=0.0,
            failed_attempts=0,
            vehicle_failures=0,
            crew_absences=0,
        )
    else:
        membership_rows = [
            {"route_id": route_id, "order_id": order_id}
            for route_id in selected["route_id"]
            for order_id in route_members[route_id]
        ]
        membership = pd.DataFrame(membership_rows)
        order_base = orders[["order_id", "actual_duration", "failure_probability_true"]].copy()
        order_replay = scenario_bank.order_events.merge(
            membership, on="order_id", how="inner", validate="many_to_one"
        ).merge(order_base, on="order_id", how="left", validate="many_to_one")
        order_replay["service_component"] = (
            order_replay["actual_duration"] * order_replay["duration_multiplier"]
        )
        order_replay["failed_component"] = (
            order_replay["failure_uniform"] < order_replay["failure_probability_true"]
        ).astype(int)
        route_replay = (
            order_replay.groupby(["replication", "route_id"], as_index=False)
            .agg(
                service_minutes=("service_component", "sum"),
                failed_attempts=("failed_component", "sum"),
            )
            .merge(
                selected[["route_id", "station_id", "vehicle_id", "crew_id", "travel_minutes"]],
                on="route_id",
                how="left",
                validate="many_to_one",
            )
            .merge(
                scenario_bank.station_events,
                on=["replication", "station_id"],
                how="left",
                validate="many_to_one",
            )
            .merge(
                scenario_bank.vehicle_events.rename(
                    columns={"failure_uniform": "vehicle_failure_uniform"}
                ),
                on=["replication", "vehicle_id"],
                how="left",
                validate="many_to_one",
            )
            .merge(
                scenario_bank.crew_events,
                on=["replication", "crew_id"],
                how="left",
                validate="many_to_one",
            )
        )
        required = [
            "traffic_multiplier",
            "vehicle_failure_uniform",
            "absence_uniform",
        ]
        if route_replay[required].isna().any().any():
            raise ValueError("Scenario bank is missing events for selected plan resources")
        route_replay["travel_component"] = (
            route_replay["travel_minutes"] * route_replay["traffic_multiplier"]
        )
        route_replay["vehicle_failure"] = (
            route_replay["vehicle_failure_uniform"]
            < float(cfg["simulation"]["vehicle_failure_probability"])
        ).astype(int)
        route_replay["crew_absence"] = (
            route_replay["absence_uniform"] < float(cfg["simulation"]["crew_absence_probability"])
        ).astype(int)
        route_replay["disruption_component"] = (
            120.0 * route_replay["vehicle_failure"] + 180.0 * route_replay["crew_absence"]
        )
        route_replay["route_minutes"] = (
            route_replay["service_minutes"]
            + route_replay["travel_component"]
            + route_replay["disruption_component"]
        )
        route_replay["overtime_component"] = np.maximum(
            0.0,
            route_replay["route_minutes"] - float(cfg["simulation"]["overtime_threshold_minutes"]),
        )
        aggregate = route_replay.groupby("replication", as_index=False).agg(
            service_minutes=("service_minutes", "sum"),
            travel_minutes=("travel_component", "sum"),
            disruption_minutes=("disruption_component", "sum"),
            overtime_minutes=("overtime_component", "sum"),
            failed_attempts=("failed_attempts", "sum"),
            vehicle_failures=("vehicle_failure", "sum"),
            crew_absences=("crew_absence", "sum"),
        )
        aggregate = replications.merge(aggregate, on="replication", how="left").fillna(0)

    aggregate["unserved_orders"] = len(plan.unserved_orders)
    aggregate["total_minutes"] = (
        aggregate["service_minutes"] + aggregate["travel_minutes"] + aggregate["disruption_minutes"]
    )
    costs = cfg["simulation"]["costs"]
    aggregate["minute_cost"] = float(costs["minute"]) * aggregate["total_minutes"]
    aggregate["overtime_cost"] = float(costs["overtime_minute"]) * aggregate["overtime_minutes"]
    aggregate["unserved_cost"] = float(costs["unserved_order"]) * aggregate["unserved_orders"]
    aggregate["failed_attempt_cost"] = float(costs["failed_attempt"]) * aggregate["failed_attempts"]
    aggregate["vehicle_failure_cost"] = (
        float(costs["vehicle_failure"]) * aggregate["vehicle_failures"]
    )
    aggregate["crew_absence_cost"] = float(costs["crew_absence"]) * aggregate["crew_absences"]
    aggregate["total_cost"] = aggregate[
        [
            "minute_cost",
            "overtime_cost",
            "unserved_cost",
            "failed_attempt_cost",
            "vehicle_failure_cost",
            "crew_absence_cost",
        ]
    ].sum(axis=1)
    output_columns = [
        "replication",
        "service_minutes",
        "travel_minutes",
        "disruption_minutes",
        "total_minutes",
        "overtime_minutes",
        "failed_attempts",
        "unserved_orders",
        "vehicle_failures",
        "crew_absences",
        "minute_cost",
        "overtime_cost",
        "unserved_cost",
        "failed_attempt_cost",
        "vehicle_failure_cost",
        "crew_absence_cost",
        "total_cost",
    ]
    return aggregate[output_columns].sort_values("replication").reset_index(drop=True)


def simulation_summary(simulation: pd.DataFrame) -> dict[str, float]:
    threshold = float(simulation["total_cost"].quantile(0.95))
    tail = simulation[simulation["total_cost"] >= threshold]
    return {
        "expected_cost": float(simulation["total_cost"].mean()),
        "cvar95_cost": float(tail["total_cost"].mean()),
        "mean_overtime_minutes": float(simulation["overtime_minutes"].mean()),
        "mean_unserved_orders": float(simulation["unserved_orders"].mean()),
        "mean_failed_attempts": float(simulation["failed_attempts"].mean()),
        "mean_vehicle_failures": float(simulation["vehicle_failures"].mean()),
        "mean_crew_absences": float(simulation["crew_absences"].mean()),
    }


def paired_policy_comparison(
    candidate: pd.DataFrame,
    baseline: pd.DataFrame,
    seed: int,
    bootstrap_samples: int = 1000,
) -> dict[str, float]:
    candidate_replications = set(candidate["replication"])
    baseline_replications = set(baseline["replication"])
    if not candidate_replications or candidate_replications != baseline_replications:
        raise ValueError("Paired policy comparison requires identical non-empty replications")
    if bootstrap_samples <= 0:
        raise ValueError("bootstrap_samples must be positive")
    paired = candidate[["replication", "total_cost"]].merge(
        baseline[["replication", "total_cost"]],
        on="replication",
        suffixes=("_candidate", "_baseline"),
        validate="one_to_one",
    )
    delta = (paired["total_cost_candidate"] - paired["total_cost_baseline"]).to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(delta), size=(bootstrap_samples, len(delta)))
    bootstrap_means = delta[indices].mean(axis=1)
    return {
        "mean_cost_delta": float(delta.mean()),
        "relative_mean_cost_delta": float(
            delta.mean() / max(float(paired["total_cost_baseline"].mean()), 1.0)
        ),
        "paired_win_rate": float(np.mean(delta < 0)),
        "bootstrap_ci95_low": float(np.quantile(bootstrap_means, 0.025)),
        "bootstrap_ci95_high": float(np.quantile(bootstrap_means, 0.975)),
    }


def vv_checks(
    simulation: pd.DataFrame,
    repeated_simulation: pd.DataFrame,
    pathological_simulation: pd.DataFrame,
    scenario_checks: dict[str, bool | int],
) -> dict[str, bool]:
    component_columns = [
        "minute_cost",
        "overtime_cost",
        "unserved_cost",
        "failed_attempt_cost",
        "vehicle_failure_cost",
        "crew_absence_cost",
    ]
    cost_reconciles = np.allclose(
        simulation[component_columns].sum(axis=1).to_numpy(dtype=float),
        simulation["total_cost"].to_numpy(dtype=float),
    )
    nonnegative = bool(
        (simulation[["total_cost", "total_minutes", "overtime_minutes"]] >= 0).all().all()
    )
    deterministic_replay = simulation.equals(repeated_simulation)
    policy_discrimination = float(simulation["total_cost"].mean()) < float(
        pathological_simulation["total_cost"].mean()
    )
    return {
        "nonnegative_invariants": nonnegative,
        "cost_component_reconciliation": bool(cost_reconciles),
        "deterministic_replay": deterministic_replay,
        "scenario_bank_valid": bool(all(bool(value) for value in scenario_checks.values())),
        "policy_discrimination_sanity": policy_discrimination,
    }
