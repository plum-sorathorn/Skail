from __future__ import annotations

import threading
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TypedDict

import pytest
from langgraph.graph import END, START, StateGraph

from skail.domain.sessions import (
    SessionStatus,
    SessionTransitionError,
    transition_session,
)
from skail.sessions.checkpoints import CheckpointStore
from skail.sessions.journal import Journal
from skail.sessions.service import SessionLockedError, SessionService

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


class _CheckpointState(TypedDict):
    marker: str


def _record_real_checkpoint(
    store: CheckpointStore,
    *,
    session_id: str,
    idempotency_key: str,
    status: str,
    payload: dict[str, object],
    live_idempotency_keys: tuple[str, ...] | None = None,
) -> None:
    store.initialize()
    graph = StateGraph(_CheckpointState)
    graph.add_node("record", lambda state: {"marker": state["marker"]})
    graph.add_edge(START, "record")
    graph.add_edge("record", END)
    config = {"configurable": {"thread_id": session_id}}
    with store.sync_saver(session_id) as saver:
        compiled = graph.compile(checkpointer=saver)
        compiled.invoke({"marker": idempotency_key}, config=config)
        snapshot = compiled.get_state(config)
    checkpoint_id = snapshot.config["configurable"]["checkpoint_id"]
    store.record(
        session_id=session_id,
        checkpoint_id=checkpoint_id,
        idempotency_key=idempotency_key,
        status=status,
        payload=payload,
        created_at=NOW,
        live_idempotency_keys=live_idempotency_keys,
    )


def _seed_session_for_resume(journal: Journal, session_id: str) -> None:
    journal.migrate()
    journal.create_session(session_id=session_id, title="Test Session", created_at=NOW)
    journal.create_run(
        run_id="run-1",
        session_id=session_id,
        status="running",
        budget_limit_usd=Decimal("5.00"),
        created_at=NOW,
    )
    # Task 1: succeeded
    journal.create_task(
        task_id="task-1",
        run_id="run-1",
        description="First task",
        status="succeeded",
        idempotency_key="key:task-1",
        created_at=NOW,
    )
    journal.create_attempt(
        attempt_id="att-1",
        task_id="task-1",
        number=1,
        status="succeeded",
        idempotency_key="key:att-1",
        created_at=NOW,
    )
    journal.create_assignment(
        assignment_id="asg-1",
        attempt_id="att-1",
        provider="fake",
        model="fake-fast",
        estimated_cost_usd=Decimal("0.50"),
        created_at=NOW,
    )
    # Task 2: running (orphaned, will be interrupted on resume)
    journal.create_task(
        task_id="task-2",
        run_id="run-1",
        description="Orphaned task",
        status="running",
        idempotency_key="key:task-2",
        created_at=NOW,
    )
    journal.create_attempt(
        attempt_id="att-2",
        task_id="task-2",
        number=1,
        status="running",
        idempotency_key="key:att-2",
        created_at=NOW,
    )
    journal.create_assignment(
        assignment_id="asg-2",
        attempt_id="att-2",
        provider="fake",
        model="fake-smart",
        estimated_cost_usd=Decimal("1.00"),
        created_at=NOW,
    )
    journal.create_reservation(
        reservation_id="res-2",
        run_id="run-1",
        task_id="task-2",
        amount_usd=Decimal("1.00"),
        status="active",
        idempotency_key="key:res-2",
        created_at=NOW,
    )
    # Pending approval
    journal.create_approval(
        approval_id="app-1",
        run_id="run-1",
        task_id="task-2",
        status="pending",
        question="May I edit this file?",
        idempotency_key="key:app-1",
        created_at=NOW,
    )


def test_session_lifecycle_transitions() -> None:
    # Valid transitions
    assert transition_session(SessionStatus.ACTIVE, SessionStatus.IDLE) == SessionStatus.IDLE
    assert transition_session(SessionStatus.IDLE, SessionStatus.ACTIVE) == SessionStatus.ACTIVE
    assert (
        transition_session(SessionStatus.ACTIVE, SessionStatus.INTERRUPTED)
        == SessionStatus.INTERRUPTED
    )
    assert (
        transition_session(SessionStatus.INTERRUPTED, SessionStatus.ACTIVE)
        == SessionStatus.ACTIVE
    )
    assert (
        transition_session(SessionStatus.ACTIVE, SessionStatus.COMPLETED)
        == SessionStatus.COMPLETED
    )
    assert (
        transition_session(SessionStatus.COMPLETED, SessionStatus.ACTIVE)
        == SessionStatus.ACTIVE
    )
    assert (
        transition_session(SessionStatus.COMPLETED, SessionStatus.ARCHIVED)
        == SessionStatus.ARCHIVED
    )
    assert (
        transition_session(SessionStatus.ACTIVE, SessionStatus.ARCHIVED)
        == SessionStatus.ARCHIVED
    )
    assert transition_session(SessionStatus.IDLE, SessionStatus.ARCHIVED) == SessionStatus.ARCHIVED
    assert (
        transition_session(SessionStatus.INTERRUPTED, SessionStatus.ARCHIVED)
        == SessionStatus.ARCHIVED
    )

    # No-op same state
    assert transition_session(SessionStatus.ACTIVE, SessionStatus.ACTIVE) == SessionStatus.ACTIVE

    # Invalid transitions from archived
    with pytest.raises(SessionTransitionError):
        transition_session(SessionStatus.ARCHIVED, SessionStatus.ACTIVE)

    with pytest.raises(SessionTransitionError):
        transition_session(SessionStatus.ARCHIVED, SessionStatus.IDLE)


