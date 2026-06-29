# Reliability-Aware Heavy-Bulky Delivery Planning Framework

## Technical Report and Evidence Review

**Repository:** `ReviveCoding/reliability-aware-heavy-bulky-delivery`
**Evidence baseline:** `v0.4.3-conditionally-qualified-forecast.1`
**Evidence commit:** `67ab004c439f61f2ddf70b58d79927b974e03453`
**Qualification verdict:** `CONDITIONALLY QUALIFIED`
**Report type:** Post-release technical documentation
**Scope:** Offline, semi-synthetic applied-science and operations-research benchmark

---

## Executive Summary

This report documents a reliability-aware planning framework for heavy-bulky delivery operations. The framework connects probabilistic demand forecasting, reference-aligned service-duration and failure-risk estimation, route candidate generation, vehicle and crew capacity planning, constrained route selection, and common-scenario operational replay.

The central design principle is **baseline-first promotion**. The framework does not adopt a more complex model merely because it is available. A candidate must demonstrate acceptable predictive quality, decision value, solver quality, reproducibility, and reliability before it can replace the active baseline.

The released evidence establishes four principal findings:

1. **Forecasting uplift.** LightGBM quantile forecasting was selected as the forecast champion under a fixed-config, no-tuning, fixed-model rolling one-step evaluation. Relative to the seasonal-naive baseline, it reduced WAPE and MAE by 25.7360 percent, worst-series WAPE by 38.6951 percent, interval coverage gap by 79.7872 percent, and the capacity-regret proxy by 17.4968 percent.

2. **Operational feasibility.** In the full synthetic validation run, the planning pipeline served all 206 planning orders using 76 feasible routes, with zero unserved orders and zero hard-constraint violations.

3. **Reliability-gated model selection.** The advanced PyTorch multi-task service challenger was trained and evaluated on CUDA, but remained `HOLD` because it regressed against the classical RASS and logistic baseline on both duration MAE and failure Brier score.

4. **Reproducibility and release integrity.** The repository includes deterministic decision fingerprints, artifact manifests, atomic publication, conflict-safe API execution, wheel and sdist validation, Docker validation, and hosted CI coverage across Windows smoke, end-to-end, and Docker jobs.

The framework is a reproducible **semi-synthetic benchmark**, not a production AMXL system. It does not establish production deployment, causal savings, customer-facing service improvement, or general forecasting state-of-the-art performance.

---

## 1. Decision Context

Heavy-bulky delivery planning differs from homogeneous parcel routing because service execution can depend on installation complexity, access constraints, crew skills, vehicle capacity, appointment windows, failure risk, and duration uncertainty. A planning system must therefore do more than predict average demand. It must translate uncertainty into resource requirements and executable route decisions.

The decision chain is:

```text
public-pattern or synthetic demand
  -> leakage-safe probabilistic forecasting
  -> forecast-driven vehicle and crew capacity
  -> RASS duration and failure-risk estimation
  -> route candidate partitions and contracts
  -> greedy incumbent plus station-decomposed CP-SAT challengers
  -> policy-independent common scenario bank
  -> vectorized operational replay and paired comparison
  -> release gates
  -> completion manifest, artifact hashes, atomic publication
  -> API and CLI integrity verification
```

The framework asks a stricter question than "which model has the lowest average error?":

> Does a candidate improve forecast and planning quality without creating unacceptable tail risk, calibration degradation, infeasibility, reproducibility loss, or publication risk?

---

## 2. Framework Scope and Claim Boundary

### 2.1 Included scope

The framework includes:

- Day-ahead demand forecasting by station and service type.
- Point and interval forecasting through p10, p50, and p90 quantiles.
- Forecast-driven vehicle and crew capacity estimation.
- Reference-Aligned Service State, or RASS, for duration and failure-risk features.
- Five route-pool generation strategies.
- A feasible greedy planning incumbent.
- Station-decomposed CP-SAT optimization challengers.
- Common-scenario simulation and paired policy comparison.
- Release gates, artifact integrity, package validation, Docker validation, API safety, and hosted CI.

### 2.2 Explicitly excluded scope

The framework does not claim:

- Amazon internal data access.
- Production AMXL integration or operational adoption.
- Production-scale route deployment.
- Causal dollar savings.
- Customer service-level improvement in a live network.
- General forecasting state-of-the-art performance.
- Chronos model superiority.
- Automatic model promotion outside the documented benchmark.

