# Strength, Weakness, and Reinforcement Loop Summary

## Earlier loops retained

- Removed post-outcome leakage and connected probabilistic forecasts to vehicle/crew capacity.
- Added exact route partitions and complete resource, skill, shift, coverage, weight, cube, and station validation.
- Isolated CP-SAT in a bounded subprocess and validated returned plans before promotion.
- Replaced policy-specific randomness with a common scenario bank and paired bootstrap comparison.
- Added atomic staged publication, artifact manifests, stable decision fingerprints, wheel/sdist validation, and source-checkout solver imports.

## v0.4.3 loop 1 — fail-closed result serving

**Weakness:** `/latest` returned HTTP 200 for a directory containing only a summary JSON, and could serve a tampered output.

**Fix:** centralized `validate_published_run` verifies success marker, run manifest, release decision, summary hash, artifact hashes, untracked files, and decision fingerprint. CLI and API share the same contract.

**Validation:** incomplete and tampered API outputs return HTTP 503; valid outputs return 200; CLI returns exit code 0 or 1 accordingly.

## v0.4.3 loop 2 — publication-lock crash recovery

**Weakness:** an empty or malformed lock left between exclusive creation and metadata write required manual deletion. A publisher also unlinked the lock path without checking whether its token still owned it.

**Fix:** fsync lock metadata, recover dead owners, recover malformed locks only after a grace period, and remove a lock only when its unique token matches.

**Validation:** fresh malformed locks remain conservative, aged malformed locks recover, live locks reject concurrent writers, and foreign-token locks survive another publisher's cleanup.

## v0.4.3 loop 3 — real API concurrency

**Weakness:** TestClient validation did not prove Uvicorn worker behavior, HTTP conflict mapping, readiness, or graceful process shutdown.

**Fix:** added a real two-worker Uvicorn smoke using network requests and simultaneous pipeline submissions.

**Validation:** statuses `[200, 409]`, readiness 200, health 200, latest 200 after integrity validation, and graceful shutdown.

## v0.4.3 loop 4 — current ASGI test dependency

**Weakness:** Starlette emitted a deprecation warning for plain `httpx` TestClient support.

**Fix:** migrated the test dependency and exact constraint to `httpx2`.

**Validation:** 64-test suite and clean dependency check pass without the prior Starlette deprecation warning; Python 3.11 Linux and Windows wheels are available.

## Structural optimization

- The final release keeps one distribution set; repeated build artifacts and duplicate API-smoke output directories are removed after evidence is frozen.
- Generated caches, build trees, egg-info, temporary files, and stale locks are excluded.
- CLI/API integrity logic is centralized rather than duplicated.
- Runtime API evidence stores only response summaries instead of the complete pipeline response body.

## Stop criterion

No unresolved high-value defect remains in model correctness, forecast-to-plan connectivity, solver isolation, publication safety, artifact integrity, API concurrency, distribution installation, or deterministic replay. Remaining items require external infrastructure or are optional research extensions.
