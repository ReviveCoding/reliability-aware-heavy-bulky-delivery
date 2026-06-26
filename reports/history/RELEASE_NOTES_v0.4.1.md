# Release Notes v0.4.1

Version 0.4.1 is a correctness, packaging, and regression hardening release built on v0.4.0.

## Fixed

- Closed FastAPI `TestClient` instances to eliminate a full-suite interpreter-shutdown hang.
- Synchronized root SQL marts with packaged SQL resources.
- Packaged `full_advanced.yaml` and `m5_small.yaml` in addition to smoke and full configs.
- Enforced exact root/package YAML and SQL parity.
- Revalidated solver-worker payloads and safely rejected malformed or infeasible returned plans.
- Broadened corrupt transport handling for solver response deserialization.
- Removed redundant CP-SAT calls from simulation unit tests, reducing native-process flakiness while preserving separate solver integration tests.
- Added durable CSV publication and run completion manifests with summary SHA-256.
- Added Python 3.11 Linux and Windows direct-wheel availability evidence.

## Validation

- 52 tests passed with {coverage:.2f}% coverage.
- Source smoke, source full, isolated-wheel smoke, and M5-pattern small runs all returned PROMOTE with zero unserved orders and zero hard-constraint violations.
- Full artifact verifier passed for source smoke, source full, wheel integrity, and wheel smoke.
- CPU PyTorch service challenger remained HOLD, preserving the classical champion.

## Claim boundary

This release is a locally validated, semi-synthetic, production-style benchmark. It does not claim a remote GitHub-hosted run, Docker execution, CUDA execution, Chronos-2 performance, full Amazon route calibration, production AMXL impact, or causal cost savings.
