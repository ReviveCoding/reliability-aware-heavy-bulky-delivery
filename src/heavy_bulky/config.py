from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


ForecastCandidate = Literal[
    "seasonal_naive",
    "rolling_mean",
    "lightgbm_quantile",
    "chronos2",
]
RouteStrategy = Literal["nearest", "sweep", "risk_first", "balanced", "skill_clustered"]


class ForecastConfig(StrictModel):
    champion_candidates: list[ForecastCandidate] = Field(
        default_factory=lambda: ["seasonal_naive", "rolling_mean", "lightgbm_quantile"]
    )
    lags: list[int] = Field(default_factory=lambda: [1, 7, 14, 28])
    quantiles: list[float] = Field(default_factory=lambda: [0.1, 0.5, 0.9])
    min_train_days: int = 56
    min_relative_improvement: float = 0.01
    max_worst_series_regression: float = 0.10

    @model_validator(mode="after")
    def validate_forecast(self) -> ForecastConfig:
        if not self.champion_candidates or "seasonal_naive" not in self.champion_candidates:
            raise ValueError("forecast.champion_candidates must include seasonal_naive")
        if len(set(self.champion_candidates)) != len(self.champion_candidates):
            raise ValueError("forecast.champion_candidates must be unique")
        if sorted(self.quantiles) != self.quantiles or any(not 0 < q < 1 for q in self.quantiles):
            raise ValueError("forecast.quantiles must be sorted values strictly between 0 and 1")
        if self.quantiles != [0.1, 0.5, 0.9]:
            raise ValueError(
                "forecast.quantiles must be exactly [0.1, 0.5, 0.9] for the core pipeline"
            )
        if any(lag <= 0 for lag in self.lags) or len(set(self.lags)) != len(self.lags):
            raise ValueError("forecast.lags must be unique positive integers")
        if self.min_train_days <= 0:
            raise ValueError("forecast.min_train_days must be positive")
        if not 0 <= self.min_relative_improvement < 1:
            raise ValueError("forecast.min_relative_improvement must be in [0, 1)")
        if not 0 <= self.max_worst_series_regression < 1:
            raise ValueError("forecast.max_worst_series_regression must be in [0, 1)")
        return self


class RASSConfig(StrictModel):
    min_reference_count: int = 8
    high_confidence_count: int = 30
    shrinkage_strength: float = 20.0

    @model_validator(mode="after")
    def validate_rass(self) -> RASSConfig:
        if self.min_reference_count <= 0:
            raise ValueError("rass.min_reference_count must be positive")
        if self.high_confidence_count < self.min_reference_count:
            raise ValueError("rass.high_confidence_count must be >= min_reference_count")
        if self.shrinkage_strength <= 0:
            raise ValueError("rass.shrinkage_strength must be positive")
        return self


class RoutingConfig(StrictModel):
    strategies: list[RouteStrategy] = Field(
        default_factory=lambda: ["nearest", "sweep", "risk_first", "balanced"]
    )
    max_orders_per_route: int = 7
    route_capacity_cube: float = 850.0
    max_route_weight: float = 1600.0
    max_route_minutes: float = 500.0
    time_window_penalty_per_minute: float = 3.0

    @model_validator(mode="after")
    def validate_routing(self) -> RoutingConfig:
        if not self.strategies or len(set(self.strategies)) != len(self.strategies):
            raise ValueError("routing.strategies must be non-empty and unique")
        positive = [
            self.max_orders_per_route,
            self.route_capacity_cube,
            self.max_route_weight,
            self.max_route_minutes,
        ]
        if any(value <= 0 for value in positive):
            raise ValueError("routing capacities and limits must be positive")
        if self.time_window_penalty_per_minute < 0:
            raise ValueError("routing time-window penalty must be nonnegative")
        return self


