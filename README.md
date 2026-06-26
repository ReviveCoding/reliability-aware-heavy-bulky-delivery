# Reliability-Aware Heavy-Bulky Delivery Planning and Operational Replay Benchmark

A reproducible Applied Science and Operations Research project connecting day-ahead probabilistic demand forecasting, heterogeneous service estimation, route generation, vehicle and crew planning, and common-scenario operational replay.

The release rule is simple: **start with strong classical baselines and promote additional complexity only when predictive, decision-value, solver-quality, reproducibility, and reliability gates all pass**.

## What the repository demonstrates

- **Forecasting fundamentals:** seasonal-naive and LightGBM quantile models with fixed-model rolling one-step backtesting, coverage, worst-series, and capacity-regret diagnostics.
- **Research-derived specialty:** Reference-Aligned Service State (RASS) with leakage-safe peers, similarity weighting, effective-sample-size shrinkage, confidence, and fallback behavior.
- **Operations research:** five route-pool strategies, vehicle/crew/skill/shift constraints, station-decomposed CP-SAT challengers, OS-subprocess isolation, hard timeout, returned-plan validation, and a feasible greedy incumbent.
- **Decision science:** common-random-number scenario banks, paired bootstrap policy comparisons, expected and tail cost, simulator V&V, and explicit champion/challenger promotion.
- **Production-style engineering:** strict configs, SQL marts, FastAPI health/readiness/integrity endpoints, durable atomic writes, stale-lock recovery, token-safe publication, artifact hashes, decision fingerprints, wheel/sdist packaging, Docker assets, and Linux/Windows CI paths.

## Frozen validation evidence for v0.4.3

| Run | Representative runtime | Demand | Historical | Planning | Candidates | WAPE | Champion | Unserved | Violations | Release |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---|
| Synthetic smoke | 6.3 s | 560 | 1,987 | 37 | 77 | 0.2796 | greedy | 0 | 0 | PROMOTE |
| Synthetic full | 18.1 s | 3,537 | 14,141 | 206 | 404 | 0.1969 | greedy | 0 | 0 | PROMOTE |
| Isolated-wheel smoke | 6.8 s | 560 | 1,987 | 37 | 77 | 0.2796 | greedy | 0 | 0 | PROMOTE |
| Isolated-sdist smoke | 6.5 s | 560 | 1,987 | 37 | 77 | 0.2796 | greedy | 0 | 0 | PROMOTE |
| M5-pattern small run | 4.0 s | 560 | 1,427 | 31 | 62 | 0.3083 | greedy | 0 | 0 | PROMOTE |

Additional evidence:

- **66 automated tests** passed with **74.47% coverage**, above the 72% gate.
- The source smoke run repeated with the same decision fingerprint: `dabb0d321813c34c46964d3b7df8f57b72ae35ed440b7d04b043b56423ebbe60`.
- Full synthetic planning served all **206 orders**, selected 76 feasible routes, and produced zero hard-constraint violations.
- CP-SAT ran without fallback in source, wheel, sdist, and M5 paths. It remained a challenger when decision-value or solver-gap gates did not justify promotion.
- Two wheel builds were byte-for-byte identical; two sdist builds had identical file contents after ignoring gzip/tar timestamp metadata.
- Wheel and sdist were each installed from the built artifacts and used for an end-to-end smoke pipeline. The validation scripts now install built artifacts with the `[full]` runtime extras so distribution smoke uses LightGBM, OR-Tools, DuckDB, FastAPI, and Uvicorn instead of accidentally falling back to base-only behavior.
- A real two-worker Uvicorn run accepted one concurrent pipeline request with HTTP 200, rejected the conflicting writer with HTTP 409, served the completed run through an integrity-checked `/latest`, and shut down gracefully.
- Every completed run contains `provenance/artifact_manifest.json` with file size, SHA-256, and decision fingerprint checks.
- The CPU PyTorch multi-task service challenger returned **HOLD**, preserving the better classical RASS/logistic baseline.
- Exact Python 3.11 wheels were available for all **18** pinned direct/validation packages on Linux x86-64 and Windows x64. This is availability evidence, not a substitute for an actual hosted Windows run.

