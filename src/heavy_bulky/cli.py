from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import sys
from pathlib import Path

from . import __version__
from .config import load_config
from .integrity import validate_published_run
from .io import json_safe
from .pipeline import run_pipeline


def _capabilities() -> dict[str, object]:
    optional = {
        name: importlib.util.find_spec(name) is not None
        for name in ["lightgbm", "ortools", "duckdb", "fastapi", "torch", "chronos"]
    }
    cuda_available = False
    if optional["torch"]:
        try:
            import torch

            cuda_available = bool(torch.cuda.is_available())
        except Exception:
            cuda_available = False
    return {
        "package_version": __version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "optional_dependencies": optional,
        "cuda_available": cuda_available,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Heavy-bulky delivery reliability benchmark")
    parser.add_argument("--version", action="version", version=f"heavy-bulky {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    full = subparsers.add_parser("full-pipeline", help="Run the end-to-end benchmark")
    full.add_argument("--config", required=True)
    full.add_argument("--output-dir", help="Override config output_dir")

    validate = subparsers.add_parser("validate-config", help="Validate and normalize a YAML config")
    validate.add_argument("--config", required=True)

    verify = subparsers.add_parser("verify-output", help="Verify a published pipeline output")
    verify.add_argument("--output-dir", required=True)

    subparsers.add_parser("capabilities", help="Report optional runtime capabilities")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    exit_code = 0
    try:
        if args.command == "full-pipeline":
            payload = run_pipeline(args.config, output_dir_override=args.output_dir)
        elif args.command == "validate-config":
            payload = load_config(args.config)
        elif args.command == "verify-output":
            output = Path(args.output_dir)
            problems = validate_published_run(output)
            payload = {"output": str(output), "valid": not problems, "problems": problems}
            exit_code = 0 if not problems else 1
        else:
            payload = _capabilities()
        print(json.dumps(json_safe(payload), indent=2, allow_nan=False))
        raise SystemExit(exit_code)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
