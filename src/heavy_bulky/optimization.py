from __future__ import annotations

import importlib.util
import os
import pickle
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass
class PlanResult:
    selected_routes: pd.DataFrame
    unserved_orders: list[str]
    status: str
    objective: float
    best_bound: float | None
    fallback_used: bool
    fallback_reason: str | None = None
    solve_time_seconds: float = 0.0
    relative_gap: float | None = None


def _solver_worker_environment() -> dict[str, str]:
    """Return a deterministic worker environment for installed and source-checkout runs.

    Pytest can import the project through ``pythonpath = ["src"]`` without installing the
    distribution. A child interpreter does not inherit that pytest-only path. Prepending the
    repository ``src`` directory when it exists keeps the isolated worker executable in both
    source and wheel installations instead of silently degrading to the greedy fallback.
    """
    environment = os.environ.copy()
    source_root = Path(__file__).resolve().parents[1]
    if (source_root / "heavy_bulky" / "solver_worker.py").is_file():
        current = [entry for entry in environment.get("PYTHONPATH", "").split(os.pathsep) if entry]
        source_text = str(source_root)
        environment["PYTHONPATH"] = os.pathsep.join(
            [source_text, *[entry for entry in current if entry != source_text]]
        )
    for variable in [
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ]:
        environment.setdefault(variable, "1")
    environment.setdefault("PYTHONHASHSEED", "0")
    return environment


def _compatible_vehicles(route: pd.Series, vehicles: pd.DataFrame) -> list[str]:
    compatible = vehicles[
        vehicles["station_id"].eq(route["station_id"])
        & vehicles["available"].eq(1)
        & vehicles["cube_capacity"].ge(float(route["cube"]))
        & vehicles["weight_capacity"].ge(float(route["weight"]))
    ]
    return sorted(compatible["vehicle_id"].tolist())


def _compatible_crews(route: pd.Series, crews: pd.DataFrame) -> list[str]:
    compatible = crews[
        crews["station_id"].eq(route["station_id"])
        & crews["available"].eq(1)
        & crews["crew_size"].ge(int(route["required_crew_size"]))
        & crews["max_minutes"].ge(float(route["p90_route_minutes"]))
    ]
    if int(route["requires_install_skill"]):
        compatible = compatible[compatible["skill"].eq("install")]
    return sorted(compatible["crew_id"].tolist())


def _route_cost(route: pd.Series, cfg: dict) -> float:
    overtime = max(
        0.0,
        float(route["p90_route_minutes"]) - float(cfg["simulation"]["overtime_threshold_minutes"]),
    )
    return (
        float(route["p90_route_minutes"])
        + float(cfg["optimization"]["overtime_penalty_per_minute"]) * overtime
        + float(cfg["optimization"]["risk_penalty"]) * float(route["failure_risk"])
        + float(cfg["optimization"]["time_window_penalty_per_minute"])
        * float(route["p90_window_violation_minutes"])
        - 20.0 * float(route["historical_plausibility"])
    )


