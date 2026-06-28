# GPU and CUDA Execution Addendum

## Scope

This addendum records post-release local CUDA execution evidence for the
advanced-service challenger and the optional Chronos-2 adapter. It does not
alter historical qualification manifests, release-bundle hashes, or the
existing v0.4.3-conditionally-qualified prerelease tag.

## Release Target

- Repository: ReviveCoding/reliability-aware-heavy-bulky-delivery
- Commit: 9faaa5631159b3efa3d2250c222d6f9991e95dcd
- Existing prerelease tag: v0.4.3-conditionally-qualified
- GPU: NVIDIA GeForce RTX 4090 Laptop GPU
- PyTorch: 2.11.0+cu128
- PyTorch CUDA runtime: 12.8
- Chronos Forecasting: 2.3.0

## Advanced Service Challenger CUDA Evidence

- Explicit execution device: cuda
- Reported runtime device: cuda
- Result: HOLD
- Elapsed seconds: 10.401154
- Training rows: 1592
- Validation rows: 395
- Baseline duration MAE: 9.874925
- Challenger duration MAE: 10.283030
- Baseline failure Brier: 0.069996
- Challenger failure Brier: 0.071078
- Local evidence SHA-256: 71e2ad38621351dcf7a4c9f4618af56956983ba0e5a251315050abd19ff429ce

The challenger executed on CUDA but was not promoted. The baseline-first
promotion rule retained the classical baseline because the challenger did not
satisfy the configured decision-quality guardrails.

## Chronos-2 CUDA Runtime Evidence

- Explicit requested device: cuda
- Probe inputs: isolated synthetic data, not P28 and not a frozen benchmark window
- Series: 2
- Prediction rows: 28
- Rows per series: 14
- Validated forecast columns: predictions, 0.1, 0.5, 0.9
- Auxiliary identifier column excluded from numeric validation: target_name
- Quantile ordering: verified
- Local evidence SHA-256: 03cb52e3132405d883f62b3a855b99e92489cd6193554b44af07dcfdefe14c15

The optional Chronos-2 adapter completed local explicit CUDA inference.
This is runtime-path evidence only. It does not establish Chronos model
superiority or authorize automatic promotion.

## Qualification Interpretation

The historical core verdict remains CONDITIONALLY QUALIFIED. Local CUDA
execution evidence now exists for the advanced service challenger and the
optional Chronos-2 adapter, while the core release record and its claim
boundaries remain unchanged.

## Remaining Boundaries

- No production AMXL data claim.
- No production deployment claim.
- No causal savings claim.
- No Chronos model-superiority claim.
- No automatic model-promotion authorization.
- No reuse of the frozen P28 evaluation window for tuning.
- The existing prerelease tag remains immutable.