Demand patterns may be synthetic or derived from public temporal structures. M5 data, when used, supplies temporal patterns only and is not treated as observed heavy-bulky demand. Public Amazon Last Mile route data is not redistributed, and heavy-bulky-specific service outcomes and costs remain synthetic assumptions.

---

## 3. Design Principles

### 3.1 Baseline-first promotion

The active policy begins with strong classical baselines. Additional complexity is promoted only when it passes all required gates:

1. Predictive quality
2. Interval calibration and uncertainty quality
3. Worst-slice robustness
4. Decision-value diagnostics
5. Solver feasibility and quality
6. Reproducibility
7. Artifact and publication integrity

This policy prevents a complex model from being adopted because of average error alone.

### 3.2 Fail closed rather than publish a partial decision

The planning workflow retains a validated greedy incumbent. If the CP-SAT worker times out, fails to import, returns malformed output, violates contracts, or cannot run, the system returns the validated incumbent instead of publishing an incomplete or invalid plan.

### 3.3 Separate evidence layers

The release lineage separates core qualification, CUDA runtime evidence, and forecast uplift evidence.

| Release tag | Target commit | Evidence added |
|---|---|---|
| `v0.4.3-conditionally-qualified` | `9faaa5631159b3efa3d2250c222d6f9991e95dcd` | Core semi-synthetic qualification |
| `v0.4.3-conditionally-qualified-cuda.1` | `16b1d54c639b6b27d05b5a11edf53d1b09d564df` | Local CUDA advanced-service and Chronos runtime evidence |
| `v0.4.3-conditionally-qualified-forecast.1` | `67ab004c439f61f2ddf70b58d79927b974e03453` | Fixed-config forecast uplift evidence |

Older tags remain immutable historical records. Later evidence is additive rather than retrospectively rewriting earlier qualification claims.

---

## 4. Data, Configuration, and Experimental Assumptions

The full configuration defines a 365-day history, 28 validation days, three stations, and three service types:

- Stations: `STATION_A`, `STATION_B`, `STATION_C`
- Service types: `threshold`, `room_of_choice`, `installation`
- Forecast candidates: seasonal naive, rolling mean, and LightGBM quantile
- Forecast quantiles: 0.1, 0.5, and 0.9
- Simulation replications: 100
- CP-SAT nominal time limit: 2 seconds
- CP-SAT hard timeout: 8 seconds
- Route strategies: nearest, sweep, risk-first, balanced, and skill-clustered

The configuration also defines planning and reliability controls, including zero permitted hard-constraint violations, maximum unserved-rate controls, interval and worst-series coverage controls, solver fallback limits, and a reproducibility requirement.

The framework uses synthetic operational assumptions for crew availability, vehicle failures, service overruns, overtime, failed attempts, and unserved-order costs. These assumptions support controlled benchmark evaluation but must not be interpreted as observed production parameters.

---

## 5. Probabilistic Demand Forecasting

### 5.1 Forecasting objective

The forecasting layer predicts daily demand at the station and service-type level. It produces p10, p50, and p90 forecasts rather than only a single point estimate.

The p50 forecast is the central estimate. The p90 forecast is used as an operational capacity signal because under-capacity can cause unserved work, overtime, or replanning. The framework therefore evaluates uncertainty quality alongside point accuracy.

### 5.2 Candidate models

Three candidates are evaluated under the same fixed-model rolling one-step protocol.

| Candidate | Method | Purpose |
|---|---|---|
| Seasonal naive | Seven-day lag with a rolling-median fallback | Transparent seasonal baseline |
| Rolling mean | Lagged 28-day rolling mean with expanding-mean fallback | Smoothed classical baseline |
| LightGBM quantile | Separate quantile gradient-boosted tree models | Nonlinear candidate with interval forecasts |

The LightGBM model uses lag features at 1, 7, 14, 28, and 56 days; 7-day and 28-day rolling means; day of week; and month. Separate quantile models are fit for p10, p50, and p90, and quantile order is enforced after prediction.

### 5.3 Temporal leakage controls

Forecast features are built from lagged or shifted demand. The planning date is held out, and validation dates precede the planning date. The LightGBM training period excludes validation dates for validation forecasting and excludes the planning date for operational forecasting.

This structure follows a rolling-origin evaluation idea: forecasts are generated from information that would have been available before each forecast origin, then evaluated at forward-moving points.

### 5.4 Forecast selection score

The framework does not select the champion from WAPE alone. For model `m`, the selection score is:

