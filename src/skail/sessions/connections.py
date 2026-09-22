from __future__ import annotations

import sqlite3
import weakref
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Lock


def _close_idle(idle: list[sqlite3.Connection]) -> None:
    while idle:
        idle.pop().close()


class JournalConnections:
    """Exclusive connection leases with at most one idle handle per journal."""

    def __init__(self, path: Path, busy_timeout_ms: int) -> None:
        self.path = path
        self.busy_timeout_ms = busy_timeout_ms
        self._idle: list[sqlite3.Connection] = []
        self._lock = Lock()
        self._generation = 0
        # The callback must not retain this owner, or collection could never close it.
        weakref.finalize(self, _close_idle, self._idle)

    def close(self) -> None:
        """Drain idle handles; outstanding leases close on return. Reopening is allowed."""
        with self._lock:
            self._generation += 1
            _close_idle(self._idle)

    def _open(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=self.busy_timeout_ms / 1_000,
            isolation_level=None,
            check_same_thread=False,
        )
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
        except BaseException:
            connection.close()
            raise
        return connection

    @contextmanager
    def lease(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            generation = self._generation
            connection = self._idle.pop() if self._idle else None
        if connection is None:
            connection = self._open()
        try:
            # Preserve SQLite's commit/rollback context behavior for direct callers.
            with connection:
                yield connection
        except BaseException:
            connection.close()
            raise
        else:
            with self._lock:
                if generation == self._generation and not self._idle:
                    self._idle.append(connection)
                else:
                    connection.close()
