from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from heavy_bulky.chronos_adapter import forecast_with_chronos2


def _read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    if path.suffix.lower() in {".parquet", ".pq"}:
        try:
            return pd.read_parquet(path)
        except ImportError as exc:
            raise RuntimeError("Parquet input requires pyarrow or fastparquet") from exc
    raise ValueError(f"Unsupported table format: {path.suffix}")


def _write_table(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".csv":
        frame.to_csv(path, index=False)
        return
    if path.suffix.lower() in {".parquet", ".pq"}:
        try:
            frame.to_parquet(path, index=False)
            return
        except ImportError as exc:
            raise RuntimeError("Parquet output requires pyarrow or fastparquet") from exc
    raise ValueError(f"Unsupported table format: {path.suffix}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the optional Chronos-2 adapter")
    parser.add_argument("--context", required=True)
    parser.add_argument("--future", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--prediction-length", type=int, required=True)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()

    context = _read_table(Path(args.context))
    future = _read_table(Path(args.future))
    prediction = forecast_with_chronos2(
        context,
        future,
        args.prediction_length,
        args.device,
    )
    _write_table(prediction, Path(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
