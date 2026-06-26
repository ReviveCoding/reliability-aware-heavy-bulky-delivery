# Project Description

## Positioning

A reliability-aware Applied Science and Operations Research benchmark for heavy-bulky day-ahead delivery planning. It turns uncertain station and service-type demand into service-risk, route, vehicle, and crew decisions and evaluates those decisions through a common-scenario operational replay environment.

## End-to-end flow

1. Strict configuration, provenance, and planning-time data contracts
2. Fixed-model rolling one-step probabilistic forecast evaluation
3. Forecast-driven vehicle and crew capacity planning
4. Reference-Aligned Service State and leakage-safe failure-risk scoring
5. Five route-pool generators with partition and feasibility contracts
6. Feasible greedy incumbent and station-decomposed CP-SAT challengers
7. Policy-independent scenario-bank generation
8. Vectorized operational replay and paired bootstrap comparison
9. Predictive, decision-value, solver-quality, and tail-risk promotion gates
10. SQL marts, reports, API assets, completion manifest, artifact hashes, and atomic publication

## Frozen v0.4.3 evidence

- 66 automated tests and 74.47% coverage
- Source smoke, repeated smoke, source full, isolated wheel, isolated sdist, M5-pattern, and extracted-release paths: PASS
- Full synthetic run: 14,141 historical orders, 206 planning orders, 404 route candidates, 76 selected routes, zero unserved orders, and zero hard-constraint violations
- Real two-worker Uvicorn concurrency: one HTTP 200, one HTTP 409, integrity-checked latest result, graceful shutdown
- CP-SAT ran without fallback across source, wheel, sdist, and M5 validation paths
- Wheel bitwise reproducibility and sdist content reproducibility: PASS
- CPU PyTorch multi-task service challenger: HOLD after failing to improve duration MAE and failure Brier
- Python 3.11 direct wheel availability: 18/18 on Linux x86-64 and Windows x64

## Reliability contribution

RASS adapts reference-state reliability to heterogeneous service work using leakage-safe peer retrieval, similarity weighting, effective-sample-size shrinkage, confidence tiers, and fallback behavior. Novelty alone is not sufficient for promotion; ablations and downstream decision metrics determine whether it remains active.

## Operational hardening

- source-checkout and installed-distribution solver-worker isolation
- hard solver timeout, malformed-response handling, and returned-plan validation
- durable atomic CSV/JSON writes and staging-to-publish commits
- PID/token publication locks, dead-owner recovery, aged malformed-lock recovery, and token-safe cleanup
- complete output artifact manifests and stable decision fingerprints
- CLI and API fail-closed verification of published runs
- real multi-worker Uvicorn concurrency validation
- wheel/sdist isolated installation and end-to-end smoke validation

## Claim discipline

The default data are semi-synthetic. M5 contributes public temporal patterns only. Amazon Last Mile data are optional public route/package inputs and are not redistributed. The project does not establish production AMXL impact, causal savings, planner adoption, CUDA execution, or Chronos performance.