These are offline semi-synthetic benchmark results, not production AMXL outcomes or causal cost savings. Runtime values are representative local measurements and vary by hardware.

## Quick start

### Linux, macOS, WSL, or Git Bash

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --constraint constraints-verified.txt -e ".[full,dev]"
make validate
```

### Windows PowerShell

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --constraint constraints-verified.txt -e ".[full,dev]"
.\scripts\run_full_validation.ps1 -Python python
```

The validation runner executes static checks, 66 tests, two source smoke runs, a full run, a real two-worker API concurrency smoke, two wheel/sdist builds, isolated wheel/sdist installs with `[full]` runtime extras, package-resource checks, end-to-end distribution smoke runs, output verification, artifact integrity, and determinism checks.

## Individual runs

```bash
make smoke
make full
make test
make advanced-check
make m5 M5_ZIP=/path/to/m5-forecasting-accuracy.zip
```

Verify any published output independently:

```bash
python -m heavy_bulky.cli verify-output --output-dir outputs/validation_smoke
```

Outputs under `outputs/<run>/` include resolved configuration, completion and artifact manifests, contracts, forecasts, service-state diagnostics, capacity plans, route candidates, planner results, scenario/replay tables, SQL marts, metrics, reports, and `_SUCCESS`.

## Architecture

```text
public-pattern or synthetic demand
  -> leakage-safe probabilistic forecasting
  -> forecast-driven vehicle and crew capacity
  -> RASS duration and failure-risk estimation
  -> route candidate partitions and contracts
  -> greedy incumbent + station-decomposed CP-SAT challengers
  -> policy-independent common scenario bank
  -> vectorized operational replay and paired comparison
  -> release gates
  -> completion manifest + artifact hashes + atomic publication
  -> API/CLI fail-closed integrity verification
```

The solver worker is importable from both an installed distribution and a source checkout. A timeout, import failure, malformed transport, invalid returned plan, or unavailable OR-Tools installation returns the already validated greedy plan instead of publishing an invalid partial decision.

Publication uses an exclusive lock with persisted PID/token metadata. Dead-owner locks and sufficiently aged malformed locks are recoverable; a publisher removes only the lock bearing its own token.

## Optional data and models

### M5 temporal patterns

M5 contributes seasonality, hierarchy, and intermittency patterns only; it is not represented as observed heavy-bulky demand.

```bash
make m5 M5_ZIP=/path/to/m5-forecasting-accuracy.zip
```

### Amazon Last Mile public route data

```bash
make download-amazon-routes
make prepare-amazon-route-marts
```

The dataset is not redistributed. Crew skills, installation complexity, heavy-bulky service outcomes, and operational costs remain explicitly synthetic assumptions.

### Advanced service challenger

```bash
python -m pip install --constraint constraints-verified.txt -e ".[full,advanced]"
make advanced-check
```

`device:auto` records the device actually used. A CPU run does not support a CUDA claim.

### Chronos-2

```bash
python -m pip install -e ".[chronos]"
python scripts/run_chronos2.py --help
```

Chronos-2 remains an optional adapter and is not part of the frozen core evidence.

## API

```bash
make serve
```

- `GET /health` — process liveness
- `GET /ready` — packaged-config and writable-output readiness
- `POST /run` — synchronous smoke/full execution; concurrent publication returns HTTP 409
- `GET /latest/{mode}` — serves only complete, hash-consistent, artifact-verified runs

## Claim boundary

Safe wording:

> Built a reproducible semi-synthetic heavy-bulky delivery planning benchmark connecting probabilistic forecasting, reference-aligned service estimation, route/resource planning, common-scenario operational replay, artifact integrity, concurrent-publication safety, and reliability-gated promotion.

Do not claim Amazon internal data, planner adoption, production-scale deployment, causal dollar savings, CUDA execution, or Chronos performance unless separately executed and documented.
