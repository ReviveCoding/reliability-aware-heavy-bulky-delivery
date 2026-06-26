from __future__ import annotations

import math
import random
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.metrics import brier_score_loss, mean_absolute_error
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .service_model import (
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES,
    failure_validation_predictions,
)


@dataclass(frozen=True)
class AdvancedServiceResult:
    planning: pd.DataFrame
    metrics: dict[str, Any]
    status: str


def _resolve_device(requested: str) -> str:
    import torch

    if requested == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("advanced_service.device=cuda but CUDA is unavailable")
    return requested


def _set_determinism(seed: int) -> None:
    import torch

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(2)
    with suppress(RuntimeError):
        torch.set_num_interop_threads(1)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)
    if hasattr(torch.backends, "cudnn"):
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False


def _preprocessor() -> ColumnTransformer:
    return ColumnTransformer(
        transformers=[
            (
                "categorical",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                CATEGORICAL_FEATURES,
            ),
            ("numeric", StandardScaler(), NUMERIC_FEATURES),
        ]
    )


def _train_network(
    x: np.ndarray,
    duration: np.ndarray,
    failure: np.ndarray,
    *,
    seed: int,
    epochs: int,
    batch_size: int,
    hidden_dim: int,
    learning_rate: float,
    device: str,
):
    import torch
    from torch import nn
    from torch.utils.data import DataLoader, TensorDataset

    _set_determinism(seed)
    duration_log = np.log(np.maximum(duration, 1.0)).astype(np.float32)
    duration_mean = float(duration_log.mean())
    duration_std = max(float(duration_log.std()), 1e-3)
    duration_target = ((duration_log - duration_mean) / duration_std).astype(np.float32)

    class MultiTaskServiceNet(nn.Module):
        def __init__(self, input_dim: int) -> None:
            super().__init__()
            self.shared = nn.Sequential(
                nn.Linear(input_dim, hidden_dim),
                nn.ReLU(),
                nn.LayerNorm(hidden_dim),
                nn.Linear(hidden_dim, hidden_dim),
                nn.ReLU(),
            )
            self.duration_head = nn.Linear(hidden_dim, 1)
            self.failure_head = nn.Linear(hidden_dim, 1)

        def forward(self, values):
            representation = self.shared(values)
            return self.duration_head(representation).squeeze(-1), self.failure_head(
                representation
            ).squeeze(-1)

    model = MultiTaskServiceNet(x.shape[1]).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=1e-4)
    duration_loss = nn.SmoothL1Loss()
    failure_loss = nn.BCEWithLogitsLoss()
    dataset = TensorDataset(
        torch.as_tensor(x, dtype=torch.float32),
        torch.as_tensor(duration_target, dtype=torch.float32),
        torch.as_tensor(failure.astype(np.float32), dtype=torch.float32),
    )
    generator = torch.Generator().manual_seed(seed)
    loader = DataLoader(
        dataset,
        batch_size=min(batch_size, len(dataset)),
        shuffle=True,
        generator=generator,
        num_workers=0,
    )
    model.train()
    final_loss = 0.0
    for _ in range(epochs):
        total = 0.0
        count = 0
        for features, duration_batch, failure_batch in loader:
            features = features.to(device)
            duration_batch = duration_batch.to(device)
            failure_batch = failure_batch.to(device)
            optimizer.zero_grad(set_to_none=True)
            duration_prediction, failure_logit = model(features)
            loss = duration_loss(duration_prediction, duration_batch) + failure_loss(
                failure_logit, failure_batch
            )
            loss.backward()
            optimizer.step()
            total += float(loss.detach().cpu()) * len(features)
            count += len(features)
        final_loss = total / max(count, 1)
    return model, duration_mean, duration_std, final_loss


def _predict(model, x: np.ndarray, duration_mean: float, duration_std: float, device: str):
    import torch

    model.eval()
    with torch.no_grad():
        duration_scaled, failure_logit = model(
            torch.as_tensor(x, dtype=torch.float32, device=device)
        )
        duration_log = duration_scaled.cpu().numpy() * duration_std + duration_mean
        duration = np.exp(duration_log)
        failure_probability = torch.sigmoid(failure_logit).cpu().numpy()
    return duration, failure_probability, duration_log


def _ece(y: np.ndarray, probability: np.ndarray, bins: int = 10) -> float:
    boundaries = np.linspace(0.0, 1.0, bins + 1)
    total = len(y)
    score = 0.0
    for lower, upper in zip(boundaries[:-1], boundaries[1:], strict=True):
        mask = (probability >= lower) & (
            probability < upper if upper < 1.0 else probability <= upper
        )
        if mask.any():
            score += float(mask.mean()) * abs(
                float(y[mask].mean()) - float(probability[mask].mean())
            )
    return score if total else float("nan")


