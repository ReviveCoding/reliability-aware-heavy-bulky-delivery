from __future__ import annotations

import argparse
import pickle
from pathlib import Path

from .optimization import _solve_plan_partitioned_native


def main() -> None:
    parser = argparse.ArgumentParser(description="Isolated OR-Tools solver worker")
    parser.add_argument("request")
    parser.add_argument("response")
    args = parser.parse_args()
    request_path = Path(args.request)
    response_path = Path(args.response)
    with request_path.open("rb") as handle:
        payload = pickle.load(handle)
    result = _solve_plan_partitioned_native(
        payload["routes"],
        payload["members"],
        payload["orders"],
        payload["vehicles"],
        payload["crews"],
        payload["cfg"],
    )
    temporary = response_path.with_suffix(".tmp")
    with temporary.open("wb") as handle:
        pickle.dump(result, handle, protocol=pickle.HIGHEST_PROTOCOL)
    temporary.replace(response_path)


if __name__ == "__main__":
    main()
