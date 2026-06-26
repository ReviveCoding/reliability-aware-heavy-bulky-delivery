from __future__ import annotations

import pandas as pd

from .data import DataBundle


class ContractViolation(ValueError):
    """Raised when an input or intermediate table violates an executable contract."""


def _require_columns(frame: pd.DataFrame, name: str, columns: set[str]) -> None:
    missing = sorted(columns - set(frame.columns))
    if missing:
        raise ContractViolation(f"{name} missing required columns: {missing}")


def _require_unique(frame: pd.DataFrame, name: str, keys: list[str]) -> None:
    if frame.duplicated(keys).any():
        examples = frame.loc[frame.duplicated(keys, keep=False), keys].head(5).to_dict("records")
        raise ContractViolation(f"{name} has duplicate keys {keys}: {examples}")


def validate_data_bundle(bundle: DataBundle) -> dict[str, int | bool]:
    _require_columns(
        bundle.demand,
        "demand",
        {"date", "station_id", "service_type", "demand", "available_at"},
    )
    order_columns = {
        "order_id",
        "date",
        "station_id",
        "service_type",
        "cube",
        "weight",
        "required_skill",
        "required_crew_size",
        "actual_duration",
        "failed_attempt",
        "failure_probability_true",
    }
    _require_columns(bundle.historical_orders, "historical_orders", order_columns)
    _require_columns(bundle.planning_orders, "planning_orders", order_columns)
    _require_columns(
        bundle.vehicles,
        "vehicles",
        {"vehicle_id", "station_id", "cube_capacity", "weight_capacity", "available"},
    )
    _require_columns(
        bundle.crews,
        "crews",
        {"crew_id", "station_id", "skill", "crew_size", "max_minutes", "available"},
    )
    _require_unique(bundle.demand, "demand", ["date", "station_id", "service_type"])
    _require_unique(bundle.historical_orders, "historical_orders", ["order_id"])
    _require_unique(bundle.planning_orders, "planning_orders", ["order_id"])
    _require_unique(bundle.vehicles, "vehicles", ["vehicle_id"])
    _require_unique(bundle.crews, "crews", ["crew_id"])

    if set(bundle.historical_orders["order_id"]) & set(bundle.planning_orders["order_id"]):
        raise ContractViolation("historical and planning order IDs overlap")
    if bundle.historical_orders["date"].max() >= bundle.planning_orders["date"].min():
        raise ContractViolation("historical labels are not strictly earlier than planning labels")
    if not (bundle.demand["demand"] >= 0).all():
        raise ContractViolation("demand contains negative values")
    if not (bundle.historical_orders[["cube", "weight", "actual_duration"]] > 0).all().all():
        raise ContractViolation("historical orders contain nonpositive physical values")
    if not (bundle.planning_orders[["cube", "weight", "actual_duration"]] > 0).all().all():
        raise ContractViolation("planning orders contain nonpositive physical values")
    known_stations = set(bundle.demand["station_id"])
    for name, frame in {
        "historical_orders": bundle.historical_orders,
        "planning_orders": bundle.planning_orders,
        "vehicles": bundle.vehicles,
        "crews": bundle.crews,
    }.items():
        unknown = sorted(set(frame["station_id"]) - known_stations)
        if unknown:
            raise ContractViolation(f"{name} references unknown stations: {unknown}")

    planning_date = pd.to_datetime(bundle.planning_orders["date"]).min()
    final_demand = bundle.demand[pd.to_datetime(bundle.demand["date"]).eq(planning_date)]
    if final_demand.empty or not final_demand["available_at"].eq("post_outcome").all():
        raise ContractViolation("planning-date realized demand must be marked post_outcome")

    return {
        "passed": True,
        "demand_rows": len(bundle.demand),
        "historical_order_rows": len(bundle.historical_orders),
        "planning_order_rows": len(bundle.planning_orders),
        "vehicle_rows": len(bundle.vehicles),
        "crew_rows": len(bundle.crews),
    }


def validate_operational_forecast(
    forecast: pd.DataFrame, expected_keys: pd.DataFrame
) -> dict[str, int | bool]:
    required = {"date", "station_id", "service_type", "p10", "p50", "p90", "prediction"}
    _require_columns(forecast, "operational_forecast", required)
    _require_unique(forecast, "operational_forecast", ["date", "station_id", "service_type"])
    if not ((forecast["p10"] <= forecast["p50"]) & (forecast["p50"] <= forecast["p90"])).all():
        raise ContractViolation("operational forecast has quantile crossing")
    if not (forecast[["p10", "p50", "p90", "prediction"]] >= 0).all().all():
        raise ContractViolation("operational forecast has negative values")
    forecast_keys = set(map(tuple, forecast[["station_id", "service_type"]].to_numpy()))
    expected = set(
        map(tuple, expected_keys[["station_id", "service_type"]].drop_duplicates().to_numpy())
    )
    if forecast_keys != expected:
        raise ContractViolation(
            f"operational forecast key mismatch: missing={sorted(expected - forecast_keys)}, "
            f"extra={sorted(forecast_keys - expected)}"
        )
    return {"passed": True, "rows": len(forecast), "series": len(forecast_keys)}