def greedy_plan(
    routes: pd.DataFrame,
    members: dict[str, list[str]],
    orders: pd.DataFrame,
    vehicles: pd.DataFrame,
    crews: pd.DataFrame,
    cfg: dict,
    *,
    fallback_reason: str | None = None,
) -> PlanResult:
    selected: list[dict] = []
    unserved: list[str] = []
    used_vehicles: set[str] = set()
    used_crews: set[str] = set()
    started = time.perf_counter()

    for station, station_orders in orders.groupby("station_id", sort=True):
        options: list[tuple[float, list[dict]]] = []
        station_routes = routes[routes["station_id"].eq(station)]
        for _, bundle in station_routes.groupby("strategy", sort=True):
            local_vehicles = {
                vehicle
                for vehicle in vehicles.loc[
                    vehicles["station_id"].eq(station) & vehicles["available"].eq(1),
                    "vehicle_id",
                ]
                if vehicle not in used_vehicles
            }
            local_crews = {
                crew
                for crew in crews.loc[
                    crews["station_id"].eq(station) & crews["available"].eq(1),
                    "crew_id",
                ]
                if crew not in used_crews
            }
            assigned: list[dict] = []
            feasible = True
            for _, route in bundle.sort_values(
                ["requires_install_skill", "required_crew_size", "p90_route_minutes"],
                ascending=[False, False, False],
            ).iterrows():
                candidate_vehicles = [
                    vehicle
                    for vehicle in _compatible_vehicles(route, vehicles)
                    if vehicle in local_vehicles
                ]
                candidate_crews = [
                    crew for crew in _compatible_crews(route, crews) if crew in local_crews
                ]
                if not candidate_vehicles or not candidate_crews:
                    feasible = False
                    break
                record = route.to_dict()
                record["vehicle_id"] = candidate_vehicles[0]
                record["crew_id"] = candidate_crews[0]
                assigned.append(record)
                local_vehicles.remove(candidate_vehicles[0])
                local_crews.remove(candidate_crews[0])
            covered = {order_id for record in assigned for order_id in members[record["route_id"]]}
            expected = set(station_orders["order_id"])
            if feasible and covered == expected:
                options.append(
                    (sum(_route_cost(pd.Series(record), cfg) for record in assigned), assigned)
                )

        if options:
            _, best = min(options, key=lambda item: (item[0], [row["route_id"] for row in item[1]]))
            selected.extend(best)
            used_vehicles.update(row["vehicle_id"] for row in best)
            used_crews.update(row["crew_id"] for row in best)
            continue

        uncovered = set(station_orders["order_id"])
        ranked = station_routes.sort_values(
            ["operational_utility", "historical_plausibility", "route_id"],
            ascending=[False, False, True],
        )
        for _, route in ranked.iterrows():
            route_orders = members[route["route_id"]]
            if not set(route_orders).issubset(uncovered):
                continue
            candidate_vehicles = [
                vehicle
                for vehicle in _compatible_vehicles(route, vehicles)
                if vehicle not in used_vehicles
            ]
            candidate_crews = [
                crew for crew in _compatible_crews(route, crews) if crew not in used_crews
            ]
            if not candidate_vehicles or not candidate_crews:
                continue
            record = route.to_dict()
            record["vehicle_id"] = candidate_vehicles[0]
            record["crew_id"] = candidate_crews[0]
            selected.append(record)
            used_vehicles.add(candidate_vehicles[0])
            used_crews.add(candidate_crews[0])
            uncovered -= set(route_orders)
        unserved.extend(sorted(uncovered))

    selected_frame = pd.DataFrame(selected)
    objective = sum(_route_cost(row, cfg) for _, row in selected_frame.iterrows())
    objective += float(cfg["optimization"]["unserved_penalty"]) * len(unserved)
    elapsed = time.perf_counter() - started
    return PlanResult(
        selected_routes=selected_frame,
        unserved_orders=sorted(unserved),
        status="FALLBACK_GREEDY" if fallback_reason else "GREEDY",
        objective=float(objective),
        best_bound=None,
        fallback_used=fallback_reason is not None,
        fallback_reason=fallback_reason,
        solve_time_seconds=elapsed,
        relative_gap=None,
    )


