# Chronos-2 LoRA Evidence

## Scope

This document records local experimental evidence for a reliability-aware
heavy and bulky delivery forecasting challenger.

The evidence is based on the repository's synthetic or proxy demand
benchmark. It is not production AMXL data, customer demand evidence,
route-calibration evidence, or a production deployment result.

## Locked Temporal Protocol

\ Stage | Date boundary | Purpose |
\---|---|---|
| Development fit boundary | Through 2025-12-02 | Candidate fitting data for development selection |
| Development selection window | 2025-12-03 through 2025-12-30 | Candidate ranking only |
| Final refit boundary | Through 2025-12-30 | Final selected LoRA refit |
|`Frozen P28 evaluation window` | 2025-12-31 through 2026-01-27 | One-time final evaluation |

The frozen P28 window was excluded from parameter updates and
hyperparameter selection. It was evaluated exactly once.

## Development Selection

Selected configuration:

```text
lora_default_lr1e-5_steps128
```

Recorded effective LoRA settings:

```text
rank = 8
alpha = 16
dropout = 0.0
b``

## Final Frozen P28 Results

| Model | WAPE |
|---|--:|
| LightGBM quantile | 0.19688236 |
| Chronos-2 zero-shot | 0.18133250 |
| Chronos-2 final LoRA | 0.18074518 |

On this one frozen window, final LoRA had the lowest observed WAPE. The
incremental difference relative to zero-shot Chronos was small.

## Decision Boundary

The result does not authorize automatic replacement of the existing
LightGM baseline.

No additional LoRA tuning may use P28 results. Any later training or model
selection cycle must use a newly defined untouched evaluation window or a
separately specified nested rolling-backtest protocol.

## CPU-Only Evidence Validation

\scripts/run_chronos_lora_evaluation.py` validates the P31, P31-A, and P32
evidence chain without loading Chronos weights, using a GPU, training,
running inference, or scoring another holdout.

The validator requires:
1. A consistent selected candidate across P31, P31-A, and P32.
2. Final refit to end exactly one day before frozen evaluation begins.
3. Frozen P28 exclusion from parameter updates.
4. Frozen P28 exclusion from hyperparameter selection.
5. Frozen P28 evaluation count equal to one.
6. Automatic promotion disabled.
