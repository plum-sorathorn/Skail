from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from threading import Event
from typing import TypedDict

import pytest
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph

from rudder.agents.lead import LeadControls
from rudder.domain.ids import new_session_id
from rudder.domain.routing import RoutingMode
from rudder.domain.tasks import AttemptStatus
from rudder.routing.requirements import TaskRisk
from rudder.runtime.errors import FrameworkContractError
from rudder.runtime.interrupts import QuestionStore
from rudder.runtime.run_controller import RunController
from rudder.sessions import CheckpointStore, Journal, RecoveryResult, recover_session
from tests.fakes.models import ScriptedChatModel, tool_call_message

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


class CheckpointState(TypedDict):
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
    graph = StateGraph(CheckpointState)
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


async def test_checkpoint_store_exposes_the_supported_langgraph_saver(
    tmp_path: Path,
) -> None:
    store = CheckpointStore(tmp_path / "checkpoints.sqlite")
    store.initialize()

    async with store.saver("saver-contract-session") as saver:
        await saver.setup()

    assert store.path.exists()


def test_checkpoint_writers_share_the_recovery_session_lock(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path / "checkpoints.sqlite")
    store.initialize()
    writer_started = Event()
    writer_entered = Event()

    def writer() -> None:
        writer_started.set()
        with store.sync_saver("locked-session"):
            writer_entered.set()

    with ThreadPoolExecutor(max_workers=1) as executor:
        with store.locked("locked-session"):
            future = executor.submit(writer)
            assert writer_started.wait(timeout=2)
            assert writer_entered.is_set() is False
        future.result(timeout=5)

    assert writer_entered.is_set() is True


def _seed_run(journal: Journal) -> None:
    journal.migrate()
    journal.create_session(session_id="session-1", title="Recovery", created_at=NOW)
    journal.create_run(
        run_id="run-1",
        session_id="session-1",
        status="running",
        budget_limit_usd=Decimal("2.00"),
        created_at=NOW,
    )


def _assert_recovery_error(result: RecoveryResult, code: str) -> None:
    assert result.ok is False
    assert isinstance(result.error, FrameworkContractError)
    assert result.error.error.code == code


def test_reconciliation_interrupts_orphans_without_replaying_terminal_work(
    tmp_path: Path,
) -> None:
    journal = Journal(tmp_path / "rudder.sqlite")
    checkpoints = CheckpointStore(tmp_path / "checkpoints.sqlite")
    assert journal.path.resolve() != checkpoints.path.resolve()
    _seed_run(journal)
    journal.create_task(
        task_id="orphaned-task",
        run_id="run-1",
        description="Interrupted provider call",
        status="running",
        idempotency_key="orphaned-call-key",
        created_at=NOW,
    )
    journal.create_attempt(
        attempt_id="orphaned-attempt",
        task_id="orphaned-task",
        number=1,
        status="running",
        idempotency_key="orphaned-call-key",
        created_at=NOW,
    )
    journal.create_reservation(
        reservation_id="orphaned-reservation",
        run_id="run-1",
        task_id="orphaned-task",
        amount_usd=Decimal("0.30"),
        status="reserved",
        idempotency_key="orphaned-reservation-key",
        created_at=NOW,
    )
    journal.create_task(
        task_id="recoverable-task",
        run_id="run-1",
        description="Checkpoint-backed provider call",
        status="running",
        idempotency_key="recoverable-call-key",
        created_at=NOW,
    )
    journal.create_attempt(
        attempt_id="recoverable-attempt",
        task_id="recoverable-task",
        number=1,
        status="running",
        idempotency_key="recoverable-call-key",
        created_at=NOW,
    )
    journal.create_reservation(
        reservation_id="recoverable-reservation",
        run_id="run-1",
        task_id="recoverable-task",
        amount_usd=Decimal("0.35"),
        status="reserved",
        idempotency_key="recoverable-reservation-key",
        created_at=NOW,
    )
    journal.create_task(
        task_id="terminal-task",
        run_id="run-1",
        description="Already completed",
        status="succeeded",
        idempotency_key="terminal-call-key",
        created_at=NOW,
    )
    journal.create_attempt(
        attempt_id="terminal-attempt",
        task_id="terminal-task",
        number=1,
        status="succeeded",
        idempotency_key="terminal-call-key",
        created_at=NOW,
    )
    journal.record_usage(
        usage_id="terminal-usage",
        run_id="run-1",
        task_id="terminal-task",
        amount_usd=Decimal("0.18"),
        authoritative=True,
        idempotency_key="terminal-call-key",
        created_at=NOW,
    )
    _record_real_checkpoint(
        checkpoints,
        session_id="session-1",
        idempotency_key="recoverable-call-key",
        status="committed",
        payload={"next": []},
    )

    first = recover_session(
        journal=journal,
        checkpoints=checkpoints,
        session_id="session-1",
    )
    second = recover_session(
        journal=journal,
        checkpoints=checkpoints,
        session_id="session-1",
    )

    assert first.ok is True
    assert first.error is None
    assert first.interrupted_call_keys == ("orphaned-call-key",)
    assert second.interrupted_call_keys == ()
    snapshot = second.snapshot
    assert snapshot is not None
    assert {task.task_id: task.status for task in snapshot.tasks} == {
        "orphaned-task": "returned_to_lead",
        "recoverable-task": "running",
        "terminal-task": "succeeded",
    }
    assert {attempt.attempt_id: attempt.status for attempt in snapshot.attempts} == {
        "orphaned-attempt": "interrupted",
        "recoverable-attempt": "running",
        "terminal-attempt": "succeeded",
    }
    assert {
        reservation.reservation_id: reservation.status
        for reservation in snapshot.budget_reservations
    } == {
        "orphaned-reservation": "released",
        "recoverable-reservation": "reserved",
    }
    assert len(snapshot.usage_records) == 1
    assert snapshot.usage_records[0].idempotency_key == "terminal-call-key"


