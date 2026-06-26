# Release Qualification Report — v0.4.3-qualified-final

## Verdict

**CONDITIONALLY QUALIFIED**. Local Linux/Python 3.13 CPU gates passed, including clean install, dependency validation, lint/format, compile, 66-test suite twice, smoke E2E three times, full E2E, M5-pattern validation, API two-worker concurrency, wheel clean install smoke, and sdist clean install smoke. GitHub-hosted Actions, Windows hosted runner, Docker daemon, GPU/CUDA, and Chronos optional path were not executed.

## Fixed issue

- Added global `heavy-bulky --version` support in `src/heavy_bulky/cli.py`.
- Added `tests/test_cli.py::test_cli_version_flag` regression coverage.

## Key local results

- Tests: 66 passed, 0 failed, two consecutive full-suite passes.
- Coverage: 74.47%.
- Smoke E2E: 3/3 PASS, release PROMOTE.
- Full E2E: release PROMOTE, rows {'demand': 3537, 'historical_orders': 14141, 'planning_orders': 206, 'route_candidates': 404}.
- API 2-worker: passed=True, statuses=[200, 409], latest latency=20.753 ms.
- Wheel/sdist built artifacts: clean install smoke PASS outside source tree.

## Conditional items

The project remains conditional only because Q4/hosted and hardware/container gates were not available in this environment. No unverified path is claimed as passed.

## Final-loop blocker fixed

A final re-audit found that the distribution smoke path installed wheel/sdist artifacts with `--no-deps`, which could allow base-only installed artifacts to run without LightGBM, OR-Tools, DuckDB, FastAPI, and Uvicorn in a truly clean environment. The Bash and PowerShell validation runners now install `${WHEEL}[full]` and `${SDIST}[full]` / `$Wheel.FullName + "[full]"` and `$Sdist.FullName + "[full]"`, and `tests/test_config_assets.py::test_distribution_smoke_installs_full_runtime_extras` prevents regression.

Targeted post-fix evidence:

- Source smoke: PROMOTE, LightGBM quantile forecast, SQL validation PASS.
- Wheel package smoke with built package first on `PYTHONPATH`: PROMOTE, LightGBM quantile forecast, SQL validation PASS.
- Sdist package smoke with built package first on `PYTHONPATH`: PROMOTE, LightGBM quantile forecast, SQL validation PASS.
- Full regression suite after this patch: 66 passed, coverage 74.47%.
