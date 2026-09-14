from __future__ import annotations

from decimal import Decimal

import pytest

from skail.agents.profiles import builtin_profiles
from skail.agents.task_graph import (
    AttemptBinding,
    build_task_graph,
)
from skail.domain.ids import (
    ReservationId,
    new_assignment_id,
    new_attempt_id,
    new_run_id,
)
from skail.domain.routing import RoutingMode, TaskAssignment
from skail.domain.tasks import TaskRequest, TaskResult, VerificationResult
from skail.routing.selector import RouteFailure
from skail.runtime.deepagents_adapter import ChildRunGate
from skail.runtime.leases import WorkspaceLeaseManager
from skail.runtime.task_validation import TaskValidator


def _spec(tmp_path):
    return TaskValidator(
        profiles=builtin_profiles(),
        workspace_root=tmp_path,
        max_depth=1,
        background_enabled=False,
    ).create_spec(
        TaskRequest(
            description="Escalation test task",
            profile="implementer",
            success_criteria=("Must pass tests",),
        ),
        run_id=new_run_id(),
        parent_task_id=None,
        parent_depth=0,
        workspace_revision="git:abc",
    )


def _assignment(spec, attempt_number: int, model: str, floor: float = 0.50):
    return TaskAssignment(
        assignment_id=new_assignment_id(),
        run_id=spec.run_id,
        task_id=spec.task_id,
        attempt_number=attempt_number,
        routing_mode=RoutingMode.AUTO,
        provider="fake",
        model=model,
        catalog_revision="test",
        capability_floor=floor,
        capability_score=floor,
        estimated_attempt_cost_usd=Decimal("0.05"),
        reservation_id=ReservationId("44444444-4444-4444-8444-444444444444"),
        binding_hard_constraint="floor",
    )


@pytest.mark.asyncio
async def test_escalation_success_first_attempt(tmp_path) -> None:
    spec = _spec(tmp_path)
    settled = []

    def assign(s, number, excluded):
        return AttemptBinding(new_attempt_id(), _assignment(s, number, "cheap-model"))

    async def execute(s, a, packet):
        return TaskResult(
            task_id=s.task_id,
            status="succeeded",
            summary="All tests pass",
            verification=(
                VerificationResult(
                    criterion="Must pass tests", passed=True, evidence="10 passed"
                ),
            ),
        )

    def settle(binding, result):
        settled.append((binding.assignment.attempt_number, result.status))

    graph = build_task_graph(
        profile=builtin_profiles()["implementer"],
        assign=assign,
        execute=execute,
        settle_attempt=settle,
        gate=ChildRunGate(3),
        leases=WorkspaceLeaseManager(),
    )
    state = await graph.ainvoke({"spec": spec})
    assert state["result"].status == "succeeded"
    assert len(state["attempts"]) == 1
    assert state["attempts"][0].number == 1
    assert state["attempts"][0].model == "cheap-model"
    assert settled == [(1, "succeeded")]


@pytest.mark.asyncio
async def test_escalation_recovers_on_second_attempt(tmp_path) -> None:
    spec = _spec(tmp_path)
    assigned_models = []
    settled = []
    packets = []

    def assign(s, number, excluded):
        if number == 1:
            assigned_models.append("weak-model")
            return AttemptBinding(
                new_attempt_id(), _assignment(s, number, "weak-model", floor=0.50)
            )
        # Attempt 2: must exclude failed model and raise floor
        assert ("fake", "weak-model") in excluded
        assigned_models.append("strong-model")
        return AttemptBinding(
            new_attempt_id(), _assignment(s, number, "strong-model", floor=0.65)
        )

    async def execute(s, a, packet):
        packets.append(packet)
        if a.attempt_number == 1:
            return TaskResult(
                task_id=s.task_id,
                status="failed",
                summary="Failed to implement correctly",
                verification=(VerificationResult(criterion="Must pass tests", passed=False),),
            )
        return TaskResult(
            task_id=s.task_id,
            status="succeeded",
            summary="Fixed on strong model",
            verification=(
                VerificationResult(
                    criterion="Must pass tests", passed=True, evidence="passed on retry"
                ),
            ),
        )

    def settle(binding, result):
        settled.append((binding.assignment.attempt_number, result.status))

    graph = build_task_graph(
        profile=builtin_profiles()["implementer"],
        assign=assign,
        execute=execute,
        settle_attempt=settle,
        gate=ChildRunGate(3),
        leases=WorkspaceLeaseManager(),
    )
    state = await graph.ainvoke({"spec": spec})
    assert state["result"].status == "succeeded"
    assert assigned_models == ["weak-model", "strong-model"]
    assert len(state["attempts"]) == 2
    assert state["attempts"][0].status == "failed"
    assert state["attempts"][1].status == "succeeded"
    # Settle called for attempt 1 before attempt 2
    assert settled == [(1, "failed"), (2, "succeeded")]
    # Packet 2 includes failure handoff from attempt 1
    assert any("failure-handoff" in c.label for c in packets[1].components)


