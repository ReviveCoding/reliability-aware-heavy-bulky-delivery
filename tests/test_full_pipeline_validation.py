from __future__ import annotations

from scripts.full_pipeline_validation import (
    decision_value_contract_problems,
)


def test_contract_allows_lowest_cost_to_differ_from_champion() -> None:
    problems = decision_value_contract_problems(
        {
            "selected_champion_policy": "greedy",
            "lowest_expected_cost_evaluated_candidate": "deterministic",
        },
        champion="greedy",
    )

    assert problems == []


def test_contract_rejects_selected_champion_mismatch() -> None:
    problems = decision_value_contract_problems(
        {
            "selected_champion_policy": "deterministic",
            "lowest_expected_cost_evaluated_candidate": "deterministic",
        },
        champion="greedy",
    )

    assert problems == ["selected_champion_policy_mismatch:deterministic!=greedy"]


def test_contract_rejects_missing_lowest_cost_candidate() -> None:
    problems = decision_value_contract_problems(
        {
            "selected_champion_policy": "greedy",
        },
        champion="greedy",
    )

    assert problems == ["invalid_lowest_expected_cost_evaluated_candidate:None"]


def test_contract_rejects_missing_selected_champion() -> None:
    problems = decision_value_contract_problems(
        {
            "lowest_expected_cost_evaluated_candidate": "deterministic",
        },
        champion="greedy",
    )

    assert problems == ["invalid_selected_champion_policy:None"]
