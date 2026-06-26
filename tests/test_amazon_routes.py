from __future__ import annotations

import json

import pytest

from heavy_bulky.amazon_routes import (
    build_public_route_marts,
    load_json,
    package_table,
    route_table,
    stop_table,
)

ROUTES = {
    "R1": {
        "station_code": "D1",
        "date_YYYY_MM_DD": "2018-01-01",
        "departure_time_utc": "12:00:00",
        "executor_capacity_cm3": 1000,
        "route_score": "High",
        "stops": {
            "AA": {"lat": 1, "lng": 2, "type": "Station", "zone_id": None},
            "AB": {"lat": 1.1, "lng": 2.1, "type": "Dropoff", "zone_id": "A-1"},
        },
    }
}
PACKAGES = {
    "R1": {
        "AB": {
            "P1": {
                "scan_status": "DELIVERED",
                "time_window": {"start_time_utc": None, "end_time_utc": None},
                "planned_service_time_seconds": 30,
                "dimensions": {"depth_cm": 2, "height_cm": 3, "width_cm": 4},
            }
        }
    }
}


def test_official_route_schema_adapters():
    routes = route_table(ROUTES)
    stops = stop_table(ROUTES)
    packages = package_table(PACKAGES)
    assert routes.loc[0, "dropoff_count"] == 1
    assert len(stops) == 2
    assert packages.loc[0, "package_cube_cm3"] == 24
    assert packages.loc[0, "available_at"] == "planning_time"
    assert packages.loc[0, "scan_status_available_at"] == "post_outcome"


def test_public_route_marts_from_files(tmp_path):
    route_path = tmp_path / "routes.json"
    package_path = tmp_path / "packages.json"
    route_path.write_text(json.dumps(ROUTES), encoding="utf-8")
    package_path.write_text(json.dumps(PACKAGES), encoding="utf-8")
    routes, stops, packages = build_public_route_marts(route_path, package_path)
    assert (len(routes), len(stops), len(packages)) == (1, 2, 1)


def test_bad_json_and_missing_file_fail(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_json(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        load_json(bad)
