from __future__ import annotations

from importlib import resources
from pathlib import Path


def package_sql_dir() -> Path:
    return Path(str(resources.files("heavy_bulky").joinpath("sql")))


def package_config_path(mode: str) -> Path:
    if mode not in {"smoke", "full"}:
        raise ValueError(f"Unsupported packaged config mode: {mode}")
    return Path(str(resources.files("heavy_bulky").joinpath("configs", f"{mode}.yaml")))