class CapacityConfig(StrictModel):
    shift_minutes: int = 480
    reserve_vehicles: int = 1
    reserve_crews: int = 1
    min_resources_per_station: int = 1
    route_fill_rate: float = 0.50
    resource_pool_per_station: int = 8
    install_skill_fraction: float = 0.75

    @model_validator(mode="after")
    def validate_capacity(self) -> CapacityConfig:
        if (
            self.shift_minutes <= 0
            or self.min_resources_per_station <= 0
            or self.resource_pool_per_station <= 0
        ):
            raise ValueError("capacity shift and minimum resources must be positive")
        if self.reserve_vehicles < 0 or self.reserve_crews < 0:
            raise ValueError("capacity reserves must be nonnegative")
        if not 0 < self.route_fill_rate <= 1:
            raise ValueError("capacity.route_fill_rate must be in (0, 1]")
        if not 0 <= self.install_skill_fraction <= 1:
            raise ValueError("capacity.install_skill_fraction must be in [0, 1]")
        return self


class OptimizationConfig(StrictModel):
    solver: Literal["cp_sat"] = "cp_sat"
    time_limit_seconds: float = 3.0
    hard_timeout_seconds: float = 8.0
    num_search_workers: int = 1
    unserved_penalty: float = 5000.0
    overtime_penalty_per_minute: float = 8.0
    risk_penalty: float = 240.0
    time_window_penalty_per_minute: float = 3.0

    @model_validator(mode="after")
    def validate_optimization(self) -> OptimizationConfig:
        if (
            self.time_limit_seconds <= 0
            or self.hard_timeout_seconds <= 0
            or self.num_search_workers <= 0
        ):
            raise ValueError("optimization time limits and workers must be positive")
        if self.hard_timeout_seconds <= self.time_limit_seconds:
            raise ValueError("optimization.hard_timeout_seconds must exceed solver time limit")
        penalties = [
            self.unserved_penalty,
            self.overtime_penalty_per_minute,
            self.risk_penalty,
            self.time_window_penalty_per_minute,
        ]
        if any(value < 0 for value in penalties):
            raise ValueError("optimization penalties must be nonnegative")
        return self


class SimulationCosts(StrictModel):
    minute: float = 1.0
    overtime_minute: float = 8.0
    unserved_order: float = 5000.0
    failed_attempt: float = 240.0
    vehicle_failure: float = 600.0
    crew_absence: float = 800.0

    @model_validator(mode="after")
    def validate_costs(self) -> SimulationCosts:
        if any(value < 0 for value in self.model_dump().values()):
            raise ValueError("simulation costs must be nonnegative")
        return self


class SimulationConfig(StrictModel):
    replications: int = 30
    service_overrun_sigma: float = 0.22
    vehicle_failure_probability: float = 0.02
    crew_absence_probability: float = 0.03
    overtime_threshold_minutes: int = 480
    costs: SimulationCosts = Field(default_factory=SimulationCosts)

    @model_validator(mode="after")
    def validate_simulation(self) -> SimulationConfig:
        if self.replications <= 0 or self.overtime_threshold_minutes <= 0:
            raise ValueError("simulation replications and overtime threshold must be positive")
        if self.service_overrun_sigma < 0:
            raise ValueError("simulation.service_overrun_sigma must be nonnegative")
        probabilities = [self.vehicle_failure_probability, self.crew_absence_probability]
        if any(not 0 <= value <= 1 for value in probabilities):
            raise ValueError("simulation probabilities must be in [0, 1]")
        return self


class AdvancedServiceConfig(StrictModel):
    enabled: bool = False
    device: Literal["auto", "cpu", "cuda"] = "auto"
    epochs: int = 20
    batch_size: int = 128
    hidden_dim: int = 64
    learning_rate: float = 0.001
    validation_days: int = 14
    min_train_rows: int = 200
    min_duration_improvement: float = 0.02
    max_failure_brier_regression: float = 0.05

    @model_validator(mode="after")
    def validate_advanced_service(self) -> AdvancedServiceConfig:
        if any(
            value <= 0
            for value in [
                self.epochs,
                self.batch_size,
                self.hidden_dim,
                self.learning_rate,
                self.validation_days,
                self.min_train_rows,
            ]
        ):
            raise ValueError("advanced_service training values must be positive")
        if not 0 <= self.min_duration_improvement < 1:
            raise ValueError("advanced_service.min_duration_improvement must be in [0, 1)")
        if not 0 <= self.max_failure_brier_regression < 1:
            raise ValueError("advanced_service.max_failure_brier_regression must be in [0, 1)")
        return self


