from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error

SERIES_KEYS = ["station_id", "service_type"]


@dataclass(frozen=True)
class ForecastSelection:
    operational_forecast: pd.DataFrame
    validation_predictions: pd.DataFrame
    model_scores: pd.DataFrame
    candidate_status: pd.DataFrame
    champion: str


def make_features(demand: pd.DataFrame, lags: list[int]) -> pd.DataFrame:
    frame = demand.sort_values([*SERIES_KEYS, "date"]).copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["dow"] = frame["date"].dt.dayofweek
    frame["month"] = frame["date"].dt.month
    group = frame.groupby(SERIES_KEYS, sort=False)["demand"]
    for lag in lags:
        frame[f"lag_{lag}"] = group.shift(lag)
    frame["roll7"] = frame.groupby(SERIES_KEYS, group_keys=False)["demand"].transform(
        lambda series: series.shift(1).rolling(7, min_periods=7).mean()
    )
    frame["roll28"] = frame.groupby(SERIES_KEYS, group_keys=False)["demand"].transform(
        lambda series: series.shift(1).rolling(28, min_periods=28).mean()
    )
    return frame


def _date_split(demand: pd.DataFrame, horizon: int) -> tuple[pd.Timestamp, list[pd.Timestamp]]:
    dates = [pd.Timestamp(value) for value in sorted(pd.to_datetime(demand["date"]).unique())]
    if len(dates) <= horizon + 1:
        raise ValueError("Not enough dates for validation plus an operational planning date")
    planning_date = dates[-1]
    validation_dates = dates[-(horizon + 1) : -1]
    return planning_date, validation_dates


