from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from rudder.runtime.errors import FrameworkContractError
from rudder.sessions.checkpoints import (
    CheckpointCorruptError,
    CheckpointStore,
    CheckpointUnavailableError,
)
from rudder.sessions.journal import Journal, SessionSnapshot


@dataclass(frozen=True)
class RecoveryResult:
    ok: bool
    error: FrameworkContractError | None
    snapshot: SessionSnapshot | None
    interrupted_call_keys: tuple[str, ...]
    pending_approval_ids: tuple[str, ...]
    released_reservation_ids: tuple[str, ...]


def recover_session(
    *, journal: Journal, checkpoints: CheckpointStore, session_id: str
) -> RecoveryResult:
    if _same_storage_file(journal.path, checkpoints.path):
        return _failure("checkpoint_path_conflict", "checkpoint and journal paths must differ")
    with checkpoints.locked(session_id):
        return _recover_locked(journal, checkpoints, session_id)


def _recover_locked(
    journal: Journal, checkpoints: CheckpointStore, session_id: str
) -> RecoveryResult:
    try:
        checkpoint = checkpoints.latest_valid(session_id)
    except CheckpointUnavailableError:
        return _failure("checkpoint_unavailable", "checkpoint store is unavailable")
    except CheckpointCorruptError:
        return _failure("checkpoint_corrupt", "checkpoint store is corrupt")
    if checkpoint is None:
        return _failure("checkpoint_unavailable", "session has no checkpoint")

    live_keys = set(checkpoint.live_idempotency_keys)

    interrupted: list[str] = []
    released: list[str] = []
    with journal.transaction() as transaction:
        connection = transaction.connection
        rows = connection.execute(
            "SELECT a.attempt_id,a.task_id,a.idempotency_key FROM attempts a "
            "JOIN tasks t ON t.task_id=a.task_id JOIN runs r ON r.run_id=t.run_id "
            "WHERE r.session_id=? AND a.status IN ('assigned','running')",
            (session_id,),
        ).fetchall()
        protected_task_ids: set[str] = set()
        orphan_task_ids: set[str] = set()
        for row in rows:
            if row["idempotency_key"] in live_keys:
                protected_task_ids.add(row["task_id"])
                continue
            interrupted.append(row["idempotency_key"])
            orphan_task_ids.add(row["task_id"])
            connection.execute(
                "UPDATE attempts SET status='interrupted',updated_at=datetime('now') "
                "WHERE attempt_id=? AND status IN ('assigned','running')",
                (row["attempt_id"],),
            )
            connection.execute(
                "UPDATE tasks SET status='returned_to_lead',updated_at=datetime('now') "
                "WHERE task_id=? AND status='running'",
                (row["task_id"],),
            )
        running_tasks = connection.execute(
            "SELECT t.task_id,t.idempotency_key FROM tasks t JOIN runs r ON r.run_id=t.run_id "
            "WHERE r.session_id=? AND t.status='running'",
            (session_id,),
        ).fetchall()
        for row in running_tasks:
            if row["task_id"] in protected_task_ids:
                continue
            if row["task_id"] not in orphan_task_ids:
                interrupted.append(row["idempotency_key"])
                orphan_task_ids.add(row["task_id"])
            connection.execute(
                "UPDATE tasks SET status='returned_to_lead',updated_at=datetime('now') "
                "WHERE task_id=? AND status='running'",
                (row["task_id"],),
            )
        for task_id in orphan_task_ids:
            released.extend(
                row[0]
                for row in connection.execute(
                    "SELECT reservation_id FROM budget_reservations "
                    "WHERE task_id=? AND status IN ('active','reserved') ORDER BY rowid",
                    (task_id,),
                )
            )
            connection.execute(
                "UPDATE budget_reservations SET status='released',updated_at=datetime('now') "
                "WHERE task_id=? AND status IN ('active','reserved')",
                (task_id,),
            )
        pending = tuple(
            row[0]
            for row in connection.execute(
                "SELECT a.approval_id FROM approvals a JOIN runs r ON r.run_id=a.run_id "
                "WHERE r.session_id=? AND a.status='pending' ORDER BY a.rowid",
                (session_id,),
            )
        )
    journal.reconcile_plan_node_executions()
    snapshot = journal.get_session_snapshot(session_id)
    return RecoveryResult(True, None, snapshot, tuple(interrupted), pending, tuple(released))


def _same_storage_file(first: Path, second: Path) -> bool:
    first_path = os.fspath(first)
    second_path = os.fspath(second)
    if os.path.exists(first_path) and os.path.exists(second_path):
        try:
            return os.path.samefile(first_path, second_path)
        except OSError:
            pass
    return os.path.realpath(first_path) == os.path.realpath(second_path)


def _failure(code: str, summary: str) -> RecoveryResult:
    return RecoveryResult(
        ok=False,
        error=FrameworkContractError(code, summary),
        snapshot=None,
        interrupted_call_keys=(),
        pending_approval_ids=(),
        released_reservation_ids=(),
    )
