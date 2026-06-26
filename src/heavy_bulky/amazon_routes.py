from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


def load_json(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(source)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object at {source}")
    return payload


def _number(value: object) -> float:
    if value in (None, ""):
        return 0.0
    return float(value)


def route_table(route_data: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for route_id, route in route_data.items():
        if not isinstance(route, dict):
            raise ValueError(f"Route {route_id} must be an object")
        stops = route.get("stops") or {}
        if not isinstance(stops, dict):
            raise ValueError(f"Route {route_id}.stops must be an object")
        dropoffs = [stop for stop in stops.values() if stop.get("type") == "Dropoff"]
        rows.append(
            {
                "route_id": route_id,
                "station_id": route.get("station_code"),
                "service_date": route.get("date_YYYY_MM_DD"),
                "departure_time_utc": route.get("departure_time_utc"),
                "executor_capacity_cm3": _number(route.get("executor_capacity_cm3")),
                "route_score": route.get("route_score"),
                "stop_count": len(stops),
                "dropoff_count": len(dropoffs),
                "zone_count": len(
                    {stop.get("zone_id") for stop in dropoffs if stop.get("zone_id")}
                ),
                "source_type": "observed_public",
                "available_at": "planning_time",
            }
        )
    return pd.DataFrame(rows)


def stop_table(route_data: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for route_id, route in route_data.items():
        for stop_id, stop in (route.get("stops") or {}).items():
            rows.append(
                {
                    "route_id": route_id,
                    "stop_id": stop_id,
                    "lat": _number(stop.get("lat")),
                    "lng": _number(stop.get("lng")),
                    "stop_type": stop.get("type"),
                    "zone_id": stop.get("zone_id"),
                    "source_type": "observed_public",
                    "available_at": "planning_time",
                }
            )
    return pd.DataFrame(rows)


def package_table(package_data: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for route_id, stops in package_data.items():
        if not isinstance(stops, dict):
            raise ValueError(f"Package route {route_id} must map stops to packages")
        for stop_id, packages in stops.items():
            for package_id, package in packages.items():
                dimensions = package.get("dimensions") or {}
                depth = _number(dimensions.get("depth_cm"))
                height = _number(dimensions.get("height_cm"))
                width = _number(dimensions.get("width_cm"))
                time_window = package.get("time_window") or {}
                rows.append(
                    {
                        "route_id": route_id,
                        "stop_id": stop_id,
                        "package_id": package_id,
                        "scan_status": package.get("scan_status"),
                        "scan_status_available_at": "post_outcome",
                        "planned_service_time_seconds": _number(
                            package.get("planned_service_time_seconds")
                        ),
                        "depth_cm": depth,
                        "height_cm": height,
                        "width_cm": width,
                        "package_cube_cm3": depth * height * width,
                        "time_window_start_utc": time_window.get("start_time_utc"),
                        "time_window_end_utc": time_window.get("end_time_utc"),
                        "source_type": "observed_public",
                        "available_at": "planning_time",
                    }
                )
    return pd.DataFrame(rows)


def build_public_route_marts(
    route_json: str | Path, package_json: str | Path
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    routes = load_json(route_json)
    return route_table(routes), stop_table(routes), package_table(load_json(package_json))
