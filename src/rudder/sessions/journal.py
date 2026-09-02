from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from threading import RLock
from typing import Any

from rudder.domain.events import EventEnvelope, SecretRedactor
from rudder.domain.tasks import AttemptStatus, TaskStatus
from rudder.runtime.errors import FrameworkContractError
from rudder.sessions.migrations import apply_migrations


def _now(value: datetime | None = None) -> str:
    return (value or datetime.now(UTC)).isoformat()


def locals_without_self(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if key != "self"}


class JournalBusyError(RuntimeError):
    pass


class JournalIdempotencyError(FrameworkContractError):
    pass


@dataclass(frozen=True)
class RunSnapshot:
    run_id: str
    status: str
    budget_limit_usd: Decimal | None


@dataclass(frozen=True)
class TaskSnapshot:
    task_id: str
    run_id: str
    description: str
    status: TaskStatus
    idempotency_key: str


@dataclass(frozen=True)
class AttemptSnapshot:
    attempt_id: str
    task_id: str
    number: int
    status: AttemptStatus
    idempotency_key: str


@dataclass(frozen=True)
class AssignmentSnapshot:
    assignment_id: str
    attempt_id: str
    provider: str
    model: str
    estimated_cost_usd: Decimal


@dataclass(frozen=True)
class ReservationSnapshot:
    reservation_id: str
    task_id: str | None
    amount_usd: Decimal
    status: str
    idempotency_key: str


@dataclass(frozen=True)
class UsageSnapshot:
    usage_id: str
    task_id: str | None
    amount_usd: Decimal
    authoritative: bool
    idempotency_key: str


@dataclass(frozen=True)
class ApprovalSnapshot:
    approval_id: str
    task_id: str | None
    status: str
    question: str


@dataclass(frozen=True)
class SessionSnapshot:
    session_id: str
    status: str
    runs: tuple[RunSnapshot, ...]
    tasks: tuple[TaskSnapshot, ...]
    attempts: tuple[AttemptSnapshot, ...]
    assignments: tuple[AssignmentSnapshot, ...]
    budget_reservations: tuple[ReservationSnapshot, ...]
    usage_records: tuple[UsageSnapshot, ...]
    approvals: tuple[ApprovalSnapshot, ...]
    events: tuple[EventEnvelope, ...]


