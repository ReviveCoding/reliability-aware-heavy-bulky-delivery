from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys

import pandas as pd

from heavy_bulky import __version__
from heavy_bulky.integrity import decision_fingerprint, verify_artifact_manifest


def test_end_to_end_pipeline_artifacts_and_release(pipeline_run):
    output, metrics = pipeline_run
    assert metrics["plan_validation"]["hard_constraint_violations"] == 0
    assert metrics["optimizer"]["unserved_orders"] == 0
    assert metrics["release"]["decision"] in {"PROMOTE", "ITERATE"}
    required = [
        "_SUCCESS",
        "metrics/summary.json",
        "reports/full_pipeline_report.md",
        "provenance/resolved_config.yaml",
        "provenance/run_manifest.json",
        "provenance/artifact_manifest.json",
        "contracts/data_contract.json",
        "contracts/forecast_contract.json",
        "contracts/route_contract.json",
        "planning/champion_routes.csv",
        "analytics/01_daily_station_service_demand.csv",
    ]
    for relative in required:
        assert (output / relative).exists(), relative


def test_pipeline_manifest_and_summary_are_consistent(pipeline_run):
    output, metrics = pipeline_run
    summary = json.loads((output / "metrics/summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((output / "provenance/run_manifest.json").read_text(encoding="utf-8"))
    assert summary["release"]["decision"] == metrics["release"]["decision"]
    assert manifest["package_version"] == __version__
    assert manifest["config_sha256"]
    assert manifest["seed"] == 20260616
    assert manifest["status"] == "complete"
    assert manifest["completed_at_utc"]
    assert manifest["release_decision"] == summary["release"]["decision"]
    expected_hash = hashlib.sha256((output / "metrics/summary.json").read_bytes()).hexdigest()
    assert manifest["summary_sha256"] == expected_hash
    assert manifest["decision_fingerprint"] == decision_fingerprint(output)
    assert verify_artifact_manifest(output) == []


def test_pipeline_planning_tables_have_no_outcome_leakage(pipeline_run):
    output, _ = pipeline_run
    decision = pd.read_csv(output / "service/planning_decision_features.csv")
    routes = pd.read_csv(output / "routing/route_candidates.csv")
    forbidden = {"actual_duration", "failed_attempt", "failure_probability_true"}
    assert forbidden.isdisjoint(decision.columns)
    assert forbidden.isdisjoint(routes.columns)


def test_pipeline_stage_lifecycles_are_complete(pipeline_run):
    output, _ = pipeline_run
    timings = json.loads((output / "provenance/stage_timings.json").read_text(encoding="utf-8"))
    assert timings
    assert all(row["status"] == "complete" for row in timings)
    assert timings[-1]["stage"] == "reporting"
    solver_stages = {
        row["stage"]: row
        for row in timings
        if row["stage"] in {"risk_aware_solve", "deterministic_solve", "label_informed_diagnostic"}
    }
    assert set(solver_stages) == {
        "risk_aware_solve",
        "deterministic_solve",
        "label_informed_diagnostic",
    }
    assert all(row["duration_seconds"] is not None for row in solver_stages.values())


def test_artifact_manifest_detects_tampering(pipeline_run, tmp_path):
    output, _ = pipeline_run
    copied = tmp_path / "tampered"
    shutil.copytree(output, copied)
    target = copied / "planning/champion_routes.csv"
    target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    problems = verify_artifact_manifest(copied)
    assert any("artifact_" in problem for problem in problems)


def test_cli_verify_output_accepts_valid_and_rejects_tampered(pipeline_run, tmp_path):
    output, _ = pipeline_run
    valid = subprocess.run(
        [sys.executable, "-m", "heavy_bulky.cli", "verify-output", "--output-dir", str(output)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert valid.returncode == 0, valid.stderr
    assert json.loads(valid.stdout)["valid"] is True

    copied = tmp_path / "tampered_cli"
    shutil.copytree(output, copied)
    (copied / "metrics/summary.json").write_text("{}", encoding="utf-8")
    invalid = subprocess.run(
        [sys.executable, "-m", "heavy_bulky.cli", "verify-output", "--output-dir", str(copied)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert invalid.returncode == 1
    assert json.loads(invalid.stdout)["valid"] is False

def test_decision_value_separates_lowest_cost_candidate_from_selected_champion() -> None:
    from heavy_bulky.pipeline import _decision_value_summary

    simulation_metrics = {
        "greedy": {"expected_cost": 100.0},
        "deterministic": {"expected_cost": 99.0},
        "risk_aware": {"expected_cost": 101.0},
        "label_informed_proxy": {"expected_cost": 98.0},
    }

    decision_value = _decision_value_summary(
        simulation_metrics,
        champion_name="greedy",
    )

    assert (
        decision_value["lowest_expected_cost_evaluated_candidate"]
        == "deterministic"
    )
    assert decision_value["selected_champion_policy"] == "greedy"
    assert decision_value["selected_champion_expected_cost"] == 100.0
    assert (
        decision_value[
            "risk_aware_regret_vs_lowest_expected_cost_evaluated_candidate"
        ]
        == 2.0
    )
    assert "does not override" in decision_value["note"]