```text
score(m)
  = WAPE(m)
  + 0.15 × interval_coverage_gap(m)
  + 0.01 × capacity_regret_proxy(m)
  + 0.05 × worst_series_WAPE(m)
```

Lower is better.

The champion must also pass a baseline-first complexity rule. A challenger must improve the seasonal-naive composite score by at least 1 percent and cannot worsen worst-series WAPE by more than 10 percent. Otherwise, seasonal naive remains the champion.

### 5.5 Capacity-regret proxy

The framework plans capacity from the p90 forecast. It penalizes under-capacity more heavily than excess capacity:

```text
planned_capacity = ceil(p90)

under = max(actual_demand - planned_capacity, 0)
over  = max(planned_capacity - actual_demand, 0)

capacity_regret_proxy = mean(5 × under + over)
```

The five-to-one asymmetry represents the greater operational consequence of insufficient capacity relative to excess capacity in a constrained heavy-bulky setting. It remains a benchmark proxy, not a direct estimate of production cost.

### 5.6 Frozen forecast uplift results

The fixed-config recovery compared all forecast candidates across nine station-service series.

| Model | WAPE | MAE | Coverage gap | Capacity-regret proxy | Worst-series WAPE | Selection score | Promoted |
|---|---:|---:|---:|---:|---:|---:|---|
| Seasonal naive | 0.265111 | 5.952381 | 0.149206 | 12.269841 | 0.420233 | 0.431202 | No |
| Rolling mean | 0.232660 | 5.223781 | Not recorded in compact row | 11.853175 | 0.292341 | 0.369619 | No |
| LightGBM quantile | 0.196882 | 4.420478 | 0.030159 | 10.123016 | 0.257624 | 0.315518 | Yes |

Relative to seasonal naive, LightGBM quantile achieved:

| Metric | Relative change |
|---|---:|
| WAPE | 25.7360 percent reduction |
| MAE | 25.7360 percent reduction |
| Worst-series WAPE | 38.6951 percent reduction |
| Interval coverage gap | 79.7872 percent reduction |
| Capacity-regret proxy | 17.4968 percent reduction |
| Composite selection score | 26.8284 percent reduction |

Relative to rolling mean, LightGBM quantile reduced WAPE and MAE by 15.3778 percent, worst-series WAPE by 11.8754 percent, capacity-regret proxy by 14.5966 percent, and composite selection score by 14.6370 percent.

The recovered result used the existing configuration and did not perform post-hoc hyperparameter tuning.

---

## 6. Reference-Aligned Service State

### 6.1 Purpose

Forecasting determines expected workload volume. RASS estimates how difficult each planned service instance is likely to be.

The RASS layer augments a planning order with:

- Predicted service duration
- Duration p90
- Failure-risk-relevant burden
- Reference count
- Effective sample size
- Similarity distance
- Confidence category
- Explicit fallback indicator

### 6.2 Leakage-safe peer set

For a planned order, eligible historical references are filtered by at least service type and required skill. The framework uses similarity weights across eligible references to calculate a local weighted duration estimate.

### 6.3 Effective sample size and shrinkage

Weighted references can appear numerous while providing little independent support if a small number of observations dominate the weights. The framework therefore calculates effective sample size:

```text
n_eff = (sum of weights)^2 / sum of squared weights
```

The local estimate is shrunk toward the global median:

```text
alpha = n_eff / (n_eff + shrinkage_strength)

shrunk_duration
  = alpha × weighted_local_duration
  + (1 - alpha) × global_median_duration
```

The full configuration uses a shrinkage strength of 30.0.

### 6.4 Confidence and fallback

Confidence is assigned from effective sample size and nearest-reference distance.

- High confidence requires at least 60 effective references and a close reference.
- Medium confidence requires at least 15 effective references and a less restrictive distance condition.
- Low confidence invokes a global-median fallback unless explicitly configured otherwise.

The p90 duration expands the predicted duration using confidence-sensitive multipliers and local dispersion. This gives downstream planning a risk-aware service-time input rather than a single unqualified duration estimate.

---

## 7. Capacity, Routing, and Optimization

### 7.1 Forecast-driven resource planning

Forecast p90 informs station-level vehicle and crew requirements. The configuration includes:

- 480-minute shifts
- Reserved vehicles and crews
- Minimum station resource allocation
- Route fill-rate assumptions
- Installation-skill share
- Per-station resource pools

The goal is not to claim a fully optimized real labor model. It is to create an explicit and testable translation from demand uncertainty into resource requirements.

