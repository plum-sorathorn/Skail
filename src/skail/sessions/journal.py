from __future__ import annotations

import json
import logging
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from threading import RLock, local
from typing import Any

from skail.domain.changesets import ChangeSet, ChangeSetStatus
from skail.domain.events import EventEnvelope, PlanPayload, SecretRedactor
from skail.domain.ids import (
    EventId,
    RunId,
    SessionId,
    ensure_uuid4,
    new_event_id,
    new_plan_id,
    new_plan_node_id,
)
from skail.domain.plans import (
    SUPPORTED_EXECUTION_POLICY_VERSION,
    SUPPORTED_PLAN_SCHEMA_VERSION,
    EffectScope,
    ExecutionPlan,
    PlanNode,
    PlanNodeKind,
    PlanNodeState,
    PlanRevision,
)
from skail.domain.strategy_estimates import (
    OutcomeObservation,
    StrategyObservationScope,
    StrategyObservationSnapshot,
    observation_snapshot,
)
from skail.domain.tasks import AttemptStatus, TaskStatus
from skail.runtime.errors import FrameworkContractError
from skail.sessions.connections import JournalConnections
from skail.sessions.migrations import apply_migrations

_LOGGER = logging.getLogger(__name__)


def _now(value: datetime | None = None) -> str:
    return (value or datetime.now(UTC)).isoformat()


def locals_without_self(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if key != "self"}


def _event_callback(
    observer: Callable[[EventEnvelope], None], event: EventEnvelope
) -> Callable[[], None]:
    return lambda: observer(event)


class JournalBusyError(RuntimeError):
    pass


class JournalIdempotencyError(FrameworkContractError):
    pass


@dataclass(frozen=True)
class RunSnapshot:
    run_id: str
    status: str
    budget_limit_usd: Decimal | None
    plan_schema_version: int | None = None
    execution_policy_version: str | None = None


@dataclass(frozen=True)
class PersistedPlan:
    plan_id: str
    run_id: str
    plan: ExecutionPlan
    node_ids: dict[str, str]
    node_states: dict[str, PlanNodeState] = field(default_factory=dict)


@dataclass(frozen=True)
class PlanNodeSnapshot:
    node_id: str
    local_id: str
    state: PlanNodeState


@dataclass(frozen=True)
class PlanNodeTaskBinding:
    node_id: str
    task_id: str
    attempt_id: str


@dataclass(frozen=True)
class PlanNodeExecution:
    node_id: str
    execution_key: str
    status: str
    result: dict[str, Any] | None


@dataclass(frozen=True)
class PersistedChangeSet:
    changeset: ChangeSet
    status: ChangeSetStatus


def _run_snapshot(row: sqlite3.Row) -> RunSnapshot:
    schema_version = row["plan_schema_version"]
    policy_version = row["execution_policy_version"]
    if schema_version is not None and schema_version != SUPPORTED_PLAN_SCHEMA_VERSION:
        raise FrameworkContractError(
            "plan.schema_unsupported", "stored run plan schema is unsupported"
        )
    if policy_version is not None and policy_version != SUPPORTED_EXECUTION_POLICY_VERSION:
        raise FrameworkContractError(
            "plan.policy_unsupported", "stored run execution policy is unsupported"
        )
    return RunSnapshot(
        row["run_id"],
        row["status"],
        None if row["budget_limit_usd"] is None else Decimal(row["budget_limit_usd"]),
        schema_version,
        policy_version,
    )


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
    payload: dict[str, Any]


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
class ContextPacketSnapshot:
    packet_id: str
    run_id: str
    task_id: str | None
    attempt_id: str | None
    payload: dict[str, Any]


@dataclass(frozen=True)
class SessionSummary:
    session_id: str
    title: str
    status: str
    created_at: str
    updated_at: str


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
    context_packets: tuple[ContextPacketSnapshot, ...] = ()
    plans: tuple[PersistedPlan, ...] = ()
    changesets: tuple[PersistedChangeSet, ...] = ()
    execution_decisions: tuple[Any, ...] = ()
    title: str = ""
    created_at: str = ""
    updated_at: str = ""