def test_pending_approval_remains_pending_across_repeated_recovery(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "rudder.sqlite")
    checkpoints = CheckpointStore(tmp_path / "checkpoints.sqlite")
    _seed_run(journal)
    journal.create_approval(
        approval_id="approval-1",
        run_id="run-1",
        task_id=None,
        status="pending",
        question="Allow a dangerous command?",
        idempotency_key="approval-key-1",
        created_at=NOW,
    )
    _record_real_checkpoint(
        checkpoints,
        session_id="session-1",
        idempotency_key="approval-key-1",
        status="interrupted",
        payload={"interrupt": "approval-1"},
    )

    first = recover_session(
        journal=journal,
        checkpoints=checkpoints,
        session_id="session-1",
    )
    second = recover_session(
        journal=journal,
        checkpoints=checkpoints,
        session_id="session-1",
    )

    assert first.pending_approval_ids == ("approval-1",)
    assert second.pending_approval_ids == ("approval-1",)
    assert second.snapshot is not None
    assert second.snapshot.approvals[0].status == "pending"


def test_missing_checkpoint_returns_structured_error_and_preserves_journal(
    tmp_path: Path,
) -> None:
    journal = Journal(tmp_path / "rudder.sqlite")
    _seed_run(journal)
    before = journal.get_session_snapshot("session-1")

    result = recover_session(
        journal=journal,
        checkpoints=CheckpointStore(tmp_path / "missing-checkpoints.sqlite"),
        session_id="session-1",
    )

    _assert_recovery_error(result, "checkpoint_unavailable")
    assert journal.get_session_snapshot("session-1") == before


def test_corrupt_checkpoint_returns_structured_error_and_preserves_journal(
    tmp_path: Path,
) -> None:
    journal = Journal(tmp_path / "rudder.sqlite")
    _seed_run(journal)
    before = journal.get_session_snapshot("session-1")
    checkpoint_path = tmp_path / "checkpoints.sqlite"
    checkpoint_path.write_bytes(b"not a sqlite database")

    result = recover_session(
        journal=journal,
        checkpoints=CheckpointStore(checkpoint_path),
        session_id="session-1",
    )

    _assert_recovery_error(result, "checkpoint_corrupt")
    assert journal.get_session_snapshot("session-1") == before


def test_recovery_rejects_a_checkpoint_store_that_reuses_the_journal_path(
    tmp_path: Path,
) -> None:
    database = tmp_path / "rudder.sqlite"
    journal = Journal(database)
    _seed_run(journal)
    before = journal.get_session_snapshot("session-1")

    result = recover_session(
        journal=journal,
        checkpoints=CheckpointStore(database),
        session_id="session-1",
    )

    _assert_recovery_error(result, "checkpoint_path_conflict")
    assert journal.get_session_snapshot("session-1") == before


