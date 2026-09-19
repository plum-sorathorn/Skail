"""D-3 regression: settling a plan node that never launched must be a no-op.

Live probe P4 crashed with ``plan.node_execution_missing`` when a settle
arrived for a plan node without a ``plan_node_executions`` row (a never
launched sibling, or a node whose row was cleared by
``retry_approved_plan_tool``/``reconcile_plan_node_executions``).  The settle
is now an idempotent no-op with a module-log diagnostic instead of raising,
so a later deterministic ``begin_plan_node_execution`` still inserts fresh.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from skail.domain.ids import new_run_id, new_session_id
from skail.domain.plans import (
    ExecutionPlan,
    PlanNode,
    PlanNodeKind,
    PlanNodeState,
)
from skail.sessions.journal import Journal

RUN_ID = str(new_run_id())


def _tool_plan() -> ExecutionPlan:
    return ExecutionPlan(
        schema_version=1,
        policy_version="adaptive-v1",
        revision=1,
        nodes=(PlanNode(local_id="probe", kind=PlanNodeKind.TOOL, objective="Probe"),),
    )


def _journal(path: Path) -> Journal:
    journal = Journal(path)
    journal.migrate()
    now = datetime.now(UTC)
    session_id = str(new_session_id())
    journal.create_session(session_id=session_id, title="D-3 settle", created_at=now)
    journal.create_run(
        run_id=RUN_ID,
        session_id=session_id,
        status="running",
        budget_limit_usd=Decimal("2.00"),
        created_at=now,
    )
    return journal


def test_settle_of_never_launched_node_is_a_logged_noop(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A settle without a launch raises nothing, logs, and inserts no row."""
    journal = _journal(tmp_path / "journal.sqlite")
    admitted = journal.admit_plan(run_id=RUN_ID, plan=_tool_plan())
    unlaunched = admitted.node_ids["probe"]

    with caplog.at_level(logging.DEBUG, logger="skail.sessions.journal"):
        journal.settle_plan_node_execution(node_id=unlaunched, result={"status": "cancelled"})

    diagnostic = [
        record
        for record in caplog.records
        if "not launched" in record.getMessage() and unlaunched in record.getMessage()
    ]
    assert diagnostic, "expected a module-log diagnostic for the no-op settle"

    with sqlite3.connect(tmp_path / "journal.sqlite") as connection:
        rows = connection.execute("SELECT node_id FROM plan_node_executions").fetchall()
    assert rows == [], "the no-op settle must not synthesize an execution row"

    execution = journal.begin_plan_node_execution(
        node_id=unlaunched, execution_key=f"tool:{unlaunched}"
    )
    assert execution.status == "running"
    assert execution.result is None


def test_settle_after_launch_settles_then_double_settle_is_idempotent(tmp_path: Path) -> None:
    """A launched node settles once; the second settle keeps the first result."""
    journal = _journal(tmp_path / "journal.sqlite")
    admitted = journal.admit_plan(run_id=RUN_ID, plan=_tool_plan())
    node_id = admitted.node_ids["probe"]

    launched = journal.begin_plan_node_execution(
        node_id=node_id, execution_key=f"tool:{node_id}"
    )
    assert launched.status == "running"

    journal.settle_plan_node_execution(node_id=node_id, result={"status": "succeeded"})
    settled = journal.begin_plan_node_execution(
        node_id=node_id, execution_key=f"tool:{node_id}"
    )
    assert settled.status == "settled"
    assert settled.result == {"status": "succeeded"}

    journal.settle_plan_node_execution(node_id=node_id, result={"status": "failed"})
    again = journal.begin_plan_node_execution(
        node_id=node_id, execution_key=f"tool:{node_id}"
    )
    assert again.status == "settled"
    assert again.result == {"status": "succeeded"}

def test_reconcile_include_allowlist_only_touches_listed_ids(tmp_path: Path) -> None:
    """include_node_ids mirrors exclude_node_ids: only listed nodes reconcile.

    A launched (execution-row-bearing) node outside the allowlist must keep its
    LAUNCHING state and its unsettled running row, while the listed
    unlaunched node is reconciled to BLOCKED exactly once.
    """
    journal = _journal(tmp_path / "journal-include.sqlite")
    plan = ExecutionPlan(
        schema_version=1,
        policy_version="adaptive-v1",
        revision=1,
        nodes=(
            PlanNode(local_id="launched", kind=PlanNodeKind.TOOL, objective="Launched"),
            PlanNode(local_id="unlaunched", kind=PlanNodeKind.TOOL, objective="Unlaunched"),
        ),
    )
    admitted = journal.admit_plan(run_id=RUN_ID, plan=plan)
    launched_id = admitted.node_ids["launched"]
    unlaunched_id = admitted.node_ids["unlaunched"]

    journal.transition_plan_node_state(
        plan_id=admitted.plan_id,
        node_id=launched_id,
        expected=PlanNodeState.READY,
        target=PlanNodeState.LAUNCHING,
    )
    journal.begin_plan_node_execution(node_id=launched_id, execution_key=f"task:{launched_id}")
    journal.transition_plan_node_state(
        plan_id=admitted.plan_id,
        node_id=unlaunched_id,
        expected=PlanNodeState.READY,
        target=PlanNodeState.LAUNCHING,
    )

    reconciled = journal.reconcile_plan_node_executions(
        include_node_ids=frozenset({unlaunched_id})
    )
    assert [snapshot.node_id for snapshot in reconciled] == [unlaunched_id]
    states = journal.get_plan(admitted.plan_id).node_states
    assert states["unlaunched"] is PlanNodeState.BLOCKED
    assert states["launched"] is PlanNodeState.LAUNCHING
    launched_execution = journal.plan_node_execution(launched_id)
    assert launched_execution is not None
    assert launched_execution.status == "running"
    blocked = [
        event
        for event in journal.events_after(run_id=RUN_ID)
        if event.type == "plan.node_blocked"
    ]
    assert [str(event.payload.node_id) for event in blocked] == [unlaunched_id]

    # An empty include mirrors the exclude-allowlist: nothing is filtered.
    again = journal.reconcile_plan_node_executions()
    assert [snapshot.node_id for snapshot in again] == [launched_id]
    states = journal.get_plan(admitted.plan_id).node_states
    assert states["launched"] is PlanNodeState.BLOCKED
    still = [
        event
        for event in journal.events_after(run_id=RUN_ID)
        if event.type == "plan.node_blocked"
    ]
    assert len(still) == 2, "the already-blocked node must not produce a second event"