def _enforce_quantile_order(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    qcols = [column for column in ["p10", "p50", "p90"] if column in out]
    values = np.sort(out[qcols].to_numpy(dtype=float), axis=1)
    out.loc[:, qcols] = np.maximum(values, 0.0)
    out["prediction"] = out["p50"]
    return out


def _seasonal_naive_all(demand: pd.DataFrame) -> pd.DataFrame:
    frame = demand.sort_values([*SERIES_KEYS, "date"]).copy()
    frame["prediction"] = frame.groupby(SERIES_KEYS)["demand"].shift(7)
    fallback = frame.groupby(SERIES_KEYS)["demand"].transform(
        lambda series: series.shift(1).rolling(28, min_periods=1).median()
    )
    frame["prediction"] = frame["prediction"].fillna(fallback).fillna(0).clip(lower=0)
    frame["p10"] = np.maximum(0, frame["prediction"] * 0.70)
    frame["p50"] = frame["prediction"]
    frame["p90"] = frame["prediction"] * 1.35 + 1.0
    frame["model"] = "seasonal_naive"
    return _enforce_quantile_order(frame)


def _rolling_mean_all(demand: pd.DataFrame) -> pd.DataFrame:
    frame = demand.sort_values([*SERIES_KEYS, "date"]).copy()
    rolling = frame.groupby(SERIES_KEYS, group_keys=False)["demand"].transform(
        lambda series: series.shift(1).rolling(28, min_periods=7).mean()
    )
    fallback = frame.groupby(SERIES_KEYS)["demand"].transform(
        lambda series: series.shift(1).expanding(min_periods=1).mean()
    )
    frame["prediction"] = rolling.fillna(fallback).fillna(0).clip(lower=0)
    residual_scale = (
        frame.groupby(SERIES_KEYS)["demand"]
        .transform(lambda series: series.shift(1).rolling(28, min_periods=7).std())
        .fillna(np.sqrt(frame["prediction"] + 1))
    )
    frame["p10"] = np.maximum(0, frame["prediction"] - 1.28 * residual_scale)
    frame["p50"] = frame["prediction"]
    frame["p90"] = frame["prediction"] + 1.28 * residual_scale
    frame["model"] = "rolling_mean"
    return _enforce_quantile_order(frame)


def _lightgbm_predictions(demand: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    from lightgbm import LGBMRegressor

    feat = make_features(demand, cfg["forecast"]["lags"]).dropna().copy()
    planning_date, validation_dates = _date_split(feat, int(cfg["validation_days"]))
    feature_cols = [column for column in feat if column.startswith("lag_")] + [
        "roll7",
        "roll28",
        "dow",
        "month",
    ]
    validation = feat[feat["date"].isin(validation_dates)].copy()
    train_validation = feat[feat["date"] < min(validation_dates)].copy()
    operational = feat[feat["date"] == planning_date].copy()
    train_operational = feat[feat["date"] < planning_date].copy()
    if train_validation["date"].nunique() < int(cfg["forecast"]["min_train_days"]):
        raise ValueError("Insufficient LightGBM training history after feature construction")

    def predict_quantiles(train: pd.DataFrame, target: pd.DataFrame) -> pd.DataFrame:
        output = target[["date", *SERIES_KEYS, "demand"]].copy()
        for quantile in cfg["forecast"]["quantiles"]:
            model = LGBMRegressor(
                objective="quantile",
                alpha=float(quantile),
                n_estimators=60,
                learning_rate=0.06,
                num_leaves=15,
                min_child_samples=12,
                verbosity=-1,
                random_state=int(cfg["seed"]),
                deterministic=True,
                force_col_wise=True,
                n_jobs=1,
            )
            model.fit(train[feature_cols], train["demand"])
            output[f"p{int(quantile * 100)}"] = np.maximum(0.0, model.predict(target[feature_cols]))
        output["model"] = "lightgbm_quantile"
        return _enforce_quantile_order(output)

    return predict_quantiles(train_validation, validation), predict_quantiles(
        train_operational, operational
    )


def pinball(y: np.ndarray, pred: np.ndarray, quantile: float) -> float:
    error = y - pred
    return float(np.mean(np.maximum(quantile * error, (quantile - 1) * error)))


def forecast_metrics(predictions: pd.DataFrame) -> dict[str, float]:
    y = predictions["demand"].to_numpy(dtype=float)
    median = predictions["prediction"].to_numpy(dtype=float)
    denominator = max(float(np.sum(np.abs(y))), 1.0)
    coverage = float(
        np.mean(
            (y >= predictions["p10"].to_numpy(dtype=float))
            & (y <= predictions["p90"].to_numpy(dtype=float))
        )
    )
    planned_capacity = np.ceil(predictions["p90"].to_numpy(dtype=float))
    under = np.maximum(y - planned_capacity, 0.0)
    over = np.maximum(planned_capacity - y, 0.0)
    capacity_regret = float(np.mean(5.0 * under + over))
    return {
        "wape": float(np.sum(np.abs(y - median)) / denominator),
        "mae": float(mean_absolute_error(y, median)),
        "pinball_p10": pinball(y, predictions["p10"].to_numpy(dtype=float), 0.1),
        "pinball_p90": pinball(y, predictions["p90"].to_numpy(dtype=float), 0.9),
        "interval_80_coverage": coverage,
        "interval_coverage_gap": abs(coverage - 0.8),
        "capacity_regret_proxy": capacity_regret,
    }


def forecast_slice_metrics(predictions: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, float | str]] = []
    model_column = "candidate_model" if "candidate_model" in predictions else "model"
    for (model, station, service), frame in predictions.groupby(
        [model_column, "station_id", "service_type"], sort=True
    ):
        rows.append(
            {
                "model": str(model),
                "station_id": str(station),
                "service_type": str(service),
                **forecast_metrics(frame),
            }
        )
    return pd.DataFrame(rows)


def select_forecast(demand: pd.DataFrame, cfg: dict) -> ForecastSelection:
    planning_date, validation_dates = _date_split(demand, int(cfg["validation_days"]))
    all_candidates: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
    status_rows: list[dict[str, str | bool]] = []

    seasonal = _seasonal_naive_all(demand)
    all_candidates["seasonal_naive"] = (
        seasonal[seasonal["date"].isin(validation_dates)].copy(),
        seasonal[seasonal["date"] == planning_date].copy(),
    )
    status_rows.append({"model": "seasonal_naive", "status": "completed", "eligible": True})
    if "rolling_mean" in cfg["forecast"]["champion_candidates"]:
        rolling = _rolling_mean_all(demand)
        all_candidates["rolling_mean"] = (
            rolling[rolling["date"].isin(validation_dates)].copy(),
            rolling[rolling["date"] == planning_date].copy(),
        )
        status_rows.append({"model": "rolling_mean", "status": "completed", "eligible": True})
    if "lightgbm_quantile" in cfg["forecast"]["champion_candidates"]:
        try:
            all_candidates["lightgbm_quantile"] = _lightgbm_predictions(demand, cfg)
            status_rows.append(
                {"model": "lightgbm_quantile", "status": "completed", "eligible": True}
            )
        except (ImportError, ValueError) as exc:
            status_rows.append(
                {
                    "model": "lightgbm_quantile",
                    "status": f"skipped:{type(exc).__name__}",
                    "eligible": False,
                }
            )
    for candidate in cfg["forecast"]["champion_candidates"]:
        if candidate not in {row["model"] for row in status_rows}:
            status_rows.append(
                {
                    "model": candidate,
                    "status": "external_optional_adapter_required",
                    "eligible": False,
                }
            )

    score_rows: list[dict[str, float | str]] = []
    validation_frames: list[pd.DataFrame] = []
    for model_name, (validation, _) in all_candidates.items():
        metrics = forecast_metrics(validation)
        candidate_validation = validation.assign(candidate_model=model_name)
        series_metrics = forecast_slice_metrics(candidate_validation)
        worst_series_wape = float(series_metrics["wape"].max())
        worst_series_coverage_gap = float(series_metrics["interval_coverage_gap"].max())
        selection_score = (
            metrics["wape"]
            + 0.15 * metrics["interval_coverage_gap"]
            + 0.01 * metrics["capacity_regret_proxy"]
            + 0.05 * worst_series_wape
        )
        score_rows.append(
            {
                "model": model_name,
                **metrics,
                "worst_series_wape": worst_series_wape,
                "worst_series_coverage_gap": worst_series_coverage_gap,
                "selection_score": selection_score,
                "backtest_protocol": "fixed_model_rolling_one_step",
            }
        )
        validation_frames.append(candidate_validation)

    scores = (
        pd.DataFrame(score_rows)
        .sort_values(["selection_score", "wape", "interval_coverage_gap", "model"])
        .reset_index(drop=True)
    )
    champion = str(scores.iloc[0]["model"])

    # Baseline-first complexity gate: retain seasonal naive unless the challenger earns a
    # material composite-score improvement.
    if champion != "seasonal_naive" and "seasonal_naive" in set(scores["model"]):
        baseline_score = float(
            scores.loc[scores["model"] == "seasonal_naive", "selection_score"].iloc[0]
        )
        challenger_score = float(scores.loc[scores["model"] == champion, "selection_score"].iloc[0])
        relative_gain = (baseline_score - challenger_score) / max(abs(baseline_score), 1e-9)
        baseline_worst = float(
            scores.loc[scores["model"] == "seasonal_naive", "worst_series_wape"].iloc[0]
        )
        challenger_worst = float(
            scores.loc[scores["model"] == champion, "worst_series_wape"].iloc[0]
        )
        worst_regression = challenger_worst / max(baseline_worst, 1e-9) - 1.0
        if relative_gain < float(
            cfg["forecast"]["min_relative_improvement"]
        ) or worst_regression > float(cfg["forecast"]["max_worst_series_regression"]):
            champion = "seasonal_naive"
    scores["promoted"] = scores["model"].eq(champion)

    operational = all_candidates[champion][1].copy().reset_index(drop=True)
    operational = operational.rename(columns={"demand": "actual_demand_offline"})
    validation_predictions = pd.concat(validation_frames, ignore_index=True)
    return ForecastSelection(
        operational_forecast=operational,
        validation_predictions=validation_predictions,
        model_scores=scores,
        candidate_status=pd.DataFrame(status_rows),
        champion=champion,
    )
