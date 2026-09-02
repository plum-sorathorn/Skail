from __future__ import annotations

import sqlite3
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from rudder.domain.events import DiagnosticPayload, EventEnvelope, SecretRedactor, TaskPayload
from rudder.domain.ids import EventId, RunId, SessionId, TaskId
from rudder.sessions import Journal, JournalIdempotencyError, SessionSnapshot
from rudder.sessions import migrations as journal_migrations

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
SESSION_ID = "11111111-1111-4111-8111-111111111111"
RUN_ID = "22222222-2222-4222-8222-222222222222"
TASK_ID = "33333333-3333-4333-8333-333333333333"
EVENT_ID = "88888888-8888-4888-8888-888888888888"
EXPECTED_TABLES = {
    "schema_migrations",
    "sessions",
    "runs",
    "tasks",
    "attempts",
    "assignments",
    "budget_reservations",
    "usage_records",
    "approvals",
    "events",
}


def _table_names(database: Path) -> set[str]:
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    return {row[0] for row in rows}


def _migration_versions(database: Path) -> list[int]:
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
    return [row[0] for row in rows]


def _seed_session(journal: Journal) -> None:
    journal.create_session(session_id=SESSION_ID, title="Journal contract", created_at=NOW)
    journal.create_run(
        run_id=RUN_ID,
        session_id=SESSION_ID,
        status="running",
        budget_limit_usd=Decimal("2.00"),
        created_at=NOW,
    )


def test_migrations_create_the_complete_schema_and_are_idempotent(tmp_path: Path) -> None:
    database = tmp_path / "rudder.sqlite"
    journal = Journal(database)

    journal.migrate()
    first_versions = _migration_versions(database)
    journal.migrate()

    assert EXPECTED_TABLES <= _table_names(database)
    assert first_versions
    assert _migration_versions(database) == first_versions
    assert len(first_versions) == len(set(first_versions))


def test_a_failed_migration_leaves_no_partial_schema_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "rudder.sqlite"
    monkeypatch.setattr(
        journal_migrations,
        "MIGRATIONS",
        (
            (
                99,
                "CREATE TABLE partial_migration_artifact(value TEXT); "
                "THIS IS NOT VALID SQL;",
            ),
        ),
    )

    with pytest.raises(sqlite3.DatabaseError):
        Journal(database).migrate()

    table_names = _table_names(database)
    assert "partial_migration_artifact" not in table_names
    if "schema_migrations" in table_names:
        assert _migration_versions(database) == []


def test_journal_returns_an_immutable_typed_session_snapshot(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "rudder.sqlite")
    journal.migrate()
    _seed_session(journal)
    journal.create_task(
        task_id=TASK_ID,
        run_id=RUN_ID,
        description="Inspect persistence",
        status="running",
        idempotency_key="task-key-1",
        created_at=NOW,
    )
    journal.create_attempt(
        attempt_id="attempt-1",
        task_id=TASK_ID,
        number=1,
        status="running",
        idempotency_key="attempt-key-1",
        created_at=NOW,
    )
    journal.create_assignment(
        assignment_id="assignment-1",
        attempt_id="attempt-1",
        provider="fake",
        model="quality-model",
        estimated_cost_usd=Decimal("0.40"),
        created_at=NOW,
    )
    journal.create_reservation(
        reservation_id="reservation-1",
        run_id=RUN_ID,
        task_id=TASK_ID,
        amount_usd=Decimal("0.40"),
        status="reserved",
        idempotency_key="reservation-key-1",
        created_at=NOW,
    )
    journal.record_usage(
        usage_id="usage-1",
        run_id=RUN_ID,
        task_id=TASK_ID,
        amount_usd=Decimal("0.12"),
        authoritative=False,
        idempotency_key="usage-key-1",
        created_at=NOW,
    )
    journal.create_approval(
        approval_id="approval-1",
        run_id=RUN_ID,
        task_id=TASK_ID,
        status="pending",
        question="Allow command?",
        idempotency_key="approval-key-1",
        created_at=NOW,
    )
    event = EventEnvelope(
        event_id=EventId(EVENT_ID),
        session_id=SessionId(SESSION_ID),
        run_id=RunId(RUN_ID),
        task_id=TaskId(TASK_ID),
        sequence=1,
        occurred_at=NOW,
        type="task.started",
        payload=TaskPayload(status="started"),
    )
    journal.append_event(event=event)

    snapshot = journal.get_session_snapshot(SESSION_ID)

    assert isinstance(snapshot, SessionSnapshot)
    assert snapshot.session_id == SESSION_ID
    assert snapshot.runs[0].budget_limit_usd == Decimal("2.00")
    assert snapshot.tasks[0].status == "running"
    assert snapshot.attempts[0].number == 1
    assert snapshot.assignments[0].model == "quality-model"
    assert snapshot.budget_reservations[0].amount_usd == Decimal("0.40")
    assert snapshot.usage_records[0].amount_usd == Decimal("0.12")
    assert snapshot.approvals[0].status == "pending"
    assert snapshot.events == (event,)
    with pytest.raises(FrozenInstanceError):
        snapshot.session_id = "mutated"  # type: ignore[misc]


