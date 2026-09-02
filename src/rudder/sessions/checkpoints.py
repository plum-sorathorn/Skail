from __future__ import annotations

import json
import sqlite3
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from rudder.runtime.errors import FrameworkContractError
from rudder.sessions.locking import process_file_lock


class CheckpointUnavailableError(RuntimeError):
    pass


class CheckpointCorruptError(RuntimeError):
    pass


@dataclass(frozen=True)
class CheckpointRecord:
    session_id: str
    checkpoint_id: str
    idempotency_key: str
    status: str
    payload: dict[str, Any]
    live_idempotency_keys: tuple[str, ...]
    created_at: datetime
    checkpoint: dict[str, Any]


class CheckpointStore:
    """Rudder correlation metadata stored beside, but separate from, the journal."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS rudder_checkpoint_refs ("
                "session_id TEXT NOT NULL, checkpoint_id TEXT PRIMARY KEY, "
                "idempotency_key TEXT NOT NULL UNIQUE, status TEXT NOT NULL, "
                "payload_json TEXT NOT NULL, live_keys_json TEXT NOT NULL, "
                "created_at TEXT NOT NULL)"
            )

    @asynccontextmanager
    async def saver(self, session_id: str) -> AsyncIterator[AsyncSqliteSaver]:
        with self.locked(session_id):
            async with AsyncSqliteSaver.from_conn_string(str(self.path)) as saver:
                yield saver

    @contextmanager
    def sync_saver(self, session_id: str) -> Iterator[SqliteSaver]:
        with self.locked(session_id):
            with SqliteSaver.from_conn_string(str(self.path)) as saver:
                yield saver

    @contextmanager
    def locked(self, session_id: str) -> Iterator[None]:
        digest = sha256(session_id.encode("utf-8")).hexdigest()[:24]
        lock_path = self.path.parent / f".rudder-session-{digest}.lock"
        with process_file_lock(lock_path):
            yield

    def record(
        self,
        *,
        session_id: str,
        checkpoint_id: str,
        idempotency_key: str,
        status: str,
        payload: dict[str, Any],
        created_at: datetime,
        live_idempotency_keys: tuple[str, ...] | None = None,
    ) -> None:
        payload_json = json.dumps(payload, sort_keys=True)
        live_keys = tuple(sorted(set(live_idempotency_keys or (idempotency_key,))))
        live_keys_json = json.dumps(live_keys)
        values = (
            session_id,
            checkpoint_id,
            idempotency_key,
            status,
            payload_json,
            live_keys_json,
        )
        with self.locked(session_id):
            with sqlite3.connect(self.path) as connection:
                try:
                    connection.execute(
                        "INSERT INTO rudder_checkpoint_refs VALUES (?,?,?,?,?,?,?)",
                        (*values, created_at.isoformat()),
                    )
                except sqlite3.IntegrityError as exc:
                    row = connection.execute(
                        "SELECT session_id,checkpoint_id,idempotency_key,status,payload_json,"
                        "live_keys_json FROM rudder_checkpoint_refs WHERE idempotency_key=?",
                        (idempotency_key,),
                    ).fetchone()
                    if row is not None and tuple(row) == values:
                        return
                    raise FrameworkContractError(
                        "session.checkpoint_idempotency_conflict",
                        "checkpoint replay conflicts with persisted content",
                        idempotency_key=idempotency_key,
                    ) from exc

    def latest_valid(self, session_id: str) -> CheckpointRecord | None:
        if not self.path.exists():
            raise CheckpointUnavailableError("checkpoint store does not exist")
        try:
            with sqlite3.connect(self.path) as connection:
                row = connection.execute(
                    "SELECT session_id,checkpoint_id,idempotency_key,status,"
                    "payload_json,live_keys_json,created_at "
                    "FROM rudder_checkpoint_refs WHERE session_id=? "
                    "ORDER BY created_at DESC LIMIT 1",
                    (session_id,),
                ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise CheckpointCorruptError("checkpoint store is corrupt") from exc
        if row is None:
            return None
        try:
            payload = json.loads(row[4])
            live_keys_value = json.loads(row[5])
            created_at = datetime.fromisoformat(row[6])
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise CheckpointCorruptError("checkpoint metadata is corrupt") from exc
        if not isinstance(payload, dict):
            raise CheckpointCorruptError("checkpoint payload must be an object")
        if not isinstance(live_keys_value, list) or not all(
            isinstance(value, str) and value for value in live_keys_value
        ):
            raise CheckpointCorruptError("checkpoint live key set is corrupt")
        if row[3] not in {"committed", "interrupted"}:
            raise CheckpointCorruptError("checkpoint metadata status is invalid")
        try:
            with SqliteSaver.from_conn_string(str(self.path)) as saver:
                latest = saver.get_tuple({"configurable": {"thread_id": session_id}})
                referenced = saver.get_tuple(
                    {
                        "configurable": {
                            "thread_id": session_id,
                            "checkpoint_id": row[1],
                        }
                    }
                )
        except (sqlite3.DatabaseError, ValueError, TypeError) as exc:
            raise CheckpointCorruptError("LangGraph checkpoint is unreadable") from exc
        if latest is None or referenced is None:
            raise CheckpointCorruptError("referenced LangGraph checkpoint does not exist")
        latest_id = latest.config.get("configurable", {}).get("checkpoint_id")
        if latest_id != row[1]:
            raise CheckpointCorruptError("checkpoint reference is not the latest session state")
        checkpoint = dict(referenced.checkpoint)
        return CheckpointRecord(
            row[0],
            row[1],
            row[2],
            row[3],
            payload,
            tuple(live_keys_value),
            created_at,
            checkpoint,
        )