def test_recovery_rejects_a_hard_link_alias_of_the_journal(tmp_path: Path) -> None:
    database = tmp_path / "rudder.sqlite"
    journal = Journal(database)
    _seed_run(journal)
    alias = tmp_path / "checkpoint-alias.sqlite"
    try:
        alias.hardlink_to(database)
    except OSError as exc:
        pytest.skip(f"hard links unavailable: {exc}")

    result = recover_session(
        journal=journal,
        checkpoints=CheckpointStore(alias),
        session_id="session-1",
    )

    _assert_recovery_error(result, "checkpoint_path_conflict")


def test_recovery_returns_live_tasks_without_an_attempt_to_the_lead(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "rudder.sqlite")
    checkpoints = CheckpointStore(tmp_path / "checkpoints.sqlite")
    _seed_run(journal)
    journal.create_task(
        task_id="task-without-attempt",
        run_id="run-1",
        description="Crashed before attempt creation",
        status="running",
        idempotency_key="task-boundary-key",
        created_at=NOW,
    )
    _record_real_checkpoint(
        checkpoints,
        session_id="session-1",
        idempotency_key="other-live-key",
        status="committed",
        payload={},
    )

    result = recover_session(journal=journal, checkpoints=checkpoints, session_id="session-1")

    assert result.interrupted_call_keys == ("task-boundary-key",)
    assert result.snapshot is not None
    assert result.snapshot.tasks[0].status == "returned_to_lead"


def test_recovery_interrupts_an_assigned_attempt_that_never_reached_checkpoint(
    tmp_path: Path,
) -> None:
    journal = Journal(tmp_path / "rudder.sqlite")
    checkpoints = CheckpointStore(tmp_path / "checkpoints.sqlite")
    _seed_run(journal)
    journal.create_task(
        task_id="assigned-task",
        run_id="run-1",
        description="Assigned before crash",
        status="running",
        idempotency_key="assigned-task-key",
        created_at=NOW,
    )
    journal.create_attempt(
        attempt_id="assigned-attempt",
        task_id="assigned-task",
        number=1,
        status="assigned",
        idempotency_key="assigned-attempt-key",
        created_at=NOW,
    )
    _record_real_checkpoint(
        checkpoints,
        session_id="session-1",
        idempotency_key="other-live-key",
        status="committed",
        payload={},
    )

    result = recover_session(journal=journal, checkpoints=checkpoints, session_id="session-1")

    assert result.interrupted_call_keys == ("assigned-attempt-key",)
    assert result.snapshot is not None
    assert result.snapshot.tasks[0].status == "returned_to_lead"
    assert result.snapshot.attempts[0].status == "interrupted"


def test_stale_checkpoint_reference_is_rejected_before_journal_mutation(
    tmp_path: Path,
) -> None:
    journal = Journal(tmp_path / "rudder.sqlite")
    checkpoints = CheckpointStore(tmp_path / "checkpoints.sqlite")
    _seed_run(journal)
    _record_real_checkpoint(
        checkpoints,
        session_id="session-1",
        idempotency_key="first-key",
        status="committed",
        payload={},
    )
    with checkpoints.sync_saver("session-1") as saver:
        graph = StateGraph(CheckpointState)
        graph.add_node("record", lambda state: {"marker": state["marker"]})
        graph.add_edge(START, "record")
        graph.add_edge("record", END)
        graph.compile(checkpointer=saver).invoke(
            {"marker": "newer"}, config={"configurable": {"thread_id": "session-1"}}
        )
    before = journal.get_session_snapshot("session-1")

    result = recover_session(journal=journal, checkpoints=checkpoints, session_id="session-1")

    _assert_recovery_error(result, "checkpoint_corrupt")
    assert journal.get_session_snapshot("session-1") == before


