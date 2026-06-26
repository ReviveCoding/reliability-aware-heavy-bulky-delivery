from __future__ import annotations

from pathlib import Path

import pytest

from heavy_bulky.capacity import plan_capacity
from heavy_bulky.config import load_config
from heavy_bulky.data import build_data_bundle
from heavy_bulky.forecasting import select_forecast
from heavy_bulky.pipeline import run_pipeline
from heavy_bulky.rass import add_rass_features, crossfit_rass_features
from heavy_bulky.routing import generate_route_candidates
from heavy_bulky.safety import planning_decision_view
from heavy_bulky.service_model import fit_predict_failure_risk

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def smoke_config() -> dict:
    return load_config(ROOT / "configs" / "smoke.yaml")


@pytest.fixture(scope="session")
def data_bundle(smoke_config):
    return build_data_bundle(smoke_config)


@pytest.fixture(scope="session")
def forecast_selection(data_bundle, smoke_config):
    return select_forecast(data_bundle.demand, smoke_config)


@pytest.fixture(scope="session")
def service_bundle(data_bundle, smoke_config):
    historical = crossfit_rass_features(data_bundle.historical_orders, smoke_config)
    planning = add_rass_features(
        data_bundle.historical_orders, data_bundle.planning_orders, smoke_config
    )
    failure = fit_predict_failure_risk(historical, planning, smoke_config["seed"])
    decision = planning_decision_view(failure.planning)
    return historical, failure.planning, decision, failure.metrics


@pytest.fixture(scope="session")
def route_bundle(service_bundle, smoke_config):
    _, _, decision, _ = service_bundle
    return (*generate_route_candidates(decision, smoke_config), decision)


@pytest.fixture(scope="session")
def capacity_bundle(data_bundle, forecast_selection, smoke_config):
    return plan_capacity(
        forecast_selection.operational_forecast,
        data_bundle.historical_orders,
        data_bundle.planning_orders,
        data_bundle.vehicles,
        data_bundle.crews,
        smoke_config,
    )


@pytest.fixture(scope="session")
def pipeline_run(tmp_path_factory):
    output = tmp_path_factory.mktemp("pipeline") / "smoke"
    metrics = run_pipeline(ROOT / "configs" / "smoke.yaml", output_dir_override=output)
    return output, metrics
