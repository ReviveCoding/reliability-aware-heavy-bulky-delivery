# Runbook

## Supported Python

Python 3.11 through 3.13. Exact direct and validation versions are recorded in `constraints-verified.txt`.

## Linux, macOS, WSL, or Git Bash

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install --constraint constraints-verified.txt -e ".[full,dev]"
make validate
```

## Windows PowerShell

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install --constraint constraints-verified.txt -e ".[full,dev]"
.\scripts\run_full_validation.ps1 -Python python
```

## Fast paths

```bash
make capabilities
make smoke
make full
make test
make advanced-check
```

## Verify an existing output

```bash
python -m heavy_bulky.cli verify-output --output-dir outputs/validation_smoke
```

Exit code 0 means the success marker, run manifest, summary hash, artifact manifest, all tracked files, and decision fingerprint are consistent. Exit code 1 means the output must not be served or promoted.

## API

```bash
export HEAVY_BULKY_OUTPUT_ROOT=outputs/api
uvicorn heavy_bulky.api:app --host 0.0.0.0 --port 8000 --workers 2
```

- `/health` checks process liveness.
- `/ready` checks packaged configs and output-root writeability.
- concurrent `/run` publication to the same mode returns HTTP 409 for the losing request.
- `/latest/{mode}` refuses incomplete or tampered outputs with HTTP 503.

A real two-worker concurrency smoke is included in `make validate` through `scripts/api_runtime_smoke.py`.

## Failure handling

- Invalid configuration fails before publication.
- Missing explicitly requested public data fails rather than silently substituting synthetic data.
- Solver timeout, import failure, corrupt payload, or invalid returned plan falls back to the validated greedy incumbent.
- An active publication lock rejects a second writer.
- A lock owned by a dead PID is recovered.
- An unparseable lock is recovered only after the configured grace period.
- A publisher removes only the lock bearing its own unique token.
- A failed run remains in staging and does not replace the last successful output.
- CLI and API readers fail closed on missing success markers, invalid manifests, summary-hash mismatches, untracked files, or artifact tampering.

## External validation boundary

Remote GitHub-hosted Actions, Docker daemon execution, CUDA execution, Chronos-2 inference, and full Amazon public-route calibration require their respective external environments and remain separately stated.
