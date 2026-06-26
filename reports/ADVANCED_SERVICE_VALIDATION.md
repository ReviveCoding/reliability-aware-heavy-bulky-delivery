# Advanced Service Challenger Validation

- Status: HOLD
- Device actually used: CPU
- Epochs: 4
- Training rows: 1,592
- Validation rows: 395
- Elapsed: 8.93 seconds

| Metric | Classical baseline | Multi-task challenger |
|---|---:|---:|
| Duration MAE | 9.8749 | 10.2830 |
| Failure Brier | 0.069996 | 0.071078 |

The neural challenger regressed on both primary promotion dimensions, so the RASS and logistic-regression baselines remain champion. The CPU run does not support a CUDA execution claim.
