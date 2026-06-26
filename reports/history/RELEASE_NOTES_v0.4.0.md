# Release Notes v0.4.0

## Summary

Version 0.4.0 converts the original runnable prototype into a correctness-first, release-gated planning benchmark. The core architecture remains forecast-to-service-to-route-to-plan-to-replay, but leakage, decision validity, solver lifecycle, simulation scaling, artifact publication, packaging, and cross-platform execution were substantially hardened.

## Major correctness fixes

- Removed post-outcome failed-attempt labels from route and planning features.
- Added a leakage-safe failure-risk model and planning-time feature view.
- Connected p90 demand forecasts to vehicle and crew rosters.
- Reconciled forecast-driven resources with route-pool minimum requirements.
- Separated operational capacity shortages from optional reserve shortages.
- Expanded plan validation to duplicate, coverage, resource reuse, station, capacity, skill, crew-size, and shift constraints.
- Replaced policy-specific random draws with one policy-independent scenario bank.
- Replaced unsupported oracle and EVPI claims with deployable-policy regret and an explicitly diagnostic label-informed proxy.
- Compared classical and multi-task service models on the same temporal validation window.

## Solver and runtime hardening

- Added a verified greedy incumbent before any CP-SAT call.
- Decomposed CP-SAT by station because route and resource decisions are station-local.
- Isolated native solver execution in an OS subprocess.
- Added native time limits and an external hard timeout.
- Preserved a feasible plan on timeout, import failure, or solver error.
- Recorded status, objective, conservative bound, relative gap, runtime, fallback, and unserved orders.
- Required solver-quality and decision-value evidence before challenger promotion.
- Vectorized operational replay, reducing the full run from an external timeout beyond 600 seconds to roughly 15 seconds in the frozen validation environment.

## Artifact and operations hardening

- Strict nested configuration with unknown-field rejection.
- Explicit failure for missing public-data files instead of silent fallback.
- Atomic JSON and CSV writes.
- Staging-directory execution followed by atomic publication.
- Concurrent-run locking, dead-PID recovery, and orphan-staging cleanup.
- Complete stage lifecycle timings, including solver durations.
- Packaged YAML and SQL resources in the wheel.
- Source, full, isolated-wheel, Linux, and Windows workflow paths.
- Non-root Docker image and writable bind-mount smoke command.
- Current GitHub action majors, job timeouts, concurrency cancellation, and required artifact upload.

## Frozen decisions

- LightGBM quantile forecasting remains the core forecast champion.
- Greedy feasible planning remains the deployable policy champion in the frozen smoke, full, and M5-pattern runs.
- CP-SAT challengers are retained as evaluated alternatives but are held when cost evidence or solver-gap gates fail.
- The PyTorch multi-task service challenger is held because it did not beat the classical duration and failure-risk baselines.

## Known external validation gaps

- The remote GitHub Actions workflow was not executed from this environment.
- A Docker daemon was unavailable, so the image definition and CI command were statically checked but not locally built.
- CUDA was unavailable; the advanced model was verified on CPU only.
- Chronos-2 model download and inference were not executed.
- Full Amazon public route-data calibration was not executed or redistributed.