class JournalTransaction:
    def __init__(self, connection: sqlite3.Connection, redactor: SecretRedactor) -> None:
        self.connection = connection
        self.redactor = redactor

    def create_session(
        self, session_id: str, title: str, created_at: datetime, status: str = "active"
    ) -> None:
        now = _now(created_at)
        self.connection.execute(
            "INSERT INTO sessions VALUES (?,?,?,?,?)", (session_id, title, status, now, now)
        )

    def create_run(
        self,
        run_id: str,
        session_id: str,
        status: str,
        budget_limit_usd: Decimal | None,
        created_at: datetime,
        idempotency_key: str | None = None,
    ) -> None:
        self.connection.execute(
            "INSERT INTO runs VALUES (?,?,?,?,?,?)",
            (
                run_id,
                session_id,
                status,
                idempotency_key or f"run:{run_id}",
                None if budget_limit_usd is None else format(budget_limit_usd, "f"),
                _now(created_at),
            ),
        )

    def create_task(
        self,
        task_id: str,
        run_id: str,
        description: str,
        status: str,
        idempotency_key: str,
        created_at: datetime,
        fingerprint: str = "unassigned",
    ) -> None:
        now = _now(created_at)
        task_status = TaskStatus(status).value
        values = (task_id, run_id, description, task_status, fingerprint, idempotency_key)
        self._insert_idempotent(
            table="tasks",
            key=idempotency_key,
            columns="task_id,run_id,description,status,fingerprint,idempotency_key",
            values=values,
            insert_values=(*values, now, now),
        )

    def create_attempt(
        self,
        attempt_id: str,
        task_id: str,
        number: int,
        status: str,
        idempotency_key: str,
        created_at: datetime,
    ) -> None:
        attempt_status = AttemptStatus(status).value
        values = (attempt_id, task_id, number, attempt_status, idempotency_key)
        self._insert_idempotent(
            table="attempts",
            key=idempotency_key,
            columns="attempt_id,task_id,attempt_number,status,idempotency_key",
            values=values,
            insert_values=(*values, _now(created_at)),
        )

    def create_assignment(
        self,
        assignment_id: str,
        attempt_id: str,
        provider: str,
        model: str,
        estimated_cost_usd: Decimal,
        created_at: datetime,
        idempotency_key: str | None = None,
    ) -> None:
        key = idempotency_key or f"assignment:{attempt_id}"
        values = (
            assignment_id,
            attempt_id,
            provider,
            model,
            format(estimated_cost_usd, "f"),
            key,
        )
        self._insert_idempotent(
            table="assignments",
            key=key,
            columns="assignment_id,attempt_id,provider,model,estimated_cost_usd,idempotency_key",
            values=values,
            insert_values=(*values, "{}", _now(created_at)),
        )

    def create_reservation(
        self,
        reservation_id: str,
        run_id: str,
        task_id: str | None,
        amount_usd: Decimal,
        status: str,
        idempotency_key: str,
        created_at: datetime,
    ) -> None:
        amount = format(amount_usd, "f")
        values = (reservation_id, run_id, task_id, amount, status, idempotency_key)
        self._insert_idempotent(
            table="budget_reservations",
            key=idempotency_key,
            columns="reservation_id,run_id,task_id,amount_usd,status,idempotency_key",
            values=values,
            insert_values=(*values, _now(created_at)),
        )

    def record_usage(
        self,
        usage_id: str,
        run_id: str,
        task_id: str | None,
        amount_usd: Decimal,
        authoritative: bool,
        idempotency_key: str,
        created_at: datetime,
    ) -> None:
        values = (
            usage_id,
            run_id,
            task_id,
            format(amount_usd, "f"),
            int(authoritative),
            idempotency_key,
        )
        self._insert_idempotent(
            table="usage_records",
            key=idempotency_key,
            columns="usage_id,run_id,task_id,amount_usd,authoritative,idempotency_key",
            values=values,
            insert_values=(*values, _now(created_at)),
        )

    def create_approval(
        self,
        approval_id: str,
        run_id: str,
        task_id: str | None,
        status: str,
        question: str,
        idempotency_key: str,
        created_at: datetime,
    ) -> None:
        values = (approval_id, run_id, task_id, status, question, idempotency_key)
        self._insert_idempotent(
            table="approvals",
            key=idempotency_key,
            columns="approval_id,run_id,task_id,status,question,idempotency_key",
            values=values,
            insert_values=(*values, _now(created_at)),
        )

    def append_event(self, event: EventEnvelope) -> None:
        redacted_event = event.redacted(self.redactor)
        envelope = redacted_event.to_json()
        try:
            self.connection.execute(
                "INSERT INTO events(event_id,run_id,sequence,envelope_json) VALUES (?,?,?,?)",
                (str(event.event_id), str(event.run_id), event.sequence, envelope),
            )
        except sqlite3.IntegrityError as exc:
            row = self.connection.execute(
                "SELECT envelope_json FROM events WHERE event_id=?", (str(event.event_id),)
            ).fetchone()
            if row is not None and row[0] == envelope:
                return
            raise JournalIdempotencyError(
                "session.idempotency_conflict",
                "event replay conflicts with persisted content",
                event_id=str(event.event_id),
            ) from exc

    def _insert_idempotent(
        self,
        *,
        table: str,
        key: str,
        columns: str,
        values: tuple[Any, ...],
        insert_values: tuple[Any, ...],
    ) -> None:
        placeholders = ",".join("?" for _ in insert_values)
        try:
            self.connection.execute(
                f"INSERT INTO {table} VALUES ({placeholders})", insert_values
            )
        except sqlite3.IntegrityError as exc:
            row = self.connection.execute(
                f"SELECT {columns} FROM {table} WHERE idempotency_key=?", (key,)
            ).fetchone()
            if row is not None and tuple(row) == values:
                return
            raise JournalIdempotencyError(
                "session.idempotency_conflict",
                "idempotency key conflicts with persisted content",
                table=table,
                idempotency_key=key,
            ) from exc


