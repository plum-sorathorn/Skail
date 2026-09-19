"""D-3: the lead's interrupt/exception exits reconcile admitted-but-unlaunched nodes.

When the lead run exits blocked/failed/cancelled, dispatches admitted by
``_admit_ready_plan_agents`` but never begun by the dispatch pump (no row in
``plan_node_executions``) must be reconciled to BLOCKED inside the same
journal transaction as the terminal status writes, the dispatch deque must be
cleared, and no child attempts may be minted by the exit.  Children that
already have an execution row keep their mid-flight state, and replaying the
exit must be idempotent (no duplicate ``plan.node_blocked``).

These tests drive ``RunController._reconcile_unlaunched_admissions`` through a
duck harness (the ``_D3PumpController`` pattern from the phase-10c tests): the
helper touches only ``journal`` and ``_planned_node_dispatches``.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from skail.domain.ids import new_attempt_id, new_run_id, new_session_id
from skail.domain.plans import (
    ExecutionPlan,
    PlanNode,
    PlanNodeKind,
    PlanNodeState,
)
from skail.runtime.run_controller import RunController, _PlannedNodeDispatch
from skail.sessions.journal import Journal


class _D3ExitController(RunController):
    """Duck harness: exactly the attributes the exit reconciliation touches."""

    def __init__(self, journal: Journal) -> None:
        self.journal = journal
        self.events = SimpleNamespace(publish_persisted_nowait=lambda event: None)
        self._planned_node_dispatches: list[_PlannedNodeDispatch] = []


def _journal(tmp_path: Path, name: str) -> tuple[Journal, str]:
    journal = Journal(tmp_path / f"exit-{name}.sqlite")
    journal.migrate()
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id),
        title="exit reconciliation",
        created_at=datetime.now(UTC),
    )
    run_id = str(new_run_id())
    journal.create_run(
        run_id=run_id,
        session_id=str(session_id),
        status="running",
        budget_limit_usd=Decimal("2.00"),
        created_at=datetime.now(UTC),
    )
    return journal, run_id


def _agent_plan() -> ExecutionPlan:
    return ExecutionPlan(
        schema_version=1,
        policy_version="adaptive-v1",
        revision=1,
        nodes=(
            PlanNode(local_id="scout", kind=PlanNodeKind.AGENT, objective="Scout"),
            PlanNode(local_id="trail", kind=PlanNodeKind.AGENT, objective="Trail"),
        ),
    )


def _simulate_admission(
    journal: Journal,
    *,
    plan_id: str,
    node_id: str,
    run_id: str,
) -> str:
    """Mimic ``_admit_ready_plan_agents``'s persistence: READY->LAUNCHING + task/attempt."""
    journal.transition_plan_node_state(
        plan_id=plan_id,
        node_id=node_id,
        expected=PlanNodeState.READY,
        target=PlanNodeState.LAUNCHING,
        event_observer=lambda _event: None,
    )
    now = datetime.now(UTC)
    task_id = f"{new_run_id()}"
    journal.create_task(
        task_id=task_id,
        run_id=run_id,
        description=f"work for {node_id}",
        status="queued",
        idempotency_key=f"task:{task_id}",
        created_at=now,
        fingerprint=f"exit-probe:{node_id}",
    )
    attempt_id = new_attempt_id()
    journal.create_attempt(
        attempt_id=str(attempt_id),
        task_id=task_id,
        number=1,
        status="assigned",
        idempotency_key=f"attempt:{attempt_id}",
        created_at=now,
    )
    journal.bind_plan_node_task(node_id=node_id, task_id=task_id, attempt_id=str(attempt_id))
    return task_id


def _dispatch(plan_id: str, node_id: str) -> _PlannedNodeDispatch:
    return _PlannedNodeDispatch(
        plan_id=plan_id,
        node_id=node_id,
        profile=SimpleNamespace(name="explorer"),
        spec=SimpleNamespace(
            task_id=node_id,
            request=SimpleNamespace(description=f"work for {node_id}", priority=0),
        ),
    )


def _row_count(journal: Journal, table: str) -> int:
    with sqlite3.connect(journal.path) as connection:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _blocked_events(journal: Journal, run_id: str) -> list[str]:
    return [
        str(event.payload.node_id)
        for event in journal.events_after(run_id=run_id)
        if event.type == "plan.node_blocked"
    ]


