from __future__ import annotations

import numpy as np
import pandas as pd


def _similarity_weights(history: pd.DataFrame, row: pd.Series) -> np.ndarray:
    cube_scale = max(float(history["cube"].std()), 1.0)
    weight_scale = max(float(history["weight"].std()), 1.0)
    cube_distance = np.abs(history["cube"].to_numpy(dtype=float) - float(row["cube"])) / cube_scale
    weight_distance = (
        np.abs(history["weight"].to_numpy(dtype=float) - float(row["weight"])) / weight_scale
    )
    access_penalty = (history["access_type"].to_numpy() != row["access_type"]).astype(float) * 0.7
    return np.exp(-(cube_distance + weight_distance + access_penalty))


def _predict_one(
    historical: pd.DataFrame,
    row: pd.Series,
    cfg: dict,
    *,
    allow_unshrunk: bool = False,
) -> dict[str, float | int | str]:
    global_median = float(historical["actual_duration"].median())
    global_dispersion = float(historical["actual_duration"].std())
    eligible = historical[
        historical["service_type"].eq(row["service_type"])
        & historical["required_skill"].eq(row["required_skill"])
    ].copy()
    if eligible.empty:
        local = global_median
        dispersion = global_dispersion
        effective_sample_size = 0.0
        nearest_distance = 999.0
    else:
        weights = _similarity_weights(eligible, row)
        weight_sum = float(weights.sum())
        durations = eligible["actual_duration"].to_numpy(dtype=float)
        local = float(np.sum(weights * durations) / max(weight_sum, 1e-9))
        dispersion = float(np.sqrt(np.average((durations - local) ** 2, weights=weights)))
        effective_sample_size = float(weight_sum**2 / max(float(np.sum(weights**2)), 1e-9))
        nearest_distance = float(-np.log(max(float(weights.max()), 1e-12)))

    strength = float(cfg["rass"]["shrinkage_strength"])
    alpha = effective_sample_size / (effective_sample_size + strength)
    shrunk = local if allow_unshrunk else alpha * local + (1.0 - alpha) * global_median
    min_count = int(cfg["rass"]["min_reference_count"])
    high_count = int(cfg["rass"]["high_confidence_count"])
    if effective_sample_size >= high_count and nearest_distance < 1.5:
        confidence = "high"
    elif effective_sample_size >= min_count and nearest_distance < 2.5:
        confidence = "medium"
    else:
        confidence = "low"

    if confidence == "low" and not allow_unshrunk:
        prediction = global_median
        interval_multiplier = 1.6
        fallback = 1
    else:
        prediction = shrunk
        interval_multiplier = 1.25 if confidence == "high" else 1.45
        fallback = 0
    prediction = max(10.0, float(prediction))
    return {
        "reference_count": int(len(eligible)),
        "reference_effective_sample_size": effective_sample_size,
        "reference_nearest_distance": nearest_distance,
        "reference_dispersion": dispersion,
        "reference_confidence": confidence,
        "reference_fallback": fallback,
        "predicted_duration": prediction,
        "duration_p90": max(15.0, prediction + interval_multiplier * max(dispersion, 8.0)),
        "rass_burden": max(0.1, prediction / max(global_median, 1.0)),
    }


