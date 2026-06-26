from __future__ import annotations

from copy import deepcopy

import pandas as pd
import pytest

from heavy_bulky.contracts import ContractViolation, validate_operational_forecast
from heavy_bulky.forecasting import forecast_metrics, forecast_slice_metrics, select_forecast


def test_forecast_quantile_and_key_contract(data_bundle, forecast_selection):
    forecast = forecast_selection.operational_forecast
    planning_date = data_bundle.demand["date"].max()
    keys = data_bundle.demand[data_bundle.demand["date"].eq(planning_date)][
        ["station_id", "service_type"]
    ]
    assert validate_operational_forecast(forecast, keys)["passed"] is True
    assert (forecast["p10"] <= forecast["p50"]).all()
    assert (forecast["p50"] <= forecast["p90"]).all()


def test_final_day_realized_demand_does_not_change_operational_forecast(data_bundle, smoke_config):
    changed = data_bundle.demand.copy()
    last_date = changed["date"].max()
    changed.loc[changed["date"].eq(last_date), "demand"] += 10000
    original = select_forecast(data_bundle.demand, smoke_config).operational_forecast
    altered = select_forecast(changed, smoke_config).operational_forecast
    columns = ["station_id", "service_type", "p10", "p50", "p90", "prediction"]
    pd.testing.assert_frame_equal(
        original[columns].sort_values(columns[:2]).reset_index(drop=True),
        altered[columns].sort_values(columns[:2]).reset_index(drop=True),
        check_exact=False,
        rtol=1e-10,
        atol=1e-10,
    )


def test_forecast_metrics_and_slices(forecast_selection):
    predictions = forecast_selection.validation_predictions
    metrics = forecast_metrics(
        predictions[predictions["candidate_model"].eq(forecast_selection.champion)]
    )
    slices = forecast_slice_metrics(predictions)
    assert metrics["wape"] >= 0
    assert 0 <= metrics["interval_80_coverage"] <= 1
    assert not slices.empty
    assert set(slices["model"]) == set(predictions["candidate_model"])


def test_external_chronos_is_reported_not_silently_used(data_bundle, smoke_config):
    cfg = deepcopy(smoke_config)
    cfg["forecast"]["champion_candidates"] = ["seasonal_naive", "chronos2"]
    result = select_forecast(data_bundle.demand, cfg)
    chronos = result.candidate_status[result.candidate_status["model"].eq("chronos2")].iloc[0]
    assert bool(chronos["eligible"]) is False
    assert chronos["status"] == "external_optional_adapter_required"
    assert result.champion == "seasonal_naive"


def test_quantile_crossing_is_rejected(data_bundle, forecast_selection):
    bad = forecast_selection.operational_forecast.copy()
    bad.loc[bad.index[0], "p10"] = bad.loc[bad.index[0], "p90"] + 1
    keys = data_bundle.demand[data_bundle.demand["date"].eq(data_bundle.demand["date"].max())][
        ["station_id", "service_type"]
    ]
    with pytest.raises(ContractViolation, match="quantile crossing"):
        validate_operational_forecast(bad, keys)
