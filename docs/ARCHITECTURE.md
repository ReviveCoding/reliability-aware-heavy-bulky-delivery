# Architecture

## Decision flow

```text
configuration and provenance
  -> demand history
  -> fixed-model rolling probabilistic backtest
  -> operational p10/p50/p90 forecast
  -> forecast-driven vehicle and crew roster
  -> RASS and failure-risk scoring
  -> route candidate partitions
  -> greedy incumbent and CP-SAT challengers
  -> common scenario bank
  -> vectorized operational replay
  -> paired promotion gates
  -> SQL/report outputs
  -> completion and artifact manifests
  -> atomic publication
```

## Runtime boundaries

The CP-SAT worker runs in a separate operating-system process and receives an explicit source/install import environment. Parent-side validation rejects malformed transport, invalid status, unserved orders, resource conflicts, skill violations, capacity violations, and excessive relative gap before promotion.

Publication uses a same-parent staging directory and exclusive PID/token lock. The last successful output remains available until a complete replacement is ready. Dead-owner and aged malformed locks are recoverable; token comparison prevents one publisher from deleting another publisher's lock.

## Read paths

The CLI `verify-output` and API `/latest/{mode}` use the same published-run integrity contract:

- `_SUCCESS` exists and contains `complete`
- run manifest status and package version are valid
- release decision matches the summary
- summary SHA-256 matches
- all artifact-manifest files exist with matching sizes and SHA-256 values
- no untracked result files are present
- stable decision fingerprint still matches

## API concurrency

A real two-worker Uvicorn smoke submits two simultaneous runs to one mode. Exactly one writer completes while the conflicting writer receives HTTP 409; the completed output is subsequently served only after integrity verification.
