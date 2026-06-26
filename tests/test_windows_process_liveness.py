from __future__ import annotations

import os

import pytest

from heavy_bulky import io as io_module


def test_process_alive_rejects_nonpositive_pid() -> None:
    assert io_module._process_alive(0) is False
    assert io_module._process_alive(-1) is False


def test_process_alive_uses_windows_probe_without_os_kill(monkeypatch) -> None:
    observed: list[int] = []

    def fake_windows_probe(pid: int) -> bool:
        observed.append(pid)
        return True

    monkeypatch.setattr(io_module.os, "name", "nt")
    monkeypatch.setattr(
        io_module,
        "_windows_process_alive",
        fake_windows_probe,
    )

    assert io_module._process_alive(4321) is True
    assert observed == [4321]


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific process probe")
def test_windows_process_probe_accepts_current_process() -> None:
    assert io_module._process_alive(os.getpid()) is True
