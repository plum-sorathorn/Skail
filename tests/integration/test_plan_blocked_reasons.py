"""Failing-first: plan.node_blocked events must carry a reason."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from skail.domain.events import EventEnvelope
from skail.domain.plans import (
    ExecutionPlan,
    PlanNode,
    PlanNodeKind,
    PlanNodeState,
)
from skail.sessions.journal import Journal

SESSION_ID = "11111111-1111-4111-8111-111111111111"
RUN_ID = "22222222-2222-4222-8222-222222222222"


def _plan() -> ExecutionPlan:
    return ExecutionPlan(
        schema_version=1,
        policy_version="adaptive-v1",
        revision=1,
        nodes=(
            PlanNode(local_id="inspect", kind=PlanNodeKind.AGENT, objective="Inspect"),
            PlanNode(
                local_id="verify",
                kind=PlanNodeKind.VERIFICATION,
                objective="Verify",
                depends_on=("inspect",),
                acceptance_criteria=("tests pass",),
            ),
        ),
    )


def _journal(path: Path) -> Journal:
    journal = Journal(path)
    journal.migrate()
    journal.create_session(session_id=SESSION_ID, title="Plans", created_at=datetime.now(UTC))
    journal.create_run(
        run_id=RUN_ID,
        session_id=SESSION_ID,
        status="running",
        budget_limit_usd=Decimal("2"),
        created_at=datetime.now(UTC),
    )
    return journal


def test_node_blocked_without_settlement_carries_sentinel(tmp_path: Path) -> None:
    journal = _journal(tmp_path / "journal.sqlite")
    admitted = journal.admit_plan(run_id=RUN_ID, plan=_plan())
    node_id = admitted.node_ids["inspect"]
    delivered: list[EventEnvelope] = []
    journal.transition_plan_node_state(
        plan_id=admitted.plan_id,
        node_id=node_id,
        expected=PlanNodeState.READY,
        target=PlanNodeState.LAUNCHING,
        event_observer=delivered.append,
    )
    delivered.clear()
    journal.transition_plan_node_state(
        plan_id=admitted.plan_id,
        node_id=node_id,
        expected=PlanNodeState.LAUNCHING,
        target=PlanNodeState.BLOCKED,
        event_observer=delivered.append,
    )
    blocked = [e for e in delivered if e.type == "plan.node_blocked"]
    assert blocked, "expected a plan.node_blocked emission"
    reason = getattr(blocked[0].payload, "reason", None)
    assert reason is not None and str(reason).strip() != ""


def test_node_blocked_with_settlement_carries_summary(tmp_path: Path) -> None:
    journal = _journal(tmp_path / "journal.sqlite")
    admitted = journal.admit_plan(run_id=RUN_ID, plan=_plan())
    node_id = admitted.node_ids["inspect"]
    journal.transition_plan_node_state(
        plan_id=admitted.plan_id,
        node_id=node_id,
        expected=PlanNodeState.READY,
        target=PlanNodeState.LAUNCHING,
    )
    journal.begin_plan_node_execution(node_id=node_id, execution_key="exec-1")
    journal.settle_plan_node_execution(
        node_id=node_id,
        result={"status": "blocked", "summary": "plan.checkpoint_revision_required"},
    )
    delivered: list[EventEnvelope] = []
    journal.transition_plan_node_state(
        plan_id=admitted.plan_id,
        node_id=node_id,
        expected=PlanNodeState.LAUNCHING,
        target=PlanNodeState.BLOCKED,
        event_observer=delivered.append,
    )
    blocked = [e for e in delivered if e.type == "plan.node_blocked"]
    assert blocked, "expected a plan.node_blocked emission"
    reason = getattr(blocked[0].payload, "reason", None)
    assert reason is not None and "plan.checkpoint_revision_required" in str(reason)