### 7.2 Route candidate generation

The framework generates route pools using five strategies:

1. Nearest
2. Sweep
3. Risk first
4. Balanced
5. Skill clustered

Each route candidate is evaluated against order assignment, vehicle cube capacity, vehicle weight capacity, shift duration, service skill, appointment windows, and route-level operational constraints.

### 7.3 Greedy incumbent

A feasible greedy plan is created before the solver challenger is evaluated. This incumbent provides:

- A verified fallback
- A deterministic comparator
- A valid plan to return if solver execution fails
- A baseline for decision-value evaluation

### 7.4 CP-SAT challenger

The optimization challenger uses OR-Tools CP-SAT to choose route candidates and penalize unserved orders. The objective contains route costs and a high unserved-order penalty.

The full configuration uses:

- CP-SAT solver
- 2-second solver time limit
- 8-second hard timeout
- Single search worker for deterministic behavior
- Unserved-order penalty of 5000
- Overtime, risk, and appointment-window penalties

CP-SAT was executed without fallback in the validated source, wheel, sdist, and M5-pattern paths. It nevertheless remained a challenger because the decision-value or solver-gap gates did not justify replacing the greedy incumbent.

This is an important result: successful solver execution does not automatically imply operational promotion.

---

## 8. Simulation-Based Operational Replay

### 8.1 Common scenario bank

Policies are evaluated on a policy-independent scenario bank rather than receiving different random environments. This common-random-number structure reduces noise in paired comparisons because two policies experience the same simulated disruptions.

### 8.2 Simulated operational risks

The full configuration models:

- Service-duration overruns
- Vehicle failures
- Crew absences
- Overtime
- Failed delivery attempts
- Unserved orders

The simulation uses 100 replications and records expected and tail-oriented operational outcomes.

### 8.3 Decision evaluation

The framework supports paired policy comparison and replay metrics rather than evaluating a planner solely through its nominal route objective. A lower deterministic planning objective can still lead to worse outcomes once service uncertainty, failure, absence, and overtime are introduced.

---

## 9. Reliability, Reproducibility, and Publication Controls

### 9.1 Release gates

The release configuration includes:

- Zero allowed hard-constraint violations
- Maximum unserved-order rate
- Maximum interval coverage gap
- Maximum worst-series coverage gap
- Maximum solver fallback rate
- Maximum solver relative gap
- Maximum capacity shortfall
- SQL validation requirement
- Reproducibility requirement
- Optional advanced-service gating when enabled

### 9.2 Artifact integrity

Completed runs contain provenance metadata, including:

- File sizes
- SHA-256 hashes
- Decision fingerprints
- Completion manifests
- Resolved configurations
- Contracts
- Forecasts
- Service diagnostics
- Capacity plans
- Route candidates
- Planner results
- Scenario and replay tables
- SQL marts
- Metrics and reports

The output verifier checks that a published run is complete and hash-consistent before it is served through the API.

### 9.3 Atomic publication and concurrency safety

Publication uses an exclusive lock with persisted process and token metadata. The system can recover dead-owner and sufficiently old malformed locks, while a publisher removes only a lock that bears its own token.

A two-worker Uvicorn validation accepted one concurrent run request with HTTP 200, rejected the conflicting writer with HTTP 409, served the completed result through an integrity-checked latest endpoint, and shut down cleanly.

### 9.4 Package and environment validation

The release evidence includes:

- 66 automated tests passed
- 74.47 percent source coverage, above the 72 percent gate
- Repeated deterministic source smoke runs with the same decision fingerprint
- Wheel and sdist builds
- Isolated wheel and sdist installation
- End-to-end distribution smoke tests with full runtime extras
- Docker build and container smoke tests
- Hosted Windows smoke, end-to-end, and Docker CI jobs

---

## 10. Advanced-Service Challenger and CUDA Evidence

### 10.1 Classical service baseline

The classical service stack combines RASS duration features with a logistic failure-risk baseline. This baseline remains active unless a more complex challenger earns promotion.

### 10.2 Multi-task PyTorch challenger

The optional advanced-service challenger uses a shared neural representation with:

- Categorical preprocessing through one-hot encoding
- Numeric preprocessing through standardization
- Two hidden linear layers with ReLU activations
- Layer normalization
- A duration head
- A failure-risk head
- Smooth L1 loss for log-duration
- Binary cross-entropy with logits for failure risk
- AdamW optimization

