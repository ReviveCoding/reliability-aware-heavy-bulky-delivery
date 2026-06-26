from __future__ import annotations

import argparse
import csv
import json
import tarfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    from .distribution_integrity import (
        distribution_resources,
        sdist_content_manifest,
        sha256_file,
        wheel_contents,
    )
except ImportError:  # direct execution: python scripts/full_pipeline_validation.py
    from distribution_integrity import (
        distribution_resources,
        sdist_content_manifest,
        sha256_file,
        wheel_contents,
    )

from heavy_bulky import __version__
from heavy_bulky.integrity import validate_published_run


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    details: dict[str, Any]


def decision_value_contract_problems(
    decision_value: dict[str, Any],
    champion: Any,
) -> list[str]:
    """Validate decision-value schema without conflating its semantics."""

    problems: list[str] = []

    selected_champion = decision_value.get("selected_champion_policy")

    allowed_policies = {
        "greedy",
        "deterministic",
        "risk_aware",
    }

    if selected_champion not in allowed_policies:
        problems.append(f"invalid_selected_champion_policy:{selected_champion}")
    elif selected_champion != champion:
        problems.append(f"selected_champion_policy_mismatch:{selected_champion}!={champion}")

    lowest_cost_candidate = decision_value.get("lowest_expected_cost_evaluated_candidate")

    if lowest_cost_candidate not in allowed_policies:
        problems.append(f"invalid_lowest_expected_cost_evaluated_candidate:{lowest_cost_candidate}")

    return problems


def artifact_integrity(
    output: Path, *, require_promote: bool = True, max_runtime_seconds: float = 120.0
) -> tuple[Check, dict]:
    required = [
        "_SUCCESS",
        "provenance/run_manifest.json",
        "provenance/artifact_manifest.json",
        "provenance/resolved_config.yaml",
        "provenance/stage_timings.json",
        "contracts/data_contract.json",
        "contracts/forecast_contract.json",
        "contracts/route_contract.json",
        "data/provenance_registry.csv",
        "forecast/operational_forecast.csv",
        "forecast/model_comparison.csv",
        "service/planning_orders_rass.csv",
        "service/planning_decision_features.csv",
        "routing/route_candidates.csv",
        "routing/route_members.csv",
        "planning/champion_routes.csv",
        "planning/champion_plan_meta.json",
        "simulation/champion_replay.csv",
        "analytics/01_daily_station_service_demand.csv",
        "analytics/02_plan_vs_actual.csv",
        "analytics/03_monitoring_daily.csv",
        "metrics/summary.json",
        "reports/full_pipeline_report.md",
    ]
    missing = [relative for relative in required if not (output / relative).exists()]
    problems: list[str] = []
    metrics: dict[str, Any] = {}
    summary = output / "metrics/summary.json"
    if summary.exists():
        try:
            metrics = json.loads(summary.read_text(encoding="utf-8"))
        except Exception as exc:
            problems.append(f"invalid_summary_json:{type(exc).__name__}:{exc}")
    if metrics:
        if require_promote and metrics.get("release", {}).get("decision") != "PROMOTE":
            problems.append(f"release_not_promote:{metrics.get('release')}")
        if metrics.get("plan_validation", {}).get("hard_constraint_violations") != 0:
            problems.append("hard_constraint_violations")
        if metrics.get("optimizer", {}).get("unserved_orders") != 0:
            problems.append("champion_has_unserved_orders")
        if not all(metrics.get("simulator_vv", {}).values()):
            problems.append("simulator_vv_failure")
        if not metrics.get("sql_validation", {}).get("passed"):
            problems.append("sql_validation_failure")
        if not metrics.get("capacity", {}).get("route_pool_reconciled"):
            problems.append("route_pool_capacity_not_reconciled")
        if metrics.get("capacity", {}).get("total_capacity_shortfall") != 0:
            problems.append("operational_capacity_shortfall")
        if not all(metrics.get("scenario_bank_validation", {}).values()):
            problems.append("scenario_bank_validation_failure")
        champion = metrics.get("policy_selection", {}).get("champion")
        if champion not in {"greedy", "deterministic", "risk_aware"}:
            problems.append(f"invalid_deployable_champion:{champion}")
        decision_value = metrics.get("decision_value", {})
        problems.extend(
            decision_value_contract_problems(
                decision_value,
                champion,
            )
        )
        for challenger in [
            "deterministic_promotion_evidence",
            "risk_aware_promotion_evidence",
        ]:
            evidence = metrics.get("policy_selection", {}).get(challenger, {})
            if "solver_quality" not in evidence:
                problems.append(f"missing_solver_quality_gate:{challenger}")
    stage_path = output / "provenance/stage_timings.json"
    if stage_path.exists():
        try:
            timings = json.loads(stage_path.read_text(encoding="utf-8"))
            incomplete = [row for row in timings if row.get("status") != "complete"]
            if incomplete:
                problems.append(f"incomplete_stage_timings:{incomplete}")
            if not timings or timings[-1].get("stage") != "reporting":
                problems.append("missing_terminal_reporting_stage")
            elif float(timings[-1].get("elapsed_seconds", 0.0)) > max_runtime_seconds:
                problems.append(f"runtime_budget_exceeded:{timings[-1].get('elapsed_seconds')}")
        except Exception as exc:
            problems.append(f"invalid_stage_timings:{type(exc).__name__}:{exc}")
    manifest_path = output / "provenance/run_manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("package_version") != __version__:
                problems.append(f"unexpected_package_version:{manifest.get('package_version')}")
            if not manifest.get("config_sha256"):
                problems.append("missing_config_hash")
            if manifest.get("status") != "complete":
                problems.append(f"incomplete_run_manifest:{manifest.get('status')}")
            if not manifest.get("completed_at_utc"):
                problems.append("missing_completed_at")
            if not manifest.get("summary_sha256"):
                problems.append("missing_summary_hash")
            elif summary.exists():
                import hashlib

                actual_summary_hash = hashlib.sha256(summary.read_bytes()).hexdigest()
                if manifest["summary_sha256"] != actual_summary_hash:
                    problems.append("summary_hash_mismatch")
            if manifest.get("release_decision") != metrics.get("release", {}).get("decision"):
                problems.append("manifest_release_mismatch")
        except Exception as exc:
            problems.append(f"invalid_run_manifest:{type(exc).__name__}:{exc}")

    problems.extend(validate_published_run(output))

    csv_contracts = {
        "forecast/operational_forecast.csv": {"station_id", "service_type", "p90"},
        "planning/champion_routes.csv": {"route_id", "vehicle_id", "crew_id"},
        "simulation/champion_replay.csv": {"replication", "total_cost"},
        "service/planning_decision_features.csv": {
            "order_id",
            "predicted_duration",
            "predicted_failure_probability",
        },
    }
    for relative, expected in csv_contracts.items():
        path = output / relative
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8", newline="") as handle:
            header = set(next(csv.reader(handle), []))
        absent = sorted(expected - header)
        if absent:
            problems.append(f"missing_csv_columns:{relative}:{absent}")
    decision_path = output / "service/planning_decision_features.csv"
    if decision_path.exists():
        with decision_path.open("r", encoding="utf-8", newline="") as handle:
            header = set(next(csv.reader(handle), []))
        forbidden = sorted(
            {"actual_duration", "failed_attempt", "failure_probability_true"} & header
        )
        if forbidden:
            problems.append(f"outcome_leakage_columns:{forbidden}")
    problems = list(dict.fromkeys(problems))
    passed = not missing and not problems
    return (
        Check(
            name=f"artifact_integrity:{output.name}",
            passed=passed,
            details={"output": str(output), "missing": missing, "problems": problems},
        ),
        metrics,
    )