def _solve_plan_native(
    routes: pd.DataFrame,
    members: dict[str, list[str]],
    orders: pd.DataFrame,
    vehicles: pd.DataFrame,
    crews: pd.DataFrame,
    cfg: dict,
) -> PlanResult:
    try:
        from ortools.sat.python import cp_model
    except ImportError:
        return greedy_plan(
            routes,
            members,
            orders,
            vehicles,
            crews,
            cfg,
            fallback_reason="ortools_not_installed",
        )

    started = time.perf_counter()
    model = cp_model.CpModel()
    route_ids = routes["route_id"].tolist()
    route_lookup = routes.set_index("route_id")
    select = {route_id: model.new_bool_var(f"select_{route_id}") for route_id in route_ids}
    unserved = {
        order_id: model.new_bool_var(f"unserved_{order_id}") for order_id in orders["order_id"]
    }
    assign_vehicle: dict[tuple[str, str], object] = {}
    assign_crew: dict[tuple[str, str], object] = {}

    for route_id in route_ids:
        route = route_lookup.loc[route_id]
        compatible_vehicles = _compatible_vehicles(route, vehicles)
        compatible_crews = _compatible_crews(route, crews)
        for vehicle in compatible_vehicles:
            assign_vehicle[route_id, vehicle] = model.new_bool_var(f"vehicle_{route_id}_{vehicle}")
        for crew in compatible_crews:
            assign_crew[route_id, crew] = model.new_bool_var(f"crew_{route_id}_{crew}")
        if compatible_vehicles:
            model.add(
                sum(assign_vehicle[route_id, vehicle] for vehicle in compatible_vehicles)
                == select[route_id]
            )
        else:
            model.add(select[route_id] == 0)
        if compatible_crews:
            model.add(
                sum(assign_crew[route_id, crew] for crew in compatible_crews) == select[route_id]
            )
        else:
            model.add(select[route_id] == 0)

    for order_id in orders["order_id"]:
        containing_routes = [route_id for route_id in route_ids if order_id in members[route_id]]
        model.add(sum(select[route_id] for route_id in containing_routes) + unserved[order_id] == 1)
    for vehicle in vehicles["vehicle_id"]:
        variables = [
            variable
            for (route_id, candidate), variable in assign_vehicle.items()
            if candidate == vehicle
        ]
        if variables:
            model.add(sum(variables) <= 1)
    for crew in crews["crew_id"]:
        variables = [
            variable for (route_id, candidate), variable in assign_crew.items() if candidate == crew
        ]
        if variables:
            model.add(sum(variables) <= 1)

    # Provide a validated feasible incumbent before branch-and-bound. This both improves
    # solution quality under a strict wall-clock budget and gives the pipeline a deterministic
    # fallback if the native solver cannot complete cleanly.
    incumbent = greedy_plan(routes, members, orders, vehicles, crews, cfg)
    incumbent_routes = (
        incumbent.selected_routes.set_index("route_id")
        if not incumbent.selected_routes.empty
        else pd.DataFrame()
    )
    incumbent_route_ids = set(incumbent.selected_routes.get("route_id", pd.Series(dtype=str)))
    incumbent_unserved = set(incumbent.unserved_orders)
    for route_id, variable in select.items():
        model.add_hint(variable, int(route_id in incumbent_route_ids))
    for order_id, variable in unserved.items():
        model.add_hint(variable, int(order_id in incumbent_unserved))
    for (route_id, vehicle_id), variable in assign_vehicle.items():
        hinted = (
            route_id in incumbent_route_ids
            and str(incumbent_routes.loc[route_id, "vehicle_id"]) == vehicle_id
        )
        model.add_hint(variable, int(hinted))
    for (route_id, crew_id), variable in assign_crew.items():
        hinted = (
            route_id in incumbent_route_ids
            and str(incumbent_routes.loc[route_id, "crew_id"]) == crew_id
        )
        model.add_hint(variable, int(hinted))

    route_coefficients = {
        route_id: int(round(_route_cost(route_lookup.loc[route_id], cfg))) for route_id in route_ids
    }
    objective_terms = [route_coefficients[route_id] * select[route_id] for route_id in route_ids]
    objective_terms.extend(
        int(round(float(cfg["optimization"]["unserved_penalty"]))) * variable
        for variable in unserved.values()
    )
    model.minimize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver_limit = float(cfg["optimization"]["time_limit_seconds"])
    solver.parameters.max_time_in_seconds = solver_limit
    solver.parameters.max_deterministic_time = solver_limit
    solver.parameters.max_number_of_conflicts = 50_000
    solver.parameters.num_search_workers = int(cfg["optimization"]["num_search_workers"])
    solver.parameters.random_seed = int(cfg["seed"] % (2**31 - 1))
    status_code = solver.solve(model)
    status = solver.status_name(status_code)
    elapsed = time.perf_counter() - started
    if status not in {"OPTIMAL", "FEASIBLE"}:
        return PlanResult(
            selected_routes=incumbent.selected_routes,
            unserved_orders=incumbent.unserved_orders,
            status="FALLBACK_GREEDY",
            objective=incumbent.objective,
            best_bound=None,
            fallback_used=True,
            fallback_reason=f"cp_sat_status_{status}",
            solve_time_seconds=elapsed,
            relative_gap=None,
        )

    selected: list[dict] = []
    for route_id in route_ids:
        if solver.value(select[route_id]):
            record = route_lookup.loc[route_id].to_dict()
            record["route_id"] = route_id
            record["vehicle_id"] = next(
                vehicle
                for (candidate_route, vehicle), variable in assign_vehicle.items()
                if candidate_route == route_id and solver.value(variable)
            )
            record["crew_id"] = next(
                crew
                for (candidate_route, crew), variable in assign_crew.items()
                if candidate_route == route_id and solver.value(variable)
            )
            selected.append(record)
    unserved_orders = [
        order_id for order_id, variable in unserved.items() if solver.value(variable)
    ]
    objective = float(solver.objective_value)
    raw_bound = float(solver.best_objective_bound)
    all_coefficients_nonnegative = (
        all(value >= 0 for value in route_coefficients.values())
        and float(cfg["optimization"]["unserved_penalty"]) >= 0
    )
    # Some short, bounded CP-SAT runs can expose an unusable negative search bound even when
    # every objective coefficient is nonnegative. Zero is then a valid conservative lower bound.
    bound = max(0.0, raw_bound) if all_coefficients_nonnegative else raw_bound
    relative_gap = abs(objective - bound) / max(abs(objective), 1.0)
    return PlanResult(
        selected_routes=pd.DataFrame(selected),
        unserved_orders=sorted(unserved_orders),
        status=status,
        objective=objective,
        best_bound=bound,
        fallback_used=False,
        solve_time_seconds=elapsed,
        relative_gap=relative_gap,
    )


