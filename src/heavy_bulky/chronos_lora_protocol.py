from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any

EXPECTED_PROMOTION_STATUS = "EVALUATED_NO_AUTOMATIC_PROMOTION"


class ChronosLoRAProtocolError(ValueError):
    """Raised when Chronos LoRA evidence violates the locked protocol."""


def _object(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ChronosLoRAProtocolError(f"{label} must be a JSON object.")
    return value


def _string(payload: Mapping[str, Any], key: str, label: str) -> str:
    value = payload.get(key)

    if not isinstance(value, str) or not value.strip():
        raise ChronosLoRAProtocolError(f"{label}.{key} must be a non-empty string.")

    return value.strip()


def _finite(payload: Mapping[str, Any], key: str, label: str) -> float:
    try:
        value = float(payload.get(key))
    except (TypeError, ValueError) as exc:
        raise ChronosLoRAProtocolError(f"{label}.{key} must be numeric.") from exc

    if not math.isfinite(value):
        raise ChronosLoRAProtocolError(f"{label}.{key} must be finite.")

    return value


def parse_calendar_date(value: object, label: str) -> date:
    """Parse an ISO-compatible date or timestamp into a calendar date."""
    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    if not isinstance(value, str) or not value.strip():
        raise ChronosLoRAProtocolError(f"{label} must be a non-empty ISO date or timestamp.")

    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).date()
    except ValueError as exc:
        raise ChronosLoRAProtocolError(f"{label} is not an ISO-compatible date: {value!r}") from exc


def _candidate(
    payload: Mapping[str, Any],
    section: str,
    key: str,
) -> str:
    return _string(
        _object(payload.get(section), section),
        key,
        section,
    )


def _wape(metrics: Mapping[str, Any], model_name: str) -> float:
    label = f"metrics.{model_name}"

    return _finite(
        _object(metrics.get(model_name), label),
        "wape",
        label,
    )


def validate_evidence_chain(
    p31_summary: Mapping[str, Any],
    p31a_summary: Mapping[str, Any],
    p32_summary: Mapping[str, Any],
) -> dict[str, Any]:
    """
    Validate P31, P31-A, and P32 consistency without model execution.

    This validates local evidence and frozen-window safeguards only. It does
    not authorize automatic promotion.
    """
    selected_candidates = {
        _candidate(
            p31_summary,
            "development_selected_candidate",
            "selected_candidate_id",
        ),
        _candidate(
            p31a_summary,
            "selected_candidate",
            "candidate_id",
        ),
        _candidate(
            p32_summary,
            "selected_configuration",
            "candidate_id",
        ),
    }

    if len(selected_candidates) != 1:
        raise ChronosLoRAProtocolError("P31, P31-A, and P32 select different LoRA candidates.")

    selected_candidate = selected_candidates.pop()

    protocol = _object(
        p32_summary.get("temporal_protocol"),
        "P32.temporal_protocol",
    )

    final_refit_end = parse_calendar_date(
        protocol.get("final_refit_data_end"),
        "P32.temporal_protocol.final_refit_data_end",
    )

    frozen_start = parse_calendar_date(
        protocol.get("frozen_p28_start"),
        "P32.temporal_protocol.frozen_p28_start",
    )

    frozen_end = parse_calendar_date(
        protocol.get("frozen_p28_end"),
        "P32.temporal_protocol.frozen_p28_end",
    )

    if final_refit_end != frozen_start - timedelta(days=1):
        raise ChronosLoRAProtocolError(
            "Final refit data must end exactly one day before the frozen evaluation window."
        )

    if frozen_end < frozen_start:
        raise ChronosLoRAProtocolError("Frozen evaluation end precedes frozen evaluation start.")

    if protocol.get("frozen_p28_parameter_updates") is not False:
        raise ChronosLoRAProtocolError("Frozen P28 labels must be excluded from parameter updates.")

    if protocol.get("frozen_p28_hyperparameter_selection") is not False:
        raise ChronosLoRAProtocolError(
            "Frozen P28 labels must be excluded from hyperparameter selection."
        )

    if protocol.get("frozen_p28_evaluation_count") != 1:
        raise ChronosLoRAProtocolError("Frozen P28 evaluation count must equal exactly one.")

    if protocol.get("automatic_promotion") is not False:
        raise ChronosLoRAProtocolError("Automatic promotion must remain disabled.")

    if _string(p32_summary, "promotion_status", "P32") != EXPECTED_PROMOTION_STATUS:
        raise ChronosLoRAProtocolError(
            f"P32 promotion status must remain {EXPECTED_PROMOTION_STATUS!r}."
        )

    metrics = _object(p32_summary.get("metrics"), "P32.metrics")

    lightgbm_wape = _wape(metrics, "lightgbm_quantile")
    zero_shot_wape = _wape(metrics, "chronos2_zero_shot")
    final_lora_wape = _wape(metrics, "chronos2_lora_final")

    return {
        "status": "EVIDENCE_VALIDATED_NO_AUTOMATIC_PROMOTION",
        "selected_candidate": selected_candidate,
        "temporal_protocol": {
            "final_refit_data_end": final_refit_end.isoformat(),
            "frozen_p28_start": frozen_start.isoformat(),
            "frozen_p28_end": frozen_end.isoformat(),
            "frozen_p28_evaluation_count": 1,
            "frozen_p28_parameter_updates": False,
            "frozen_p28_hyperparameter_selection": False,
            "automatic_promotion": False,
        },
        "metrics": {
            "lightgbm_quantile": {"wape": lightgbm_wape},
            "chronos2_zero_shot": {"wape": zero_shot_wape},
            "chronos2_lora_final": {"wape": final_lora_wape},
        },
        "wape_deltas": {
            "final_lora_minus_lightgbm": final_lora_wape - lightgbm_wape,
            "final_lora_minus_zero_shot": final_lora_wape - zero_shot_wape,
        },
        "claim_boundary": (
            "Local synthetic/proxy benchmark evidence only. The consumed "
            "P28 frozen window must not be reused for additional tuning "
            "or automatic promotion."
        ),
    }
