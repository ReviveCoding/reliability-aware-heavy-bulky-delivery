"""Optional Chronos-2 adapter.

Not executed in the CPU smoke pipeline. It follows the current unified predict_df API and
keeps model download/GPU requirements out of the core reproducibility path.
"""

from __future__ import annotations

import pandas as pd


def forecast_with_chronos2(
    context_df: pd.DataFrame,
    future_df: pd.DataFrame,
    prediction_length: int,
    device_map: str = "cuda",
) -> pd.DataFrame:
    try:
        from chronos import Chronos2Pipeline
    except ImportError as exc:
        raise RuntimeError("Install optional dependencies: pip install -e '.[chronos]'") from exc
    pipeline = Chronos2Pipeline.from_pretrained("amazon/chronos-2", device_map=device_map)
    return pipeline.predict_df(
        context_df,
        future_df=future_df,
        prediction_length=prediction_length,
        quantile_levels=[0.1, 0.5, 0.9],
        id_column="id",
        timestamp_column="timestamp",
        target="target",
    )
