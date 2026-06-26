from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from heavy_bulky.advanced_service import fit_advanced_service_challenger
from heavy_bulky.config import load_config
from heavy_bulky.data import build_data_bundle
from heavy_bulky.io import write_json
from heavy_bulky.rass import add_rass_features, crossfit_rass_features
from heavy_bulky.service_model import fit_predict_failure_risk


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate the optional multi-task service challenger"
    )
    parser.add_argument("--config", default="configs/smoke.yaml")
    parser.add_argument("--output", default="reports/advanced_service_validation.json")
    parser.add_argument("--epochs", type=int, default=4)
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    args = parser.parse_args()

    cfg = load_config(args.config)
    cfg["advanced_service"].update(
        {
            "enabled": True,
            "epochs": args.epochs,
            "device": args.device,
        }
    )
    started = time.perf_counter()
    data = build_data_bundle(cfg)
    historical = crossfit_rass_features(data.historical_orders, cfg)
    planning = add_rass_features(data.historical_orders, data.planning_orders, cfg)
    baseline = fit_predict_failure_risk(historical, planning, int(cfg["seed"]))
    result = fit_advanced_service_challenger(historical, baseline.planning, cfg)
    payload = {
        "status": result.status,
        "elapsed_seconds": time.perf_counter() - started,
        "metrics": result.metrics,
        "claim_boundary": (
            "Reports the device actually used. A CPU run does not support a CUDA execution claim; "
            "a HOLD result demonstrates that the baseline-first promotion gate remained active."
        ),
    }
    write_json(Path(args.output), payload)
    print(json.dumps(payload, indent=2, allow_nan=False))
    return 0 if result.status in {"promoted", "hold"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
