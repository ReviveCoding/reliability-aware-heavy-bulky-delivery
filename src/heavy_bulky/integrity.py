from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from . import __version__

ARTIFACT_MANIFEST = Path("provenance/artifact_manifest.json")
_IGNORED_OUTPUT_PATHS = {ARTIFACT_MANIFEST.as_posix(), "_SUCCESS"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_scalar(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, float):
        return round(value, 10)
    if hasattr(value, "item"):
        return _json_scalar(value.item())
    return value


def _stable_csv_records(path: Path, sort_by: list[str]) -> list[dict[str, Any]]:
    frame = pd.read_csv(path)
    usable_sort = [column for column in sort_by if column in frame.columns]
    if usable_sort:
        frame = frame.sort_values(usable_sort, kind="mergesort")
    frame = frame.reindex(sorted(frame.columns), axis=1)
    return [
        {column: _json_scalar(value) for column, value in row.items()}
        for row in frame.to_dict(orient="records")
    ]


def decision_fingerprint(output: Path) -> str:
    """Hash only stable decision artifacts, excluding runtimes and timestamps."""
    summary = json.loads((output / "metrics/summary.json").read_text(encoding="utf-8"))
    payload = {
        "release_decision": summary["release"]["decision"],
        "policy_champion": summary["policy_selection"]["champion"],
        "unserved_orders": int(summary["optimizer"]["unserved_orders"]),
        "forecast": _stable_csv_records(
            output / "forecast/operational_forecast.csv", ["station_id", "service_type"]
        ),
        "capacity": _stable_csv_records(
            output / "capacity/capacity_plan.csv", ["station_id", "service_type"]
        ),
        "champion_routes": _stable_csv_records(
            output / "planning/champion_routes.csv", ["station_id", "route_id"]
        ),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def build_artifact_manifest(output: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for path in sorted(candidate for candidate in output.rglob("*") if candidate.is_file()):
        relative = path.relative_to(output).as_posix()
        if relative in _IGNORED_OUTPUT_PATHS or ".tmp" in path.name:
            continue
        files.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return {
        "schema_version": 1,
        "package_version": __version__,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "decision_fingerprint": decision_fingerprint(output),
        "file_count": len(files),
        "files": files,
    }


def verify_artifact_manifest(output: Path) -> list[str]:
    path = output / ARTIFACT_MANIFEST
    if not path.exists():
        return ["missing_artifact_manifest"]
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"invalid_artifact_manifest:{type(exc).__name__}"]

    problems: list[str] = []
    if manifest.get("package_version") != __version__:
        problems.append(f"artifact_manifest_version:{manifest.get('package_version')}")
    entries = manifest.get("files")
    if not isinstance(entries, list):
        return [*problems, "artifact_manifest_files_not_list"]

    expected_paths: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            problems.append("artifact_manifest_invalid_entry")
            continue
        relative = entry["path"]
        expected_paths.add(relative)
        candidate = output / relative
        if not candidate.is_file():
            problems.append(f"artifact_missing:{relative}")
            continue
        if int(entry.get("bytes", -1)) != candidate.stat().st_size:
            problems.append(f"artifact_size_mismatch:{relative}")
        if entry.get("sha256") != sha256_file(candidate):
            problems.append(f"artifact_hash_mismatch:{relative}")

    actual_paths = {
        candidate.relative_to(output).as_posix()
        for candidate in output.rglob("*")
        if candidate.is_file()
        and candidate.relative_to(output).as_posix() not in _IGNORED_OUTPUT_PATHS
        and ".tmp" not in candidate.name
    }
    extras = sorted(actual_paths - expected_paths)
    if extras:
        problems.append(f"artifact_untracked:{extras}")
    if int(manifest.get("file_count", -1)) != len(entries):
        problems.append("artifact_manifest_file_count_mismatch")
    try:
        fingerprint = decision_fingerprint(output)
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        problems.append(f"decision_fingerprint_error:{type(exc).__name__}")
    else:
        if manifest.get("decision_fingerprint") != fingerprint:
            problems.append("decision_fingerprint_mismatch")
    return problems


def validate_published_run(output: Path, *, verify_all_artifacts: bool = True) -> list[str]:
    """Validate that a published run is complete, internally consistent, and untampered."""
    problems: list[str] = []
    success = output / "_SUCCESS"
    if not success.is_file():
        problems.append("missing_success_marker")
    else:
        try:
            if success.read_text(encoding="utf-8").strip() != "complete":
                problems.append("invalid_success_marker")
        except OSError as exc:
            problems.append(f"success_marker_error:{type(exc).__name__}")

    summary_path = output / "metrics/summary.json"
    run_manifest_path = output / "provenance/run_manifest.json"
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        problems.append(f"invalid_summary:{type(exc).__name__}")
        summary = {}
    try:
        run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        problems.append(f"invalid_run_manifest:{type(exc).__name__}")
        run_manifest = {}

    if run_manifest:
        if run_manifest.get("package_version") != __version__:
            problems.append(f"run_manifest_version:{run_manifest.get('package_version')}")
        if run_manifest.get("status") != "complete":
            problems.append(f"run_manifest_status:{run_manifest.get('status')}")
        if not run_manifest.get("completed_at_utc"):
            problems.append("missing_completed_at")
        if summary and run_manifest.get("release_decision") != summary.get("release", {}).get(
            "decision"
        ):
            problems.append("release_decision_mismatch")
        if summary_path.is_file():
            expected_hash = run_manifest.get("summary_sha256")
            if not expected_hash:
                problems.append("missing_summary_hash")
            elif expected_hash != sha256_file(summary_path):
                problems.append("summary_hash_mismatch")

    if verify_all_artifacts:
        problems.extend(verify_artifact_manifest(output))
    return sorted(set(problems))
