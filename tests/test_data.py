from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pandas as pd
import pytest

from heavy_bulky.contracts import ContractViolation, validate_data_bundle
from heavy_bulky.data import build_data_bundle, generate_demand


def test_data_contracts(data_bundle):
    result = validate_data_bundle(data_bundle)
    assert result["passed"] is True
    assert result["planning_order_rows"] > 0
    assert data_bundle.historical_orders["date"].max() < data_bundle.planning_orders["date"].min()


def test_data_generation_is_reproducible(smoke_config):
    first = build_data_bundle(smoke_config)
    second = build_data_bundle(smoke_config)
    pd.testing.assert_frame_equal(first.demand, second.demand)
    pd.testing.assert_frame_equal(first.planning_orders, second.planning_orders)


def test_planning_realized_demand_marked_post_outcome(data_bundle):
    date = data_bundle.planning_orders["date"].min()
    final = data_bundle.demand[pd.to_datetime(data_bundle.demand["date"]).eq(date)]
    assert not final.empty
    assert final["available_at"].eq("post_outcome").all()


def test_bad_duplicate_demand_key_is_rejected(data_bundle):
    duplicate = pd.concat([data_bundle.demand, data_bundle.demand.iloc[[0]]], ignore_index=True)
    with pytest.raises(ContractViolation):
        validate_data_bundle(replace(data_bundle, demand=duplicate))


def test_missing_m5_archive_fails_explicitly(smoke_config, tmp_path):
    cfg = deepcopy(smoke_config)
    cfg["m5_zip"] = str(tmp_path / "missing.zip")
    with pytest.raises(FileNotFoundError, match="M5 archive"):
        generate_demand(cfg)