@pytest.mark.asyncio
async def test_escalation_fail_twice_returns_to_lead_and_exhausts_fingerprint(tmp_path) -> None:
    spec = _spec(tmp_path)
    exhausted_specs = []

    def assign(s, number, excluded):
        floor = 0.50 if number == 1 else 0.65
        return AttemptBinding(
            new_attempt_id(), _assignment(s, number, f"model-{number}", floor=floor)
        )

    async def execute(s, a, packet):
        return TaskResult(
            task_id=s.task_id,
            status="failed",
            summary=f"Failed attempt {a.attempt_number}",
        )

    def exhaust(task_spec):
        exhausted_specs.append(task_spec.fingerprint)

    graph = build_task_graph(
        profile=builtin_profiles()["implementer"],
        assign=assign,
        execute=execute,
        exhaust_fingerprint=exhaust,
        gate=ChildRunGate(3),
        leases=WorkspaceLeaseManager(),
    )
    state = await graph.ainvoke({"spec": spec})
    result = state["result"]
    assert result.status == "returned_to_lead"
    assert len(result.attempts) == 2
    assert result.attempts[0].number == 1
    assert result.attempts[1].number == 2
    assert len(exhausted_specs) == 1
    assert exhausted_specs[0] == spec.fingerprint


@pytest.mark.asyncio
async def test_unaffordable_escalation_returns_budget_blocked(tmp_path) -> None:
    spec = _spec(tmp_path)

    def assign(s, number, excluded):
        if number == 1:
            return AttemptBinding(new_attempt_id(), _assignment(s, number, "cheap-model"))
        return RouteFailure(
            binding_constraint="budget_unaffordable",
            excluded_counts={"excluded": len(excluded)},
        )

    async def execute(s, a, packet):
        return TaskResult(
            task_id=s.task_id,
            status="failed",
            summary="cheap model failed",
        )

    graph = build_task_graph(
        profile=builtin_profiles()["implementer"],
        assign=assign,
        execute=execute,
        gate=ChildRunGate(3),
        leases=WorkspaceLeaseManager(),
    )
    state = await graph.ainvoke({"spec": spec})
    assert state["result"].status == "budget_blocked"


@pytest.mark.asyncio
async def test_no_eligible_candidate_returns_blocked(tmp_path) -> None:
    spec = _spec(tmp_path)

    def assign(s, number, excluded):
        if number == 1:
            return AttemptBinding(new_attempt_id(), _assignment(s, number, "only-model"))
        return RouteFailure(
            binding_constraint="no_eligible_model",
            excluded_counts={"excluded": len(excluded)},
        )

    async def execute(s, a, packet):
        return TaskResult(
            task_id=s.task_id,
            status="failed",
            summary="only model failed",
        )

    graph = build_task_graph(
        profile=builtin_profiles()["implementer"],
        assign=assign,
        execute=execute,
        gate=ChildRunGate(3),
        leases=WorkspaceLeaseManager(),
    )
    state = await graph.ainvoke({"spec": spec})
    assert state["result"].status == "blocked"


@pytest.mark.asyncio
async def test_cancelled_attempt_does_not_escalate(tmp_path) -> None:
    spec = _spec(tmp_path)
    assigned = []

    def assign(s, number, excluded):
        assigned.append(number)
        return AttemptBinding(new_attempt_id(), _assignment(s, number, "model"))

    async def execute(s, a, packet):
        return TaskResult(
            task_id=s.task_id,
            status="cancelled",
            summary="User cancelled the task",
        )

    graph = build_task_graph(
        profile=builtin_profiles()["implementer"],
        assign=assign,
        execute=execute,
        gate=ChildRunGate(3),
        leases=WorkspaceLeaseManager(),
    )
    state = await graph.ainvoke({"spec": spec})
    assert state["result"].status == "cancelled"
    # Never called attempt 2
    assert assigned == [1]
