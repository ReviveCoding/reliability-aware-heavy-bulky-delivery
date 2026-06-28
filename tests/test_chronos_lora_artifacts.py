from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

SELECTED_CANDIDATE = "lora_default_lr1e-5_steps128"


def load_runner_module() -> ModuleType:
    runner_path = Path(__file__).resolve().parents[1] / "scripts" / "run_chronos_lora_evaluation.py"

    specification = importlib.util.spec_from_file_location(
        "run_chronos_lora_evaluation",
        runner_path,
    )

    assert specification is not None
    assert specification.loader is not None

    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)

    return module


def write_json(
    path: Path,
    payload: dict[str, object],
) -> None:
    path.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )


def test_runner_writes_validated_json_and_markdown(
    tmp_path: Path,
) -> None:
    p31_path = tmp_path / "p31.json"
    p31a_path = tmp_path / "p31a.json"
    p32_path = tmp_path / "p32.json"

    report_path = tmp_path / "validated.json"
    markdown_path = tmp_path / "validated.md"

    write_json(
        p31_path,
        {
            "development_selected_candidate": {
                "selected_candidate_id": SELECTED_CANDIDATE,
            },
        },
    )

    write_json(
        p31a_path,
        {
            "selected_candidate": {
                "candidate_id": SELECTED_CANDIDATE,
            },
        },
    )

    write_json(
        p32_path,
        {
            "selected_configuration": {
                "candidate_id": SELECTED_CANDIDATE,
            },
            "temporal_protocol": {
                "final_refit_data_end": "2025-12-30T00:00:00",
                "frozen_p28_start": "2025-12-31T00:00:00",
                "frozen_p28_end": "2026-01-27T00:00:00",
                "frozen_p28_evaluation_count": 1,
                "frozen_p28_parameter_updates": False,
                "frozen_p28_hyperparameter_selection": False,
                "automatic_promotion": False,
            },
            "promotion_status": ("EVALUATED_NO_AUTOMATIC_PROMOTION"),
            "metrics": {
                "lightgbm_quantile": {
                    "wape": 0.19688236,
                },
                "chronos2_zero_shot": {
                    "wape": 0.18133250,
                },
                "chronos2_lora_final": {
                    "wape": 0.18074518,
                },
            },
        },
    )

    runner = load_runner_module()

    result = runner.main(
        [
            "--p31-summary",
            str(p31_path),
            "--p31a-summary",
            str(p31a_path),
            "--p32-summary",
            str(p32_path),
            "--out",
            str(report_path),
            "--markdown-out",
            str(markdown_path),
        ]
    )

    assert result == 0
    assert report_path.is_file()
    assert markdown_path.is_file()

    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert report["status"] == "EVIDENCE_VALIDATED_NO_AUTOMATIC_PROMOTION"
    assert report["selected_candidate"] == SELECTED_CANDIDATE
    assert report["temporal_protocol"]["frozen_p28_evaluation_count"] == 1
    assert report["temporal_protocol"]["automatic_promotion"] is False
    assert report["metrics"]["chronos2_lora_final"]["wape"] == 0.18074518

    markdown = markdown_path.read_text(encoding="utf-8")

    assert "Chronos LoRA Evidence Report" in markdown
    assert SELECTED_CANDIDATE in markdown
    assert "Automatic promotion: `False`" in markdown