The candidate is evaluated against the classical baseline using duration MAE and failure Brier score.

### 10.3 CUDA result

The CUDA evaluation ran on:

- GPU: NVIDIA GeForce RTX 4090 Laptop GPU
- PyTorch: 2.11.0+cu128
- CUDA runtime: 12.8
- Training rows: 1,592
- Validation rows: 395
- Epochs: 4

| Metric | Classical baseline | CUDA challenger | Direction |
|---|---:|---:|---|
| Duration MAE | 9.874925 | 10.283030 | Worse |
| Failure Brier | 0.069996 | 0.071078 | Worse |

The challenger status was therefore `HOLD`.

This is not evidence that CUDA training failed. It is evidence that the promotion rule worked as designed. The advanced model trained and evaluated successfully, but did not meet the configured improvement and calibration guardrails.

---

## 11. Chronos-2 Optional Adapter Evidence

Chronos-2 is treated as an optional adapter rather than part of the frozen core benchmark.

The local CUDA runtime validation confirmed:

- Explicit requested device: `cuda`
- Chronos Forecasting version: 2.3.0
- GPU: NVIDIA GeForce RTX 4090 Laptop GPU
- Probe data: isolated synthetic inputs, not the frozen P28 window
- Series: 2
- Forecast rows: 28
- Rows per series: 14
- Validated forecast fields: `predictions`, `0.1`, `0.5`, `0.9`
- Quantile ordering: verified

The `target_name` column was identified as an auxiliary identifier rather than a numeric forecast field. It was excluded from numeric forecast validation.

This evidence confirms the local CUDA runtime path. It does not establish Chronos superiority, fine-tuning effectiveness, production utility, or an automatic promotion decision.

---

## 12. Frozen Validation Results

### 12.1 Core validation runs

| Run | Demand rows | Historical orders | Planning orders | Route candidates | Forecast WAPE | Champion | Unserved | Hard violations |
|---|---:|---:|---:|---:|---:|---|---:|---:|
| Synthetic smoke | 560 | 1,987 | 37 | 77 | 0.2796 | greedy | 0 | 0 |
| Synthetic full | 3,537 | 14,141 | 206 | 404 | 0.1969 | greedy | 0 | 0 |
| Isolated wheel smoke | 560 | 1,987 | 37 | 77 | 0.2796 | greedy | 0 | 0 |
| Isolated sdist smoke | 560 | 1,987 | 37 | 77 | 0.2796 | greedy | 0 | 0 |
| M5-pattern small run | 560 | 1,427 | 31 | 62 | 0.3083 | greedy | 0 | 0 |

### 12.2 Full synthetic planning result

The full synthetic run produced:

- 206 planning orders served
- 76 feasible selected routes
- Zero unserved orders
- Zero hard-constraint violations
- LightGBM quantile forecasting champion
- Greedy planning incumbent retained as champion
- CP-SAT executed as a challenger but was not promoted

---

## 13. Evidence Interpretation

### 13.1 What the framework demonstrates

The evidence supports these statements:

- A LightGBM quantile approach outperformed seasonal-naive and rolling-mean baselines on the documented fixed rolling one-step semi-synthetic benchmark.
- The forecasting candidate improved point accuracy, worst-series robustness, interval calibration, and a capacity-oriented decision proxy together.
- The planning pipeline generated feasible routes and served all full-run planning orders under the documented synthetic constraints.
- The framework preserves a valid greedy plan when the optimizer does not justify promotion or fails to return a safe result.
- CUDA execution was verified for the neural service challenger and Chronos-2 runtime path.
- The neural challenger was correctly retained as `HOLD` when it did not beat the classical baseline.
- The repository provides substantial reproducibility and release-integrity controls.

### 13.2 What the framework does not demonstrate

The evidence does not support claims of:

- Production heavy-bulky delivery performance
- Amazon internal planner adoption
- Causal cost reduction
- Customer-facing SLA improvement
- General LightGBM superiority across forecasting domains
- General Chronos-2 superiority
- Automatic promotion in an external operating environment

---

## 14. Limitations and Next Research Questions

The benchmark is intentionally constrained and semi-synthetic. Its current limitations create useful next research questions.

1. **External validity.** Evaluate the methodology on additional public delivery, retail, or workforce-planning datasets while preserving temporal and operational semantics.

2. **Synthetic-regime robustness.** Test the forecast and planning policy under different demand volatility, intermittency, network imbalance, crew-skill scarcity, and disruption rates.

