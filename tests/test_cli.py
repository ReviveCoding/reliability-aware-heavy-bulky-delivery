from __future__ import annotations

import sys

import pytest

from heavy_bulky import __version__
from heavy_bulky.cli import main


def test_cli_version_flag(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["heavy-bulky", "--version"])
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert f"heavy-bulky {__version__}" in captured.out