class ReleaseGateConfig(StrictModel):
    hard_constraint_violations: int = 0
    max_interval_coverage_gap: float = 0.20
    max_solver_fallback_rate: float = 0.10
    require_reproducibility: bool = True
    require_sql_validation: bool = True
    max_unserved_rate: float = 0.05
    max_relative_gap: float = 0.20
    max_capacity_shortfall: int = 0
    max_failure_brier: float = 0.20
    max_worst_series_coverage_gap: float = 0.40
    max_rass_p90_coverage_gap: float = 0.20
    max_singleton_route_time_exceptions: int = 0
    require_advanced_service_when_enabled: bool = False

    @model_validator(mode="after")
    def validate_release_gates(self) -> ReleaseGateConfig:
        if any(
            value < 0
            for value in [
                self.hard_constraint_violations,
                self.max_capacity_shortfall,
                self.max_singleton_route_time_exceptions,
            ]
        ):
            raise ValueError("release hard-constraint thresholds must be nonnegative")
        rates = [
            self.max_interval_coverage_gap,
            self.max_solver_fallback_rate,
            self.max_unserved_rate,
            self.max_relative_gap,
            self.max_failure_brier,
            self.max_worst_series_coverage_gap,
            self.max_rass_p90_coverage_gap,
        ]
        if any(not 0 <= value <= 1 for value in rates):
            raise ValueError("release rate thresholds must be in [0, 1]")
        return self


class ProjectConfig(StrictModel):
    seed: int
    mode: Literal["smoke", "full", "test"]
    output_dir: str
    m5_zip: str | None = None
    history_days: int
    validation_days: int
    stations: list[str]
    service_types: list[str]
    orders_per_unit: float = 1.0
    forecast: ForecastConfig = Field(default_factory=ForecastConfig)
    rass: RASSConfig = Field(default_factory=RASSConfig)
    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    capacity: CapacityConfig = Field(default_factory=CapacityConfig)
    optimization: OptimizationConfig = Field(default_factory=OptimizationConfig)
    simulation: SimulationConfig = Field(default_factory=SimulationConfig)
    advanced_service: AdvancedServiceConfig = Field(default_factory=AdvancedServiceConfig)
    release_gates: ReleaseGateConfig = Field(default_factory=ReleaseGateConfig)

    @model_validator(mode="after")
    def validate_project(self) -> ProjectConfig:
        if self.history_days <= max(self.forecast.lags) + self.validation_days:
            raise ValueError("history_days must exceed max forecast lag + validation_days")
        if self.validation_days <= 0:
            raise ValueError("validation_days must be positive")
        if not self.stations or not self.service_types:
            raise ValueError("stations and service_types must be non-empty")
        if len(set(self.stations)) != len(self.stations):
            raise ValueError("stations must be unique")
        if len(set(self.service_types)) != len(self.service_types):
            raise ValueError("service_types must be unique")
        if self.orders_per_unit <= 0:
            raise ValueError("orders_per_unit must be positive")
        minimum_hard_timeout = self.optimization.time_limit_seconds * len(self.stations) + 1.0
        if self.optimization.hard_timeout_seconds < minimum_hard_timeout:
            raise ValueError(
                "optimization.hard_timeout_seconds must cover station-decomposed solver "
                f"budgets; require at least {minimum_hard_timeout:.3g} seconds"
            )
        return self


def _expand_paths(config: dict[str, Any]) -> dict[str, Any]:
    expanded = dict(config)
    expanded["output_dir"] = os.path.expanduser(os.path.expandvars(str(expanded["output_dir"])))
    if expanded.get("m5_zip"):
        expanded["m5_zip"] = os.path.expanduser(os.path.expandvars(str(expanded["m5_zip"])))
    return expanded


def validate_config(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate a config mapping and return a normalized, JSON-serializable dictionary."""
    if not isinstance(raw, dict):
        raise ValueError("Config root must be a mapping")
    return _expand_paths(ProjectConfig.model_validate(raw).model_dump())


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")
    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    return validate_config(raw)