def _solve_plan_partitioned_native(
    routes: pd.DataFrame,
    members: dict[str, list[str]],
    orders: pd.DataFrame,
    vehicles: pd.DataFrame,
    crews: pd.DataFrame,
    cfg: dict,
) -> PlanResult:
    """Exploit station separability before solving the route-selection problem.

    Routes and resources are station-local in this benchmark, so a monolithic model adds search
    complexity without adding coupling. Solving one bounded model per station preserves the exact
    feasible set while improving reliability under strict solver budgets.
    """
    stations = sorted(set(orders["station_id"]))
    if len(stations) <= 1:
        return _solve_plan_native(routes, members, orders, vehicles, crews, cfg)

    results: list[tuple[str, PlanResult]] = []
    for station_id in stations:
        station_routes = routes[routes["station_id"].eq(station_id)].copy()
        route_ids = set(station_routes["route_id"])
        station_members = {route_id: members[route_id] for route_id in route_ids}
        station_orders = orders[orders["station_id"].eq(station_id)].copy()
        station_vehicles = vehicles[vehicles["station_id"].eq(station_id)].copy()
        station_crews = crews[crews["station_id"].eq(station_id)].copy()
        results.append(
            (
                station_id,
                _solve_plan_native(
                    station_routes,
                    station_members,
                    station_orders,
                    station_vehicles,
                    station_crews,
                    cfg,
                ),
            )
        )

    selected_frames = [
        result.selected_routes for _, result in results if not result.selected_routes.empty
    ]
    selected = pd.concat(selected_frames, ignore_index=True) if selected_frames else pd.DataFrame()
    unserved = sorted(order_id for _, result in results for order_id in result.unserved_orders)
    fallback_results = [(station, result) for station, result in results if result.fallback_used]
    statuses = {result.status for _, result in results}
    if fallback_results:
        status = "FALLBACK_GREEDY"
        fallback_reason = ";".join(
            f"{station}:{result.fallback_reason}" for station, result in fallback_results
        )
    elif statuses == {"OPTIMAL"}:
        status = "OPTIMAL"
        fallback_reason = None
    else:
        status = "FEASIBLE"
        fallback_reason = None

    bounds = [result.best_bound for _, result in results]
    best_bound = float(sum(bounds)) if all(bound is not None for bound in bounds) else None
    objective = float(sum(result.objective for _, result in results))
    relative_gap = (
        abs(objective - best_bound) / max(abs(objective), 1.0) if best_bound is not None else None
    )
    return PlanResult(
        selected_routes=selected,
        unserved_orders=unserved,
        status=status,
        objective=objective,
        best_bound=best_bound,
        fallback_used=bool(fallback_results),
        fallback_reason=fallback_reason,
        solve_time_seconds=float(sum(result.solve_time_seconds for _, result in results)),
        relative_gap=relative_gap,
    )


