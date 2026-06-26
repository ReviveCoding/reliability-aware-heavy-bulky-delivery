# Reliability Method

## Reference-Aligned Service State

RASS compares each delivery with leakage-safe historical peers, estimates local service burden and dispersion, computes effective reference sample size, shrinks sparse estimates toward cohort behavior, and exposes confidence and fallback status.

Required ablations include unshrunk similarity, shrunk RASS, random reference, cohort median, and global median. Novelty does not guarantee promotion.

## Forecast reliability

Forecast selection combines WAPE, pinball loss, interval coverage, worst-series error, worst-series coverage gap, and a capacity-regret proxy under a fixed-model rolling one-step protocol.

## Solver reliability

A challenger must have an eligible status, no fallback, no unserved orders, a sufficient relative gap, a valid returned plan, and downstream decision-value evidence. Otherwise the feasible greedy incumbent remains deployable.

## Replay reliability

All policies use one policy-independent common scenario bank. Paired deltas and bootstrap intervals determine promotion; label-informed diagnostics are not described as an oracle or EVPI.

## Operational reliability

Completed outputs are cryptographically tracked. CLI and API reads fail closed on missing success markers, incomplete manifests, summary-hash mismatch, artifact tampering, or untracked files. Concurrent writers are serialized by PID/token locks with dead-owner and aged malformed-lock recovery.
