from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import aiosqlite
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from rudder.runtime.errors import FrameworkContractError
from rudder.sessions.locking import process_file_lock


class RedactingSerializer:
    def __init__(self, serde: Any, redactor: Any = None) -> None:
        self._serde = serde
        self._redactor = redactor

    def dumps_typed(self, obj: Any) -> tuple[str, bytes]:
        if self._redactor is not None:
            obj = self._redactor.scrub(obj)
        return cast(tuple[str, bytes], self._serde.dumps_typed(obj))

    def loads_typed(self, data: tuple[str, bytes]) -> Any:
        return self._serde.loads_typed(data)


_LOCAL_CHECKPOINT_LOCKS = threading.local()


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

    def __init__(self, path: Path, *, redactor: Any = None) -> None:
        self.path = path
        self.redactor = redactor

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        try:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS rudder_checkpoint_refs ("
                "session_id TEXT NOT NULL, checkpoint_id TEXT PRIMARY KEY, "
                "idempotency_key TEXT NOT NULL UNIQUE, status TEXT NOT NULL, "
                "payload_json TEXT NOT NULL, live_keys_json TEXT NOT NULL, "
                "created_at TEXT NOT NULL)"
            )
        finally:
            connection.close()

    @asynccontextmanager
    async def saver(self, session_id: str) -> AsyncIterator[AsyncSqliteSaver]:
        with self.locked(session_id):
            serde = (
                RedactingSerializer(JsonPlusSerializer(), self.redactor)
                if self.redactor
                else None
            )
            async with aiosqlite.connect(str(self.path)) as conn:
                saver_instance = AsyncSqliteSaver(conn, serde=serde)
                await saver_instance.setup()
                yield saver_instance

    @contextmanager
    def sync_saver(self, session_id: str) -> Iterator[SqliteSaver]:
        with self.locked(session_id):
            serde = (
                RedactingSerializer(JsonPlusSerializer(), self.redactor)
                if self.redactor
                else None
            )
            conn = sqlite3.connect(str(self.path), check_same_thread=False)
            try:
                saver_instance = SqliteSaver(conn, serde=serde)
                saver_instance.setup()
                yield saver_instance
            finally:
                conn.close()

    @contextmanager
    def locked(self, session_id: str) -> Iterator[None]:
        held: set[str] | None = getattr(_LOCAL_CHECKPOINT_LOCKS, "held", None)
        if held is None:
            held = set()
            _LOCAL_CHECKPOINT_LOCKS.held = held

        if session_id in held:
            yield
            return

        digest = sha256(session_id.encode("utf-8")).hexdigest()[:24]
        lock_path = self.path.parent / f".rudder-session-{digest}.lock"
        with process_file_lock(lock_path):
            held.add(session_id)
            try:
                yield
            finally:
                held.discard(session_id)

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
        payload_data = (
            self.redactor.scrub(payload) if self.redactor is not None else payload
        )
        payload_json = json.dumps(payload_data, sort_keys=True)
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
            connection = sqlite3.connect(self.path)
            try:
                try:
                    connection.execute(
                        "INSERT INTO rudder_checkpoint_refs VALUES (?,?,?,?,?,?,?)",
                        (*values, created_at.isoformat()),
                    )
                    connection.commit()
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
            finally:
                connection.close()

    def latest_valid(self, session_id: str) -> CheckpointRecord | None:
        if not self.path.exists():
            raise CheckpointUnavailableError("checkpoint store does not exist")
        try:
            connection = sqlite3.connect(self.path)
            try:
                row = connection.execute(
                    "SELECT session_id,checkpoint_id,idempotency_key,status,"
                    "payload_json,live_keys_json,created_at "
                    "FROM rudder_checkpoint_refs WHERE session_id=? "
                    "ORDER BY created_at DESC LIMIT 1",
                    (session_id,),
                ).fetchone()
            finally:
                connection.close()
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
