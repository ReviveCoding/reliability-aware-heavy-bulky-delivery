from __future__ import annotations

import math

import numpy as np
import pandas as pd


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _order_sequence(group: pd.DataFrame, strategy: str) -> list[str]:
    frame = group.copy()
    if strategy == "sweep":
        frame["angle"] = np.arctan2(frame["lat"], frame["lon"])
        return frame.sort_values(["angle", "order_id"])["order_id"].tolist()
    if strategy == "risk_first":
        return frame.sort_values(
            ["predicted_failure_probability", "duration_p90", "order_id"],
            ascending=[False, False, True],
        )["order_id"].tolist()
    if strategy == "skill_clustered":
        sequences: list[str] = []
        for requires_install in [True, False]:
            subset = frame[frame["required_skill"].eq("install") == requires_install]
            if subset.empty:
                continue
            remaining = {
                row.order_id: (float(row.lat), float(row.lon))
                for row in subset.itertuples(index=False)
            }
            current = (0.0, 0.0)
            while remaining:
                next_order = min(
                    remaining,
                    key=lambda order_id: (_distance(current, remaining[order_id]), order_id),
                )
                sequences.append(next_order)
                current = remaining.pop(next_order)
        return sequences
    if strategy == "balanced":
        raise ValueError("balanced routing uses _balanced_chunks")

    remaining = {
        row.order_id: (float(row.lat), float(row.lon)) for row in frame.itertuples(index=False)
    }
    current = (0.0, 0.0)
    sequence: list[str] = []
    while remaining:
        next_order = min(
            remaining,
            key=lambda order_id: (_distance(current, remaining[order_id]), order_id),
        )
        sequence.append(next_order)
        current = remaining.pop(next_order)
    return sequence


def _balanced_chunks(
    lookup: pd.DataFrame, max_orders: int, max_cube: float, max_weight: float, max_minutes: float
) -> list[list[str]]:
    ordered = lookup.sort_values(["duration_p90", "order_id"], ascending=[False, True])
    total_cube = float(lookup["cube"].sum())
    total_weight = float(lookup["weight"].sum())
    bin_count = max(
        1,
        int(math.ceil(len(lookup) / max_orders)),
        int(math.ceil(total_cube / max_cube)),
        int(math.ceil(total_weight / max_weight)),
    )
    bins = [[] for _ in range(bin_count)]
    loads = [0.0] * bin_count
    cubes = [0.0] * bin_count
    weights = [0.0] * bin_count
    minutes = [0.0] * bin_count
    for row in ordered.itertuples(index=False):
        feasible = [
            index
            for index in range(len(bins))
            if len(bins[index]) < max_orders
            and cubes[index] + float(row.cube) <= max_cube
            and weights[index] + float(row.weight) <= max_weight
            and minutes[index] + float(row.duration_p90) <= max_minutes
        ]
        if not feasible:
            bins.append([])
            loads.append(0.0)
            cubes.append(0.0)
            weights.append(0.0)
            minutes.append(0.0)
            feasible = [len(bins) - 1]
        index = min(feasible, key=lambda candidate: (loads[candidate], candidate))
        bins[index].append(row.order_id)
        loads[index] += float(row.duration_p90)
        cubes[index] += float(row.cube)
        weights[index] += float(row.weight)
        minutes[index] += float(row.duration_p90)
    return [chunk for chunk in bins if chunk]


def _chunks(
    sequence: list[str],
    lookup: pd.DataFrame,
    max_orders: int,
    max_cube: float,
    max_weight: float,
    max_minutes: float,
) -> list[list[str]]:
    chunks: list[list[str]] = []
    current: list[str] = []
    cube = 0.0
    weight = 0.0
    minutes = 0.0
    cube_map = lookup.set_index("order_id")["cube"].to_dict()
    weight_map = lookup.set_index("order_id")["weight"].to_dict()
    minute_map = lookup.set_index("order_id")["duration_p90"].to_dict()
    for order_id in sequence:
        order_cube = float(cube_map[order_id])
        order_weight = float(weight_map[order_id])
        order_minutes = float(minute_map[order_id])
        would_overflow = (
            len(current) >= max_orders
            or cube + order_cube > max_cube
            or weight + order_weight > max_weight
            or minutes + order_minutes > max_minutes
        )
        if current and would_overflow:
            chunks.append(current)
            current = []
            cube = 0.0
            weight = 0.0
            minutes = 0.0
        current.append(order_id)
        cube += order_cube
        weight += order_weight
        minutes += order_minutes
    if current:
        chunks.append(current)
    return chunks


def _schedule_metrics(ordered: pd.DataFrame, duration_column: str) -> dict[str, float]:
    current_location = (0.0, 0.0)
    clock = 0.0
    travel = 0.0
    service = 0.0
    waiting = 0.0
    violation = 0.0
    for row in ordered.itertuples(index=False):
        next_location = (float(row.lat), float(row.lon))
        leg = _distance(current_location, next_location) * 12.0
        travel += leg
        clock += leg
        if clock < float(row.time_window_start):
            wait = float(row.time_window_start) - clock
            waiting += wait
            clock += wait
        violation += max(0.0, clock - float(row.time_window_end))
        duration = float(getattr(row, duration_column))
        service += duration
        clock += duration
        current_location = next_location
    return_leg = _distance(current_location, (0.0, 0.0)) * 12.0
    travel += return_leg
    clock += return_leg
    return {
        "travel_minutes": travel,
        "service_minutes": service,
        "waiting_minutes": waiting,
        "window_violation_minutes": violation,
        "route_minutes": clock,
    }