def test_session_service_lifecycle(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "journal.sqlite")
    journal.migrate()
    checkpoints = CheckpointStore(tmp_path / "checkpoints.sqlite")
    checkpoints.initialize()

    service = SessionService(
        journal=journal,
        checkpoints=checkpoints,
        sessions_dir=tmp_path / "sessions",
    )

    session = service.create_session(title="My Coding Session")
    assert session.status == SessionStatus.ACTIVE
    assert session.title == "My Coding Session"

    # Transition to idle
    service.transition_session(session.session_id, SessionStatus.IDLE)
    assert service.get_session(session.session_id).status == SessionStatus.IDLE

    # Transition to active
    service.transition_session(session.session_id, SessionStatus.ACTIVE)
    assert service.get_session(session.session_id).status == SessionStatus.ACTIVE

    # Transition to completed
    service.transition_session(session.session_id, SessionStatus.COMPLETED)
    assert service.get_session(session.session_id).status == SessionStatus.COMPLETED

    # Transition to archived
    service.transition_session(session.session_id, SessionStatus.ARCHIVED)
    assert service.get_session(session.session_id).status == SessionStatus.ARCHIVED

    # Cannot transition out of archived
    with pytest.raises(SessionTransitionError):
        service.transition_session(session.session_id, SessionStatus.ACTIVE)


def test_session_service_list_sessions(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "journal.sqlite")
    journal.migrate()
    checkpoints = CheckpointStore(tmp_path / "checkpoints.sqlite")
    checkpoints.initialize()

    service = SessionService(
        journal=journal,
        checkpoints=checkpoints,
        sessions_dir=tmp_path / "sessions",
    )

    s1 = service.create_session(title="First")
    s2 = service.create_session(title="Second")

    sessions = service.list_sessions()
    assert len(sessions) == 2
    session_ids = [s.session_id for s in sessions]
    assert s1.session_id in session_ids
    assert s2.session_id in session_ids


def test_session_process_lock_prevents_concurrent_mutation(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "journal.sqlite")
    journal.migrate()
    checkpoints = CheckpointStore(tmp_path / "checkpoints.sqlite")
    checkpoints.initialize()

    service = SessionService(
        journal=journal,
        checkpoints=checkpoints,
        sessions_dir=tmp_path / "sessions",
    )

    session = service.create_session(title="Lock Test")

    locked_event = threading.Event()
    release_event = threading.Event()

    def worker() -> None:
        with service.session_lock(session.session_id):
            locked_event.set()
            release_event.wait(timeout=5)

    thread = threading.Thread(target=worker)
    thread.start()
    assert locked_event.wait(timeout=3)

    # Attempting to acquire non-blocking should fail with SessionLockedError
    with pytest.raises(SessionLockedError):
        with service.session_lock(session.session_id, timeout_sec=0.05):
            pass

    release_event.set()
    thread.join(timeout=3)

    # Now locking succeeds
    with service.session_lock(session.session_id, timeout_sec=1.0):
        pass


def test_session_resume_restores_state_without_duplicate_calls(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "journal.sqlite")
    checkpoints = CheckpointStore(tmp_path / "checkpoints.sqlite")
    _seed_session_for_resume(journal, "session-res-1")

    # Record a valid checkpoint with only task-1 live (so task-2 is an orphan)
    _record_real_checkpoint(
        checkpoints,
        session_id="session-res-1",
        idempotency_key="key:task-1",
        status="committed",
        payload={"task_id": "task-1"},
        live_idempotency_keys=("key:task-1",),
    )

    service = SessionService(
        journal=journal,
        checkpoints=checkpoints,
        sessions_dir=tmp_path / "sessions",
    )

    resume_result = service.resume_session("session-res-1")
    assert resume_result.ok is True
    assert resume_result.session.status == SessionStatus.ACTIVE
    assert "key:att-2" in resume_result.interrupted_call_keys
    assert "res-2" in resume_result.released_reservation_ids
    assert "app-1" in resume_result.pending_approval_ids

    # Verify task-1 was preserved as succeeded and not duplicated
    snapshot = journal.get_session_snapshot("session-res-1")
    t1 = next(t for t in snapshot.tasks if t.task_id == "task-1")
    assert t1.status.value == "succeeded"

    t2 = next(t for t in snapshot.tasks if t.task_id == "task-2")
    assert t2.status.value == "returned_to_lead"

    # Reservation for task-2 released
    r2 = next(r for r in snapshot.budget_reservations if r.reservation_id == "res-2")
    assert r2.status == "released"
