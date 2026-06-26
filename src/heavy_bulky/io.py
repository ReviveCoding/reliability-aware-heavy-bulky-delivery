from __future__ import annotations

import json
import math
import os
import re
import shutil
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd

LOCK_STALE_GRACE_SECONDS = 60.0


def json_safe(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, set):
        return [json_safe(item) for item in sorted(value, key=lambda item: str(item))]
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return json_safe(value.item())
    if isinstance(value, (pd.Timestamp, pd.Timedelta, Path)):
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _atomic_text_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def write_json(path: str | Path, obj: object) -> None:
    destination = Path(path)
    content = json.dumps(json_safe(obj), indent=2, allow_nan=False)
    _atomic_text_write(destination, content)


def write_csv(path: str | Path, frame: pd.DataFrame) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp"
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="") as handle:
            frame.to_csv(handle, index=False)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(destination)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _lock_owner_pid(lock_path: Path) -> int | None:
    try:
        content = lock_path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"(?:^|\s)pid=(\d+)(?:\s|$)", content)
    return int(match.group(1)) if match else None


def _windows_process_alive(pid: int) -> bool:
    """Return whether *pid* is active using non-destructive Win32 queries."""
    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    still_active = 259
    error_access_denied = 5
    error_invalid_parameter = 87
    error_not_found = 1168

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    kernel32.OpenProcess.argtypes = (
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    )
    kernel32.OpenProcess.restype = wintypes.HANDLE

    kernel32.GetExitCodeProcess.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    )
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL

    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(
        process_query_limited_information,
        False,
        pid,
    )

    if not handle:
        error_code = ctypes.get_last_error()
        if error_code in {error_invalid_parameter, error_not_found}:
            return False

        # A process that cannot be inspected safely must be treated as live.
        return error_code == error_access_denied or error_code != 0

    try:
        exit_code = wintypes.DWORD()

        # Conservatively preserve a lock if process state cannot be queried.
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True

        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False

    if os.name == "nt":
        return _windows_process_alive(pid)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _lock_age_seconds(lock_path: Path) -> float | None:
    try:
        return max(0.0, time.time() - lock_path.stat().st_mtime)
    except OSError:
        return None


def _lock_owned_by_token(lock_path: Path, token: str) -> bool:
    try:
        content = lock_path.read_text(encoding="utf-8")
    except OSError:
        return False
    return re.search(rf"(?:^|\s)token={re.escape(token)}(?:\s|$)", content) is not None


def _recover_stale_publication(final: Path, lock_path: Path) -> bool:
    """Recover artifacts left by an abruptly terminated publisher.

    A parseable lock is recoverable only when its owner process is dead. An empty or
    malformed lock is recoverable only after a grace period, covering the tiny crash
    window between exclusive file creation and metadata persistence without deleting a
    lock that a live publisher may still be initializing.
    """
    owner_pid = _lock_owner_pid(lock_path)
    if owner_pid is not None:
        if _process_alive(owner_pid):
            return False
    else:
        age_seconds = _lock_age_seconds(lock_path)
        if age_seconds is None or age_seconds < LOCK_STALE_GRACE_SECONDS:
            return False

    backups = sorted(
        final.parent.glob(f".{final.name}.previous-*"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not final.exists() and backups:
        backups[0].replace(final)
        backups = backups[1:]
    for path in backups:
        shutil.rmtree(path, ignore_errors=True)
    for path in final.parent.glob(f".{final.name}.staging-*"):
        shutil.rmtree(path, ignore_errors=True)
    lock_path.unlink(missing_ok=True)
    return True


@contextmanager
def staged_run_directory(final_path: str | Path) -> Iterator[Path]:
    """Build a complete run in isolation and publish only after success."""
    final = Path(final_path)
    final.parent.mkdir(parents=True, exist_ok=True)
    run_token = uuid4().hex
    stage = final.parent / f".{final.name}.staging-{run_token}"
    backup = final.parent / f".{final.name}.previous-{run_token}"
    lock_path = final.parent / f".{final.name}.lock"
    try:
        lock_descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        if not _recover_stale_publication(final, lock_path):
            raise RuntimeError(f"Another run is already publishing to {final}") from exc
        lock_descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(lock_descriptor, f"pid={os.getpid()} token={run_token}\n".encode())
    os.fsync(lock_descriptor)
    os.close(lock_descriptor)
    shutil.rmtree(stage, ignore_errors=True)
    shutil.rmtree(backup, ignore_errors=True)
    stage.mkdir(parents=True)
    try:
        yield stage
        (stage / "_SUCCESS").write_text("complete\n", encoding="utf-8")
        if final.exists():
            final.replace(backup)
        stage.replace(final)
        shutil.rmtree(backup, ignore_errors=True)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        if backup.exists() and not final.exists():
            backup.replace(final)
        raise
    finally:
        if _lock_owned_by_token(lock_path, run_token):
            lock_path.unlink(missing_ok=True)
