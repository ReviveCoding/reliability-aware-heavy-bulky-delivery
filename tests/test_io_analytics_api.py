from __future__ import annotations

import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from heavy_bulky import api
from heavy_bulky.analytics import run_sql_marts
from heavy_bulky.io import json_safe, staged_run_directory, write_csv, write_json


def test_json_safe_and_atomic_writes(tmp_path):
    assert json_safe({"x": np.nan, "y": np.int64(2)}) == {"x": None, "y": 2}
    target = tmp_path / "nested" / "value.json"
    write_json(target, {"x": np.nan})
    assert json.loads(target.read_text()) == {"x": None}
    csv_path = tmp_path / "table.csv"
    write_csv(csv_path, pd.DataFrame({"a": [1, 2]}))
    assert pd.read_csv(csv_path)["a"].tolist() == [1, 2]
    assert not list(tmp_path.rglob("*.tmp"))


def test_staged_publication_is_atomic_and_preserves_previous_on_failure(tmp_path):
    final = tmp_path / "published"
    with staged_run_directory(final) as stage:
        (stage / "value.txt").write_text("v1", encoding="utf-8")
    assert (final / "_SUCCESS").exists()
    assert (final / "value.txt").read_text() == "v1"
    with pytest.raises(RuntimeError), staged_run_directory(final) as stage:
        (stage / "value.txt").write_text("broken", encoding="utf-8")
        raise RuntimeError("fail")
    assert (final / "value.txt").read_text() == "v1"


def test_concurrent_lock_and_stale_lock_recovery(tmp_path):
    final = tmp_path / "published"
    lock = tmp_path / ".published.lock"
    lock.write_text(f"pid={os.getpid()} token=live\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="already publishing"), staged_run_directory(final):
        pass
    lock.write_text("pid=99999999 token=dead\n", encoding="utf-8")
    with staged_run_directory(final) as stage:
        (stage / "ok").write_text("yes", encoding="utf-8")
    assert (final / "ok").exists()


def test_sql_marts_are_executed(pipeline_run, tmp_path):
    output, _ = pipeline_run
    import shutil

    isolated = tmp_path / "pipeline_copy"
    shutil.copytree(output, isolated)
    result = run_sql_marts(isolated, Path(__file__).resolve().parents[1] / "sql")
    assert result["available"] is True
    assert result["passed"] is True
    assert result["mart_count"] == 3


def test_api_health_and_latest(pipeline_run, monkeypatch):
    output, metrics = pipeline_run
    root = output.parents[1]
    monkeypatch.setattr(api, "OUTPUT_ROOT", root)
    expected = root / "outputs" / "smoke"
    expected.parent.mkdir(parents=True, exist_ok=True)
    if expected.exists():
        import shutil

        shutil.rmtree(expected)
    import shutil

    shutil.copytree(output, expected)
    with TestClient(api.app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["version"] == "0.4.3"
        latest = client.get("/latest/smoke")
        assert latest.status_code == 200
        assert latest.json()["release"]["decision"] == metrics["release"]["decision"]
        assert client.get("/latest/full").status_code == 404


def test_sql_marts_fail_closed_when_sql_directory_is_empty(pipeline_run, tmp_path):
    output, _ = pipeline_run
    result = run_sql_marts(output, tmp_path / "empty_sql")
    assert result["available"] is True
    assert result["passed"] is False
    assert result["reason"] == "no_sql_marts_found"


def test_api_run_uses_packaged_config_and_configured_output(monkeypatch, tmp_path):
    captured = {}

    def fake_run_pipeline(config_path, output_dir_override=None):
        captured["config_path"] = Path(config_path)
        captured["output_dir"] = Path(output_dir_override)
        return {"release": {"decision": "PROMOTE"}}

    monkeypatch.setattr(api, "OUTPUT_ROOT", tmp_path)
    monkeypatch.setattr(api, "run_pipeline", fake_run_pipeline)
    with TestClient(api.app) as client:
        response = client.post("/run", json={"mode": "smoke"})
    assert response.status_code == 200
    assert captured["config_path"].name == "smoke.yaml"
    assert captured["output_dir"] == tmp_path / "outputs" / "smoke"


def test_json_safe_sorts_sets_deterministically():
    assert json_safe({"values": {"z", "a", "m"}}) == {"values": ["a", "m", "z"]}


def test_aged_unparseable_lock_recovers_but_fresh_lock_is_conservative(tmp_path):
    final = tmp_path / "published"
    lock = tmp_path / ".published.lock"
    lock.write_text("", encoding="utf-8")
    with pytest.raises(RuntimeError, match="already publishing"), staged_run_directory(final):
        pass
    old = time.time() - 3600
    os.utime(lock, (old, old))
    with staged_run_directory(final) as stage:
        (stage / "recovered.txt").write_text("yes", encoding="utf-8")
    assert (final / "recovered.txt").read_text(encoding="utf-8") == "yes"


def test_lock_cleanup_does_not_delete_foreign_token(tmp_path):
    final = tmp_path / "published"
    lock = tmp_path / ".published.lock"
    with staged_run_directory(final) as stage:
        (stage / "value.txt").write_text("complete", encoding="utf-8")
        lock.write_text("pid=99999999 token=foreign\n", encoding="utf-8")
    assert lock.read_text(encoding="utf-8") == "pid=99999999 token=foreign\n"


def test_api_readiness_and_latest_fail_closed(monkeypatch, pipeline_run, tmp_path):
    output, _ = pipeline_run
    monkeypatch.setattr(api, "OUTPUT_ROOT", tmp_path)
    published = tmp_path / "outputs" / "smoke"
    import shutil

    shutil.copytree(output, published)
    with TestClient(api.app) as client:
        ready = client.get("/ready")
        assert ready.status_code == 200
        assert ready.json()["status"] == "ready"
        assert client.get("/latest/smoke").status_code == 200
        (published / "planning/champion_routes.csv").write_text("tampered\n", encoding="utf-8")
        broken = client.get("/latest/smoke")
        assert broken.status_code == 503
        assert broken.json()["detail"]["message"] == "run integrity failure"


def test_api_latest_rejects_incomplete_run(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "OUTPUT_ROOT", tmp_path)
    incomplete = tmp_path / "outputs" / "smoke" / "metrics"
    incomplete.mkdir(parents=True)
    (incomplete / "summary.json").write_text(
        json.dumps({"release": {"decision": "PROMOTE"}}), encoding="utf-8"
    )
    with TestClient(api.app) as client:
        response = client.get("/latest/smoke")
    assert response.status_code == 503
    assert "missing_success_marker" in response.json()["detail"]["problems"]


def test_api_maps_concurrent_publication_to_conflict(monkeypatch, tmp_path):
    def conflict(*args, **kwargs):
        raise RuntimeError(f"Another run is already publishing to {tmp_path}")

    monkeypatch.setattr(api, "OUTPUT_ROOT", tmp_path)
    monkeypatch.setattr(api, "run_pipeline", conflict)
    with TestClient(api.app) as client:
        response = client.post("/run", json={"mode": "smoke"})
    assert response.status_code == 409
    assert "already publishing" in response.json()["detail"]
