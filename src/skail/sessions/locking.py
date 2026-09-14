from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO


class FileLockBusyError(TimeoutError):
    pass


@contextmanager
def process_file_lock(path: Path, timeout_sec: float | None = None) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        _acquire_lock(handle, timeout_sec=timeout_sec)
        try:
            yield
        finally:
            _unlock(handle)


def _acquire_lock(handle: BinaryIO, timeout_sec: float | None = None) -> None:
    handle.seek(0)
    start_time = time.monotonic()
    while True:
        try:
            _lock(handle, non_blocking=True)
            return
        except OSError as exc:
            if timeout_sec is not None and time.monotonic() - start_time >= timeout_sec:
                raise FileLockBusyError("failed to acquire file lock within timeout") from exc
            time.sleep(0.01)


def _lock(handle: BinaryIO, non_blocking: bool = False) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        if handle.read(1) == b"":
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        mode = msvcrt.LK_NBLCK if non_blocking else msvcrt.LK_LOCK
        msvcrt.locking(handle.fileno(), mode, 1)
    else:
        import fcntl

        flags = fcntl.LOCK_EX | (fcntl.LOCK_NB if non_blocking else 0)  # type: ignore[attr-defined]
        fcntl.flock(handle.fileno(), flags)  # type: ignore[attr-defined]


def _unlock(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]
