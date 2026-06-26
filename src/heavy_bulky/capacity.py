from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class CapacityPlanningResult:
    capacity_plan: pd.DataFrame
    vehicles: pd.DataFrame
    crews: pd.DataFrame
    metrics: dict[str, float]


def plan_capacity(
    forecast: pd.DataFrame,
    historical_orders: pd.DataFrame,
    planning_orders: pd.DataFrame,
    vehicles: pd.DataFrame,
    crews: pd.DataFrame,
    cfg: dict,
) -> CapacityPlanningResult:
    duration_median = historical_orders.groupby("service_type")["actual_duration"].median()
    cube_p75 = historical_orders.groupby("service_type")["cube"].quantile(0.75)
    rows: list[dict[str, float | int | str]] = []
    rostered_vehicles = vehicles.copy()
    rostered_crews = crews.copy()
    rostered_vehicles["available"] = 0
    rostered_crews["available"] = 0

    for station, station_forecast in forecast.groupby("station_id"):
        expected_orders = 0.0
        p90_orders = 0.0
        expected_workload = 0.0
        p90_workload = 0.0
        p90_cube = 0.0
        install_workload = 0.0
        for rec in station_forecast.itertuples(index=False):
            multiplier = float(cfg["orders_per_unit"])
            expected = float(rec.p50) * multiplier
            tail = float(rec.p90) * multiplier
            median_duration = float(duration_median.get(rec.service_type, duration_median.median()))
            service_cube = float(cube_p75.get(rec.service_type, cube_p75.median()))
            expected_orders += expected
            p90_orders += tail
            expected_workload += expected * median_duration
            p90_workload += tail * median_duration
            p90_cube += tail * service_cube
            if rec.service_type == "installation":
                install_workload += tail * median_duration

        effective_orders_per_route = max(
            1.0,
            float(cfg["routing"]["max_orders_per_route"])
            * float(cfg["capacity"]["route_fill_rate"]),
        )
        route_count_by_orders = math.ceil(p90_orders / effective_orders_per_route)
        route_count_by_cube = math.ceil(
            p90_cube / max(float(cfg["routing"]["route_capacity_cube"]), 1.0)
        )
        route_count_by_workload = math.ceil(
            p90_workload / max(float(cfg["routing"]["max_route_minutes"]), 1.0)
        )
        route_count = max(route_count_by_orders, route_count_by_cube, route_count_by_workload, 1)
        crew_count_by_workload = math.ceil(
            p90_workload / max(int(cfg["capacity"]["shift_minutes"]), 1)
        )
        minimum_vehicle_required = max(
            int(cfg["capacity"]["min_resources_per_station"]),
            route_count,
        )
        minimum_crew_required = max(
            int(cfg["capacity"]["min_resources_per_station"]),
            route_count,
            crew_count_by_workload,
        )
        vehicle_required = minimum_vehicle_required + int(cfg["capacity"]["reserve_vehicles"])
        crew_required = minimum_crew_required + int(cfg["capacity"]["reserve_crews"])
        install_crews_required = math.ceil(
            install_workload / max(int(cfg["capacity"]["shift_minutes"]), 1)
        )

        available_vehicle_count = int(rostered_vehicles["station_id"].eq(station).sum())
        available_crew_count = int(rostered_crews["station_id"].eq(station).sum())
        available_install_crew_count = int(
            (rostered_crews["station_id"].eq(station) & rostered_crews["skill"].eq("install")).sum()
        )
        station_vehicle_index = rostered_vehicles.index[
            rostered_vehicles["station_id"].eq(station)
        ][:vehicle_required]
        rostered_vehicles.loc[station_vehicle_index, "available"] = 1

        install_index = rostered_crews.index[
            rostered_crews["station_id"].eq(station) & rostered_crews["skill"].eq("install")
        ][:install_crews_required]
        rostered_crews.loc[install_index, "available"] = 1
        remaining = max(0, crew_required - len(install_index))
        other_index = rostered_crews.index[
            rostered_crews["station_id"].eq(station) & ~rostered_crews.index.isin(install_index)
        ][:remaining]
        rostered_crews.loc[other_index, "available"] = 1

        actual_station = planning_orders[planning_orders["station_id"].eq(station)]
        rows.append(
            {
                "station_id": station,
                "forecast_p50_orders": expected_orders,
                "forecast_p90_orders": p90_orders,
                "forecast_p50_workload_minutes": expected_workload,
                "forecast_p90_workload_minutes": p90_workload,
                "forecast_p90_cube": p90_cube,
                "minimum_required_vehicles": minimum_vehicle_required,
                "minimum_required_crews": minimum_crew_required,
                "minimum_required_install_crews": install_crews_required,
                "requested_vehicles": vehicle_required,
                "requested_crews": crew_required,
                "requested_install_crews": install_crews_required,
                "available_vehicles": available_vehicle_count,
                "available_crews": available_crew_count,
                "available_install_crews": available_install_crew_count,
                "vehicle_shortfall": max(0, minimum_vehicle_required - available_vehicle_count),
                "crew_shortfall": max(0, minimum_crew_required - available_crew_count),
                "install_crew_shortfall": max(
                    0, install_crews_required - available_install_crew_count
                ),
                "reserve_vehicle_shortfall": max(0, vehicle_required - available_vehicle_count),
                "reserve_crew_shortfall": max(0, crew_required - available_crew_count),
                "planned_vehicles": int(
                    rostered_vehicles[
                        rostered_vehicles["station_id"].eq(station)
                        & rostered_vehicles["available"].eq(1)
                    ].shape[0]
                ),
                "planned_crews": int(
                    rostered_crews[
                        rostered_crews["station_id"].eq(station) & rostered_crews["available"].eq(1)
                    ].shape[0]
                ),
                "planned_install_crews": int(
                    rostered_crews[
                        rostered_crews["station_id"].eq(station)
                        & rostered_crews["available"].eq(1)
                        & rostered_crews["skill"].eq("install")
                    ].shape[0]
                ),
                "actual_orders_offline": int(len(actual_station)),
                "actual_workload_minutes_offline": float(actual_station["actual_duration"].sum()),
            }
        )

    capacity_plan = pd.DataFrame(rows)
    under_orders = np.maximum(
        capacity_plan["actual_orders_offline"] - capacity_plan["forecast_p90_orders"], 0
    )
    over_orders = np.maximum(
        capacity_plan["forecast_p90_orders"] - capacity_plan["actual_orders_offline"], 0
    )
    metrics = {
        "capacity_regret_proxy": float(np.mean(5.0 * under_orders + over_orders)),
        "mean_planned_vehicles": float(capacity_plan["planned_vehicles"].mean()),
        "mean_planned_crews": float(capacity_plan["planned_crews"].mean()),
        "station_underforecast_rate": float((under_orders > 0).mean()),
        "total_capacity_shortfall": int(
            capacity_plan[["vehicle_shortfall", "crew_shortfall", "install_crew_shortfall"]]
            .sum()
            .sum()
        ),
        "station_capacity_shortfall_rate": float(
            (
                capacity_plan[
                    ["vehicle_shortfall", "crew_shortfall", "install_crew_shortfall"]
                ].sum(axis=1)
                > 0
            ).mean()
        ),
        "total_reserve_shortfall": int(
            capacity_plan[["reserve_vehicle_shortfall", "reserve_crew_shortfall"]].sum().sum()
        ),
    }
    return CapacityPlanningResult(capacity_plan, rostered_vehicles, rostered_crews, metrics)