class JournalTransaction:
    def __init__(self, connection: sqlite3.Connection, redactor: Any) -> None:
        self.connection = connection
        self.redactor = redactor
        self.after_commit_callbacks: list[Callable[[], None]] = []

    def after_commit(self, callback: Callable[[], None]) -> None:
        self.after_commit_callbacks.append(callback)

    def create_session(
        self, session_id: str, title: str, created_at: datetime, status: str = "active"
    ) -> None:
        now = _now(created_at)
        self.connection.execute(
            "INSERT INTO sessions VALUES (?,?,?,?,?)", (session_id, title, status, now, now)
        )

    def record_changeset(
        self,
        *,
        changeset: ChangeSet,
        idempotency_key: str,
        created_at: datetime,
    ) -> None:
        payload = self.redactor.scrub(changeset.model_dump(mode="json"))
        if ChangeSet.model_validate(payload).content_digest != changeset.content_digest:
            raise ValueError("changeset.payload_redacted")
        payload_json = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        )
        self._insert_idempotent(
            table="change_sets",
            key=idempotency_key,
            columns="changeset_id,task_id,attempt_id,snapshot_id,base_head,content_digest,status,payload_json",
            values=(
                changeset.changeset_id,
                changeset.task_id,
                changeset.attempt_id,
                changeset.snapshot_id,
                changeset.base_head,
                changeset.content_digest,
                ChangeSetStatus.CAPTURED.value,
                payload_json,
            ),
            insert_values=(
                changeset.changeset_id,
                changeset.task_id,
                changeset.attempt_id,
                changeset.snapshot_id,
                changeset.base_head,
                changeset.content_digest,
                ChangeSetStatus.CAPTURED.value,
                payload_json,
                idempotency_key,
                _now(created_at),
                _now(created_at),
            ),
        )

    def transition_changeset_status(
        self,
        *,
        changeset_id: str,
        expected: ChangeSetStatus,
        target: ChangeSetStatus,
        operation_id: str,
        updated_at: datetime,
    ) -> None:
        ensure_uuid4(operation_id)
        allowed = {
            ChangeSetStatus.CAPTURED: {ChangeSetStatus.APPLYING, ChangeSetStatus.BLOCKED},
            ChangeSetStatus.APPLYING: {
                ChangeSetStatus.IN_DOUBT,
                ChangeSetStatus.INTEGRATED,
                ChangeSetStatus.BLOCKED,
            },
            ChangeSetStatus.IN_DOUBT: {ChangeSetStatus.INTEGRATED, ChangeSetStatus.BLOCKED},
        }
        if target not in allowed.get(expected, set()):
            raise ValueError("changeset.transition_invalid")
        row = self.connection.execute(
            "SELECT changeset_id,expected_status,target_status,content_digest "
            "FROM change_set_operations WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
        changeset = self.connection.execute(
            "SELECT content_digest,status FROM change_sets WHERE changeset_id=?",
            (changeset_id,),
        ).fetchone()
        if changeset is None:
            raise KeyError(changeset_id)
        values = (changeset_id, expected.value, target.value, changeset["content_digest"])
        if row is not None:
            if tuple(row) != values:
                raise JournalIdempotencyError(
                    "session.idempotency_conflict",
                    "changeset operation conflicts with persisted content",
                    table="change_set_operations",
                    idempotency_key=operation_id,
                )
            return
        if changeset["status"] != expected.value:
            raise ValueError("changeset.transition_conflict")
        self.connection.execute(
            "UPDATE change_sets SET status=?,updated_at=? WHERE changeset_id=?",
            (target.value, _now(updated_at), changeset_id),
        )
        self.connection.execute(
            "INSERT INTO change_set_operations VALUES (?,?,?,?,?,?)",
            (operation_id, *values, _now(updated_at)),
        )

    def begin_changeset_apply(
        self, *, changeset: ChangeSet, operation_id: str, updated_at: datetime
    ) -> None:
        self.transition_changeset_status(
            changeset_id=changeset.changeset_id,
            expected=ChangeSetStatus.CAPTURED,
            target=ChangeSetStatus.APPLYING,
            operation_id=operation_id,
            updated_at=updated_at,
        )
        for item in changeset.paths:
            self.connection.execute(
                "INSERT INTO change_set_file_operations VALUES (?,?,?,?,?,?)",
                (
                    changeset.changeset_id,
                    item.path,
                    item.before.digest if item.before else None,
                    item.after.digest if item.after else None,
                    "intended",
                    _now(updated_at),
                ),
            )

    def mark_changeset_file_applied(
        self, *, changeset_id: str, path: str, updated_at: datetime
    ) -> None:
        cursor = self.connection.execute(
            "UPDATE change_set_file_operations SET status=?,updated_at=? "
            "WHERE changeset_id=? AND path=? AND status='intended'",
            ("applied", _now(updated_at), changeset_id, path),
        )
        if cursor.rowcount != 1:
            raise ValueError("changeset.file_operation_conflict")

    def update_session_status(
        self, session_id: str, status: str, updated_at: datetime | None = None
    ) -> None:
        now = _now(updated_at or datetime.now(UTC))
        cursor = self.connection.execute(
            "UPDATE sessions SET status=?, updated_at=? WHERE session_id=?",
            (status, now, session_id),
        )
        if cursor.rowcount == 0:
            raise KeyError(session_id)

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
            "INSERT INTO runs("
            "run_id,session_id,status,idempotency_key,budget_limit_usd,created_at"
            ") "
            "VALUES (?,?,?,?,?,?)",
            (
                run_id,
                session_id,
                status,
                idempotency_key or f"run:{run_id}",
                None if budget_limit_usd is None else format(budget_limit_usd, "f"),
                _now(created_at),
            ),
        )

    def update_run_status(self, run_id: str, status: str) -> None:
        cursor = self.connection.execute(
            "UPDATE runs SET status=? WHERE run_id=?", (status, run_id)
        )
        if cursor.rowcount == 0:
            raise KeyError(run_id)

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
        scrubbed_desc = (
            self.redactor.scrub_text(description)
            if hasattr(self.redactor, "scrub_text")
            else str(self.redactor.scrub(description))
        )
        values = (task_id, run_id, scrubbed_desc, task_status, fingerprint, idempotency_key)
        self._insert_idempotent(
            table="tasks",
            key=idempotency_key,
            columns="task_id,run_id,description,status,fingerprint,idempotency_key",
            values=values,
            insert_values=(*values, now, now),
        )

    def update_task_status(self, task_id: str, status: TaskStatus) -> None:
        cursor = self.connection.execute(
            "UPDATE tasks SET status=?,updated_at=? WHERE task_id=?",
            (status.value, _now(), task_id),
        )
        if cursor.rowcount == 0:
            raise KeyError(task_id)

    def ensure_task(
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
        scrubbed_desc = (
            self.redactor.scrub_text(description)
            if hasattr(self.redactor, "scrub_text")
            else str(self.redactor.scrub(description))
        )
        values = (task_id, run_id, scrubbed_desc, task_status, fingerprint, idempotency_key)
        try:
            self._insert_idempotent(
                table="tasks",
                key=idempotency_key,
                columns="task_id,run_id,description,status,fingerprint,idempotency_key",
                values=values,
                insert_values=(*values, now, now),
            )
        except JournalIdempotencyError:
            row = self.connection.execute(
                "SELECT task_id FROM tasks WHERE idempotency_key=?", (idempotency_key,)
            ).fetchone()
            if row is None or str(row[0]) != task_id:
                raise
            # Same task_id (e.g. the queued launch insert already persisted it): this
            # repeat persist is a status transition, not a conflicting replay.
            self.connection.execute(
                "UPDATE tasks SET status=?,fingerprint=?,updated_at=? WHERE task_id=?",
                (task_status, fingerprint, now, task_id),
            )

    def record_task_result(self, task_id: str, payload: dict[str, Any]) -> None:
        payload_json = json.dumps(
            self.redactor.scrub(payload), sort_keys=True, separators=(",", ":")
        )
        self.connection.execute(
            "INSERT INTO task_results(task_id,payload_json,updated_at) VALUES (?,?,?) "
            "ON CONFLICT(task_id) DO UPDATE SET payload_json=excluded.payload_json,"
            "updated_at=excluded.updated_at",
            (task_id, payload_json, _now()),
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

    def update_attempt_status(self, attempt_id: str, status: AttemptStatus) -> None:
        cursor = self.connection.execute(
            "UPDATE attempts SET status=?,updated_at=? WHERE attempt_id=?",
            (status.value, _now(), attempt_id),
        )
        if cursor.rowcount == 0:
            raise KeyError(attempt_id)

    def create_assignment(
        self,
        assignment_id: str,
        attempt_id: str,
        provider: str,
        model: str,
        estimated_cost_usd: Decimal,
        created_at: datetime,
        idempotency_key: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        key = idempotency_key or f"assignment:{attempt_id}"
        payload_json = json.dumps(
            self.redactor.scrub(payload or {}), sort_keys=True, separators=(",", ":")
        )
        values = (
            assignment_id,
            attempt_id,
            provider,
            model,
            format(estimated_cost_usd, "f"),
            key,
            payload_json,
        )
        self._insert_idempotent(
            table="assignments",
            key=key,
            columns=(
                "assignment_id,attempt_id,provider,model,estimated_cost_usd,"
                "idempotency_key,payload_json"
            ),
            values=values,
            insert_values=(
                *values,
                _now(created_at),
            ),
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
        purpose: str = "task_attempt",
    ) -> None:
        amount = format(amount_usd, "f")
        values = (reservation_id, run_id, task_id, amount, status, idempotency_key, purpose)
        self._insert_idempotent(
            table="budget_reservations",
            key=idempotency_key,
            columns=("reservation_id,run_id,task_id,amount_usd,status,idempotency_key,purpose"),
            values=values,
            insert_values=(*values[:-1], _now(created_at), purpose),
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
            insert_columns=(
                "usage_id,run_id,task_id,amount_usd,authoritative,idempotency_key,created_at"
            ),
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
        scrubbed_q = (
            self.redactor.scrub_text(question)
            if hasattr(self.redactor, "scrub_text")
            else str(self.redactor.scrub(question))
        )
        values = (approval_id, run_id, task_id, status, scrubbed_q, idempotency_key)
        self._insert_idempotent(
            table="approvals",
            key=idempotency_key,
            columns="approval_id,run_id,task_id,status,question,idempotency_key",
            values=values,
            insert_values=(*values, _now(created_at)),
        )

    def create_context_packet(
        self,
        packet_id: str,
        run_id: str,
        task_id: str | None,
        attempt_id: str | None,
        payload: dict[str, Any],
        idempotency_key: str,
        created_at: datetime,
    ) -> None:
        payload_json = json.dumps(
            self.redactor.scrub(payload), sort_keys=True, separators=(",", ":")
        )
        values = (
            packet_id, run_id, task_id, attempt_id, payload_json, idempotency_key
        )
        self._insert_idempotent(
            table="context_packets",
            key=idempotency_key,
            columns=(
                "packet_id,run_id,task_id,attempt_id,payload_json,idempotency_key"
            ),
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
        insert_columns: str | None = None,
    ) -> None:
        placeholders = ",".join("?" for _ in insert_values)
        target = table if insert_columns is None else f"{table} ({insert_columns})"
        try:
            self.connection.execute(f"INSERT INTO {target} VALUES ({placeholders})", insert_values)
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
        redactor: Any = None,
    ) -> None:
        self.path = path
        self.busy_timeout_ms = busy_timeout_ms
        self.max_retries = max_retries
        self.redactor = redactor or SecretRedactor()
        self._migration_lock = RLock()
        self._transactions = local()
        self._connections = JournalConnections(path, busy_timeout_ms)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with self._connections.lease() as connection:
            yield connection

    def close(self) -> None:
        """Release retained connections without interrupting active transactions."""
        self._connections.close()

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
                self._backfill_plan_node_states(connection)
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def record_outcome_observation(
        self, observation: OutcomeObservation, *, idempotency_key: str
    ) -> None:
        payload_json = json.dumps(
            self.redactor.scrub(observation.model_dump(mode="json")),
            sort_keys=True,
            separators=(",", ":"),
        )
        values = (
            observation.observation_id,
            observation.work_family,
            observation.provider_revision,
            observation.harness_revision,
            observation.authority.value,
            observation.strategy.value,
            _now(observation.recorded_at),
            payload_json,
            idempotency_key,
        )
        with self.transaction() as transaction:
            try:
                transaction.connection.execute(
                    "INSERT INTO strategy_observations VALUES (?,?,?,?,?,?,?,?,?)", values
                )
            except sqlite3.IntegrityError as exc:
                existing = transaction.connection.execute(
                    "SELECT observation_id,work_family,provider_revision,harness_revision,"
                    "authority,"
                    "strategy,recorded_at,payload_json,idempotency_key FROM strategy_observations "
                    "WHERE idempotency_key=?",
                    (idempotency_key,),
                ).fetchone()
                if existing is not None and tuple(existing) == values:
                    return
                raise JournalIdempotencyError(
                    "session.idempotency_conflict",
                    "outcome observation replay conflicts with persisted content",
                    table="strategy_observations",
                    idempotency_key=idempotency_key,
                ) from exc

    def strategy_observation_snapshot(
        self, scope: StrategyObservationScope, *, limit: int = 500
    ) -> StrategyObservationSnapshot:
        if not 1 <= limit <= 1_000:
            raise ValueError("strategy observation snapshot limit must be between 1 and 1000")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM strategy_observations WHERE work_family=? "
                "AND provider_revision=? AND harness_revision=? AND authority=? "
                "ORDER BY recorded_at,observation_id LIMIT ?",
                (
                    scope.work_family,
                    scope.provider_revision,
                    scope.harness_revision,
                    scope.authority.value,
                    limit,
                ),
            ).fetchall()
        observations = tuple(
            OutcomeObservation.model_validate(json.loads(row["payload_json"])) for row in rows
        )
        return observation_snapshot(scope, observations)

    @staticmethod
    def _backfill_plan_node_states(connection: sqlite3.Connection) -> None:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='plan_node_states'"
        ).fetchone()
        if table is None:
            return
        plans = connection.execute(
            "SELECT plan_id,payload_json FROM execution_plans"
        ).fetchall()
        for plan_row in plans:
            plan = ExecutionPlan.model_validate_json(plan_row["payload_json"])
            nodes = connection.execute(
                "SELECT node_id,local_id FROM plan_nodes "
                "WHERE plan_id=? AND retired_revision IS NULL ORDER BY rowid",
                (plan_row["plan_id"],),
            ).fetchall()
            by_local_id = {node.local_id: node for node in plan.nodes}
            for node_row in nodes:
                node = by_local_id[node_row["local_id"]]
                state = (
                    PlanNodeState.READY if not node.depends_on else PlanNodeState.WAITING
                )
                connection.execute(
                    "INSERT OR IGNORE INTO plan_node_states VALUES (?,?,?)",
                    (node_row["node_id"], state.value, _now()),
                )

    @contextmanager
    def transaction(self) -> Iterator[JournalTransaction]:
        active = getattr(self._transactions, "active", None)
        if active is not None:
            nested_connection, transaction, depth = active
            savepoint = f"skail_nested_{depth}"
            callback_count = len(transaction.after_commit_callbacks)
            nested_connection.execute(f"SAVEPOINT {savepoint}")
            self._transactions.active = (nested_connection, transaction, depth + 1)
            try:
                yield transaction
            except BaseException:
                nested_connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                nested_connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                del transaction.after_commit_callbacks[callback_count:]
                raise
            else:
                nested_connection.execute(f"RELEASE SAVEPOINT {savepoint}")
            finally:
                self._transactions.active = active
            return
        for attempt in range(self.max_retries + 1):
            with self._connect() as connection:
                try:
                    connection.execute("BEGIN IMMEDIATE")
                except sqlite3.OperationalError as exc:
                    if "locked" not in str(exc).lower() or attempt >= self.max_retries:
                        raise JournalBusyError(
                            "journal remained busy after bounded retries"
                        ) from exc
                    time.sleep(min(0.005 * (attempt + 1), 0.025))
                    continue
                transaction = JournalTransaction(connection, self.redactor)
                self._transactions.active = (connection, transaction, 1)
                try:
                    yield transaction
                except BaseException:
                    connection.rollback()
                    raise
                else:
                    connection.commit()
                    for callback in transaction.after_commit_callbacks:
                        callback()
                finally:
                    self._transactions.active = None
                return
        raise JournalBusyError("journal connection was not acquired")

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

    def update_session_status(
        self, *, session_id: str, status: str, updated_at: datetime | None = None
    ) -> None:
        self._write(
            "update_session_status",
            session_id=session_id,
            status=status,
            updated_at=updated_at,
        )

    def list_sessions(self) -> tuple[SessionSummary, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT session_id, title, status, created_at, updated_at "
                "FROM sessions ORDER BY created_at DESC"
            ).fetchall()
            return tuple(
                SessionSummary(
                    session_id=row["session_id"],
                    title=row["title"],
                    status=row["status"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
                for row in rows
            )

    def get_session_record(self, session_id: str) -> SessionSummary:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT session_id, title, status, created_at, updated_at "
                "FROM sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
            if row is None:
                raise KeyError(session_id)
            return SessionSummary(
                session_id=row["session_id"],
                title=row["title"],
                status=row["status"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
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

    def update_run_status(self, *, run_id: str, status: str) -> None:
        self._write("update_run_status", run_id=run_id, status=status)

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

    def update_task_status(self, *, task_id: str, status: TaskStatus) -> None:
        self._write("update_task_status", task_id=task_id, status=status)

    def ensure_task(
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
        self._write("ensure_task", **locals_without_self(locals()))

    def record_task_result(self, *, task_id: str, payload: dict[str, Any]) -> None:
        self._write("record_task_result", task_id=task_id, payload=payload)

    def record_changeset(
        self,
        *,
        changeset: ChangeSet,
        idempotency_key: str,
        created_at: datetime | None = None,
    ) -> None:
        self._write(
            "record_changeset",
            changeset=changeset,
            idempotency_key=idempotency_key,
            created_at=created_at or datetime.now(UTC),
        )

    def get_changeset(self, changeset_id: str) -> PersistedChangeSet:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json,status,content_digest FROM change_sets WHERE changeset_id=?",
                (changeset_id,),
            ).fetchone()
        if row is None:
            raise KeyError(changeset_id)
        changeset = ChangeSet.model_validate_json(row["payload_json"])
        if changeset.content_digest != row["content_digest"]:
            raise ValueError("changeset.persistence_corrupt")
        return PersistedChangeSet(changeset=changeset, status=ChangeSetStatus(row["status"]))

    def transition_changeset_status(
        self,
        *,
        changeset_id: str,
        expected: ChangeSetStatus,
        target: ChangeSetStatus,
        operation_id: str,
        updated_at: datetime | None = None,
    ) -> None:
        self._write(
            "transition_changeset_status",
            changeset_id=changeset_id,
            expected=expected,
            target=target,
            operation_id=operation_id,
            updated_at=updated_at or datetime.now(UTC),
        )

    def begin_changeset_apply(
        self, *, changeset: ChangeSet, operation_id: str, updated_at: datetime | None = None
    ) -> None:
        self._write(
            "begin_changeset_apply",
            changeset=changeset,
            operation_id=operation_id,
            updated_at=updated_at or datetime.now(UTC),
        )

    def mark_changeset_file_applied(
        self, *, changeset_id: str, path: str, updated_at: datetime | None = None
    ) -> None:
        self._write(
            "mark_changeset_file_applied",
            changeset_id=changeset_id,
            path=path,
            updated_at=updated_at or datetime.now(UTC),
        )

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

    def update_attempt_status(self, *, attempt_id: str, status: AttemptStatus) -> None:
        self._write("update_attempt_status", attempt_id=attempt_id, status=status)

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
        payload: dict[str, Any] | None = None,
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
        purpose: str = "task_attempt",
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

    def create_context_packet(
        self,
        *,
        packet_id: str,
        run_id: str,
        task_id: str | None,
        attempt_id: str | None,
        payload: dict[str, Any],
        idempotency_key: str,
        created_at: datetime,
    ) -> None:
        self._write("create_context_packet", **locals_without_self(locals()))

    def append_event(self, *, event: EventEnvelope) -> None:
        self._write("append_event", event=event)

    def events_after(self, *, run_id: str, cursor: int = 0) -> tuple[EventEnvelope, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT envelope_json FROM events WHERE run_id=? AND sequence>? ORDER BY sequence",
                (run_id, cursor),
            ).fetchall()
        return tuple(EventEnvelope.from_json(row["envelope_json"]) for row in rows)

    def admit_plan(
        self,
        *,
        run_id: str,
        plan: ExecutionPlan,
        event_observer: Callable[[EventEnvelope], None] | None = None,
        authorized_effects: frozenset[EffectScope] = frozenset({EffectScope.READ}),
    ) -> PersistedPlan:
        if plan.schema_version != SUPPORTED_PLAN_SCHEMA_VERSION:
            raise FrameworkContractError(
                "plan.schema_unsupported", "execution plan schema is unsupported"
            )
        if plan.policy_version != SUPPORTED_EXECUTION_POLICY_VERSION:
            raise FrameworkContractError(
                "plan.policy_unsupported", "execution policy version is unsupported"
            )
        if plan.revision != 1:
            raise FrameworkContractError(
                "plan.initial_revision_invalid", "initial plan revision must be one"
            )
        if any(node.effect_scope not in authorized_effects for node in plan.nodes):
            raise FrameworkContractError(
                "plan.effect_unauthorized", "execution plan requests an unauthorized effect"
            )
        plan_id = str(new_plan_id())
        node_ids = {node.local_id: str(new_plan_node_id()) for node in plan.nodes}
        payload = json.dumps(
            self.redactor.scrub(plan.model_dump(mode="json")),
            sort_keys=True,
            separators=(",", ":"),
        )
        now = _now()
        with self.transaction() as transaction:
            connection = transaction.connection
            run = connection.execute(
                "SELECT session_id FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if run is None:
                raise KeyError(run_id)
            if connection.execute(
                "SELECT 1 FROM execution_plans WHERE run_id=?", (run_id,)
            ).fetchone():
                raise FrameworkContractError(
                    "plan.already_admitted", "run already has an execution plan"
                )
            connection.execute(
                "INSERT INTO execution_plans VALUES (?,?,?,?,?,?,?)",
                (plan_id, run_id, plan.schema_version, plan.policy_version, 1, payload, now),
            )
            for node in plan.nodes:
                node_payload = json.dumps(
                    self.redactor.scrub(node.model_dump(mode="json")),
                    sort_keys=True,
                    separators=(",", ":"),
                )
                connection.execute(
                    "INSERT INTO plan_nodes(node_id,plan_id,local_id,payload_json,created_at) "
                    "VALUES (?,?,?,?,?)",
                    (node_ids[node.local_id], plan_id, node.local_id, node_payload, now),
                )
                state = PlanNodeState.READY if not node.depends_on else PlanNodeState.WAITING
                connection.execute(
                    "INSERT INTO plan_node_states VALUES (?,?,?)",
                    (node_ids[node.local_id], state.value, now),
                )
            connection.execute(
                "INSERT INTO plan_revisions VALUES (?,?,?,?,?)",
                (plan_id, 1, 0, payload, now),
            )
            connection.execute(
                "UPDATE runs SET plan_schema_version=?,execution_policy_version=? WHERE run_id=?",
                (plan.schema_version, plan.policy_version, run_id),
            )
            sequence = int(
                connection.execute(
                    "SELECT COALESCE(MAX(sequence),0) FROM events WHERE run_id=?", (run_id,)
                ).fetchone()[0]
            )
            event_values = [
                ("plan.admitted", None),
                *(("plan.node_admitted", node_id) for node_id in node_ids.values()),
            ]
            for event_type, node_id in event_values:
                sequence += 1
                event = EventEnvelope(
                    event_id=EventId(str(new_event_id())),
                    session_id=SessionId(run["session_id"]),
                    run_id=RunId(run_id),
                    sequence=sequence,
                    occurred_at=datetime.now(UTC),
                    type=event_type,
                    payload=PlanPayload(
                        action=event_type.split(".", 1)[1],
                        plan_id=plan_id,
                        revision=plan.revision,
                        node_id=node_id,
                    ),
                )
                transaction.append_event(event)
                if event_observer is not None:
                    transaction.after_commit(_event_callback(event_observer, event))
        return PersistedPlan(
            plan_id=plan_id,
            run_id=run_id,
            plan=plan,
            node_ids=node_ids,
            node_states={
                node.local_id: (
                    PlanNodeState.READY if not node.depends_on else PlanNodeState.WAITING
                )
                for node in plan.nodes
            },
        )

    def get_plan(self, plan_id: str) -> PersistedPlan:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT run_id,schema_version,policy_version,payload_json FROM execution_plans "
                "WHERE plan_id=?",
                (plan_id,),
            ).fetchone()
            if row is None:
                raise KeyError(plan_id)
            if row["schema_version"] != SUPPORTED_PLAN_SCHEMA_VERSION:
                raise FrameworkContractError(
                    "plan.schema_unsupported", "stored execution plan schema is unsupported"
                )
            if row["policy_version"] != SUPPORTED_EXECUTION_POLICY_VERSION:
                raise FrameworkContractError(
                    "plan.policy_unsupported", "stored execution policy is unsupported"
                )
            nodes = connection.execute(
                "SELECT n.local_id,n.node_id,s.status FROM plan_nodes n "
                "JOIN plan_node_states s ON s.node_id=n.node_id "
                "WHERE n.plan_id=? AND n.retired_revision IS NULL ORDER BY n.rowid",
                (plan_id,),
            ).fetchall()
        return PersistedPlan(
            plan_id=plan_id,
            run_id=row["run_id"],
            plan=ExecutionPlan.model_validate_json(row["payload_json"]),
            node_ids={item["local_id"]: item["node_id"] for item in nodes},
            node_states={
                item["local_id"]: PlanNodeState(item["status"])
                for item in nodes
            },
        )

    def ready_plan_nodes(self, plan_id: str) -> tuple[PlanNodeSnapshot, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT n.node_id,n.local_id,s.status FROM plan_nodes n "
                "JOIN plan_node_states s ON s.node_id=n.node_id "
                "WHERE n.plan_id=? AND n.retired_revision IS NULL AND s.status=? ORDER BY n.rowid",
                (plan_id, PlanNodeState.READY.value),
            ).fetchall()
        return tuple(
            PlanNodeSnapshot(
                node_id=row["node_id"],
                local_id=row["local_id"],
                state=PlanNodeState(row["status"]),
            )
            for row in rows
        )

    def bind_plan_node_task(
        self, *, node_id: str, task_id: str, attempt_id: str
    ) -> PlanNodeTaskBinding:
        with self.transaction() as transaction:
            try:
                transaction.connection.execute(
                    "INSERT INTO plan_node_task_bindings VALUES (?,?,?,?)",
                    (node_id, task_id, attempt_id, _now()),
                )
            except sqlite3.IntegrityError as error:
                raise FrameworkContractError(
                    "plan.node_task_binding_conflict",
                    "plan node already has a task binding",
                ) from error
        return PlanNodeTaskBinding(node_id, task_id, attempt_id)

    def plan_node_task_binding(self, node_id: str) -> PlanNodeTaskBinding | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT node_id,task_id,attempt_id FROM plan_node_task_bindings WHERE node_id=?",
                (node_id,),
            ).fetchone()
        return None if row is None else PlanNodeTaskBinding(**dict(row))

    def begin_plan_node_execution(
        self, *, node_id: str, execution_key: str
    ) -> PlanNodeExecution:
        now = _now()
        with self.transaction() as transaction:
            row = transaction.connection.execute(
                "SELECT execution_key,status,result_json FROM plan_node_executions WHERE node_id=?",
                (node_id,),
            ).fetchone()
            if row is None:
                transaction.connection.execute(
                    "INSERT INTO plan_node_executions VALUES (?,?,?,?,?,?)",
                    (node_id, execution_key, "running", None, now, now),
                )
                return PlanNodeExecution(node_id, execution_key, "running", None)
            if row["execution_key"] != execution_key:
                raise FrameworkContractError(
                    "plan.node_execution_conflict",
                    "plan node execution identity did not match the persisted launch",
                )
            return PlanNodeExecution(
                node_id,
                execution_key,
                row["status"],
                None if row["result_json"] is None else json.loads(row["result_json"]),
            )

    def plan_node_execution(self, node_id: str) -> PlanNodeExecution | None:
        """Return the persisted execution row for a node, if the dispatch pump began it."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT execution_key,status,result_json FROM plan_node_executions WHERE node_id=?",
                (node_id,),
            ).fetchone()
        if row is None:
            return None
        return PlanNodeExecution(
            node_id,
            row["execution_key"],
            row["status"],
            None if row["result_json"] is None else json.loads(row["result_json"]),
        )

    def settle_plan_node_execution(self, *, node_id: str, result: dict[str, Any]) -> None:
        payload = json.dumps(self.redactor.scrub(result), sort_keys=True, separators=(",", ":"))
        with self.transaction() as transaction:
            row = transaction.connection.execute(
                "SELECT status FROM plan_node_executions WHERE node_id=?", (node_id,)
            ).fetchone()
            if row is None:
                _LOGGER.debug(
                    "plan node execution %s: not launched; settle is a no-op", node_id
                )
                return
            if row["status"] == "settled":
                return
            transaction.connection.execute(
                "UPDATE plan_node_executions SET status='settled',result_json=?,updated_at=? "
                "WHERE node_id=?",
                (payload, _now(), node_id),
            )

    def retry_approved_plan_tool(self, *, plan_id: str, node_id: str) -> None:
        """Return one approval-blocked tool node to READY without replaying an effect."""
        with self.transaction() as transaction:
            row = transaction.connection.execute(
                "SELECT status FROM plan_node_states WHERE node_id=?", (node_id,)
            ).fetchone()
            if row is None or row["status"] != PlanNodeState.BLOCKED.value:
                raise FrameworkContractError(
                    "plan.node_not_approval_blocked", "plan tool is not blocked"
                )
            transaction.connection.execute(
                "DELETE FROM plan_node_executions WHERE node_id=?", (node_id,)
            )
            transaction.connection.execute(
                "UPDATE plan_node_states SET status=?,updated_at=? WHERE node_id=?",
                (PlanNodeState.READY.value, _now(), node_id),
            )

    def reconcile_plan_node_executions(
        self,
        *,
        exclude_node_ids: frozenset[str] = frozenset(),
        include_node_ids: frozenset[str] = frozenset(),
    ) -> tuple[PlanNodeSnapshot, ...]:
        """Finish durable settlements and block ambiguous launches without replaying them.

        Nodes in ``exclude_node_ids`` (already admitted by this resume) are left
        untouched so fresh LAUNCHING work is never reconciled to BLOCKED.
        When ``include_node_ids`` is non-empty it mirrors that allowlist: only
        the listed node_ids are considered; when it is empty nothing is
        filtered.
        """
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT n.plan_id,n.node_id,s.status,e.status AS execution_status,e.result_json "
                "FROM plan_nodes n JOIN plan_node_states s ON s.node_id=n.node_id "
                "LEFT JOIN plan_node_executions e ON e.node_id=n.node_id "
                "WHERE n.retired_revision IS NULL "
                "AND s.status IN ('launching','running') ORDER BY n.rowid"
            ).fetchall()
        reconciled: list[PlanNodeSnapshot] = []
        for row in rows:
            if include_node_ids and row["node_id"] not in include_node_ids:
                continue
            if row["node_id"] in exclude_node_ids:
                continue
            state = PlanNodeState(row["status"])
            if row["execution_status"] == "settled" and row["result_json"] is not None:
                result = json.loads(row["result_json"])
                target = {
                    "succeeded": PlanNodeState.SUCCEEDED,
                    "cancelled": PlanNodeState.CANCELLED,
                    "blocked": PlanNodeState.BLOCKED,
                    "budget_blocked": PlanNodeState.BLOCKED,
                }.get(result.get("status"), PlanNodeState.FAILED)
            else:
                target = PlanNodeState.BLOCKED
            if state is PlanNodeState.LAUNCHING and target is not PlanNodeState.BLOCKED:
                self.transition_plan_node_state(
                    plan_id=row["plan_id"], node_id=row["node_id"],
                    expected=PlanNodeState.LAUNCHING, target=PlanNodeState.RUNNING,
                )
                state = PlanNodeState.RUNNING
            reconciled.extend(
                self.transition_plan_node_state(
                    plan_id=row["plan_id"], node_id=row["node_id"],
                    expected=state, target=target,
                )
            )
        return tuple(reconciled)

    @staticmethod
    def _scrub_blocked_text(redactor: Any, value: str) -> str:
        try:
            scrubbed: Any = (
                redactor.scrub(value) if hasattr(redactor, "scrub") else value
            )
        except Exception:
            scrubbed = value
        text = scrubbed if isinstance(scrubbed, str) else str(scrubbed)
        return text.strip()[:500] or "unexplained_block"

    def _blocked_reason(
        self, connection: sqlite3.Connection, node_id: str
    ) -> str:
        """Redacted reason for a blocked node, or a sentinel if unknown."""
        try:
            row = connection.execute(
                "SELECT result_json FROM plan_node_executions WHERE node_id=?",
                (node_id,),
            ).fetchone()
            result_json = row["result_json"] if row is not None else None
        except Exception:
            result_json = None
        if result_json:
            try:
                result = json.loads(result_json)
            except (TypeError, ValueError):
                result = None
            if isinstance(result, dict):
                for key in ("summary", "status"):
                    value = result.get(key)
                    if isinstance(value, str) and value.strip():
                        return self._scrub_blocked_text(self.redactor, value)
        return "unexplained_block"

    def transition_plan_node_state(
        self,
        *,
        plan_id: str,
        node_id: str,
        expected: PlanNodeState,
        target: PlanNodeState,
        event_observer: Callable[[EventEnvelope], None] | None = None,
    ) -> tuple[PlanNodeSnapshot, ...]:
        legal = {
            (PlanNodeState.READY, PlanNodeState.LAUNCHING),
            (PlanNodeState.LAUNCHING, PlanNodeState.RUNNING),
            (PlanNodeState.LAUNCHING, PlanNodeState.BLOCKED),
            (PlanNodeState.RUNNING, PlanNodeState.SUCCEEDED),
            (PlanNodeState.RUNNING, PlanNodeState.FAILED),
            (PlanNodeState.RUNNING, PlanNodeState.BLOCKED),
            (PlanNodeState.RUNNING, PlanNodeState.CANCELLED),
        }
        if (expected, target) not in legal:
            raise FrameworkContractError(
                "plan.node_state_illegal", "plan node state transition is not legal"
            )
        now = _now()
        with self.transaction() as transaction:
            connection = transaction.connection
            owner = connection.execute(
                "SELECT p.run_id,r.session_id,p.current_revision,p.payload_json "
                "FROM execution_plans p JOIN runs r ON r.run_id=p.run_id WHERE p.plan_id=?",
                (plan_id,),
            ).fetchone()
            if owner is None:
                raise KeyError(plan_id)
            node_rows = connection.execute(
                "SELECT n.node_id,n.local_id,s.status FROM plan_nodes n "
                "JOIN plan_node_states s ON s.node_id=n.node_id "
                "WHERE n.plan_id=? AND n.retired_revision IS NULL ORDER BY n.rowid",
                (plan_id,),
            ).fetchall()
            by_id = {row["node_id"]: row for row in node_rows}
            if node_id not in by_id:
                retired = connection.execute(
                    "SELECT 1 FROM plan_nodes WHERE plan_id=? AND node_id=? "
                    "AND retired_revision IS NOT NULL",
                    (plan_id, node_id),
                ).fetchone()
                if retired is not None:
                    raise FrameworkContractError(
                        "plan.node_stale_revision",
                        "plan node was retired by a newer revision",
                    )
                raise KeyError(node_id)
            current = PlanNodeState(by_id[node_id]["status"])
            if current is not expected:
                raise FrameworkContractError(
                    "plan.node_state_conflict", "plan node state did not match expectation"
                )
            cursor = connection.execute(
                "UPDATE plan_node_states SET status=?,updated_at=? WHERE node_id=? AND status=?",
                (target.value, now, node_id, expected.value),
            )
            if cursor.rowcount != 1:
                raise FrameworkContractError(
                    "plan.node_state_conflict", "plan node state did not match expectation"
                )
            states = {row["local_id"]: PlanNodeState(row["status"]) for row in node_rows}
            changed = [(node_id, by_id[node_id]["local_id"], target)]
            states[by_id[node_id]["local_id"]] = target
            plan = ExecutionPlan.model_validate_json(owner["payload_json"])
            if target is PlanNodeState.SUCCEEDED:
                for node in plan.nodes:
                    if (
                        states[node.local_id] is PlanNodeState.WAITING
                        and all(
                            states[dependency] is PlanNodeState.SUCCEEDED
                            for dependency in node.depends_on
                        )
                    ):
                        child_id = next(
                            row["node_id"]
                            for row in node_rows
                            if row["local_id"] == node.local_id
                        )
                        connection.execute(
                            "UPDATE plan_node_states SET status=?,updated_at=? WHERE node_id=?",
                            (PlanNodeState.READY.value, now, child_id),
                        )
                        states[node.local_id] = PlanNodeState.READY
                        changed.append((child_id, node.local_id, PlanNodeState.READY))
            elif target in {
                PlanNodeState.FAILED,
                PlanNodeState.BLOCKED,
                PlanNodeState.CANCELLED,
            }:
                blocked = {by_id[node_id]["local_id"]}
                while True:
                    newly_blocked = {
                        node.local_id
                        for node in plan.nodes
                        if node.local_id not in blocked
                        and any(dependency in blocked for dependency in node.depends_on)
                    }
                    if not newly_blocked:
                        break
                    blocked.update(newly_blocked)
                for node in plan.nodes:
                    if node.local_id in blocked and states[node.local_id] is PlanNodeState.WAITING:
                        child_id = next(
                            row["node_id"]
                            for row in node_rows
                            if row["local_id"] == node.local_id
                        )
                        connection.execute(
                            "UPDATE plan_node_states SET status=?,updated_at=? WHERE node_id=?",
                            (PlanNodeState.BLOCKED.value, now, child_id),
                        )
                        states[node.local_id] = PlanNodeState.BLOCKED
                        changed.append((child_id, node.local_id, PlanNodeState.BLOCKED))
            sequence = int(
                connection.execute(
                    "SELECT COALESCE(MAX(sequence),0) FROM events WHERE run_id=?",
                    (owner["run_id"],),
                ).fetchone()[0]
            )
            blocked_reasons: dict[str, str] = {}
            for changed_node_id, _, state in changed:
                if state is PlanNodeState.BLOCKED:
                    blocked_reasons[changed_node_id] = self._blocked_reason(
                        connection, changed_node_id
                    )
            for changed_node_id, _, state in changed:
                sequence += 1
                event = EventEnvelope(
                    event_id=EventId(str(new_event_id())),
                    session_id=SessionId(owner["session_id"]),
                    run_id=RunId(owner["run_id"]),
                    sequence=sequence,
                    occurred_at=datetime.now(UTC),
                    type=f"plan.node_{state.value}",
                    payload=PlanPayload(
                        action=f"node_{state.value}",
                        plan_id=plan_id,
                        revision=owner["current_revision"],
                        node_id=changed_node_id,
                        reason=blocked_reasons.get(changed_node_id),
                    ),
                )
                transaction.append_event(event)
                if event_observer is not None:
                    transaction.after_commit(_event_callback(event_observer, event))
        return tuple(
            PlanNodeSnapshot(node_id=changed_node_id, local_id=local_id, state=state)
            for changed_node_id, local_id, state in changed
        )

    def revise_plan(
        self,
        *,
        plan_id: str,
        revision: PlanRevision,
        plan: ExecutionPlan,
        event_observer: Callable[[EventEnvelope], None] | None = None,
        authorized_effects: frozenset[EffectScope] = frozenset({EffectScope.READ}),
    ) -> PersistedPlan:
        if not revision.evidence_refs:
            raise FrameworkContractError(
                "plan.revision_evidence_required",
                "plan revisions require at least one evidence reference",
            )
        if plan.schema_version != SUPPORTED_PLAN_SCHEMA_VERSION:
            raise FrameworkContractError(
                "plan.schema_unsupported", "execution plan schema is unsupported"
            )
        if plan.policy_version != SUPPORTED_EXECUTION_POLICY_VERSION:
            raise FrameworkContractError(
                "plan.policy_unsupported", "execution policy version is unsupported"
            )
        if plan.revision != revision.expected_revision + 1:
            raise FrameworkContractError(
                "plan.revision_invalid", "new plan revision must follow the expected revision"
            )
        if any(node.effect_scope not in authorized_effects for node in plan.nodes):
            raise FrameworkContractError(
                "plan.effect_unauthorized", "execution plan requests an unauthorized effect"
            )
        payload = json.dumps(
            self.redactor.scrub(plan.model_dump(mode="json")),
            sort_keys=True,
            separators=(",", ":"),
        )
        revision_payload = json.dumps(
            self.redactor.scrub(revision.model_dump(mode="json")),
            sort_keys=True,
            separators=(",", ":"),
        )
        now = _now()
        with self.transaction() as transaction:
            connection = transaction.connection
            current = connection.execute(
                "SELECT current_revision,payload_json FROM execution_plans WHERE plan_id=?",
                (plan_id,),
            ).fetchone()
            if current is None:
                raise KeyError(plan_id)
            if current["current_revision"] != revision.expected_revision:
                raise FrameworkContractError(
                    "plan.revision_conflict", "plan revision compare-and-set failed"
                )
            previous = ExecutionPlan.model_validate_json(current["payload_json"])
            previous_nodes = {node.local_id: node for node in previous.nodes}
            existing = {
                row["local_id"]: row
                for row in connection.execute(
                    "SELECT n.node_id,n.local_id,n.payload_json,s.status FROM plan_nodes n "
                    "JOIN plan_node_states s ON s.node_id=n.node_id "
                    "WHERE n.plan_id=? AND n.retired_revision IS NULL",
                    (plan_id,),
                )
            }
            wanted = {node.local_id: node for node in plan.nodes}
            existing_ids = set(existing)
            wanted_ids = set(wanted)
            added_ids = wanted_ids - existing_ids
            replaced_ids = set(revision.replaced_local_ids)
            cancelled_ids = set(revision.cancelled_local_ids)
            declared_added = {node.local_id: node for node in revision.added_nodes}
            if (
                len(declared_added) != len(revision.added_nodes)
                or declared_added != {local_id: wanted[local_id] for local_id in added_ids}
                or len(replaced_ids) != len(revision.replaced_local_ids)
                or len(cancelled_ids) != len(revision.cancelled_local_ids)
                or replaced_ids & cancelled_ids
                or existing_ids - wanted_ids != replaced_ids
                or not replaced_ids <= existing_ids
                or not cancelled_ids <= existing_ids
                or cancelled_ids - wanted_ids
            ):
                raise FrameworkContractError(
                    "plan.revision_delta_invalid",
                    "plan revision does not describe the active-plan delta",
                )
            for local_id in replaced_ids:
                previous_node = previous_nodes[local_id]
                if previous_node.kind is PlanNodeKind.AGENT:
                    lineage = previous_node.task_lineage or previous_node.local_id
                    if not any(
                        node.kind is PlanNodeKind.AGENT and node.task_lineage == lineage
                        for node in declared_added.values()
                    ):
                        raise FrameworkContractError(
                            "plan.replacement_lineage_required",
                            "replacement agent must retain the replaced node lineage",
                        )
            terminal = {
                PlanNodeState.SUCCEEDED,
                PlanNodeState.FAILED,
                PlanNodeState.BLOCKED,
                PlanNodeState.CANCELLED,
            }
            for local_id in existing_ids & wanted_ids:
                persisted = PlanNode.model_validate_json(existing[local_id]["payload_json"])
                if persisted != wanted[local_id]:
                    code = (
                        "plan.completed_node_immutable"
                        if PlanNodeState(existing[local_id]["status"]) in terminal
                        else "plan.revision_mutation_requires_replacement"
                    )
                    raise FrameworkContractError(
                        code, "active plan node payload cannot be rewritten"
                    )
            if not added_ids and not replaced_ids and not cancelled_ids:
                raise FrameworkContractError(
                    "plan.revision_no_progress",
                    "plan revision must change executable work",
                )
            for local_id in replaced_ids | cancelled_ids:
                if PlanNodeState(existing[local_id]["status"]) in terminal:
                    raise FrameworkContractError(
                        "plan.completed_node_immutable",
                        "terminal plan nodes cannot be replaced or cancelled",
                    )
                connection.execute(
                    "UPDATE plan_node_states SET status=?,updated_at=? WHERE node_id=?",
                    (PlanNodeState.CANCELLED.value, now, existing[local_id]["node_id"]),
                )
            blocked_ids = set(cancelled_ids)
            while True:
                newly_blocked = {
                    node.local_id
                    for node in previous.nodes
                    if node.local_id not in blocked_ids
                    and any(dependency in blocked_ids for dependency in node.depends_on)
                }
                if not newly_blocked:
                    break
                blocked_ids.update(newly_blocked)
            for local_id in blocked_ids - cancelled_ids:
                state = PlanNodeState(existing[local_id]["status"])
                if state not in terminal:
                    connection.execute(
                        "UPDATE plan_node_states SET status=?,updated_at=? WHERE node_id=?",
                        (PlanNodeState.BLOCKED.value, now, existing[local_id]["node_id"]),
                    )
            for local_id in replaced_ids:
                connection.execute(
                    "UPDATE plan_nodes SET retired_revision=? WHERE node_id=?",
                    (plan.revision, existing[local_id]["node_id"]),
                )
            active_states = {
                row["local_id"]: PlanNodeState(row["status"])
                for row in connection.execute(
                    "SELECT n.local_id,s.status FROM plan_nodes n "
                    "JOIN plan_node_states s ON s.node_id=n.node_id "
                    "WHERE n.plan_id=? AND n.retired_revision IS NULL",
                    (plan_id,),
                )
            }
            for node in plan.nodes:
                node_payload = json.dumps(
                    self.redactor.scrub(node.model_dump(mode="json")),
                    sort_keys=True,
                    separators=(",", ":"),
                )
                if node.local_id not in existing:
                    node_id = str(new_plan_node_id())
                    connection.execute(
                        "INSERT INTO plan_nodes(node_id,plan_id,local_id,payload_json,created_at) "
                        "VALUES (?,?,?,?,?)",
                        (node_id, plan_id, node.local_id, node_payload, now),
                    )
                    state = PlanNodeState.READY if all(
                        active_states.get(dependency) is PlanNodeState.SUCCEEDED
                        for dependency in node.depends_on
                    ) else PlanNodeState.WAITING
                    connection.execute(
                        "INSERT INTO plan_node_states VALUES (?,?,?)",
                        (node_id, state.value, now),
                    )
                    active_states[node.local_id] = state
            cursor = connection.execute(
                "UPDATE execution_plans SET current_revision=?,payload_json=? "
                "WHERE plan_id=? AND current_revision=?",
                (plan.revision, payload, plan_id, revision.expected_revision),
            )
            if cursor.rowcount != 1:
                raise FrameworkContractError(
                    "plan.revision_conflict", "plan revision compare-and-set failed"
                )
            connection.execute(
                "INSERT INTO plan_revisions VALUES (?,?,?,?,?)",
                (plan_id, plan.revision, revision.expected_revision, revision_payload, now),
            )
            owner = connection.execute(
                "SELECT p.run_id,r.session_id FROM execution_plans p "
                "JOIN runs r ON r.run_id=p.run_id WHERE p.plan_id=?",
                (plan_id,),
            ).fetchone()
            sequence = int(
                connection.execute(
                    "SELECT COALESCE(MAX(sequence),0) FROM events WHERE run_id=?",
                    (owner["run_id"],),
                ).fetchone()[0]
            ) + 1
            event = EventEnvelope(
                event_id=EventId(str(new_event_id())),
                session_id=SessionId(owner["session_id"]),
                run_id=RunId(owner["run_id"]),
                sequence=sequence,
                occurred_at=datetime.now(UTC),
                type="plan.revised",
                payload=PlanPayload(
                    action="revised", plan_id=plan_id, revision=plan.revision
                ),
            )
            transaction.append_event(event)
            if event_observer is not None:
                transaction.after_commit(_event_callback(event_observer, event))
        return self.get_plan(plan_id)

    def plans_for_run(self, run_id: str) -> tuple[PersistedPlan, ...]:
        with self._connect() as connection:
            ids = connection.execute(
                "SELECT plan_id FROM execution_plans WHERE run_id=? ORDER BY rowid", (run_id,)
            ).fetchall()
        return tuple(self.get_plan(row["plan_id"]) for row in ids)

    def record_execution_decision(self, *, run_id: str, decision: Any) -> None:
        """Persist the accepted execution decision for crash/interrupt recovery."""
        from skail.domain.decisions import ExecutionDecision as _ExecutionDecision

        payload = decision.model_dump(mode="json") if isinstance(
            decision, _ExecutionDecision
        ) else dict(decision)
        payload_json = json.dumps(
            self.redactor.scrub(payload), sort_keys=True, separators=(",", ":")
        )
        now = _now()
        with self.transaction() as transaction:
            transaction.connection.execute(
                "INSERT INTO execution_decisions(run_id,payload_json,created_at,updated_at) "
                "VALUES (?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET "
                "payload_json=excluded.payload_json,updated_at=excluded.updated_at",
                (run_id, payload_json, now, now),
            )

    def get_execution_decision(self, run_id: str) -> Any | None:
        """Reload the accepted execution decision, or None when never accepted."""
        from skail.domain.decisions import ExecutionDecision as _ExecutionDecision

        with self._connect() as connection:
            try:
                row = connection.execute(
                    "SELECT payload_json FROM execution_decisions WHERE run_id=?",
                    (run_id,),
                ).fetchone()
            except sqlite3.OperationalError:
                return None
        if row is None:
            return None
        return _ExecutionDecision.model_validate_json(row["payload_json"])

    def get_session_snapshot(self, session_id: str) -> SessionSnapshot:
        with self._connect() as connection:
            session = connection.execute(
                "SELECT session_id,title,status,created_at,updated_at "
                "FROM sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
            if session is None:
                raise KeyError(session_id)
            run_rows = connection.execute(
                "SELECT run_id,status,budget_limit_usd,plan_schema_version,"
                "execution_policy_version FROM runs WHERE session_id=? ORDER BY rowid",
                (session_id,),
            ).fetchall()
            run_ids = tuple(row["run_id"] for row in run_rows)
            if not run_ids:
                return SessionSnapshot(
                    session_id=session["session_id"],
                    status=session["status"],
                    runs=(),
                    tasks=(),
                    attempts=(),
                    assignments=(),
                    budget_reservations=(),
                    usage_records=(),
                    approvals=(),
                    events=(),
                    context_packets=(),
                    title=session["title"],
                    created_at=session["created_at"],
                    updated_at=session["updated_at"],
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
                f"SELECT assignment_id,attempt_id,provider,model,estimated_cost_usd,payload_json "
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
            context_packets = connection.execute(
                f"SELECT packet_id,run_id,task_id,attempt_id,payload_json "
                f"FROM context_packets WHERE run_id IN ({placeholders}) ORDER BY rowid",
                run_ids,
            ).fetchall()
            events = connection.execute(
                f"SELECT envelope_json FROM events WHERE run_id IN ({placeholders}) ORDER BY rowid",
                run_ids,
            ).fetchall()
        plans: list[PersistedPlan] = []
        for run_id in run_ids:
            plans.extend(self.plans_for_run(run_id))
        changesets: list[PersistedChangeSet] = []
        if task_ids:
            with self._connect() as connection:
                query = (
                    f"SELECT changeset_id FROM change_sets "
                    f"WHERE task_id IN ({task_placeholders}) ORDER BY rowid"
                )
                cs_rows = connection.execute(
                    query,
                    task_ids,
                ).fetchall()
            for cs_row in cs_rows:
                changesets.append(self.get_changeset(cs_row["changeset_id"]))
        decisions: list[Any] = []
        for run_id in run_ids:
            dec = self.get_execution_decision(run_id)
            if dec is not None:
                decisions.append(dec)
        return SessionSnapshot(
            session_id=session["session_id"],
            status=session["status"],
            runs=tuple(_run_snapshot(row) for row in run_rows),
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
                    json.loads(row["payload_json"]),
                )
                for row in assignments
            ),
            budget_reservations=tuple(
                ReservationSnapshot(
                    row["reservation_id"],
                    row["task_id"],
                    Decimal(row["amount_usd"]),
                    row["status"],
                    row["idempotency_key"],
                )
                for row in reservations
            ),
            usage_records=tuple(
                UsageSnapshot(
                    row["usage_id"],
                    row["task_id"],
                    Decimal(row["amount_usd"]),
                    bool(row["authoritative"]),
                    row["idempotency_key"],
                )
                for row in usage
            ),
            approvals=tuple(ApprovalSnapshot(**dict(row)) for row in approvals),
            events=tuple(EventEnvelope.from_json(row["envelope_json"]) for row in events),
            context_packets=tuple(
                ContextPacketSnapshot(
                    row["packet_id"], row["run_id"], row["task_id"],
                    row["attempt_id"], json.loads(row["payload_json"])
                )
                for row in context_packets
            ),
            plans=tuple(plans),
            changesets=tuple(changesets),
            execution_decisions=tuple(decisions),
            title=session["title"],
            created_at=session["created_at"],
            updated_at=session["updated_at"],
        )