def wheel_integrity(wheel: Path) -> Check:
    if not wheel.exists():
        return Check("wheel_integrity", False, {"missing_wheel": str(wheel)})
    names = wheel_contents(wheel)
    missing = distribution_resources(names)
    return Check(
        "wheel_integrity",
        not missing,
        {
            "wheel": str(wheel),
            "sha256": sha256_file(wheel),
            "missing": missing,
            "file_count": len(names),
        },
    )


def sdist_integrity(sdist: Path) -> Check:
    if not sdist.exists():
        return Check("sdist_integrity", False, {"missing_sdist": str(sdist)})
    with tarfile.open(sdist, "r:gz") as archive:
        names = []
        for member in archive.getmembers():
            parts = Path(member.name).parts
            if len(parts) > 1:
                names.append(Path(*parts[1:]).as_posix().replace("src/", "", 1))
    missing = distribution_resources(names)
    return Check(
        "sdist_integrity",
        not missing,
        {
            "sdist": str(sdist),
            "sha256": sha256_file(sdist),
            "missing": missing,
            "file_count": len(names),
        },
    )


def wheel_reproducibility(first: Path, second: Path) -> Check:
    first_hash = sha256_file(first) if first.exists() else None
    second_hash = sha256_file(second) if second.exists() else None
    passed = first_hash is not None and first_hash == second_hash
    return Check(
        "wheel_bitwise_reproducibility",
        passed,
        {"first_sha256": first_hash, "second_sha256": second_hash},
    )


def sdist_reproducibility(first: Path, second: Path) -> Check:
    if not first.exists() or not second.exists():
        return Check(
            "sdist_content_reproducibility",
            False,
            {"first_exists": first.exists(), "second_exists": second.exists()},
        )
    first_manifest = sdist_content_manifest(first)
    second_manifest = sdist_content_manifest(second)
    differing = sorted(
        path
        for path in set(first_manifest) | set(second_manifest)
        if first_manifest.get(path) != second_manifest.get(path)
    )
    return Check(
        "sdist_content_reproducibility",
        not differing,
        {
            "first_sha256": sha256_file(first),
            "second_sha256": sha256_file(second),
            "content_file_count": len(first_manifest),
            "differing_files": differing,
        },
    )


