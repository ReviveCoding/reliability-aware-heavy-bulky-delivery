from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import auc, brier_score_loss, log_loss, precision_recall_curve
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

CATEGORICAL_FEATURES = ["station_id", "service_type", "access_type", "required_skill"]
NUMERIC_FEATURES = [
    "cube",
    "weight",
    "required_crew_size",
    "time_window_start",
    "time_window_end",
    "rass_burden",
    "reference_nearest_distance",
]


@dataclass(frozen=True)
class FailureModelResult:
    planning: pd.DataFrame
    metrics: dict[str, float | str]


def _build_pipeline(seed: int) -> Pipeline:
    transformer = ColumnTransformer(
        transformers=[
            ("categorical", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
            ("numeric", StandardScaler(), NUMERIC_FEATURES),
        ]
    )
    return Pipeline(
        steps=[
            ("preprocess", transformer),
            (
                "classifier",
                LogisticRegression(
                    max_iter=500,
                    random_state=seed,
                    solver="liblinear",
                ),
            ),
        ]
    )


def expected_calibration_error(
    y_true: np.ndarray, probability: np.ndarray, bins: int = 10
) -> float:
    boundaries = np.linspace(0.0, 1.0, bins + 1)
    score = 0.0
    for lower, upper in zip(boundaries[:-1], boundaries[1:], strict=True):
        mask = (probability >= lower) & (
            probability < upper if upper < 1.0 else probability <= upper
        )
        if mask.any():
            score += float(mask.mean()) * abs(
                float(y_true[mask].mean()) - float(probability[mask].mean())
            )
    return score


def failure_validation_predictions(
    train: pd.DataFrame,
    validation: pd.DataFrame,
    seed: int,
) -> tuple[np.ndarray, str]:
    """Return leakage-safe failure probabilities for a fixed temporal validation split."""
    if validation.empty:
        raise ValueError("validation data must be non-empty")
    y_train = train["failed_attempt"].astype(int)
    if y_train.nunique() < 2 or len(train) < 30:
        probability = float(train["failed_attempt"].mean()) if len(train) else 0.0
        return np.full(len(validation), probability, dtype=float), "historical_rate_fallback"
    model = _build_pipeline(seed)
    model.fit(train[CATEGORICAL_FEATURES + NUMERIC_FEATURES], y_train)
    probability = model.predict_proba(validation[CATEGORICAL_FEATURES + NUMERIC_FEATURES])[:, 1]
    return np.clip(probability, 0.001, 0.999), "logistic_regression"


def fit_predict_failure_risk(
    historical_with_rass: pd.DataFrame,
    planning_with_rass: pd.DataFrame,
    seed: int,
) -> FailureModelResult:
    historical = historical_with_rass.sort_values("date").copy()
    planning = planning_with_rass.copy()
    unique_dates = sorted(pd.to_datetime(historical["date"]).unique())
    validation_days = min(14, max(1, len(unique_dates) // 5))
    validation_dates = unique_dates[-validation_days:]
    train = historical[~historical["date"].isin(validation_dates)]
    validation = historical[historical["date"].isin(validation_dates)]

    y_train = train["failed_attempt"].astype(int)
    if y_train.nunique() < 2 or len(train) < 30:
        probability = float(historical["failed_attempt"].mean())
        planning["predicted_failure_probability"] = probability
        return FailureModelResult(
            planning=planning,
            metrics={
                "model": "historical_rate_fallback",
                "validation_brier": float("nan"),
                "validation_log_loss": float("nan"),
                "validation_pr_auc": float("nan"),
                "validation_ece": float("nan"),
                "planning_mean_risk": probability,
            },
        )

    validation_prob, validation_model_name = failure_validation_predictions(train, validation, seed)
    y_validation = validation["failed_attempt"].astype(int).to_numpy()
    precision, recall, _ = precision_recall_curve(y_validation, validation_prob)
    pr_auc = float(auc(recall, precision))

    final_model = _build_pipeline(seed)
    final_model.fit(
        historical[CATEGORICAL_FEATURES + NUMERIC_FEATURES],
        historical["failed_attempt"].astype(int),
    )
    planning_probability = final_model.predict_proba(
        planning[CATEGORICAL_FEATURES + NUMERIC_FEATURES]
    )[:, 1]
    planning["predicted_failure_probability"] = np.clip(planning_probability, 0.001, 0.999)
    return FailureModelResult(
        planning=planning,
        metrics={
            "model": validation_model_name,
            "validation_brier": float(brier_score_loss(y_validation, validation_prob)),
            "validation_log_loss": float(log_loss(y_validation, validation_prob, labels=[0, 1])),
            "validation_pr_auc": pr_auc,
            "validation_ece": expected_calibration_error(y_validation, validation_prob),
            "planning_mean_risk": float(np.mean(planning_probability)),
        },
    )
