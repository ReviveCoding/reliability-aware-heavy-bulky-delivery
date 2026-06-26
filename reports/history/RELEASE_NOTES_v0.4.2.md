# Release Notes v0.4.2

Version 0.4.2 is a reproducibility, distribution, and artifact-integrity hardening release on top of v0.4.1.

## Fixed

- Ensured the isolated CP-SAT worker can import the project from a source checkout, not only from an editable or wheel install.
- Added a complete run artifact manifest with file sizes and SHA-256 hashes.
- Added a stable decision fingerprint that excludes timestamps and runtime noise.
- Added repeated source-smoke comparison and exact fingerprint verification.
- Added two-build wheel and sdist verification.
- Added isolated sdist installation and end-to-end smoke execution.
- Made the validation verifier usable both as a direct script and as an imported Python module.
- Isolated SQL mart tests from session-scoped pipeline artifacts so integrity checks cannot be invalidated by test mutation.
- Added explicit setuptools pinning for no-build-isolation sdist validation.
- Synchronized Bash and PowerShell validation contracts.

## Validation

- 56 tests passed with 73.68% coverage.
- Source smoke, repeated smoke, full, wheel smoke, sdist smoke, and M5 pattern run passed artifact integrity.
- Decision fingerprint reproduced: `dabb0d321813c34c46964d3b7df8f57b72ae35ed440b7d04b043b56423ebbe60`.
- Wheel builds were bitwise identical.
- Sdist build contents were identical; gzip archive bytes may differ because archive timestamps are metadata.
- CP-SAT challengers executed without fallback. The full risk-aware challenger remained FEASIBLE with a relative gap above the promotion gate, so greedy remained champion.
- CPU service challenger remained HOLD.

## Remaining external gaps

Remote GitHub-hosted execution, Docker daemon execution, CUDA benchmarking, Chronos-2 inference, and full Amazon public route calibration were not performed in this environment.
