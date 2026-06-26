from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import yaml

from . import __version__
from .advanced_service import fit_advanced_service_challenger
from .analytics import run_sql_marts
from .assets import package_sql_dir
from .capacity import plan_capacity, reconcile_capacity_with_route_pool
from .config import load_config
from .contracts import (
    validate_data_bundle,
    validate_operational_forecast,
    validate_route_candidates,
)
from .data import build_data_bundle
from .forecasting import forecast_slice_metrics, select_forecast
from .integrity import build_artifact_manifest, decision_fingerprint
from .io import staged_run_directory, write_csv, write_json
from .optimization import PlanResult, greedy_plan, solve_plan, validate_plan
from .rass import (
    add_rass_features,
    crossfit_rass_features,
    rass_ablation_metrics,
    rass_metrics,
)
from .reporting import df_md, markdown_report
from .routing import generate_route_candidates, route_members_table
from .safety import assert_no_post_outcome_features, planning_decision_view
from .service_model import fit_predict_failure_risk
from .simulation import (
    generate_scenario_bank,
    paired_policy_comparison,
    simulate_plan,
    simulation_summary,
    validate_scenario_bank,
    vv_checks,
)


def _write_run_context(cfg: dict, output: Path) -> None:
    resolved_yaml = yaml.safe_dump(cfg, sort_keys=True)
    config_hash = hashlib.sha256(resolved_yaml.encode("utf-8")).hexdigest()
    (output / "provenance").mkdir(parents=True, exist_ok=True)
    (output / "provenance" / "resolved_config.yaml").write_text(resolved_yaml, encoding="utf-8")
    dependencies: dict[str, str | None] = {}
    for distribution in [
        "numpy",
        "pandas",
        "scikit-learn",
        "PyYAML",
        "pydantic",
        "tabulate",
        "lightgbm",
        "ortools",
        "duckdb",
        "fastapi",
        "torch",
        "chronos-forecasting",
    ]:
        try:
            dependencies[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            dependencies[distribution] = None
    write_json(
        output / "provenance" / "run_manifest.json",
        {
            "package_version": __version__,
            "config_sha256": config_hash,
            "seed": cfg["seed"],
            "mode": cfg["mode"],
            "started_at_utc": datetime.now(UTC).isoformat(),
            "python": sys.version,
            "platform": platform.platform(),
            "github_sha": os.environ.get("GITHUB_SHA"),
            "dependencies": dependencies,
        },
    )


def _finalize_run_context(output: Path, metrics: dict, elapsed_seconds: float) -> None:
    manifest_path = output / "provenance" / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    summary_path = output / "metrics" / "summary.json"
    summary_hash = hashlib.sha256(summary_path.read_bytes()).hexdigest()
    manifest.update(
        {
            "status": "complete",
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "elapsed_seconds": round(float(elapsed_seconds), 6),
            "release_decision": metrics["release"]["decision"],
            "summary_sha256": summary_hash,
            "decision_fingerprint": decision_fingerprint(output),
        }
    )
    write_json(manifest_path, manifest)


def _plan_metadata(plan: PlanResult) -> dict:
    return {
        "status": plan.status,
        "objective": plan.objective,
        "best_bound": plan.best_bound,
        "relative_gap": plan.relative_gap,
        "fallback_used": plan.fallback_used,
        "fallback_reason": plan.fallback_reason,
        "solve_time_seconds": plan.solve_time_seconds,
        "selected_routes": len(plan.selected_routes),
        "unserved_orders": len(plan.unserved_orders),
    }


def _release_decision(metrics: dict, cfg: dict) -> tuple[str, list[str]]:
    reasons: list[str] = []
    gates = cfg["release_gates"]
    if (
        metrics["plan_validation"]["hard_constraint_violations"]
        > gates["hard_constraint_violations"]
    ):
        reasons.append("hard constraint violations")
    if metrics["forecast_champion"]["interval_coverage_gap"] > gates["max_interval_coverage_gap"]:
        reasons.append("forecast interval coverage gap")
    if (
        metrics["forecast_champion"]["worst_series_coverage_gap"]
        > gates["max_worst_series_coverage_gap"]
    ):
        reasons.append("forecast worst-series coverage gap")
    if abs(metrics["rass"]["p90_coverage"] - 0.9) > gates["max_rass_p90_coverage_gap"]:
        reasons.append("RASS p90 coverage gap")
    if (
        metrics["contracts"]["routes"]["singleton_time_exceptions"]
        > gates["max_singleton_route_time_exceptions"]
    ):
        reasons.append("singleton route-time exceptions")
    if (
        gates["require_advanced_service_when_enabled"]
        and cfg["advanced_service"]["enabled"]
        and metrics["advanced_service"]["status"] not in {"promoted", "hold"}
    ):
        reasons.append("advanced service challenger unavailable")
    if metrics["capacity"]["total_capacity_shortfall"] > gates["max_capacity_shortfall"]:
        reasons.append("forecast-driven capacity shortfall")
    failure_brier = metrics["failure_model"].get("validation_brier")
    if (
        isinstance(failure_brier, (int, float))
        and pd.notna(failure_brier)
        and failure_brier > gates["max_failure_brier"]
    ):
        reasons.append("failure-risk Brier score")
    if not all(metrics["simulator_vv"].values()):
        reasons.append("simulator V&V failure")
    if gates["require_sql_validation"] and not metrics["sql_validation"]["passed"]:
        reasons.append("SQL mart validation failure")
    fallback_rate = float(metrics["optimizer"]["fallback_used"])
    if fallback_rate > float(gates["max_solver_fallback_rate"]):
        reasons.append("solver fallback rate")
    unserved_rate = metrics["optimizer"]["unserved_orders"] / max(
        metrics["rows"]["planning_orders"], 1
    )
    if unserved_rate > float(gates["max_unserved_rate"]):
        reasons.append("unserved-order rate")
    relative_gap = metrics["optimizer"].get("relative_gap")
    if relative_gap is not None and relative_gap > float(gates["max_relative_gap"]):
        reasons.append("solver relative gap")
    champion_key = metrics["policy_selection"]["champion_simulation_key"]
    if (
        metrics[champion_key]["expected_cost"]
        > metrics["greedy_simulation"]["expected_cost"] * 1.05
    ):
        reasons.append("selected policy cost regression")
    rass_table = metrics["rass_ablation"]
    methods = {row["method"]: row for row in rass_table}
    if (
        "shrunk_rass" in methods
        and "global_median" in methods
        and methods["shrunk_rass"]["duration_mae"] > methods["global_median"]["duration_mae"] * 1.05
    ):
        reasons.append("RASS materially regressed against global baseline")
    return ("PROMOTE" if not reasons else "ITERATE", reasons)


def _policy_promotion_pass(
    candidate: dict[str, float],
    baseline: dict[str, float],
    paired: dict[str, float],
) -> tuple[bool, dict[str, bool]]:
    expected_improvement = (
        candidate["expected_cost"] <= baseline["expected_cost"] * 0.98
        and paired["bootstrap_ci95_high"] < 0
    )
    tail_improvement = (
        candidate["cvar95_cost"] <= baseline["cvar95_cost"] * 0.95
        and candidate["expected_cost"] <= baseline["expected_cost"] * 1.02
    )
    return expected_improvement or tail_improvement, {
        "expected_cost_improvement_with_paired_ci": bool(expected_improvement),
        "tail_cost_improvement_with_mean_guardrail": bool(tail_improvement),
    }


def _execute_pipeline(cfg: dict, output: Path) -> dict:
    started = time.perf_counter()
    stage_events: list[dict[str, object]] = []
    stage_started_at: dict[str, float] = {}

    def mark(stage: str, status: str = "complete") -> None:
        """Persist one lifecycle row per stage.

        A started row is written immediately so interrupted runs remain diagnosable.
        Completing the stage updates that same row instead of appending a second,
        permanently incomplete event.
        """
        now = time.perf_counter()
        elapsed = round(now - started, 6)
        if status == "started":
            if stage in stage_started_at:
                raise RuntimeError(f"Stage already started: {stage}")
            stage_started_at[stage] = now
            stage_events.append(
                {
                    "stage": stage,
                    "status": "started",
                    "elapsed_seconds": elapsed,
                    "duration_seconds": None,
                }
            )
        else:
            stage_start = stage_started_at.pop(stage, None)
            if stage_start is None:
                stage_events.append(
                    {
                        "stage": stage,
                        "status": "complete",
                        "elapsed_seconds": elapsed,
                        "duration_seconds": None,
                    }
                )
            else:
                matching = [
                    row
                    for row in stage_events
                    if row.get("stage") == stage and row.get("status") == "started"
                ]
                if len(matching) != 1:
                    raise RuntimeError(f"Invalid stage lifecycle for: {stage}")
                matching[0].update(
                    {
                        "status": "complete",
                        "elapsed_seconds": elapsed,
                        "duration_seconds": round(now - stage_start, 6),
                    }
                )
        write_json(output / "provenance/stage_timings.json", stage_events)

    _write_run_context(cfg, output)
    mark("run_context")
    data = build_data_bundle(cfg)
    mark("data_bundle")
    data_contract = validate_data_bundle(data)
    write_json(output / "contracts/data_contract.json", data_contract)
    write_csv(output / "data/demand.csv", data.demand)
    write_csv(output / "data/historical_orders.csv", data.historical_orders)
    write_csv(output / "data/planning_orders_raw.csv", data.planning_orders)
    write_csv(output / "data/vehicles_all.csv", data.vehicles)
    write_csv(output / "data/crews_all.csv", data.crews)
    write_csv(output / "data/provenance_registry.csv", data.provenance)

    forecast_selection = select_forecast(data.demand, cfg)
    mark("forecast_selection")
    forecast = forecast_selection.operational_forecast
    forecast_scores = forecast_selection.model_scores
    planning_demand_keys = data.demand[
        pd.to_datetime(data.demand["date"]).eq(pd.to_datetime(data.demand["date"]).max())
    ][["station_id", "service_type"]]
    forecast_contract = validate_operational_forecast(forecast, planning_demand_keys)
    write_json(output / "contracts/forecast_contract.json", forecast_contract)
    write_csv(output / "forecast/operational_forecast.csv", forecast)
    write_csv(
        output / "forecast/validation_predictions.csv",
        forecast_selection.validation_predictions,
    )
    forecast_slices = forecast_slice_metrics(forecast_selection.validation_predictions)
    write_csv(output / "forecast/model_comparison.csv", forecast_scores)
    write_csv(output / "forecast/slice_metrics.csv", forecast_slices)
    write_csv(output / "forecast/candidate_status.csv", forecast_selection.candidate_status)

    capacity = plan_capacity(
        forecast,
        data.historical_orders,
        data.planning_orders,
        data.vehicles,
        data.crews,
        cfg,
    )
    write_csv(output / "capacity/capacity_plan.csv", capacity.capacity_plan)
    write_csv(output / "capacity/vehicles_rostered.csv", capacity.vehicles)
    write_csv(output / "capacity/crews_rostered.csv", capacity.crews)

    planning_rass = add_rass_features(data.historical_orders, data.planning_orders, cfg)
    mark("planning_rass")
    historical_rass = crossfit_rass_features(data.historical_orders, cfg)
    mark("historical_rass_crossfit")
    failure_result = fit_predict_failure_risk(historical_rass, planning_rass, int(cfg["seed"]))
    baseline_planning = failure_result.planning
    advanced_result = fit_advanced_service_challenger(
        historical_rass,
        baseline_planning,
        cfg,
    )
    planning = advanced_result.planning.copy()
    if advanced_result.status == "promoted":
        planning["baseline_predicted_duration"] = planning["predicted_duration"]
        planning["baseline_duration_p90"] = planning["duration_p90"]
        planning["baseline_predicted_failure_probability"] = planning[
            "predicted_failure_probability"
        ]
        planning["predicted_duration"] = planning["advanced_predicted_duration"]
        planning["duration_p90"] = planning["advanced_duration_p90"]
        planning["predicted_failure_probability"] = planning[
            "advanced_predicted_failure_probability"
        ]
    rass_ablation = rass_ablation_metrics(data.historical_orders, planning, cfg)
    write_csv(output / "service/planning_orders_rass.csv", planning)
    write_csv(output / "service/historical_orders_rass_crossfit.csv", historical_rass)
    write_csv(output / "service/rass_ablation.csv", rass_ablation)
    write_json(
        output / "service/advanced_service_status.json",
        {"status": advanced_result.status, "metrics": advanced_result.metrics},
    )

    decision_orders = planning_decision_view(planning)
    assert_no_post_outcome_features(decision_orders)
    write_csv(output / "service/planning_decision_features.csv", decision_orders)

    routes, members = generate_route_candidates(decision_orders, cfg)
    mark("route_generation")
    route_contract = validate_route_candidates(routes, members, decision_orders, cfg["routing"])
    capacity = reconcile_capacity_with_route_pool(capacity, routes, data.vehicles, data.crews, cfg)
    write_csv(output / "capacity/capacity_plan.csv", capacity.capacity_plan)
    write_csv(output / "capacity/vehicles_rostered.csv", capacity.vehicles)
    write_csv(output / "capacity/crews_rostered.csv", capacity.crews)
    write_json(output / "contracts/route_contract.json", route_contract)
    members_table = route_members_table(members)
    write_csv(output / "routing/route_candidates.csv", routes)
    write_csv(output / "routing/route_members.csv", members_table)
    write_json(output / "routing/route_members.json", members)

    mark("risk_aware_solve", "started")
    optimized = solve_plan(routes, members, decision_orders, capacity.vehicles, capacity.crews, cfg)
    mark("risk_aware_solve")
    greedy = greedy_plan(routes, members, decision_orders, capacity.vehicles, capacity.crews, cfg)

    deterministic_routes = routes.copy()
    deterministic_routes["p90_service_minutes"] = deterministic_routes["predicted_service_minutes"]
    deterministic_routes["p90_waiting_minutes"] = deterministic_routes["predicted_waiting_minutes"]
    deterministic_routes["p90_window_violation_minutes"] = deterministic_routes[
        "predicted_window_violation_minutes"
    ]
    deterministic_routes["p90_route_minutes"] = deterministic_routes["predicted_route_minutes"]
    mark("deterministic_solve", "started")
    deterministic = solve_plan(
        deterministic_routes,
        members,
        decision_orders,
        capacity.vehicles,
        capacity.crews,
        cfg,
    )
    mark("deterministic_solve")

    label_informed_routes = routes.copy()
    order_lookup = planning.set_index("order_id")
    realized_label_minutes: list[float] = []
    realized_label_risk: list[float] = []
    for route in label_informed_routes.itertuples(index=False):
        route_orders = order_lookup.loc[members[route.route_id]]
        realized_label_minutes.append(
            float(route.travel_minutes)
            + float(route.predicted_waiting_minutes)
            + float(route_orders["actual_duration"].sum())
        )
        realized_label_risk.append(float(route_orders["failed_attempt"].max()))
    label_informed_routes["p90_route_minutes"] = realized_label_minutes
    label_informed_routes["failure_risk"] = realized_label_risk
    mark("label_informed_diagnostic", "started")
    label_informed = greedy_plan(
        label_informed_routes,
        members,
        decision_orders,
        capacity.vehicles,
        capacity.crews,
        cfg,
    )
    mark("label_informed_diagnostic")

    plans = {
        "risk_aware": optimized,
        "greedy": greedy,
        "deterministic": deterministic,
        "label_informed_proxy": label_informed,
    }
    for name, plan in plans.items():
        write_csv(output / f"planning/{name}_routes.csv", plan.selected_routes)
        write_json(output / f"planning/{name}_plan_meta.json", _plan_metadata(plan))

    scenario_bank = generate_scenario_bank(planning, data.vehicles, data.crews, cfg)
    mark("scenario_bank")
    scenario_checks = validate_scenario_bank(scenario_bank, cfg)
    write_csv(output / "simulation/scenario_order_events.csv", scenario_bank.order_events)
    write_csv(output / "simulation/scenario_station_events.csv", scenario_bank.station_events)
    write_csv(output / "simulation/scenario_vehicle_events.csv", scenario_bank.vehicle_events)
    write_csv(output / "simulation/scenario_crew_events.csv", scenario_bank.crew_events)

    simulations: dict[str, pd.DataFrame] = {}
    for name, plan in plans.items():
        simulation = simulate_plan(
            plan,
            members,
            planning,
            cfg,
            scenario_bank,
            vehicles=data.vehicles,
            crews=data.crews,
        )
        simulations[name] = simulation
        write_csv(output / f"simulation/{name}_replay.csv", simulation)

    mark("policy_simulations")

    simulation_metrics = {
        name: simulation_summary(simulation) for name, simulation in simulations.items()
    }
    greedy_cost = simulation_metrics["greedy"]["expected_cost"]
    deterministic_cost = simulation_metrics["deterministic"]["expected_cost"]
    risk_cost = simulation_metrics["risk_aware"]["expected_cost"]

    paired_comparisons = {
        "risk_aware_vs_greedy": paired_policy_comparison(
            simulations["risk_aware"], simulations["greedy"], int(cfg["seed"]) + 1
        ),
        "deterministic_vs_greedy": paired_policy_comparison(
            simulations["deterministic"], simulations["greedy"], int(cfg["seed"]) + 2
        ),
        "risk_aware_vs_deterministic": paired_policy_comparison(
            simulations["risk_aware"],
            simulations["deterministic"],
            int(cfg["seed"]) + 3,
        ),
    }

    champion_name = "greedy"
    champion_plan = greedy
    champion_simulation = simulations["greedy"]
    champion_key = "greedy_simulation"
    deterministic_value_pass, deterministic_evidence = _policy_promotion_pass(
        simulation_metrics["deterministic"],
        simulation_metrics["greedy"],
        paired_comparisons["deterministic_vs_greedy"],
    )
    deterministic_solver_pass, deterministic_solver_evidence = _solver_promotion_quality(
        deterministic, cfg
    )
    deterministic_evidence["solver_quality"] = deterministic_solver_evidence
    deterministic_pass = deterministic_value_pass and deterministic_solver_pass
    deterministic_decision = "HOLD_DETERMINISTIC"
    if deterministic_pass:
        champion_name = "deterministic"
        champion_plan = deterministic
        champion_simulation = simulations["deterministic"]
        champion_key = "deterministic_simulation"
        deterministic_decision = "PROMOTE"

    risk_baseline_name = champion_name
    risk_comparison_key = (
        "risk_aware_vs_deterministic"
        if champion_name == "deterministic"
        else "risk_aware_vs_greedy"
    )
    risk_value_pass, risk_aware_evidence = _policy_promotion_pass(
        simulation_metrics["risk_aware"],
        simulation_metrics[risk_baseline_name],
        paired_comparisons[risk_comparison_key],
    )
    risk_solver_pass, risk_solver_evidence = _solver_promotion_quality(optimized, cfg)
    risk_aware_evidence["solver_quality"] = risk_solver_evidence
    risk_aware_pass = risk_value_pass and risk_solver_pass
    risk_decision = "HOLD_RISK_AWARE"
    if risk_aware_pass:
        champion_name = "risk_aware"
        champion_plan = optimized
        champion_simulation = simulations["risk_aware"]
        champion_key = "optimized_simulation"
        risk_decision = "PROMOTE"

    write_csv(output / "planning/champion_routes.csv", champion_plan.selected_routes)
    write_json(output / "planning/champion_plan_meta.json", _plan_metadata(champion_plan))
    write_csv(output / "simulation/champion_replay.csv", champion_simulation)

    repeated_champion = simulate_plan(
        champion_plan,
        members,
        planning,
        cfg,
        scenario_bank,
        vehicles=data.vehicles,
        crews=data.crews,
    )
    pathological_plan = PlanResult(
        selected_routes=pd.DataFrame(columns=routes.columns.tolist() + ["vehicle_id", "crew_id"]),
        unserved_orders=sorted(planning["order_id"].tolist()),
        status="PATHOLOGICAL_ALL_UNSERVED",
        objective=float(cfg["optimization"]["unserved_penalty"]) * len(planning),
        best_bound=None,
        fallback_used=False,
    )
    pathological_simulation = simulate_plan(
        pathological_plan,
        members,
        planning,
        cfg,
        scenario_bank,
        vehicles=data.vehicles,
        crews=data.crews,
    )
    write_csv(output / "simulation/pathological_all_unserved_replay.csv", pathological_simulation)

    plan_validation = validate_plan(
        champion_plan, members, planning, capacity.vehicles, capacity.crews
    )
    simulator_vv = vv_checks(
        champion_simulation,
        repeated_champion,
        pathological_simulation,
        scenario_checks,
    )
    sql_validation = run_sql_marts(output, package_sql_dir())
    mark("sql_marts")

    forecast_champion_row = (
        forecast_scores[forecast_scores["model"].eq(forecast_selection.champion)].iloc[0].to_dict()
    )
    metrics = {
        "used_m5_public_pattern": data.used_m5,
        "contracts": {
            "data": data_contract,
            "forecast": forecast_contract,
            "routes": route_contract,
        },
        "rows": {
            "demand": len(data.demand),
            "historical_orders": len(data.historical_orders),
            "planning_orders": len(planning),
            "route_candidates": len(routes),
        },
        "forecast_champion": forecast_champion_row,
        "forecast_all": forecast_scores.to_dict(orient="records"),
        "forecast_candidate_status": forecast_selection.candidate_status.to_dict(orient="records"),
        "forecast_slices": forecast_slices.to_dict(orient="records"),
        "capacity": capacity.metrics,
        "rass": rass_metrics(planning),
        "rass_ablation": rass_ablation.to_dict(orient="records"),
        "failure_model": failure_result.metrics,
        "advanced_service": {
            "status": advanced_result.status,
            "metrics": advanced_result.metrics,
        },
        "optimizer": _plan_metadata(champion_plan),
        "risk_aware_optimizer_challenger": _plan_metadata(optimized),
        "deterministic_optimizer_challenger": _plan_metadata(deterministic),
        "label_informed_diagnostic_planner": _plan_metadata(label_informed),
        "plan_validation": plan_validation,
        "optimized_simulation": simulation_metrics["risk_aware"],
        "greedy_simulation": simulation_metrics["greedy"],
        "deterministic_simulation": simulation_metrics["deterministic"],
        "label_informed_proxy_simulation": simulation_metrics["label_informed_proxy"],
        "scenario_bank_validation": scenario_checks,
        "simulator_vv": simulator_vv,
        "sql_validation": sql_validation,
        "paired_policy_comparisons": paired_comparisons,
    }
    metrics["decision_value"] = _decision_value_summary(
        simulation_metrics,
        champion_name,
    )
    metrics["policy_selection"] = {
        "champion": champion_name,
        "champion_simulation_key": champion_key,
        "deterministic_component_decision": deterministic_decision,
        "risk_aware_component_decision": risk_decision,
        "deterministic_promotion_evidence": deterministic_evidence,
        "risk_aware_baseline": risk_baseline_name,
        "risk_aware_promotion_evidence": risk_aware_evidence,
        "promotion_rule": (
            "Promote for >=2% expected-cost improvement only when the paired bootstrap 95% "
            "CI is entirely below zero, or for >=5% CVaR95 improvement with expected cost "
            "within 2%; solver status, fallback, unserved-order, and relative-gap gates must "
            "also pass."
        ),
    }
    metrics["relative_expected_cost_change_vs_greedy"] = (
        metrics[champion_key]["expected_cost"] / max(greedy_cost, 1.0) - 1.0
    )
    decision, reasons = _release_decision(metrics, cfg)
    metrics["release"] = {"decision": decision, "reasons": reasons}
    write_json(output / "metrics/summary.json", metrics)
    mark("metrics_and_release")

    markdown_report(
        output / "reports/full_pipeline_report.md",
        "Heavy-Bulky Forecast-to-Execution Benchmark",
        [
            (
                "Claim boundary",
                "Public M5 patterns are optional. Route, crew, skill, service-duration and "
                "counterfactual outcomes in the verified smoke run are semi-synthetic. Results "
                "are offline simulation evidence, not production AMXL impact.",
            ),
            ("Data and provenance", df_md(data.provenance)),
            ("Forecast model comparison", df_md(forecast_scores)),
            ("Forecast-driven capacity plan", df_md(capacity.capacity_plan)),
            ("RASS ablation", df_md(rass_ablation)),
            (
                "Service reliability",
                "```json\n"
                + json.dumps(
                    {
                        "rass": metrics["rass"],
                        "failure_model": metrics["failure_model"],
                        "advanced_service": metrics["advanced_service"],
                    },
                    indent=2,
                )
                + "\n```",
            ),
            (
                "Optimization and constraint validation",
                "```json\n"
                + json.dumps(
                    {"optimizer": metrics["optimizer"], "validation": plan_validation},
                    indent=2,
                )
                + "\n```",
            ),
            (
                "Operational replay",
                "```json\n"
                + json.dumps(
                    {
                        "risk_aware": metrics["optimized_simulation"],
                        "deterministic": metrics["deterministic_simulation"],
                        "greedy": metrics["greedy_simulation"],
                        "label_informed_proxy": metrics["label_informed_proxy_simulation"],
                        "paired": metrics["paired_policy_comparisons"],
                        "decision_value": metrics["decision_value"],
                        "vv": metrics["simulator_vv"],
                    },
                    indent=2,
                )
                + "\n```",
            ),
            (
                "Policy promotion",
                "```json\n" + json.dumps(metrics["policy_selection"], indent=2) + "\n```",
            ),
            (
                "Release decision",
                f"**{decision}**\n\nReasons: {reasons or ['all configured gates passed']}",
            ),
        ],
    )
    mark("reporting")
    _finalize_run_context(output, metrics, time.perf_counter() - started)
    write_json(output / "provenance/artifact_manifest.json", build_artifact_manifest(output))
    return metrics



def _decision_value_summary(
    simulation_metrics: dict[str, dict],
    champion_name: str,
) -> dict[str, float | str]:
    """Describe offline candidate performance without overriding promotion gates.

    The lowest expected-cost evaluated candidate is descriptive only. The
    selected champion remains the policy that passed the value and solver-quality
    promotion gates in ``policy_selection``.
    """
    expected_costs = {
        name: float(simulation_metrics[name]["expected_cost"])
        for name in ("greedy", "deterministic", "risk_aware")
    }

    lowest_candidate = min(
        expected_costs,
        key=lambda name: (expected_costs[name], name),
    )

    greedy_cost = expected_costs["greedy"]
    deterministic_cost = expected_costs["deterministic"]
    risk_cost = expected_costs["risk_aware"]
    selected_champion_cost = expected_costs[champion_name]
    label_informed_cost = float(
        simulation_metrics["label_informed_proxy"]["expected_cost"]
    )

    return {
        "relative_expected_cost_change_vs_greedy": (
            risk_cost / max(greedy_cost, 1.0) - 1.0
        ),
        "deterministic_minus_risk_aware_expected_cost_delta": (
            deterministic_cost - risk_cost
        ),
        "lowest_expected_cost_evaluated_candidate": lowest_candidate,
        "lowest_expected_cost_evaluated_candidate_expected_cost": (
            expected_costs[lowest_candidate]
        ),
        "selected_champion_policy": champion_name,
        "selected_champion_expected_cost": selected_champion_cost,
        "risk_aware_regret_vs_lowest_expected_cost_evaluated_candidate": max(
            0.0,
            risk_cost - expected_costs[lowest_candidate],
        ),
        "label_informed_proxy_cost_delta_vs_risk_aware": (
            label_informed_cost - risk_cost
        ),
        "note": (
            "Offline common-scenario comparisons. "
            "lowest_expected_cost_evaluated_candidate is descriptive across "
            "evaluated candidate simulations and does not override the "
            "promotion-gated selected_champion_policy. The label-informed "
            "proxy uses realized base service labels for route scoring but is "
            "not a scenario-wise perfect-information lower bound, so no EVPI "
            "or oracle-regret claim is made."
        ),
    }



def _solver_promotion_quality(plan: PlanResult, cfg: dict) -> tuple[bool, dict[str, bool]]:
    relative_gap = plan.relative_gap
    status_ok = plan.status in {"OPTIMAL", "FEASIBLE"}
    no_fallback = not plan.fallback_used
    no_unserved = len(plan.unserved_orders) == 0
    gap_ok = relative_gap is not None and relative_gap <= float(
        cfg["release_gates"]["max_relative_gap"]
    )
    if plan.status == "OPTIMAL":
        gap_ok = True
    evidence = {
        "status_eligible": status_ok,
        "no_solver_fallback": no_fallback,
        "no_unserved_orders": no_unserved,
        "relative_gap_within_gate": gap_ok,
    }
    return all(evidence.values()), evidence


def run_pipeline(
    config_path: str | Path,
    output_dir_override: str | Path | None = None,
) -> dict:
    cfg = load_config(config_path)
    if output_dir_override is not None:
        cfg["output_dir"] = str(Path(output_dir_override))
    with staged_run_directory(cfg["output_dir"]) as output:
        return _execute_pipeline(cfg, output)
