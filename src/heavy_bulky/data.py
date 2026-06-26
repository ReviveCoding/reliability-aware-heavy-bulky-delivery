from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class DataBundle:
    demand: pd.DataFrame
    historical_orders: pd.DataFrame
    planning_orders: pd.DataFrame
    vehicles: pd.DataFrame
    crews: pd.DataFrame
    provenance: pd.DataFrame
    used_m5: bool


def _m5_patterns(m5_zip: str | Path, history_days: int, n_series: int) -> list[np.ndarray]:
    path = Path(m5_zip)
    if not path.exists():
        raise FileNotFoundError(f"Configured M5 archive not found: {path}")
    with ZipFile(path) as zf, zf.open("sales_train_evaluation.csv") as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8")
        frame = pd.read_csv(text, nrows=max(n_series, 12))
    day_cols = [c for c in frame.columns if c.startswith("d_")]
    if not day_cols:
        raise ValueError("M5 archive sales_train_evaluation.csv has no d_* columns")
    values = frame[day_cols[-history_days:]].to_numpy(dtype=float)
    patterns: list[np.ndarray] = []
    for row in values[:n_series]:
        smooth = pd.Series(row).rolling(7, min_periods=1).mean().to_numpy()
        scale = np.quantile(smooth, 0.8)
        if scale <= 0:
            continue
        patterns.append(smooth / scale)
    return patterns


def generate_demand(cfg: dict) -> tuple[pd.DataFrame, bool]:
    rng = np.random.default_rng(cfg["seed"])
    history_days = int(cfg["history_days"])
    horizon = int(cfg["validation_days"])
    n_total = history_days + horizon
    stations = cfg["stations"]
    service_types = cfg["service_types"]
    n_series = len(stations) * len(service_types)
    patterns = []
    m5_zip = cfg.get("m5_zip")
    if m5_zip:
        patterns = _m5_patterns(m5_zip, n_total, n_series)
    dates = pd.date_range("2025-01-01", periods=n_total, freq="D")
    rows = []
    used_m5 = bool(patterns)
    for idx, (station, service) in enumerate((s, t) for s in stations for t in service_types):
        dow = np.array([d.dayofweek for d in dates])
        weekly = 1.0 + 0.22 * np.sin(2 * np.pi * dow / 7 + idx * 0.4)
        trend = np.linspace(0.92, 1.12 + idx * 0.02, n_total)
        if patterns:
            p = patterns[idx % len(patterns)]
            if len(p) < n_total:
                p = np.resize(p, n_total)
            base = 7.0 + 2.0 * idx
            lam = np.maximum(1.0, base * (0.45 + 0.55 * p[-n_total:]) * weekly * trend)
        else:
            base = 8.0 + 2.5 * idx
            promo = np.where((np.arange(n_total) + idx * 3) % 31 < 3, 1.45, 1.0)
            lam = np.maximum(1.0, base * weekly * trend * promo)
        counts = rng.poisson(lam)
        for date, count in zip(dates, counts, strict=True):
            rows.append(
                {
                    "date": date,
                    "station_id": station,
                    "service_type": service,
                    "demand": int(count),
                    "source_type": "public_pattern_conditioned_synthetic"
                    if used_m5
                    else "assumption_driven_synthetic",
                    "available_at": "post_outcome" if date == dates[-1] else "planning_time",
                }
            )
    return pd.DataFrame(rows), used_m5


def _service_parameters(service_type: str) -> dict[str, float | str]:
    if service_type == "installation":
        return {"cube": 135, "weight": 120, "duration": 92, "skill": "install", "crew_size": 2}
    if service_type == "room_of_choice":
        return {"cube": 105, "weight": 90, "duration": 55, "skill": "general", "crew_size": 2}
    return {"cube": 75, "weight": 55, "duration": 32, "skill": "general", "crew_size": 1}


