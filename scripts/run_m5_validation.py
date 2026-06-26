from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

import yaml

from heavy_bulky.config import load_config, validate_config
from heavy_bulky.pipeline import run_pipeline


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the small M5-pattern validation path")
    parser.add_argument("--m5-zip", required=True)
    parser.add_argument("--config", default="configs/m5_small.yaml")
    parser.add_argument("--output-dir", default="outputs/m5_small")
    args = parser.parse_args()

    archive = Path(args.m5_zip).expanduser().resolve()
    if not archive.exists():
        raise FileNotFoundError(f"M5 archive not found: {archive}")
    config = load_config(args.config)
    config["m5_zip"] = str(archive)
    config["output_dir"] = str(Path(args.output_dir))
    config = validate_config(config)

    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, sort_keys=False)
        temporary_config = Path(handle.name)
    try:
        metrics = run_pipeline(temporary_config)
    finally:
        temporary_config.unlink(missing_ok=True)
    print(yaml.safe_dump({"release": metrics["release"], "rows": metrics["rows"]}))
    return 0 if metrics["release"]["decision"] == "PROMOTE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
