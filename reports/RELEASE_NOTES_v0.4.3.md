# Release Notes v0.4.3

Version 0.4.3 is an API integrity, concurrent-publication, lock-recovery, and runtime-validation hardening release on top of v0.4.2.

## Fixed

- `/latest/{mode}` no longer serves a summary merely because the JSON file exists; it now requires a valid success marker, complete run manifest, matching summary hash, valid artifact manifest, no untracked files, and a matching decision fingerprint.
- Concurrent API publication now maps the losing writer to HTTP 409 instead of an opaque HTTP 500.
- Added `/ready` to verify packaged configs and output-root writeability separately from `/health` liveness.
- Added `verify-output` CLI with exit code 0 for valid published runs and 1 for incomplete or tampered outputs.
- Added recovery for sufficiently aged empty or malformed lock files left during the exclusive-create/write crash window.
- Lock cleanup now removes only a lock bearing the publisher's own unique token.
- Publication-lock metadata is fsynced before pipeline work begins.
- Set serialization is deterministic in JSON artifacts.
- Replaced deprecated Starlette TestClient use through `httpx` with the officially recommended `httpx2` test dependency.

## Runtime validation

- Added a real two-worker Uvicorn smoke test.
- Two concurrent `/run` requests yielded exactly one HTTP 200 and one HTTP 409.
- The completed run was served through integrity-checked `/latest`.
- The server shut down gracefully.
- The API runtime report is included in full validation and GitHub artifact upload.

## Frozen validation

- 66 tests passed with 74.47% coverage.
- Source smoke, repeated smoke, source full, wheel smoke, sdist smoke, and M5-pattern runs returned PROMOTE with zero unserved orders and zero hard-constraint violations.
- CP-SAT ran without fallback in source, wheel, sdist, and M5 paths.
- Wheel bitwise reproducibility and sdist content reproducibility passed.
- Python 3.11 direct-wheel availability remained 18/18 for Linux x86-64 and Windows x64.

## Claim boundary

This remains a locally validated, semi-synthetic, production-style benchmark. Remote GitHub-hosted execution, Docker daemon execution, CUDA, Chronos-2, full Amazon public-route calibration, actual planner adoption, and production AMXL impact remain unclaimed.