def validate_route_candidates(
    routes: pd.DataFrame,
    members: dict[str, list[str]],
    planning_orders: pd.DataFrame,
    routing_cfg: dict,
) -> dict[str, int | bool]:
    _require_columns(
        routes,
        "route_candidates",
        {
            "route_id",
            "station_id",
            "strategy",
            "order_count",
            "p90_route_minutes",
            "cube",
            "weight",
        },
    )
    _require_unique(routes, "route_candidates", ["route_id"])
    route_ids = set(routes["route_id"])
    if route_ids != set(members):
        raise ContractViolation("route table and route-members mapping have different route IDs")
    if any(not values for values in members.values()):
        raise ContractViolation("route-members mapping contains an empty route")
    duplicate_members = {
        route_id: values for route_id, values in members.items() if len(values) != len(set(values))
    }
    if duplicate_members:
        raise ContractViolation(
            f"route-members mapping contains duplicate orders: {list(duplicate_members)[:5]}"
        )

    known_orders = set(planning_orders["order_id"])
    unknown = sorted(
        {order_id for values in members.values() for order_id in values} - known_orders
    )
    if unknown:
        raise ContractViolation(f"route members contain unknown orders: {unknown[:5]}")

    order_station = planning_orders.set_index("order_id")["station_id"].to_dict()
    route_lookup = routes.set_index("route_id")
    count_mismatches: list[str] = []
    station_mismatches: list[str] = []
    for route_id, order_ids in members.items():
        route = route_lookup.loc[route_id]
        if int(route["order_count"]) != len(order_ids):
            count_mismatches.append(route_id)
        if any(order_station[order_id] != route["station_id"] for order_id in order_ids):
            station_mismatches.append(route_id)
    if count_mismatches:
        raise ContractViolation(f"route order_count mismatch: {count_mismatches[:5]}")
    if station_mismatches:
        raise ContractViolation(f"route station/member mismatch: {station_mismatches[:5]}")

    expected_strategies = list(routing_cfg["strategies"])
    observed_strategies = set(routes["strategy"])
    missing_strategies = sorted(set(expected_strategies) - observed_strategies)
    if missing_strategies:
        raise ContractViolation(f"route candidates missing strategies: {missing_strategies}")

    # Each strategy is generated as an independent partition of every station's manifest.
    partition_errors: list[str] = []
    for station_id, station_orders in planning_orders.groupby("station_id", sort=True):
        expected = set(station_orders["order_id"])
        for strategy in expected_strategies:
            strategy_routes = routes[
                routes["station_id"].eq(station_id) & routes["strategy"].eq(strategy)
            ]
            flattened = [
                order_id
                for route_id in strategy_routes["route_id"]
                for order_id in members[route_id]
            ]
            if set(flattened) != expected or len(flattened) != len(set(flattened)):
                partition_errors.append(f"{station_id}:{strategy}")
    if partition_errors:
        raise ContractViolation(
            f"route strategies do not partition station manifests: {partition_errors[:5]}"
        )

    if not (routes[["p90_route_minutes", "cube", "weight"]] > 0).all().all():
        raise ContractViolation("route candidates contain nonpositive resource values")
    if (routes["cube"] > float(routing_cfg["route_capacity_cube"]) + 1e-9).any():
        raise ContractViolation("route candidates exceed configured cube limit")
    if (routes["weight"] > float(routing_cfg["max_route_weight"]) + 1e-9).any():
        raise ContractViolation("route candidates exceed configured weight limit")
    multi_order_time_exceptions = int(
        (
            routes["order_count"].gt(1)
            & routes["p90_route_minutes"].gt(float(routing_cfg["max_route_minutes"]) + 1e-9)
        ).sum()
    )
    if multi_order_time_exceptions:
        raise ContractViolation("multi-order route candidates exceed configured time limit")
    singleton_time_exceptions = int(
        (
            routes["order_count"].eq(1)
            & routes["p90_route_minutes"].gt(float(routing_cfg["max_route_minutes"]) + 1e-9)
        ).sum()
    )
    return {
        "passed": True,
        "routes": len(routes),
        "member_rows": sum(len(values) for values in members.values()),
        "strategies": len(observed_strategies),
        "partition_checks": len(planning_orders["station_id"].unique()) * len(expected_strategies),
        "singleton_time_exceptions": singleton_time_exceptions,
    }
