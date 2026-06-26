from __future__ import annotations

from copy import deepcopy

import numpy as np
import pytest

from heavy_bulky.advanced_service import fit_advanced_service_challenger
from heavy_bulky.rass import rass_ablation_metrics, rass_metrics
from heavy_bulky.safety import assert_no_post_outcome_features


def test_rass_outputs_and_quality(service_bundle, data_bundle, smoke_config):
    _, planning, _, _ = service_bundle
    needed = {
        "reference_effective_sample_size",
        "reference_confidence",
        "predicted_duration",
        "duration_p90",
        "rass_burden",
    }
    assert needed.issubset(planning.columns)
    assert (planning["duration_p90"] >= planning["predicted_duration"]).all()
    metrics = rass_metrics(planning)
    assert metrics["duration_mae"] >= 0
    assert 0 <= metrics["reference_fallback_rate"] <= 1
    ablation = rass_ablation_metrics(data_bundle.historical_orders, planning, smoke_config)
    assert {"global_median", "random_reference", "unshrunk_similarity", "shrunk_rass"}.issubset(
        set(ablation["method"])
    )


def test_planning_decision_view_removes_post_outcomes(service_bundle):
    _, planning, decision, _ = service_bundle
    assert {"actual_duration", "failed_attempt", "failure_probability_true"}.isdisjoint(
        decision.columns
    )
    assert_no_post_outcome_features(decision)
    with pytest.raises(ValueError, match="post-outcome"):
        assert_no_post_outcome_features(planning)


def test_failure_probabilities_are_bounded(service_bundle):
    _, planning, _, metrics = service_bundle
    assert planning["predicted_failure_probability"].between(0.001, 0.999).all()
    value = metrics["validation_brier"]
    assert np.isnan(value) or 0 <= value <= 1


def test_advanced_service_disabled_is_explicit(service_bundle, smoke_config):
    historical, planning, _, _ = service_bundle
    cfg = deepcopy(smoke_config)
    cfg["advanced_service"]["enabled"] = False
    result = fit_advanced_service_challenger(historical, planning, cfg)
    assert result.status == "disabled"
    assert result.planning.equals(planning)
