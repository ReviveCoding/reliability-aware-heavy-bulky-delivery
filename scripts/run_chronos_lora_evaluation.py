from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "src"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeError(f"Could not read JSON evidence artifact: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON evidence artifact: {path}") from exc

    if not isinstance(payload, dict):
        raise RuntimeError(f"Evidence artifact must contain a JSON object: {path}")

    return payload


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    temporary_path = path.with_suffix(path.suffix + ".tmp")

    temporary_path.write_text(
        content,
        encoding="utf-8",
    )

    os.replace(temporary_path, path)


def render_markdown(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    protocol = report["temporal_protocol"]

    return "\n".join(
        (
            "# Chronos LoRA Evidence Report",
            "",
            f"- Selected candidate: `{report['selected_candidate']}`",
            (f"- Final refit end: `{protocol['final_refit_data_end']}`"),
            (
                "- Frozen evaluation window: "
                f"`{protocol['frozen_p28_start']}` to "
                f"`{protocol['frozen_p28_end']}`"
            ),
            (f"- Frozen evaluation count: `{protocol['frozen_p28_evaluation_count']}`"),
            "- Automatic promotion: `False`",
            "",
            "## Frozen-window WAPE",
            "",
            "| Model | WAPE |",
            "|---|---:|",
            (f"| LightGBM quantile | {metrics['lightgbm_quantile']['wape']:.8f} |"),
            (f"| Chronos-2 zero-shot | {metrics['chronos2_zero_shot']['wape']:.8f} |"),
            (f"| Chronos-2 final LoRA | {metrics['chronos2_lora_final']['wape']:.8f} |"),
            "",
            "## Claim Boundary",
            "",
            str(report["claim_boundary"]),
            "",
        )
    )


def parse_args(
    argv: Sequence[str] | None = None,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate Chronos LoRA evidence without model loading, GPU "
            "usage, training, inference, or frozen-window scoring."
        )
    )

    parser.add_argument(
        "--p31-summary",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--p31a-summary",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--p32-summary",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--out",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--markdown-out",
        type=Path,
        default=None,
    )

    return parser.parse_args(argv)


def main(
    argv: Sequence[str] | None = None,
) -> int:
    if str(SOURCE_ROOT) not in sys.path:
        sys.path.insert(0, str(SOURCE_ROOT))

    from heavy_bulky.chronos_lora_protocol import (
        validate_evidence_chain,
    )

    args = parse_args(argv)

    report = validate_evidence_chain(
        read_json_object(args.p31_summary),
        read_json_object(args.p31a_summary),
        read_json_object(args.p32_summary),
    )

    report["input_fingerprints"] = {
        "p31_summary_sha256": sha256(args.p31_summary),
        "p31a_summary_sha256": sha256(args.p31a_summary),
        "p32_summary_sha256": sha256(args.p32_summary),
    }

    report["runner_scope"] = (
        "CPU-only evidence validation. No Chronos weights are loaded. "
        "No training, inference, tuning, or frozen-window scoring occurs."
    )

    atomic_write_text(
        args.out,
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
    )

    if args.markdown_out is not None:
        atomic_write_text(
            args.markdown_out,
            render_markdown(report),
        )

    print("CHRONOS_LORA_EVIDENCE_VALIDATION_PASSED")
    print(f"SELECTED_CANDIDATE={report['selected_candidate']}")
    print(
        f"FROZEN_P28_EVALUATION_COUNT={report['temporal_protocol']['frozen_p28_evaluation_count']}"
    )
    print("AUTOMATIC_PROMOTION=False")
    print(f"FINAL_LORA_WAPE={report['metrics']['chronos2_lora_final']['wape']:.8f}")
    print(f"OUT={args.out}")

    if args.markdown_out is not None:
        print(f"MARKDOWN_OUT={args.markdown_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
