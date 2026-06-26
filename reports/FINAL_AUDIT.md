# Final Audit

**Version:** 0.4.3
**Local-equivalent validation:** PASS
**Automated tests:** 64
**Coverage:** 74.47% (gate 72%)

## Frozen runs

| Run | Runtime | Planning orders | Candidates | WAPE | Champion | Fallback | Unserved | Violations | Release |
|---|---:|---:|---:|---:|---|---|---:|---:|---|
| Synthetic smoke | 6.58 s | 37 | 77 | 0.2796 | greedy | false | 0 | 0 | PROMOTE |
| Repeated smoke | 6.45 s | 37 | 77 | 0.2796 | greedy | false | 0 | 0 | PROMOTE |
| Synthetic full | 18.77 s | 206 | 404 | 0.1969 | greedy | false | 0 | 0 | PROMOTE |
| Isolated-wheel smoke | 6.74 s | 37 | 77 | 0.2796 | greedy | false | 0 | 0 | PROMOTE |
| Isolated-sdist smoke | 6.55 s | 37 | 77 | 0.2796 | greedy | false | 0 | 0 | PROMOTE |
| M5-pattern small | 4.00 s | 31 | 62 | 0.3083 | greedy | false | 0 | 0 | PROMOTE |

The two source smoke runs produced the same decision fingerprint:

`dabb0d321813c34c46964d3b7df8f57b72ae35ed440b7d04b043b56423ebbe60`

## v0.4.3 operational hardening

- `/latest/{mode}` fails closed for incomplete, tampered, or hash-inconsistent outputs.
- `/ready` verifies packaged configuration availability and writable output storage.
- A real two-worker Uvicorn run returned exactly HTTP 200 and HTTP 409 for concurrent publication attempts.
- The latest valid run was then served with full artifact verification in 32.596 ms.
- The server exited with code 0 and graceful shutdown `true`.
- Dead-owner and aged malformed locks recover; fresh malformed locks remain conservative.
- Publisher cleanup removes only a matching token-bearing lock.
- Starlette TestClient uses `httpx2` rather than the deprecated plain `httpx` path.

## Model and optimizer decisions

The full synthetic run processed 14,141 historical orders and 206 planning orders, generated 404 candidates, selected 76 feasible routes, and had zero unserved orders and zero hard violations.

The CPU multi-task service challenger remained **HOLD**: duration MAE 10.2830 versus 9.8749, and failure Brier 0.071078 versus 0.069996. The classical baseline was correctly retained.

## Distribution evidence

- Wheel SHA-256: `a7dbf422f7e65eab0db497fd3c269d18716b88efd3723c0519d2f0a63d4600f2`
- Sdist SHA-256: `3bd51fb59a31a41b4119a8ba081564eb08c5d5673b88ef6e9c236866f54aaa08`
- Wheel builds: byte-for-byte reproducible
- Sdist builds: content-identical after archive timestamp normalization
- Isolated wheel and sdist installations: PASS
- End-to-end wheel and sdist smoke pipelines: PASS
- Exact direct wheel availability for CPython 3.11: Linux x86-64 18/18, Windows x64 18/18

The final repository ZIP hash is written to the external release checksum file after packaging to avoid a self-referential archive.

## External validation gaps

- remote GitHub-hosted Actions run
- Docker image build or container run because no Docker daemon was available
- CUDA execution because CUDA was unavailable
- Chronos-2 model download and inference
- full Amazon public route-data calibration
- production planner study or causal business impact measurement

## Stop decision

No unresolved high-value core correctness, pipeline-connectivity, solver-isolation, publication-lock, API-integrity, determinism, artifact-integrity, distribution-installation, or local-runtime defect remained after the final v0.4.3 pass. Further core changes would primarily add complexity or require external infrastructure.

## Distribution smoke extras correction

The final re-audit found that a built-artifact smoke can silently degrade if the wheel/sdist is installed without the `[full]` runtime extras. In that base-only mode the pipeline remains structurally valid but can select seasonal-naive forecasting and fail release gates due missing LightGBM/DuckDB/OR-Tools functionality. The validation scripts now install built artifacts with `[full]` extras and a regression test enforces this. Post-fix wheel and sdist package-first smoke runs returned PROMOTE with LightGBM quantile forecasting, SQL validation PASS, no fallback, zero unserved orders, and zero hard violations.