class Journal:
    def __init__(
        self,
        path: Path,
        *,
        busy_timeout_ms: int = 5_000,
        max_retries: int = 5,
        redactor: SecretRedactor | None = None,
    ) -> None:
        self.path = path
        self.busy_timeout_ms = busy_timeout_ms
        self.max_retries = max_retries
        self.redactor = redactor or SecretRedactor()
        self._migration_lock = RLock()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path, timeout=self.busy_timeout_ms / 1_000, isolation_level=None
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def migrate(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._migration_lock, self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            connection.commit()
            connection.execute("BEGIN IMMEDIATE")
            try:
                apply_migrations(connection)
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    @contextmanager
    def transaction(self) -> Iterator[JournalTransaction]:
        connection: sqlite3.Connection | None = None
        for attempt in range(self.max_retries + 1):
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                break
            except sqlite3.OperationalError as exc:
                connection.close()
                connection = None
                if "locked" not in str(exc).lower() or attempt >= self.max_retries:
                    raise JournalBusyError("journal remained busy after bounded retries") from exc
                time.sleep(min(0.005 * (attempt + 1), 0.025))
        if connection is None:
            raise JournalBusyError("journal connection was not acquired")
        try:
            yield JournalTransaction(connection, self.redactor)
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()

    def _write(self, method: str, **values: Any) -> None:
        with self.transaction() as transaction:
            getattr(transaction, method)(**values)

    def create_session(
        self, *, session_id: str, title: str, created_at: datetime, status: str = "active"
    ) -> None:
        self._write(
            "create_session",
            session_id=session_id,
            title=title,
            created_at=created_at,
            status=status,
        )

    def create_run(
        self,
        *,
        run_id: str,
        session_id: str,
        status: str,
        budget_limit_usd: Decimal | None,
        created_at: datetime,
        idempotency_key: str | None = None,
    ) -> None:
        self._write(
            "create_run",
            run_id=run_id,
            session_id=session_id,
            status=status,
            budget_limit_usd=budget_limit_usd,
            created_at=created_at,
            idempotency_key=idempotency_key,
        )

    def create_task(
        self,
        *,
        task_id: str,
        run_id: str,
        description: str,
        status: str,
        idempotency_key: str,
        created_at: datetime,
        fingerprint: str = "unassigned",
    ) -> None:
        self._write("create_task", **locals_without_self(locals()))

    def create_attempt(
        self,
        *,
        attempt_id: str,
        task_id: str,
        number: int,
        status: str,
        idempotency_key: str,
        created_at: datetime,
    ) -> None:
        self._write("create_attempt", **locals_without_self(locals()))

    def create_assignment(
        self,
        *,
        assignment_id: str,
        attempt_id: str,
        provider: str,
        model: str,
        estimated_cost_usd: Decimal,
        created_at: datetime,
        idempotency_key: str | None = None,
    ) -> None:
        self._write("create_assignment", **locals_without_self(locals()))

    def create_reservation(
        self,
        *,
        reservation_id: str,
        run_id: str,
        task_id: str | None,
        amount_usd: Decimal,
        status: str,
        idempotency_key: str,
        created_at: datetime,
    ) -> None:
        self._write("create_reservation", **locals_without_self(locals()))

    def record_usage(
        self,
        *,
        usage_id: str,
        run_id: str,
        task_id: str | None,
        amount_usd: Decimal,
        authoritative: bool,
        idempotency_key: str,
        created_at: datetime,
    ) -> None:
        self._write("record_usage", **locals_without_self(locals()))

    def create_approval(
        self,
        *,
        approval_id: str,
        run_id: str,
        task_id: str | None,
        status: str,
        question: str,
        idempotency_key: str,
        created_at: datetime,
    ) -> None:
        self._write("create_approval", **locals_without_self(locals()))

    def append_event(self, *, event: EventEnvelope) -> None:
        self._write("append_event", event=event)

    def get_session_snapshot(self, session_id: str) -> SessionSnapshot:
        with self._connect() as connection:
            session = connection.execute(
                "SELECT session_id,status FROM sessions WHERE session_id=?", (session_id,)
            ).fetchone()
            if session is None:
                raise KeyError(session_id)
            run_rows = connection.execute(
                "SELECT run_id,status,budget_limit_usd FROM runs WHERE session_id=? ORDER BY rowid",
                (session_id,),
            ).fetchall()
            run_ids = tuple(row["run_id"] for row in run_rows)
            if not run_ids:
                return SessionSnapshot(
                    session_id, session["status"], (), (), (), (), (), (), (), ()
                )
            placeholders = ",".join("?" for _ in run_ids)
            tasks = connection.execute(
                f"SELECT task_id,run_id,description,status,idempotency_key FROM tasks "
                f"WHERE run_id IN ({placeholders}) ORDER BY rowid",
                run_ids,
            ).fetchall()
            task_ids = tuple(row["task_id"] for row in tasks)
            task_placeholders = ",".join("?" for _ in task_ids) or "NULL"
            attempts = connection.execute(
                f"SELECT attempt_id,task_id,attempt_number AS number,status,idempotency_key "
                f"FROM attempts WHERE task_id IN ({task_placeholders}) ORDER BY rowid",
                task_ids,
            ).fetchall()
            attempt_ids = tuple(row["attempt_id"] for row in attempts)
            attempt_placeholders = ",".join("?" for _ in attempt_ids) or "NULL"
            assignments = connection.execute(
                f"SELECT assignment_id,attempt_id,provider,model,estimated_cost_usd "
                f"FROM assignments "
                f"WHERE attempt_id IN ({attempt_placeholders}) ORDER BY rowid",
                attempt_ids,
            ).fetchall()
            reservations = connection.execute(
                f"SELECT reservation_id,task_id,amount_usd,status,idempotency_key "
                f"FROM budget_reservations WHERE run_id IN ({placeholders}) ORDER BY rowid",
                run_ids,
            ).fetchall()
            usage = connection.execute(
                f"SELECT usage_id,task_id,amount_usd,authoritative,idempotency_key "
                f"FROM usage_records WHERE run_id IN ({placeholders}) ORDER BY rowid",
                run_ids,
            ).fetchall()
            approvals = connection.execute(
                f"SELECT approval_id,task_id,status,question FROM approvals "
                f"WHERE run_id IN ({placeholders}) ORDER BY rowid",
                run_ids,
            ).fetchall()
            events = connection.execute(
                f"SELECT envelope_json FROM events "
                f"WHERE run_id IN ({placeholders}) ORDER BY rowid",
                run_ids,
            ).fetchall()
        return SessionSnapshot(
            session_id=session["session_id"],
            status=session["status"],
            runs=tuple(
                RunSnapshot(
                    row["run_id"],
                    row["status"],
                    None if row["budget_limit_usd"] is None else Decimal(row["budget_limit_usd"]),
                )
                for row in run_rows
            ),
            tasks=tuple(
                TaskSnapshot(
                    row["task_id"],
                    row["run_id"],
                    row["description"],
                    TaskStatus(row["status"]),
                    row["idempotency_key"],
                )
                for row in tasks
            ),
            attempts=tuple(
                AttemptSnapshot(
                    row["attempt_id"],
                    row["task_id"],
                    row["number"],
                    AttemptStatus(row["status"]),
                    row["idempotency_key"],
                )
                for row in attempts
            ),
            assignments=tuple(
                AssignmentSnapshot(
                    row["assignment_id"],
                    row["attempt_id"],
                    row["provider"],
                    row["model"],
                    Decimal(row["estimated_cost_usd"]),
                )
                for row in assignments
            ),
            budget_reservations=tuple(
                ReservationSnapshot(
                    row["reservation_id"], row["task_id"], Decimal(row["amount_usd"]),
                    row["status"], row["idempotency_key"]
                )
                for row in reservations
            ),
            usage_records=tuple(
                UsageSnapshot(
                    row["usage_id"], row["task_id"], Decimal(row["amount_usd"]),
                    bool(row["authoritative"]), row["idempotency_key"]
                )
                for row in usage
            ),
            approvals=tuple(ApprovalSnapshot(**dict(row)) for row in approvals),
            events=tuple(EventEnvelope.from_json(row["envelope_json"]) for row in events),
        )