def test_interrupt_exit_blocks_unlaunched_node_in_blocked_tx_without_minting(
    tmp_path: Path,
) -> None:
    journal, run_id = _journal(tmp_path, "interrupt")
    admitted = journal.admit_plan(run_id=run_id, plan=_agent_plan())
    plan_id = admitted.plan_id
    scout = admitted.node_ids["scout"]
    trail = admitted.node_ids["trail"]
    # Both admitted; neither ever begun by the dispatch pump (no execution rows).
    _simulate_admission(journal, plan_id=plan_id, node_id=scout, run_id=run_id)
    _simulate_admission(journal, plan_id=plan_id, node_id=trail, run_id=run_id)
    controller = _D3ExitController(journal)
    controller._planned_node_dispatches = [_dispatch(plan_id, scout), _dispatch(plan_id, trail)]
    attempts_before = _row_count(journal, "attempts")

    # The interrupt/blocked exit: terminal statuses and the reconciliation must
    # land in ONE journal transaction.
    with journal.transaction() as tx:
        tx.update_run_status(run_id=run_id, status="blocked")
        controller._reconcile_unlaunched_admissions()

    states = journal.get_plan(plan_id).node_states
    assert states["scout"] is PlanNodeState.BLOCKED
    assert states["trail"] is PlanNodeState.BLOCKED
    assert controller._planned_node_dispatches == []
    assert _row_count(journal, "attempts") == attempts_before, (
        "the exit must launch nothing: zero child attempts may be minted"
    )
    assert _blocked_events(journal, run_id) == [scout, trail]


def test_exception_exit_replay_is_idempotent_and_keeps_running_child(
    tmp_path: Path,
) -> None:
    journal, run_id = _journal(tmp_path, "exception")
    admitted = journal.admit_plan(run_id=run_id, plan=_agent_plan())
    plan_id = admitted.plan_id
    scout = admitted.node_ids["scout"]
    trail = admitted.node_ids["trail"]
    # scout: admitted-but-unlaunched; trail: begun by the pump and now RUNNING.
    _simulate_admission(journal, plan_id=plan_id, node_id=scout, run_id=run_id)
    _simulate_admission(journal, plan_id=plan_id, node_id=trail, run_id=run_id)
    journal.begin_plan_node_execution(node_id=trail, execution_key=f"task:{trail}")
    journal.transition_plan_node_state(
        plan_id=plan_id,
        node_id=trail,
        expected=PlanNodeState.LAUNCHING,
        target=PlanNodeState.RUNNING,
        event_observer=lambda _event: None,
    )
    controller = _D3ExitController(journal)
    controller._planned_node_dispatches = [_dispatch(plan_id, scout), _dispatch(plan_id, trail)]
    attempts_before = _row_count(journal, "attempts")
    tasks_before = _row_count(journal, "tasks")

    # The exception/cancel exit: the RUNNING child must not be swept.
    with journal.transaction() as tx:
        tx.update_run_status(run_id=run_id, status="failed")
        controller._reconcile_unlaunched_admissions()

    states = journal.get_plan(plan_id).node_states
    assert states["scout"] is PlanNodeState.BLOCKED
    assert states["trail"] is PlanNodeState.RUNNING, (
        "a mid-flight child with an execution row must keep its state"
    )
    trail_execution = journal.plan_node_execution(trail)
    assert trail_execution is not None
    assert trail_execution.status == "running"
    assert controller._planned_node_dispatches == []
    assert _blocked_events(journal, run_id) == [scout]

    # Replay the same exit (the D-7 guard): deque restored, no duplicates.
    controller._planned_node_dispatches = [_dispatch(plan_id, scout), _dispatch(plan_id, trail)]
    with journal.transaction() as tx:
        tx.update_run_status(run_id=run_id, status="failed")
        controller._reconcile_unlaunched_admissions()

    states = journal.get_plan(plan_id).node_states
    assert states["scout"] is PlanNodeState.BLOCKED
    assert states["trail"] is PlanNodeState.RUNNING
    assert controller._planned_node_dispatches == []
    assert _blocked_events(journal, run_id) == [scout], "no duplicate plan.node_blocked"
    assert _row_count(journal, "attempts") == attempts_before
    assert _row_count(journal, "tasks") == tasks_before, "no duplicate task insert"
