# Frozen Forecast Uplift Addendum

## Scope

This addendum records a fixed-config recovery of existing forecast
baseline-comparison metrics. It does not change historical qualification
manifests, prior prerelease tags, or existing GPU/CUDA evidence.

## Release Target

- Repository: ReviveCoding/reliability-aware-heavy-bulky-delivery
- Current commit: 16b1d54c639b6b27d05b5a11edf53d1b09d564df
- Existing prerelease tag: v0.4.3-conditionally-qualified-cuda.1
- Recovery mode: fixed config, no tuning
- Backtest protocol: fixed-model rolling one-step
- Forecast series: 9

## Forecast Model Comparison

| Model | WAPE | MAE | Coverage gap | Capacity-regret proxy | Worst-series WAPE | Selection score | Promoted |
|---|---:|---:|---:|---:|---:|---:|---|
| Seasonal naive | 0.265111 | 5.952381 | 0.149206 | 12.269841 | 0.420233 | 0.431202 | No |
| Rolling mean | 0.232660 | 5.223781 | Not recorded in this compact row | 11.853175 | 0.292341 | 0.369619 | No |
| LightGBM quantile | 0.196882 | 4.420478 | 0.030159 | 10.123016 | 0.257624 | 0.315518 | Yes |

## Uplift Versus Seasonal Naive

- WAPE reduction: 25.7360 percent
- MAE reduction: 25.7360 percent
- Worst-series WAPE reduction: 38.6951 percent
- Interval coverage-gap reduction: 79.7872 percent
- Capacity-regret proxy reduction: 17.4968 percent
- Composite selection-score reduction: 26.8284 percent

## Additional Comparison Versus Rolling Mean

- WAPE reduction: 15.3778 percent
- MAE reduction: 15.3778 percent
- Worst-series WAPE reduction: 11.8754 percent
- Capacity-regret proxy reduction: 14.5966 percent
- Composite selection-score reduction: 14.6370 percent

## Selection Interpretation

LightGBM quantile was the selected forecast champion. It improved the
composite selection score and satisfied the worst-series guardrail under the
fixed rolling one-step protocol. The recovery used the existing configuration
and did not perform post-hoc hyperparameter tuning.

## Evidence Integrity

- Recovery evidence SHA-256: 8cdcc071f3a0bbeb88ff63e694ac6b3e96a842f9216b4751e728fc9f0604be8b
- Model comparison SHA-256: 0258a2aa1125cf3f8c0c8913a1a8ed8bb0fc61f3b22f75a60607e04c92175f25
- Summary SHA-256: 2bb867fc63e79b76c602e2186a5b6fe6377c2021169226723cd4485049b543b6
- Config SHA-256: d4c745f9e4a6fc73096c3473e8c46acf5d85c009c4f1f7e8c7aa757e6f247db5

## Remaining Boundaries

- Semi-synthetic benchmark evidence only.
- Fixed rolling one-step backtest only.
- No production AMXL data claim.
- No production deployment claim.
- No causal savings claim.
- No general forecasting state-of-the-art claim.
- No automatic promotion authorization outside the documented benchmark.
- No post-hoc hyperparameter tuning occurred in this recovery.