def solve_plan(
    routes: pd.DataFrame,
    members: dict[str, list[str]],
    orders: pd.DataFrame,
    vehicles: pd.DataFrame,
    crews: pd.DataFrame,
    cfg: dict,
) -> PlanResult:
    """Run CP-SAT in an isolated interpreter with a hard wall-clock fallback.

    A separate interpreter avoids native-solver shutdown leaks and guarantees that the caller can
    recover a validated greedy incumbent when startup, presolve, solve, serialization, or teardown
    exceeds the configured wall-clock budget.
    """
    incumbent = greedy_plan(routes, members, orders, vehicles, crews, cfg)
    if importlib.util.find_spec("ortools") is None:
        return PlanResult(
            selected_routes=incumbent.selected_routes,
            unserved_orders=incumbent.unserved_orders,
            status="FALLBACK_GREEDY",
            objective=incumbent.objective,
            best_bound=None,
            fallback_used=True,
            fallback_reason="ortools_not_installed",
            solve_time_seconds=incumbent.solve_time_seconds,
            relative_gap=None,
        )

    started = time.perf_counter()
    hard_timeout = float(cfg["optimization"]["hard_timeout_seconds"])
    environment = _solver_worker_environment()

    with tempfile.TemporaryDirectory(prefix="heavy_bulky_solver_") as directory:
        root = Path(directory)
        request_path = root / "request.pkl"
        response_path = root / "response.pkl"
        with request_path.open("wb") as handle:
            pickle.dump(
                {
                    "routes": routes,
                    "members": members,
                    "orders": orders,
                    "vehicles": vehicles,
                    "crews": crews,
                    "cfg": cfg,
                },
                handle,
                protocol=pickle.HIGHEST_PROTOCOL,
            )

        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "heavy_bulky.solver_worker",
                    str(request_path),
                    str(response_path),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=hard_timeout,
                env=environment,
            )
        except subprocess.TimeoutExpired:
            return PlanResult(
                selected_routes=incumbent.selected_routes,
                unserved_orders=incumbent.unserved_orders,
                status="FALLBACK_GREEDY",
                objective=incumbent.objective,
                best_bound=None,
                fallback_used=True,
                fallback_reason="cp_sat_hard_timeout",
                solve_time_seconds=time.perf_counter() - started,
                relative_gap=None,
            )

        if completed.returncode != 0 or not response_path.exists():
            detail = (completed.stderr or completed.stdout or "missing response").strip()
            detail = detail[-500:].replace("\n", " ")
            return PlanResult(
                selected_routes=incumbent.selected_routes,
                unserved_orders=incumbent.unserved_orders,
                status="FALLBACK_GREEDY",
                objective=incumbent.objective,
                best_bound=None,
                fallback_used=True,
                fallback_reason=f"cp_sat_worker_error:{detail}",
                solve_time_seconds=time.perf_counter() - started,
                relative_gap=None,
            )

        try:
            with response_path.open("rb") as handle:
                result = pickle.load(handle)
        except (
            OSError,
            EOFError,
            pickle.PickleError,
            AttributeError,
            TypeError,
            ValueError,
        ) as exc:
            return PlanResult(
                selected_routes=incumbent.selected_routes,
                unserved_orders=incumbent.unserved_orders,
                status="FALLBACK_GREEDY",
                objective=incumbent.objective,
                best_bound=None,
                fallback_used=True,
                fallback_reason=f"cp_sat_worker_transport:{type(exc).__name__}",
                solve_time_seconds=time.perf_counter() - started,
                relative_gap=None,
            )

    if not isinstance(result, PlanResult):
        return PlanResult(
            selected_routes=incumbent.selected_routes,
            unserved_orders=incumbent.unserved_orders,
            status="FALLBACK_GREEDY",
            objective=incumbent.objective,
            best_bound=None,
            fallback_used=True,
            fallback_reason="cp_sat_worker_invalid_payload",
            solve_time_seconds=time.perf_counter() - started,
            relative_gap=None,
        )
    try:
        validation = validate_plan(result, members, orders, vehicles, crews)
    except (KeyError, AttributeError, TypeError, ValueError, IndexError) as exc:
        return PlanResult(
            selected_routes=incumbent.selected_routes,
            unserved_orders=incumbent.unserved_orders,
            status="FALLBACK_GREEDY",
            objective=incumbent.objective,
            best_bound=None,
            fallback_used=True,
            fallback_reason=f"cp_sat_worker_validation_error:{type(exc).__name__}",
            solve_time_seconds=time.perf_counter() - started,
            relative_gap=None,
        )
    if validation["hard_constraint_violations"]:
        return PlanResult(
            selected_routes=incumbent.selected_routes,
            unserved_orders=incumbent.unserved_orders,
            status="FALLBACK_GREEDY",
            objective=incumbent.objective,
            best_bound=None,
            fallback_used=True,
            fallback_reason=(
                f"cp_sat_worker_invalid_plan:{validation['hard_constraint_violations']}_violations"
            ),
            solve_time_seconds=time.perf_counter() - started,
            relative_gap=None,
        )
    return result


