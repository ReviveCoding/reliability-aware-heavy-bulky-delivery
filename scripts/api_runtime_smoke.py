from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _request(
    url: str, *, method: str = "GET", payload: dict | None = None, timeout: float = 10
) -> tuple[int, dict]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {} if data is None else {"Content-Type": "application/json"}
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
            return int(response.status), body
    except urllib.error.HTTPError as exc:
        body = json.loads(exc.read().decode("utf-8"))
        return int(exc.code), body


def _wait_ready(base_url: str, timeout_seconds: float) -> dict:
    deadline = time.monotonic() + timeout_seconds
    last_error = "server did not start"
    while time.monotonic() < deadline:
        try:
            status, body = _request(f"{base_url}/ready", timeout=2)
            if status == 200:
                return body
            last_error = f"ready returned {status}: {body}"
        except Exception as exc:  # startup connection errors are expected during polling
            last_error = f"{type(exc).__name__}: {exc}"
        time.sleep(0.2)
    raise RuntimeError(last_error)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a real multi-worker Uvicorn API smoke test")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--startup-timeout", type=float, default=30.0)
    args = parser.parse_args()

    output_root = Path(args.output_root).resolve()
    report_path = Path(args.report).resolve()
    shutil.rmtree(output_root, ignore_errors=True)
    output_root.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    log_path = report_path.with_suffix(".server.log")
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env["HEAVY_BULKY_OUTPUT_ROOT"] = str(output_root)
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "heavy_bulky.api:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--workers",
        str(args.workers),
        "--log-level",
        "warning",
    ]
    popen_kwargs: dict = {
        "env": env,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True
    process = subprocess.Popen(command, **popen_kwargs)
    started = time.perf_counter()
    report: dict[str, object] = {
        "command": ["python", *command[1:]],
        "workers": args.workers,
        "port": port,
    }
    failure: Exception | None = None
    functional_passed = False
    try:
        ready = _wait_ready(base_url, args.startup_timeout)
        health_status, health = _request(f"{base_url}/health")
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    _request,
                    f"{base_url}/run",
                    method="POST",
                    payload={"mode": "smoke"},
                    timeout=180,
                )
                for _ in range(2)
            ]
            run_results = [future.result() for future in futures]
        latest_started = time.perf_counter()
        latest_status, latest = _request(f"{base_url}/latest/smoke", timeout=30)
        latest_elapsed_ms = (time.perf_counter() - latest_started) * 1000.0
        statuses = sorted(status for status, _ in run_results)
        functional_passed = (
            ready.get("status") == "ready"
            and health_status == 200
            and health.get("status") == "ok"
            and statuses == [200, 409]
            and latest_status == 200
            and latest.get("release", {}).get("decision") in {"PROMOTE", "ITERATE"}
        )
        response_summaries = []
        for status, body in run_results:
            response_summaries.append(
                {
                    "status": status,
                    "release": body.get("release", {}).get("decision")
                    if isinstance(body, dict)
                    else None,
                    "detail": (
                        "publication_conflict"
                        if status == 409
                        else body.get("detail")
                        if isinstance(body, dict)
                        else None
                    ),
                }
            )
        report.update(
            {
                "ready": ready,
                "health_status": health_status,
                "run_statuses": statuses,
                "run_responses": response_summaries,
                "latest_status": latest_status,
                "latest_release": latest.get("release", {}).get("decision"),
                "latest_elapsed_ms": round(latest_elapsed_ms, 3),
                "elapsed_seconds": round(time.perf_counter() - started, 6),
            }
        )
        if not functional_passed:
            failure = RuntimeError(f"API runtime smoke failed: {report}")
    except Exception as exc:
        failure = exc
        report["exception"] = f"{type(exc).__name__}: {exc}"
    finally:
        process.terminate()
        try:
            stdout, _ = process.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, _ = process.communicate(timeout=5)
        graceful_shutdown = process.returncode == 0
        report.update(
            {
                "server_returncode": process.returncode,
                "graceful_shutdown": graceful_shutdown,
                "passed": functional_passed and graceful_shutdown and failure is None,
            }
        )
        log_path.write_text(stdout or "", encoding="utf-8")
        report_path.write_text(
            json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
    if failure is not None:
        raise failure
    if not report["passed"]:
        raise RuntimeError(f"API runtime smoke did not shut down cleanly: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
