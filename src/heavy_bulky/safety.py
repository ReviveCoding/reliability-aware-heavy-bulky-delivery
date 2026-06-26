from __future__ import annotations

import pandas as pd

POST_OUTCOME_COLUMNS = {
    "actual_duration",
    "failed_attempt",
    "failure_probability_true",
}


def planning_decision_view(frame: pd.DataFrame) -> pd.DataFrame:
    """Return the planning-time feature view used by decision modules.

    Outcome labels remain available to offline evaluation and operational replay, but they are
    deliberately removed before route generation and optimization to prevent accidental leakage.
    """
    return frame.drop(columns=[c for c in POST_OUTCOME_COLUMNS if c in frame.columns]).copy()


def assert_no_post_outcome_features(frame: pd.DataFrame) -> None:
    leaked = sorted(POST_OUTCOME_COLUMNS & set(frame.columns))
    if leaked:
        raise ValueError(f"Decision input contains post-outcome fields: {leaked}")