def fit_advanced_service_challenger(
    historical_with_rass: pd.DataFrame,
    planning_with_baselines: pd.DataFrame,
    cfg: dict,
) -> AdvancedServiceResult:
    advanced = cfg["advanced_service"]
    planning = planning_with_baselines.copy()
    if not advanced["enabled"]:
        return AdvancedServiceResult(planning, {"enabled": False}, "disabled")
    try:
        import torch  # noqa: F401
    except ImportError:
        return AdvancedServiceResult(
            planning,
            {"enabled": True, "reason": "torch_not_installed"},
            "unavailable",
        )

    historical = historical_with_rass.sort_values(["date", "order_id"]).copy()
    dates = sorted(pd.to_datetime(historical["date"]).unique())
    validation_days = min(int(advanced["validation_days"]), max(1, len(dates) // 5))
    validation_dates = dates[-validation_days:]
    train = historical[~historical["date"].isin(validation_dates)].copy()
    validation = historical[historical["date"].isin(validation_dates)].copy()
    if len(train) < int(advanced["min_train_rows"]) or validation.empty:
        return AdvancedServiceResult(
            planning,
            {
                "enabled": True,
                "reason": "insufficient_training_rows",
                "train_rows": len(train),
                "validation_rows": len(validation),
            },
            "unavailable",
        )

    seed = int(cfg["seed"]) + 2301
    try:
        device = _resolve_device(str(advanced["device"]))
    except RuntimeError as exc:
        return AdvancedServiceResult(
            planning,
            {"enabled": True, "reason": str(exc)},
            "unavailable",
        )

    feature_columns = CATEGORICAL_FEATURES + NUMERIC_FEATURES
    transformer = _preprocessor()
    x_train = np.asarray(transformer.fit_transform(train[feature_columns]), dtype=np.float32)
    x_validation = np.asarray(transformer.transform(validation[feature_columns]), dtype=np.float32)
    validation_model, mean_log, std_log, validation_training_loss = _train_network(
        x_train,
        train["actual_duration"].to_numpy(dtype=float),
        train["failed_attempt"].to_numpy(dtype=float),
        seed=seed,
        epochs=int(advanced["epochs"]),
        batch_size=int(advanced["batch_size"]),
        hidden_dim=int(advanced["hidden_dim"]),
        learning_rate=float(advanced["learning_rate"]),
        device=device,
    )
    validation_duration, validation_failure, validation_duration_log = _predict(
        validation_model, x_validation, mean_log, std_log, device
    )
    y_failure = validation["failed_attempt"].to_numpy(dtype=float)
    baseline_duration_mae = float(
        mean_absolute_error(validation["actual_duration"], validation["predicted_duration"])
    )
    advanced_duration_mae = float(
        mean_absolute_error(validation["actual_duration"], validation_duration)
    )
    baseline_failure_probability, baseline_failure_model = failure_validation_predictions(
        train, validation, seed
    )
    baseline_failure_brier_value = float(brier_score_loss(y_failure, baseline_failure_probability))
    advanced_failure_brier = float(brier_score_loss(y_failure, validation_failure))

    final_transformer = _preprocessor()
    x_historical = np.asarray(
        final_transformer.fit_transform(historical[feature_columns]), dtype=np.float32
    )
    x_planning = np.asarray(
        final_transformer.transform(planning[feature_columns]), dtype=np.float32
    )
    final_model, final_mean, final_std, final_training_loss = _train_network(
        x_historical,
        historical["actual_duration"].to_numpy(dtype=float),
        historical["failed_attempt"].to_numpy(dtype=float),
        seed=seed + 1,
        epochs=int(advanced["epochs"]),
        batch_size=int(advanced["batch_size"]),
        hidden_dim=int(advanced["hidden_dim"]),
        learning_rate=float(advanced["learning_rate"]),
        device=device,
    )
    advanced_duration, advanced_failure, training_duration_log = _predict(
        final_model, x_planning, final_mean, final_std, device
    )
    historical_fit_duration, _, _ = _predict(
        final_model, x_historical, final_mean, final_std, device
    )
    residual_log_sigma = max(
        float(
            np.std(
                np.log(np.maximum(validation["actual_duration"].to_numpy(dtype=float), 1.0))
                - validation_duration_log
            )
        ),
        0.05,
    )
    planning["advanced_predicted_duration"] = np.maximum(10.0, advanced_duration)
    planning["advanced_duration_p90"] = np.exp(
        training_duration_log + 1.2815515655446004 * residual_log_sigma
    )
    planning["advanced_predicted_failure_probability"] = np.clip(advanced_failure, 0.001, 0.999)

    duration_gain = (baseline_duration_mae - advanced_duration_mae) / max(
        baseline_duration_mae, 1e-9
    )
    if math.isfinite(baseline_failure_brier_value):
        brier_change = (advanced_failure_brier - baseline_failure_brier_value) / max(
            baseline_failure_brier_value, 1e-9
        )
    else:
        brier_change = float("nan")
    duration_promote = duration_gain >= float(advanced["min_duration_improvement"])
    failure_guardrail = not math.isfinite(brier_change) or brier_change <= float(
        advanced["max_failure_brier_regression"]
    )
    promoted = duration_promote and failure_guardrail
    status = "promoted" if promoted else "hold"
    metrics = {
        "enabled": True,
        "status": status,
        "device": device,
        "train_rows": len(train),
        "validation_rows": len(validation),
        "epochs": int(advanced["epochs"]),
        "baseline_duration_mae": baseline_duration_mae,
        "advanced_duration_mae": advanced_duration_mae,
        "relative_duration_improvement": duration_gain,
        "baseline_failure_model": baseline_failure_model,
        "baseline_failure_brier": baseline_failure_brier_value,
        "advanced_failure_brier": advanced_failure_brier,
        "relative_failure_brier_change": brier_change,
        "advanced_failure_ece": _ece(y_failure, validation_failure),
        "validation_training_loss": validation_training_loss,
        "final_training_loss": final_training_loss,
        "residual_log_sigma": residual_log_sigma,
        "historical_fit_duration_mae": float(
            mean_absolute_error(historical["actual_duration"], historical_fit_duration)
        ),
        "promotion_rule": (
            "Promote only when duration MAE improves by the configured minimum and failure "
            "Brier relative regression stays within its guardrail."
        ),
    }
    return AdvancedServiceResult(planning, metrics, status)
