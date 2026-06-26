# Improvement Report: Candidate Handoff Re-Audit

## Executive summary

This re-audit started from the uploaded `reliability-aware-heavy-bulky-delivery-v0.4.3.zip` without changing production code. The v0.4.3 implementation already satisfied the important runtime gates: source, full, wheel, sdist, M5-pattern, and two-worker API validation passed in the clean re-audit environment. The only meaningful candidate-level gap found was handoff completeness: the repository did not include the explicit `release_candidate_handoff.json`, `docs/improvement_report.md`, and `docs/known_limitations.md` requested by the handoff contract.

## Baseline evidence

| Check | Result |
|---|---:|
| Tests | 66 passed |
| Coverage | 74.47% |
| Coverage gate | 72.00% |
| Lint/format | PASS |
| Full validation wrapper | PASS |
| Source smoke fingerprint repeat | PASS |
| Source full pipeline | PASS |
| Wheel build/install/smoke | PASS |
| Sdist build/install/smoke | PASS |
| API 2-worker concurrency smoke | PASS |
| M5-pattern small run | PASS |

## Final runtime evidence

| Run | Runtime | Planning orders | Route candidates | WAPE | Champion | Fallback | Unserved | Violations | Release |
|---|---:|---:|---:|---:|---|---|---:|---:|---|
| Source smoke | 4.84s | 37 | 77 | 0.2796 | greedy | False | 0 | 0 | PROMOTE |
| Repeated smoke | 4.96s | 37 | 77 | 0.2796 | greedy | False | 0 | 0 | PROMOTE |
| Source full | 13.57s | 206 | 404 | 0.1969 | greedy | False | 0 | 0 | PROMOTE |
| Wheel smoke | 5.13s | 37 | 77 | 0.2796 | greedy | False | 0 | 0 | PROMOTE |
| Sdist smoke | 4.91s | 37 | 77 | 0.2796 | greedy | False | 0 | 0 | PROMOTE |
| M5-pattern | 3.32s | 31 | 62 | 0.3083 | greedy | False | 0 | 0 | PROMOTE |

## Resolved candidate-level gap

- **Severity:** Medium
- **Root cause:** v0.4.3 had rich reports and validation outputs but did not include the explicit handoff manifest and two handoff docs required by the provided project-improvement contract.
- **Fix:** Added `release_candidate_handoff.json`, `docs/improvement_report.md`, and `docs/known_limitations.md`.
- **Evidence:** Generated from actual re-audit outputs, distribution artifacts, source fingerprint, and command evidence.
- **Production code changed:** No.

## Stop criterion

No Critical or High code/runtime issue was found in the re-audit. The remaining work is external qualification: GitHub-hosted Actions, Docker daemon build/run, CUDA, Chronos-2, and larger public-route calibration.