def validate_plan(
    plan: PlanResult,
    members: dict[str, list[str]],
    orders: pd.DataFrame,
    vehicles: pd.DataFrame | None = None,
    crews: pd.DataFrame | None = None,
) -> dict[str, int]:
    served: list[str] = []
    selected = plan.selected_routes
    if not selected.empty:
        for route_id in selected["route_id"]:
            served.extend(members.get(route_id, []))
    known_orders = set(orders["order_id"])
    duplicate_assignments = len(served) - len(set(served))
    missing_decisions = len(known_orders - set(served) - set(plan.unserved_orders))
    served_unserved_overlap = len(set(served) & set(plan.unserved_orders))
    unknown_orders = len((set(served) | set(plan.unserved_orders)) - known_orders)

    reused_vehicles = 0
    reused_crews = 0
    capacity_violations = 0
    resource_station_violations = 0
    skill_violations = 0
    crew_size_violations = 0
    shift_violations = 0
    if not selected.empty:
        reused_vehicles = int(selected["vehicle_id"].duplicated().sum())
        reused_crews = int(selected["crew_id"].duplicated().sum())
    if vehicles is not None and crews is not None and not selected.empty:
        vehicle_lookup = vehicles.set_index("vehicle_id")
        crew_lookup = crews.set_index("crew_id")
        for route in selected.itertuples(index=False):
            vehicle = vehicle_lookup.loc[route.vehicle_id]
            crew = crew_lookup.loc[route.crew_id]
            capacity_violations += int(
                float(route.cube) > float(vehicle.cube_capacity)
                or float(route.weight) > float(vehicle.weight_capacity)
            )
            resource_station_violations += int(
                route.station_id != vehicle.station_id or route.station_id != crew.station_id
            )
            skill_violations += int(bool(route.requires_install_skill) and crew.skill != "install")
            crew_size_violations += int(int(route.required_crew_size) > int(crew.crew_size))
            shift_violations += int(float(route.p90_route_minutes) > float(crew.max_minutes))

    violations = sum(
        [
            duplicate_assignments,
            missing_decisions,
            served_unserved_overlap,
            unknown_orders,
            reused_vehicles,
            reused_crews,
            capacity_violations,
            resource_station_violations,
            skill_violations,
            crew_size_violations,
            shift_violations,
        ]
    )
    return {
        "duplicate_assignments": duplicate_assignments,
        "missing_decisions": missing_decisions,
        "served_unserved_overlap": served_unserved_overlap,
        "unknown_orders": unknown_orders,
        "reused_vehicles": reused_vehicles,
        "reused_crews": reused_crews,
        "capacity_violations": capacity_violations,
        "resource_station_violations": resource_station_violations,
        "skill_violations": skill_violations,
        "crew_size_violations": crew_size_violations,
        "shift_violations": shift_violations,
        "hard_constraint_violations": violations,
    }
