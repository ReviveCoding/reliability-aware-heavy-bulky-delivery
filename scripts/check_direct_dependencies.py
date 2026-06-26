from __future__ import annotations

import argparse
import importlib.metadata
from pathlib import Path


def parse_constraints(path: Path) -> dict[str, str]:
    expected: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "==" not in line:
            continue
        name, version = line.split("==", 1)
        expected[name.lower().replace("_", "-")] = version
    return expected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--constraints", default="constraints-verified.txt")
    parser.add_argument(
        "--required",
        nargs="*",
        default=[
            "numpy",
            "pandas",
            "scikit-learn",
            "PyYAML",
            "pydantic",
            "tabulate",
            "lightgbm",
            "ortools",
            "fastapi",
            "uvicorn",
            "duckdb",
            "pytest",
            "pytest-cov",
            "ruff",
            "wheel",
            "httpx2",
            "build",
            "setuptools",
        ],
    )
    args = parser.parse_args()
    expected = parse_constraints(Path(args.constraints))
    failures: list[str] = []
    for distribution in args.required:
        normalized = distribution.lower().replace("_", "-")
        try:
            installed = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            failures.append(f"missing:{distribution}")
            continue
        pinned = expected.get(normalized)
        if pinned and installed != pinned:
            failures.append(f"version:{distribution}:expected={pinned}:installed={installed}")
        print(f"{distribution}=={installed}")
    if failures:
        print("Dependency validation failures:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