3. **Service-model development.** Train advanced candidates only on a fully disjoint development cohort, then evaluate once on an untouched confirmation cohort.

4. **Decision calibration.** Validate whether the capacity-regret proxy aligns with more realistic cost and service-level structures.

5. **Chronos evaluation.** Compare the optional Chronos adapter against existing forecast candidates through a separately pre-registered protocol. Do not infer superiority from runtime validation alone.

6. **Production translation.** Replace synthetic operational assumptions with audited empirical assumptions only when a legitimate data-governance and deployment context exists.

---

## 15. Reproduction Path

A standard local validation path is:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --constraint constraints-verified.txt -e ".[full,dev]"
.\scripts\run_full_validation.ps1 -Python python
```

Useful individual commands include:

```powershell
make smoke
make full
make test
make advanced-check
make m5 M5_ZIP=/path/to/m5-forecasting-accuracy.zip
python -m heavy_bulky.cli verify-output --output-dir outputs/validation_smoke
```

The main release validation includes static checks, tests, source smoke runs, a full run, API concurrency validation, wheel and sdist builds, isolated distribution installation, package-resource checks, output verification, artifact integrity checks, and determinism checks.

---

## 16. Source Provenance

| Evidence source | Role |
|---|---|
| `README.md` | Framework architecture, release behavior, quick-start, claim boundary |
| `configs/full.yaml` | Experimental configuration, thresholds, resource assumptions, simulation settings |
| `qualification_manifest.json` | Frozen local qualification results and reproducibility evidence |
| `forecast_uplift_addendum.json` | Fixed-config baseline-comparison recovery and forecast uplift |
| `gpu_cuda_execution_addendum.json` | CUDA advanced-service and Chronos runtime evidence |
| `src/heavy_bulky/forecasting.py` | Forecast candidates, quantiles, metrics, selection score, promotion rule |
| `src/heavy_bulky/rass.py` | Reference weighting, effective sample size, shrinkage, confidence, fallback |
| `src/heavy_bulky/optimization.py` | CP-SAT challenger and route-selection objective |
| `src/heavy_bulky/simulation.py` | Common-scenario replay and paired policy evaluation |
| `src/heavy_bulky/advanced_service.py` | Multi-task neural challenger and promotion rule |
| `src/heavy_bulky/integrity.py` | Artifact and publication integrity checks |
| `src/heavy_bulky/api.py` | Health, readiness, run, and integrity-checked latest endpoints |

---

## 17. External Technical References

1. Ke, G., Meng, Q., Finley, T., et al. "LightGBM: A Highly Efficient Gradient Boosting Decision Tree." NeurIPS, 2017.
   https://proceedings.neurips.cc/paper_files/paper/2017/file/6449f44a102fde848669bdd9eb6b76fa-Paper.pdf

2. Hyndman, R. J., and Athanasopoulos, G. "Forecasting: Principles and Practice." Time-series cross-validation and rolling forecasting origin.
   https://otexts.com/fpp3/tscv.html

3. Google OR-Tools. "CP-SAT Solver."
   https://developers.google.com/optimization/cp/cp_solver

4. Ansari, A. F., et al. "Chronos-2: From Univariate to Universal Forecasting."
   https://arxiv.org/abs/2510.15821

---

## Conclusion

The Reliability-Aware Heavy-Bulky Delivery Planning Framework demonstrates an integrated applied-science workflow in which forecasting, service estimation, planning, simulation, and release engineering are evaluated as one decision system.

Its strongest positive result is not merely a lower forecast error. LightGBM quantile forecasting improved average error, worst-series robustness, interval calibration, and a capacity-oriented decision proxy relative to simple baselines, while meeting the configured promotion guardrails.

Equally important, the framework records negative evidence correctly. The CUDA-trained advanced service challenger did not outperform the classical baseline and was retained as `HOLD`. The CP-SAT optimizer ran successfully but was not promoted without sufficient decision-value justification. Chronos-2 runtime was validated without making unsupported performance claims.

This combination of positive uplift, explicit hold decisions, reproducibility controls, and bounded claims is the framework's primary contribution.

---

## Claim Boundary Confirmation

This report documents offline semi-synthetic benchmark evidence.

- Semi-synthetic benchmark evidence only.
- No production AMXL data claim.
- No production deployment claim.
- No causal savings claim.
- No general forecasting state-of-the-art claim.
- No automatic model-promotion authorization outside the documented benchmark.
- CUDA runtime validation does not establish Chronos superiority.