def test_checkpoint_idempotency_rejects_conflicting_metadata(tmp_path: Path) -> None:
    checkpoints = CheckpointStore(tmp_path / "checkpoints.sqlite")
    _record_real_checkpoint(
        checkpoints,
        session_id="session-1",
        idempotency_key="checkpoint-key",
        status="committed",
        payload={"value": "original"},
    )
    record = checkpoints.latest_valid("session-1")
    assert record is not None

    with pytest.raises(FrameworkContractError) as caught:
        checkpoints.record(
            session_id="session-1",
            checkpoint_id=record.checkpoint_id,
            idempotency_key="checkpoint-key",
            status="committed",
            payload={"value": "conflict"},
            created_at=NOW,
        )

    assert caught.value.error.code == "session.checkpoint_idempotency_conflict"


def test_one_checkpoint_can_preserve_multiple_live_child_attempts(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "rudder.sqlite")
    checkpoints = CheckpointStore(tmp_path / "checkpoints.sqlite")
    _seed_run(journal)
    for index in (1, 2, 3):
        journal.create_task(
            task_id=f"live-task-{index}",
            run_id="run-1",
            description=f"Live child {index}",
            status="running",
            idempotency_key=f"live-task-key-{index}",
            created_at=NOW,
        )
        journal.create_attempt(
            attempt_id=f"live-attempt-{index}",
            task_id=f"live-task-{index}",
            number=1,
            status="running",
            idempotency_key=f"live-attempt-key-{index}",
            created_at=NOW,
        )
    live_keys = tuple(f"live-attempt-key-{index}" for index in (1, 2, 3))
    _record_real_checkpoint(
        checkpoints,
        session_id="session-1",
        idempotency_key=live_keys[0],
        status="committed",
        payload={},
        live_idempotency_keys=live_keys,
    )

    result = recover_session(journal=journal, checkpoints=checkpoints, session_id="session-1")

    assert result.interrupted_call_keys == ()
    assert result.snapshot is not None
    assert {task.status for task in result.snapshot.tasks} == {"running"}
    assert {attempt.status for attempt in result.snapshot.attempts} == {"running"}


@pytest.mark.asyncio
async def test_controller_interrupt_checkpoint_preserves_live_attempt_on_recovery(
    tmp_path: Path,
) -> None:
    journal = Journal(tmp_path / "journal.sqlite")
    journal.migrate()
    checkpoints = CheckpointStore(tmp_path / "checkpoints.sqlite")
    checkpoints.initialize()
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id),
        title="controller interrupt",
        created_at=datetime.now(UTC),
    )
    questions = QuestionStore(tmp_path / "questions.sqlite")
    model = ScriptedChatModel(
        responses=[
            tool_call_message(
                "ask_user",
                {"prompt": "Proceed?", "reason": "confirmation"},
                call_id="recover-ask",
            )
        ]
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        checkpoints=checkpoints,
        models={"lead-model": model, "implementer-model": model},
        question_store=questions,
    )

    controls = LeadControls(
        delegation="off",
        write_allowed=False,
        max_children=1,
        routing_mode=RoutingMode.QUALITY,
        risk=TaskRisk.HIGH,
    )
    result = await controller.run_instruction(
        "Ask before continuing",
        controls=controls,
        workspace_revision="workspace:abc123",
        delegation_approved=True,
    )
    assert result.status == "blocked"
    recovered = recover_session(
        journal=journal,
        checkpoints=checkpoints,
        session_id=str(session_id),
    )

    assert recovered.ok
    assert recovered.interrupted_call_keys == ()
    assert recovered.released_reservation_ids == ()
    assert recovered.snapshot is not None
    assert recovered.snapshot.attempts[-1].status is AttemptStatus.RUNNING

    resumed_model = ScriptedChatModel(
        responses=[AIMessage(content="Recovered execution completed.")]
    )
    resumed_controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        checkpoints=checkpoints,
        models={"lead-model": resumed_model, "implementer-model": resumed_model},
        question_store=questions,
    )
    assert resumed_controller.restore_interrupted()
    assert resumed_controller._pending_run is not None
    assert resumed_controller._pending_run.controls == controls
    assert resumed_controller._pending_run.workspace_revision == "workspace:abc123"
    assert resumed_controller._pending_run.delegation_approved is True

    resumed = await resumed_controller.resume_interrupted("yes")

    assert resumed.status == "completed"
    assert resumed.output == "Recovered execution completed."
    assert questions.pending(f"{session_id}:{result.run_id}:lead") == ()