def add_rass_features(historical: pd.DataFrame, planning: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    if historical.empty:
        raise ValueError("RASS requires non-empty historical data")
    rows: list[dict] = []
    for _, row in planning.iterrows():
        record = row.to_dict()
        record.update(_predict_one(historical, row, cfg))
        rows.append(record)
    return pd.DataFrame(rows)


def crossfit_rass_features(historical: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Create fast leakage-safe historical RASS features from prior cohort observations."""
    frame = historical.sort_values(["date", "order_id"]).copy()
    cohort_keys = ["service_type", "required_skill", "access_type"]
    cohort = frame.groupby(cohort_keys, sort=False)["actual_duration"]
    frame["reference_count"] = frame.groupby(cohort_keys, sort=False).cumcount()
    frame["cohort_prior_mean"] = cohort.transform(
        lambda series: series.shift(1).expanding(min_periods=1).mean()
    )
    frame["cohort_prior_std"] = cohort.transform(
        lambda series: series.shift(1).expanding(min_periods=2).std()
    )
    global_prior_mean = frame["actual_duration"].shift(1).expanding(min_periods=1).mean()
    global_prior_std = frame["actual_duration"].shift(1).expanding(min_periods=2).std()
    warmup_mean = float(frame["actual_duration"].head(min(30, len(frame))).mean())
    warmup_std = float(frame["actual_duration"].head(min(30, len(frame))).std())
    global_prior_mean = global_prior_mean.fillna(warmup_mean)
    global_prior_std = global_prior_std.fillna(warmup_std).fillna(8.0)
    local = frame["cohort_prior_mean"].fillna(global_prior_mean)
    dispersion = frame["cohort_prior_std"].fillna(global_prior_std).clip(lower=8.0)
    count = frame["reference_count"].astype(float)
    strength = float(cfg["rass"]["shrinkage_strength"])
    alpha = count / (count + strength)
    prediction = alpha * local + (1.0 - alpha) * global_prior_mean
    min_count = int(cfg["rass"]["min_reference_count"])
    high_count = int(cfg["rass"]["high_confidence_count"])
    confidence = np.where(
        count >= high_count, "high", np.where(count >= min_count, "medium", "low")
    )
    fallback = (count < min_count).astype(int)
    prediction = np.where(fallback == 1, global_prior_mean, prediction)
    interval_multiplier = np.where(
        confidence == "high", 1.25, np.where(confidence == "medium", 1.45, 1.6)
    )
    frame["reference_effective_sample_size"] = count
    frame["reference_nearest_distance"] = np.where(count > 0, 0.0, 999.0)
    frame["reference_dispersion"] = dispersion
    frame["reference_confidence"] = confidence
    frame["reference_fallback"] = fallback
    frame["predicted_duration"] = np.maximum(10.0, prediction)
    frame["duration_p90"] = np.maximum(
        15.0, frame["predicted_duration"] + interval_multiplier * dispersion
    )
    frame["rass_burden"] = np.maximum(
        0.1, frame["predicted_duration"] / np.maximum(global_prior_mean, 1.0)
    )
    return frame.drop(columns=["cohort_prior_mean", "cohort_prior_std"])


def rass_metrics(frame: pd.DataFrame) -> dict[str, float]:
    error = frame["actual_duration"] - frame["predicted_duration"]
    p90_under = np.maximum(frame["actual_duration"] - frame["duration_p90"], 0)
    return {
        "duration_mae": float(np.mean(np.abs(error))),
        "duration_bias": float(np.mean(error)),
        "p90_underprediction_mean": float(np.mean(p90_under)),
        "p90_coverage": float(np.mean(frame["actual_duration"] <= frame["duration_p90"])),
        "reference_fallback_rate": float(frame["reference_fallback"].mean()),
        "high_confidence_rate": float((frame["reference_confidence"] == "high").mean()),
    }


def rass_ablation_metrics(
    historical: pd.DataFrame, planning_rass: pd.DataFrame, cfg: dict
) -> pd.DataFrame:
    rng = np.random.default_rng(int(cfg["seed"]) + 811)
    global_prediction = float(historical["actual_duration"].median())
    rows: list[dict[str, float | str]] = []
    actual = planning_rass["actual_duration"].to_numpy(dtype=float)

    predictions: dict[str, np.ndarray] = {
        "global_median": np.full(len(planning_rass), global_prediction),
        "shrunk_rass": planning_rass["predicted_duration"].to_numpy(dtype=float),
    }
    cohort_prediction: list[float] = []
    random_prediction: list[float] = []
    unshrunk_prediction: list[float] = []
    for _, row in planning_rass.iterrows():
        eligible = historical[
            historical["service_type"].eq(row["service_type"])
            & historical["required_skill"].eq(row["required_skill"])
        ]
        if eligible.empty:
            cohort_prediction.append(global_prediction)
            random_prediction.append(global_prediction)
            unshrunk_prediction.append(global_prediction)
            continue
        cohort_prediction.append(float(eligible["actual_duration"].median()))
        sample_size = min(len(eligible), max(1, int(cfg["rass"]["min_reference_count"])))
        random_prediction.append(
            float(rng.choice(eligible["actual_duration"].to_numpy(), size=sample_size).mean())
        )
        unshrunk_prediction.append(
            float(_predict_one(historical, row, cfg, allow_unshrunk=True)["predicted_duration"])
        )
    predictions["cohort_median"] = np.asarray(cohort_prediction)
    predictions["random_reference"] = np.asarray(random_prediction)
    predictions["unshrunk_similarity"] = np.asarray(unshrunk_prediction)

    for method, prediction in predictions.items():
        rows.append(
            {
                "method": method,
                "duration_mae": float(np.mean(np.abs(actual - prediction))),
                "duration_bias": float(np.mean(actual - prediction)),
            }
        )
    return pd.DataFrame(rows).sort_values(["duration_mae", "method"]).reset_index(drop=True)