def decision_reproducibility(first: Path, second: Path) -> Check:
    def read(path: Path) -> str | None:
        manifest = path / "provenance/artifact_manifest.json"
        if not manifest.exists():
            return None
        return json.loads(manifest.read_text(encoding="utf-8")).get("decision_fingerprint")

    first_fingerprint = read(first)
    second_fingerprint = read(second)
    return Check(
        "decision_fingerprint_reproducibility",
        first_fingerprint is not None and first_fingerprint == second_fingerprint,
        {"first": first_fingerprint, "second": second_fingerprint},
    )


def api_runtime_smoke(report_path: Path) -> Check:
    if not report_path.is_file():
        return Check("api_runtime_smoke", False, {"missing_report": str(report_path)})
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return Check(
            "api_runtime_smoke",
            False,
            {"invalid_report": f"{type(exc).__name__}: {exc}"},
        )
    expected = {
        "passed": True,
        "graceful_shutdown": True,
        "health_status": 200,
        "run_statuses": [200, 409],
        "latest_status": 200,
    }
    mismatches = {
        key: {"expected": value, "actual": report.get(key)}
        for key, value in expected.items()
        if report.get(key) != value
    }
    return Check(
        "api_runtime_smoke",
        not mismatches,
        {
            "report": str(report_path),
            "mismatches": mismatches,
            "workers": report.get("workers"),
            "latest_elapsed_ms": report.get("latest_elapsed_ms"),
            "elapsed_seconds": report.get("elapsed_seconds"),
        },
    )


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Full Pipeline Validation Report",
        "",
        f"**Overall:** {'PASS' if payload['passed'] else 'FAIL'}",
        "",
        "## Checks",
        "",
    ]
    for check in payload["checks"]:
        lines.append(f"- **{check['name']}**: {'PASS' if check['passed'] else 'FAIL'}")
        if check["details"]:
            lines.append(f"  - `{json.dumps(check['details'], sort_keys=True)}`")
    for label, metrics in payload.get("metrics", {}).items():
        if not metrics:
            continue
        lines.extend(
            [
                "",
                f"## {label} frozen metrics",
                "",
                "```json",
                json.dumps(
                    {
                        "release": metrics.get("release"),
                        "rows": metrics.get("rows"),
                        "forecast_champion": metrics.get("forecast_champion"),
                        "capacity": metrics.get("capacity"),
                        "optimizer": metrics.get("optimizer"),
                        "policy_selection": metrics.get("policy_selection"),
                        "sql_validation": metrics.get("sql_validation"),
                    },
                    indent=2,
                ),
                "```",
            ]
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify completed validation artifacts")
    parser.add_argument("--smoke-output", default="outputs/validation_smoke")
    parser.add_argument("--full-output", default="outputs/validation_full")
    parser.add_argument("--wheel", required=True)
    parser.add_argument("--wheel-repeat")
    parser.add_argument("--sdist")
    parser.add_argument("--sdist-repeat")
    parser.add_argument("--wheel-smoke-output", required=True)
    parser.add_argument("--sdist-smoke-output")
    parser.add_argument("--repeat-smoke-output")
    parser.add_argument("--api-smoke-report")
    parser.add_argument("--report-dir", default="reports")
    args = parser.parse_args()

    checks: list[Check] = []
    metrics: dict[str, dict] = {}
    smoke_check, metrics["smoke"] = artifact_integrity(
        Path(args.smoke_output), max_runtime_seconds=60.0
    )
    full_check, metrics["full"] = artifact_integrity(
        Path(args.full_output), max_runtime_seconds=120.0
    )
    wheel_smoke_check, metrics["wheel_smoke"] = artifact_integrity(
        Path(args.wheel_smoke_output), max_runtime_seconds=60.0
    )
    checks.extend([smoke_check, full_check, wheel_integrity(Path(args.wheel)), wheel_smoke_check])
    if args.repeat_smoke_output:
        repeat_check, metrics["repeat_smoke"] = artifact_integrity(
            Path(args.repeat_smoke_output), max_runtime_seconds=60.0
        )
        checks.extend(
            [
                repeat_check,
                decision_reproducibility(Path(args.smoke_output), Path(args.repeat_smoke_output)),
            ]
        )
    if args.wheel_repeat:
        checks.append(wheel_reproducibility(Path(args.wheel), Path(args.wheel_repeat)))
    if args.sdist:
        checks.append(sdist_integrity(Path(args.sdist)))
    if args.sdist and args.sdist_repeat:
        checks.append(sdist_reproducibility(Path(args.sdist), Path(args.sdist_repeat)))
    if args.sdist_smoke_output:
        sdist_smoke_check, metrics["sdist_smoke"] = artifact_integrity(
            Path(args.sdist_smoke_output), max_runtime_seconds=60.0
        )
        checks.append(sdist_smoke_check)
    if args.api_smoke_report:
        checks.append(api_runtime_smoke(Path(args.api_smoke_report)))
    passed = all(check.passed for check in checks)
    payload = {
        "passed": passed,
        "checks": [asdict(check) for check in checks],
        "metrics": metrics,
    }
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "full_pipeline_validation_summary.json").write_text(
        json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8"
    )
    (report_dir / "full_pipeline_validation_report.md").write_text(
        render_report(payload), encoding="utf-8"
    )
    print(json.dumps({"passed": passed, "checks": [asdict(check) for check in checks]}, indent=2))
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