def generate_orders(demand: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(cfg["seed"] + 7)
    planning_date = demand["date"].max()
    hist_dates = demand.loc[demand["date"] < planning_date, "date"].sort_values().unique()
    sample_hist_dates = hist_dates[-min(len(hist_dates), 70) :]
    rows = []
    order_id = 0
    selected = demand[demand["date"].isin(list(sample_hist_dates) + [planning_date])]
    for rec in selected.itertuples(index=False):
        n = max(0, int(round(rec.demand * cfg.get("orders_per_unit", 1.0))))
        pars = _service_parameters(rec.service_type)
        for _ in range(n):
            order_id += 1
            access = rng.choice(["easy", "stairs", "elevator"], p=[0.56, 0.22, 0.22])
            complexity = {"easy": 0.88, "elevator": 1.05, "stairs": 1.28}[access]
            cube = max(20, rng.normal(pars["cube"], pars["cube"] * 0.22))
            weight = max(15, rng.normal(pars["weight"], pars["weight"] * 0.20))
            base_duration = float(pars["duration"]) * complexity * (0.88 + 0.24 * rng.random())
            actual_duration = max(12, rng.lognormal(np.log(base_duration), 0.18))
            failure_prob = min(
                0.55,
                0.025 + 0.11 * (access == "stairs") + 0.08 * (rec.service_type == "installation"),
            )
            failed_attempt = int(rng.random() < failure_prob)
            lat = rng.normal(0, 1.0) + (0.8 if rec.station_id.endswith("B") else 0)
            lon = rng.normal(0, 1.0) + (0.8 if rec.station_id.endswith("C") else 0)
            window_start = int(rng.choice([0, 60, 120, 180]))
            window_end = window_start + int(rng.choice([180, 240, 300]))
            rows.append(
                {
                    "order_id": f"O{order_id:06d}",
                    "date": pd.Timestamp(rec.date),
                    "station_id": rec.station_id,
                    "service_type": rec.service_type,
                    "cube": round(cube, 2),
                    "weight": round(weight, 2),
                    "access_type": access,
                    "required_skill": pars["skill"],
                    "required_crew_size": int(pars["crew_size"]),
                    "lat": float(lat),
                    "lon": float(lon),
                    "time_window_start": window_start,
                    "time_window_end": window_end,
                    "actual_duration": round(actual_duration, 2),
                    "failed_attempt": failed_attempt,
                    "failure_probability_true": failure_prob,
                    "source_type": "assumption_driven_synthetic",
                    "record_scope": "mixed_fields_see_provenance",
                }
            )
    frame = pd.DataFrame(rows)
    historical = frame[frame["date"] < planning_date].reset_index(drop=True)
    planning = frame[frame["date"] == planning_date].reset_index(drop=True)
    return historical, planning


def generate_resources(cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    vehicle_rows, crew_rows = [], []
    pool_size = int(cfg["capacity"]["resource_pool_per_station"])
    install_count = int(round(pool_size * float(cfg["capacity"]["install_skill_fraction"])))
    large_vehicle_count = max(1, int(round(pool_size * 0.25)))
    single_person_count = max(1, int(round(pool_size * 0.125)))
    for station in cfg["stations"]:
        for i in range(pool_size):
            is_large = i >= pool_size - large_vehicle_count
            vehicle_rows.append(
                {
                    "vehicle_id": f"{station}_V{i}",
                    "station_id": station,
                    "cube_capacity": 1200 if is_large else 900,
                    "weight_capacity": 1600 if is_large else 1100,
                    "available": 1,
                }
            )
        for i in range(pool_size):
            crew_rows.append(
                {
                    "crew_id": f"{station}_C{i}",
                    "station_id": station,
                    "skill": "install" if i < install_count else "general",
                    "crew_size": 1 if i >= pool_size - single_person_count else 2,
                    "max_minutes": 520,
                    "available": 1,
                }
            )
    return pd.DataFrame(vehicle_rows), pd.DataFrame(crew_rows)


def provenance_registry() -> pd.DataFrame:
    records = [
        (
            "historical_demand",
            "public_pattern_conditioned_or_assumption_driven_synthetic",
            "planning_time",
            "proxy",
        ),
        (
            "planning_day_realized_demand",
            "public_pattern_conditioned_or_assumption_driven_synthetic",
            "post_outcome",
            "offline_evaluation_only",
        ),
        ("cube", "assumption_driven_synthetic", "planning_time", "assumption_dependent"),
        ("weight", "assumption_driven_synthetic", "planning_time", "assumption_dependent"),
        ("required_skill", "assumption_driven_synthetic", "planning_time", "assumption_dependent"),
        ("access_type", "assumption_driven_synthetic", "planning_time", "assumption_dependent"),
        (
            "time_window_start",
            "assumption_driven_synthetic",
            "planning_time",
            "assumption_dependent",
        ),
        ("time_window_end", "assumption_driven_synthetic", "planning_time", "assumption_dependent"),
        ("actual_duration", "assumption_driven_synthetic", "post_outcome", "simulation_only"),
        ("failed_attempt", "assumption_driven_synthetic", "post_outcome", "simulation_only"),
        (
            "failure_probability_true",
            "assumption_driven_synthetic",
            "post_outcome",
            "simulation_only",
        ),
        ("predicted_failure_probability", "model_output", "planning_time", "offline_model_output"),
    ]
    return pd.DataFrame(
        records, columns=["field_name", "source_type", "available_at", "claim_scope"]
    )


def build_data_bundle(cfg: dict) -> DataBundle:
    demand, used_m5 = generate_demand(cfg)
    historical, planning = generate_orders(demand, cfg)
    vehicles, crews = generate_resources(cfg)
    return DataBundle(demand, historical, planning, vehicles, crews, provenance_registry(), used_m5)
