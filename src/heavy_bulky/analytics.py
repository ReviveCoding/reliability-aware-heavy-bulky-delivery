from __future__ import annotations

from pathlib import Path

import pandas as pd

from .io import write_csv


def run_sql_marts(output_dir: str | Path, sql_dir: str | Path) -> dict[str, bool | int | str]:
    try:
        import duckdb
    except ImportError:
        return {
            "available": False,
            "passed": False,
            "reason": "duckdb_not_installed",
            "mart_count": 0,
        }

    output = Path(output_dir)
    sql_root = Path(sql_dir)
    sources = {
        "demand": output / "data/demand.csv",
        "optimized_routes": output / "planning/champion_routes.csv",
        "route_members": output / "routing/route_members.csv",
        "planning_orders": output / "service/planning_orders_rass.csv",
        "planning_orders_rass": output / "service/planning_orders_rass.csv",
    }
    missing = [str(path) for path in sources.values() if not path.exists()]
    if missing:
        return {
            "available": True,
            "passed": False,
            "reason": f"missing_sources:{missing}",
            "mart_count": 0,
        }

    connection = duckdb.connect(database=":memory:")
    try:
        for name, path in sources.items():
            connection.register(name, pd.read_csv(path))
        sql_paths = sorted(sql_root.glob("*.sql"))
        if not sql_paths:
            return {
                "available": True,
                "passed": False,
                "reason": "no_sql_marts_found",
                "mart_count": 0,
            }
        mart_dir = output / "analytics"
        mart_dir.mkdir(parents=True, exist_ok=True)
        mart_count = 0
        total_rows = 0
        for sql_path in sql_paths:
            query = sql_path.read_text(encoding="utf-8")
            result = connection.execute(query).fetch_df()
            write_csv(mart_dir / f"{sql_path.stem}.csv", result)
            mart_count += 1
            total_rows += len(result)
        return {
            "available": True,
            "passed": True,
            "reason": "",
            "mart_count": mart_count,
            "row_count": total_rows,
        }
    except Exception as exc:
        return {
            "available": True,
            "passed": False,
            "reason": f"{type(exc).__name__}: {exc}",
            "mart_count": 0,
        }
    finally:
        connection.close()
