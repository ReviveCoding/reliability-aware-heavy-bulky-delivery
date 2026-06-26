from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from heavy_bulky import api


def test_windows_path_budget_allows_short_output_root(
    tmp_path: Path,
) -> None:
    api._validate_windows_output_path_budget(
        tmp_path / "a6",
        is_windows=True,
    )


def test_windows_path_budget_rejects_deep_output_root() -> None:
    deep_root = Path("C:/") / ("x" * 190)

    with pytest.raises(HTTPException) as raised:
        api._validate_windows_output_path_budget(
            deep_root,
            is_windows=True,
        )

    assert raised.value.status_code == 422
    assert "too deep" in str(raised.value.detail).lower()
