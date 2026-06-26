# Data and Assumption Card

## Claim boundary

The verified core is an offline, semi-synthetic operational benchmark. It does not use Amazon internal AMXL data and does not claim production cost savings, causal intervention effects, or planner adoption.

## Evidence classes

| Class | Meaning | Examples |
|---|---|---|
| `observed_public_pattern` | Pattern extracted from a supplied public dataset | M5 temporal seasonality and intermittency |
| `derived_from_public` | Deterministic transformation of public fields | package cube from dimensions |
| `observed_calibrated_synthetic` | Generated variable aligned to a public marginal target | optional route/package burden calibration |
| `assumption_driven_synthetic` | Domain assumption without direct public AMXL ground truth | crew skill, stairs, installation complexity, actual duration |
| `simulator_counterfactual` | Outcome generated under a planning policy and event scenario | overtime, failed attempts, replay cost |

Each generated row includes source and availability semantics where applicable. Planning-time models cannot use execution-time or post-outcome fields.

## Dataset roles

### M5

Permitted role:

- temporal seasonality
- correlated hierarchical demand patterns
- intermittent and zero-demand behavior

Not permitted:

- treating Walmart item sales as observed heavy-bulky delivery demand
- claiming AMXL volume, cost, crew, or service behavior

### Amazon Last Mile public data

Permitted role:

- route, stop, zone, package-dimension, time-window, planned-service-time, and transit features supplied by the public release

Not permitted:

- treating planned service time as observed installation duration
- inferring actual heavy-bulky weights, skills, stairs, assembly complexity, or AMXL costs without explicit synthetic labeling
- redistributing the dataset in this repository

## Temporal availability

- `planning_time`: eligible for day-ahead models and optimization
- `execution_time`: eligible only for replay or future intraday recovery work
- `post_outcome`: eligible only for evaluation and diagnostics

The tests reject known outcome columns from planning and routing feature tables.

## Sensitivity

Cost coefficients, disruption rates, and synthetic service assumptions are configurable. Reported policy comparisons are conditional on the frozen configuration and common scenarios, not universal business estimates.
