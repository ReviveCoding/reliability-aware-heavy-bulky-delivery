from __future__ import annotations

from copy import deepcopy

import pytest

from heavy_bulky.chronos_lora_protocol import (
    ChronosLoRAProtocolError,
    validate_evidence_chain,
)

SELECTED_CANDIDATE = "lora_default_lr1e-5_steps128"


def evidence_payloads() -> tuple[dict[str, object], ...]:
    p31 = {
        "development_selected_candidate": {
            "selected_candidate_id": SELECTED_CANDIDATE,
        },
    }

    p31a = {
        "selected_candidate": {
            "candidate_id": SELECTED_CANDIDATE,
        },
    }

    p32 = {
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
        "promotion_status": "EVALUATED_NO_AUTOMATIC_PROMOTION",
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
    }

    return p31, p31a, p32


def test_valid_evidence_chain_preserves_no_promotion() -> None:
    p31, p31a, p32 = evidence_payloads()

    report = validate_evidence_chain(
        p31,
        p31a,
        p32,
    )

    assert report["status"] == "EVIDENCE_VALIDATED_NO_AUTOMATIC_PROMOTION"
    assert report["selected_candidate"] == SELECTED_CANDIDATE
    assert report["temporal_protocol"]["frozen_p28_evaluation_count"] == 1
    assert report["temporal_protocol"]["automatic_promotion"] is False
    assert report["metrics"]["chronos2_lora_final"]["wape"] == pytest.approx(0.18074518)


def test_rejects_candidate_mismatch() -> None:
    p31, p31a, p32 = evidence_payloads()
    invalid_p32 = deepcopy(p32)

    invalid_p32["selected_configuration"] = {
        "candidate_id": "lora_default_lr1e-5_steps64",
    }

    with pytest.raises(
        ChronosLoRAProtocolError,
        match="different LoRA candidates",
    ):
        validate_evidence_chain(
            p31,
            p31a,
            invalid_p32,
        )


@pytest.mark.parametrize(
    ("field_name", "invalid_value", "message"),
    (
        (
            "frozen_p28_parameter_updates",
            True,
            "parameter updates",
        ),
        (
            "frozen_p28_hyperparameter_selection",
            True,
            "hyperparameter selection",
        ),
        (
            "frozen_p28_evaluation_count",
            2,
            "evaluation count",
        ),
        (
            "automatic_promotion",
            True,
            "Automatic promotion",
        ),
    ),
)
def test_rejects_frozen_window_protocol_violations(
    field_name: str,
    invalid_value: object,
    message: str,
) -> None:
    p31, p31a, p32 = evidence_payloads()
    invalid_p32 = deepcopy(p32)

    protocol = invalid_p32["temporal_protocol"]

    assert isinstance(protocol, dict)

    protocol[field_name] = invalid_value

    with pytest.raises(
        ChronosLoRAProtocolError,
        match=message,
    ):
        validate_evidence_chain(
            p31,
            p31a,
            invalid_p32,
        )


def test_rejects_non_adjacent_final_refit_boundary() -> None:
    p31, p31a, p32 = evidence_payloads()
    invalid_p32 = deepcopy(p32)

    protocol = invalid_p32["temporal_protocol"]

    assert isinstance(protocol, dict)

    protocol["final_refit_data_end"] = "2025-12-29"

    with pytest.raises(
        ChronosLoRAProtocolError,
        match="exactly one day before",
    ):
        validate_evidence_chain(
            p31,
            p31a,
            invalid_p32,
        )


def test_rejects_invalid_promotion_status() -> None:
    p31, p31a, p32 = evidence_payloads()
    invalid_p32 = deepcopy(p32)

    invalid_p32["promotion_status"] = "PROMOTED"

    with pytest.raises(
        ChronosLoRAProtocolError,
        match="promotion status",
    ):
        validate_evidence_chain(
            p31,
            p31a,
            invalid_p32,
        )