def reconcile_capacity_with_route_pool(
    result: CapacityPlanningResult,
    routes: pd.DataFrame,
    all_vehicles: pd.DataFrame,
    all_crews: pd.DataFrame,
    cfg: dict,
) -> CapacityPlanningResult:
    """Raise the roster to the smallest complete route partition for each station.

    Forecasts support tactical capacity planning, while the known day-ahead manifest and generated
    feasible route pool reveal time-window fragmentation that aggregate workload estimates cannot
    see. This planning-time reconciliation prevents a structurally infeasible assignment model.
    """
    capacity_plan = result.capacity_plan.copy()
    vehicles = all_vehicles.copy()
    crews = all_crews.copy()
    vehicles["available"] = 0
    crews["available"] = 0

    for station_id in capacity_plan["station_id"]:
        station_routes = routes[routes["station_id"].eq(station_id)]
        strategy_counts = station_routes.groupby("strategy").size()
        if strategy_counts.empty:
            minimum_routes = 0
            reference_strategy = ""
            minimum_install_routes = 0
        else:
            minimum_routes = int(strategy_counts.min())
            reference_strategy = str(
                sorted(strategy_counts[strategy_counts.eq(minimum_routes)].index)[0]
            )
            reference_routes = station_routes[station_routes["strategy"].eq(reference_strategy)]
            minimum_install_routes = int(
                reference_routes["requires_install_skill"].astype(bool).sum()
            )

        row_index = capacity_plan.index[capacity_plan["station_id"].eq(station_id)][0]
        forecast_minimum_vehicle = int(capacity_plan.loc[row_index, "minimum_required_vehicles"])
        forecast_minimum_crew = int(capacity_plan.loc[row_index, "minimum_required_crews"])
        forecast_install_request = int(
            capacity_plan.loc[row_index, "minimum_required_install_crews"]
        )
        minimum_vehicle_request = max(forecast_minimum_vehicle, minimum_routes)
        minimum_crew_request = max(forecast_minimum_crew, minimum_routes)
        install_request = max(forecast_install_request, minimum_install_routes)
        vehicle_request = minimum_vehicle_request + int(cfg["capacity"]["reserve_vehicles"])
        crew_request = minimum_crew_request + int(cfg["capacity"]["reserve_crews"])

        station_vehicle_index = vehicles.index[vehicles["station_id"].eq(station_id)][
            :vehicle_request
        ]
        vehicles.loc[station_vehicle_index, "available"] = 1

        install_index = crews.index[
            crews["station_id"].eq(station_id) & crews["skill"].eq("install")
        ][:install_request]
        crews.loc[install_index, "available"] = 1
        remaining = max(0, crew_request - len(install_index))
        other_index = crews.index[
            crews["station_id"].eq(station_id) & ~crews.index.isin(install_index)
        ][:remaining]
        crews.loc[other_index, "available"] = 1

        available_vehicle_count = int(vehicles["station_id"].eq(station_id).sum())
        available_crew_count = int(crews["station_id"].eq(station_id).sum())
        available_install_count = int(
            (crews["station_id"].eq(station_id) & crews["skill"].eq("install")).sum()
        )
        capacity_plan.loc[row_index, "route_pool_reference_strategy"] = reference_strategy
        capacity_plan.loc[row_index, "route_pool_min_routes"] = minimum_routes
        capacity_plan.loc[row_index, "route_pool_min_install_routes"] = minimum_install_routes
        capacity_plan.loc[row_index, "minimum_required_vehicles"] = minimum_vehicle_request
        capacity_plan.loc[row_index, "minimum_required_crews"] = minimum_crew_request
        capacity_plan.loc[row_index, "minimum_required_install_crews"] = install_request
        capacity_plan.loc[row_index, "requested_vehicles"] = vehicle_request
        capacity_plan.loc[row_index, "requested_crews"] = crew_request
        capacity_plan.loc[row_index, "requested_install_crews"] = install_request
        capacity_plan.loc[row_index, "available_vehicles"] = available_vehicle_count
        capacity_plan.loc[row_index, "available_crews"] = available_crew_count
        capacity_plan.loc[row_index, "available_install_crews"] = available_install_count
        capacity_plan.loc[row_index, "vehicle_shortfall"] = max(
            0, minimum_vehicle_request - available_vehicle_count
        )
        capacity_plan.loc[row_index, "crew_shortfall"] = max(
            0, minimum_crew_request - available_crew_count
        )
        capacity_plan.loc[row_index, "install_crew_shortfall"] = max(
            0, install_request - available_install_count
        )
        capacity_plan.loc[row_index, "reserve_vehicle_shortfall"] = max(
            0, vehicle_request - available_vehicle_count
        )
        capacity_plan.loc[row_index, "reserve_crew_shortfall"] = max(
            0, crew_request - available_crew_count
        )
        capacity_plan.loc[row_index, "planned_vehicles"] = int(
            (vehicles["station_id"].eq(station_id) & vehicles["available"].eq(1)).sum()
        )
        capacity_plan.loc[row_index, "planned_crews"] = int(
            (crews["station_id"].eq(station_id) & crews["available"].eq(1)).sum()
        )
        capacity_plan.loc[row_index, "planned_install_crews"] = int(
            (
                crews["station_id"].eq(station_id)
                & crews["available"].eq(1)
                & crews["skill"].eq("install")
            ).sum()
        )

    metrics = dict(result.metrics)
    metrics.update(
        {
            "route_pool_reconciled": True,
            "route_pool_min_routes_total": int(capacity_plan["route_pool_min_routes"].sum()),
            "mean_planned_vehicles": float(capacity_plan["planned_vehicles"].mean()),
            "mean_planned_crews": float(capacity_plan["planned_crews"].mean()),
            "total_capacity_shortfall": int(
                capacity_plan[["vehicle_shortfall", "crew_shortfall", "install_crew_shortfall"]]
                .sum()
                .sum()
            ),
            "station_capacity_shortfall_rate": float(
                (
                    capacity_plan[
                        ["vehicle_shortfall", "crew_shortfall", "install_crew_shortfall"]
                    ].sum(axis=1)
                    > 0
                ).mean()
            ),
            "total_reserve_shortfall": int(
                capacity_plan[["reserve_vehicle_shortfall", "reserve_crew_shortfall"]].sum().sum()
            ),
        }
    )
    return CapacityPlanningResult(capacity_plan, vehicles, crews, metrics)