def _split_chunks_by_route_time(
    chunks: list[list[str]], lookup: pd.DataFrame, max_route_minutes: float
) -> list[list[str]]:
    refined: list[list[str]] = []
    for chunk in chunks:
        queue = [chunk]
        while queue:
            current = queue.pop(0)
            ordered = lookup.set_index("order_id").loc[current].reset_index()
            route_minutes = _schedule_metrics(ordered, "duration_p90")["route_minutes"]
            if route_minutes <= max_route_minutes or len(current) == 1:
                refined.append(current)
                continue
            midpoint = max(1, len(current) // 2)
            queue.insert(0, current[midpoint:])
            queue.insert(0, current[:midpoint])
    return refined


def generate_route_candidates(
    orders: pd.DataFrame, cfg: dict
) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    required = {
        "predicted_duration",
        "duration_p90",
        "predicted_failure_probability",
        "time_window_start",
        "time_window_end",
    }
    missing = required - set(orders.columns)
    if missing:
        raise ValueError(f"Routing input missing planning-time model outputs: {sorted(missing)}")

    rows: list[dict] = []
    members: dict[str, list[str]] = {}
    route_number = 0
    max_orders = int(cfg["routing"]["max_orders_per_route"])
    max_cube = float(cfg["routing"]["route_capacity_cube"])
    max_weight = float(cfg["routing"]["max_route_weight"])
    max_minutes = float(cfg["routing"]["max_route_minutes"])

    for station, station_orders in orders.groupby("station_id", sort=True):
        for strategy in cfg["routing"]["strategies"]:
            if strategy == "balanced":
                chunks = _balanced_chunks(
                    station_orders, max_orders, max_cube, max_weight, max_minutes
                )
            else:
                sequence = _order_sequence(station_orders, strategy)
                chunks = _chunks(
                    sequence, station_orders, max_orders, max_cube, max_weight, max_minutes
                )
            chunks = _split_chunks_by_route_time(chunks, station_orders, max_minutes)
            for chunk in chunks:
                route_number += 1
                route_id = f"R{route_number:05d}"
                part = station_orders[station_orders["order_id"].isin(chunk)].copy()
                ordered = part.set_index("order_id").loc[chunk].reset_index()
                expected = _schedule_metrics(ordered, "predicted_duration")
                tail = _schedule_metrics(ordered, "duration_p90")
                failure_risk = float(
                    1.0
                    - np.prod(1.0 - ordered["predicted_failure_probability"].to_numpy(dtype=float))
                )
                requires_install = int((ordered["required_skill"] == "install").any())
                crew_size = int(ordered["required_crew_size"].max())
                plausibility = {
                    "nearest": 0.72,
                    "sweep": 0.86,
                    "risk_first": 0.61,
                    "balanced": 0.68,
                    "skill_clustered": 0.74,
                }.get(strategy, 0.50)
                window_penalty = float(cfg["routing"]["time_window_penalty_per_minute"])
                utility = (
                    -(
                        tail["route_minutes"]
                        + 240.0 * failure_risk
                        + window_penalty * tail["window_violation_minutes"]
                    )
                    + 50.0 * plausibility
                )
                rows.append(
                    {
                        "route_id": route_id,
                        "station_id": station,
                        "strategy": strategy,
                        "order_count": len(chunk),
                        "cube": float(ordered["cube"].sum()),
                        "weight": float(ordered["weight"].sum()),
                        "predicted_service_minutes": expected["service_minutes"],
                        "p90_service_minutes": tail["service_minutes"],
                        "travel_minutes": expected["travel_minutes"],
                        "predicted_waiting_minutes": expected["waiting_minutes"],
                        "p90_waiting_minutes": tail["waiting_minutes"],
                        "predicted_window_violation_minutes": expected["window_violation_minutes"],
                        "p90_window_violation_minutes": tail["window_violation_minutes"],
                        "predicted_route_minutes": expected["route_minutes"],
                        "p90_route_minutes": tail["route_minutes"],
                        "failure_risk": failure_risk,
                        "requires_install_skill": requires_install,
                        "required_crew_size": crew_size,
                        "historical_plausibility": plausibility,
                        "operational_utility": utility,
                    }
                )
                members[route_id] = chunk
    return pd.DataFrame(rows), members


def route_members_table(members: dict[str, list[str]]) -> pd.DataFrame:
    rows = [
        {"route_id": route_id, "sequence_position": position, "order_id": order_id}
        for route_id, order_ids in sorted(members.items())
        for position, order_id in enumerate(order_ids, start=1)
    ]
    return pd.DataFrame(rows)