def test_task_and_budget_changes_commit_or_roll_back_together(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "rudder.sqlite")
    journal.migrate()
    _seed_session(journal)

    with pytest.raises(RuntimeError, match="force rollback"):
        with journal.transaction() as transaction:
            transaction.create_task(
                task_id="rolled-back-task",
                run_id=RUN_ID,
                description="Must disappear",
                status="queued",
                idempotency_key="rolled-back-task-key",
                created_at=NOW,
            )
            transaction.create_reservation(
                reservation_id="rolled-back-reservation",
                run_id=RUN_ID,
                task_id="rolled-back-task",
                amount_usd=Decimal("0.25"),
                status="reserved",
                idempotency_key="rolled-back-reservation-key",
                created_at=NOW,
            )
            raise RuntimeError("force rollback")

    rolled_back = journal.get_session_snapshot(SESSION_ID)
    assert rolled_back.tasks == ()
    assert rolled_back.budget_reservations == ()

    with journal.transaction() as transaction:
        transaction.create_task(
            task_id="committed-task",
            run_id=RUN_ID,
            description="Must persist",
            status="queued",
            idempotency_key="committed-task-key",
            created_at=NOW,
        )
        transaction.create_reservation(
            reservation_id="committed-reservation",
            run_id=RUN_ID,
            task_id="committed-task",
            amount_usd=Decimal("0.25"),
            status="reserved",
            idempotency_key="committed-reservation-key",
            created_at=NOW,
        )

    committed = journal.get_session_snapshot(SESSION_ID)
    assert [task.task_id for task in committed.tasks] == ["committed-task"]
    assert [record.reservation_id for record in committed.budget_reservations] == [
        "committed-reservation"
    ]


def test_conflicting_idempotency_replay_is_rejected(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "rudder.sqlite")
    journal.migrate()
    _seed_session(journal)
    common = {
        "run_id": RUN_ID,
        "task_id": None,
        "authoritative": False,
        "idempotency_key": "same-provider-call",
        "created_at": NOW,
    }
    journal.record_usage(usage_id="usage-a", amount_usd=Decimal("0.10"), **common)

    with pytest.raises(JournalIdempotencyError) as caught:
        journal.record_usage(usage_id="usage-b", amount_usd=Decimal("0.11"), **common)

    assert caught.value.error.code == "session.idempotency_conflict"
    assert journal.get_session_snapshot(SESSION_ID).usage_records[0].amount_usd == Decimal(
        "0.10"
    )


def test_event_journal_persists_only_typed_redacted_envelopes(tmp_path: Path) -> None:
    canary = "canary-must-not-reach-sqlite"
    journal = Journal(
        tmp_path / "rudder.sqlite", redactor=SecretRedactor([canary])
    )
    journal.migrate()
    _seed_session(journal)
    event = EventEnvelope(
        event_id=EventId(EVENT_ID),
        session_id=SessionId(SESSION_ID),
        run_id=RunId(RUN_ID),
        sequence=1,
        occurred_at=NOW,
        type="diagnostic.error",
        payload=DiagnosticPayload(
            code="test.error", summary=canary, details={"api_key": canary}
        ),
    )

    journal.append_event(event=event)

    with sqlite3.connect(journal.path) as connection:
        stored = connection.execute("SELECT envelope_json FROM events").fetchone()[0]
    assert canary not in stored
    redacted = event.redacted(SecretRedactor([canary]))
    assert journal.get_session_snapshot(SESSION_ID).events == (redacted,)


def test_one_attempt_cannot_receive_conflicting_assignments(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "rudder.sqlite")
    journal.migrate()
    _seed_session(journal)
    journal.create_task(
        task_id=TASK_ID,
        run_id=RUN_ID,
        description="Assign once",
        status="running",
        idempotency_key="assignment-task-key",
        created_at=NOW,
    )
    journal.create_attempt(
        attempt_id="attempt-for-assignment",
        task_id=TASK_ID,
        number=1,
        status="running",
        idempotency_key="assignment-attempt-key",
        created_at=NOW,
    )
    journal.create_assignment(
        assignment_id="assignment-a",
        attempt_id="attempt-for-assignment",
        provider="fake",
        model="model-a",
        estimated_cost_usd=Decimal("0.10"),
        idempotency_key="assignment-key-a",
        created_at=NOW,
    )

    with pytest.raises(JournalIdempotencyError):
        journal.create_assignment(
            assignment_id="assignment-b",
            attempt_id="attempt-for-assignment",
            provider="fake",
            model="model-b",
            estimated_cost_usd=Decimal("0.20"),
            idempotency_key="assignment-key-b",
            created_at=NOW,
        )

    models = [item.model for item in journal.get_session_snapshot(SESSION_ID).assignments]
    assert models == ["model-a"]


def test_task_replay_requires_identical_content(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "rudder.sqlite")
    journal.migrate()
    _seed_session(journal)
    common = {
        "run_id": RUN_ID,
        "status": "queued",
        "idempotency_key": "task-replay-key",
        "created_at": NOW,
    }
    journal.create_task(task_id="task-first", description="same", **common)
    journal.create_task(task_id="task-first", description="same", **common)

    with pytest.raises(JournalIdempotencyError):
        journal.create_task(task_id="task-replay", description="same", **common)

    assert len(journal.get_session_snapshot(SESSION_ID).tasks) == 1
