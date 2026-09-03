from __future__ import annotations

from collections import deque
from decimal import Decimal

import pytest
from fakes.models import ScriptedChatModel, parallel_tool_call_message
from langchain_core.messages import AIMessage

from rudder.agents.profiles import builtin_profiles
from rudder.agents.task_graph import (
    AttemptBinding,
    build_compiled_profile_subagent,
    build_task_graph,
)
from rudder.domain.ids import (
    AssignmentId,
    ReservationId,
    new_assignment_id,
    new_attempt_id,
    new_run_id,
)
from rudder.domain.routing import RoutingMode, TaskAssignment
from rudder.domain.tasks import TaskRequest, TaskResult
from rudder.routing.selector import RouteFailure
from rudder.runtime.deepagents_adapter import ChildRunGate, build_lead_agent
from rudder.runtime.leases import WorkspaceLeaseManager
from rudder.runtime.task_validation import TaskValidator


def _spec(tmp_path):
    return TaskValidator(
        profiles=builtin_profiles(), workspace_root=tmp_path, max_depth=1,
        background_enabled=False,
    ).create_spec(
        TaskRequest(description="Implement one change", profile="implementer"),
        run_id=new_run_id(), parent_task_id=None, parent_depth=0,
        workspace_revision="git:abc",
    )


def _assignment(spec, number: int, model: str) -> TaskAssignment:
    return TaskAssignment(
        assignment_id=AssignmentId(new_assignment_id()), task_id=spec.task_id,
        attempt_number=number, provider="fake", model=model,
        routing_mode=RoutingMode.AUTO, capability_floor=0.5 + 0.15 * (number - 1),
        estimated_attempt_cost_usd=Decimal("0.01"),
        reservation_id=ReservationId(new_assignment_id()), explanation=("fixture",),
        catalog_revision="catalog",
    )


@pytest.mark.asyncio
async def test_task_graph_escalates_once_with_isolated_context_and_returns_to_lead(
    tmp_path,
) -> None:
    spec = _spec(tmp_path)
    assignments = [_assignment(spec, 1, "economy"), _assignment(spec, 2, "quality")]
    results = deque([
        TaskResult(task_id=spec.task_id, status="failed", summary="first failed"),
        TaskResult(task_id=spec.task_id, status="failed", summary="second failed"),
    ])
    calls: list[tuple[int, tuple[tuple[str, str], ...]]] = []
    packets = []
    settled = []
    exhausted = []

    def assign(task, number, excluded):
        calls.append((number, excluded))
        return AttemptBinding(new_attempt_id(), assignments[number - 1])

    async def execute(task, assignment, packet):
        assert assignment.assignment_id
        assert all(item.label != "lead-transcript" for item in packet.components)
        return results.popleft()

    graph = build_task_graph(
        profile=builtin_profiles()["implementer"], assign=assign, execute=execute,
        persist_context=packets.append,
        settle_attempt=lambda binding, result: settled.append(binding.attempt_id),
        exhaust_fingerprint=lambda task: exhausted.append(task.fingerprint),
        gate=ChildRunGate(3), leases=WorkspaceLeaseManager(),
    )
    state = await graph.ainvoke({"spec": spec})

    assert state["result"].status == "returned_to_lead"
    assert calls == [(1, ()), (2, (("fake", "economy"),))]
    assert len(packets) == 2
    assert len(set(settled)) == 2
    assert exhausted == [spec.fingerprint]
    assert len(state["result"].attempts) == 2


@pytest.mark.asyncio
async def test_task_graph_keeps_budget_block_distinct_and_never_executes(tmp_path) -> None:
    spec = _spec(tmp_path)

    async def execute(*args):
        raise AssertionError("blocked task must not execute")

    graph = build_task_graph(
        profile=builtin_profiles()["implementer"],
        assign=lambda *args: RouteFailure(
            excluded_counts={"budget": 1}, binding_constraint="budget_unaffordable"
        ),
        execute=execute,
        gate=ChildRunGate(3), leases=WorkspaceLeaseManager(),
    )
    state = await graph.ainvoke({"spec": spec})
    assert state["result"].status == "budget_blocked"


@pytest.mark.asyncio
async def test_standard_task_surface_creates_distinct_task_and_assignment_identity(
    tmp_path,
) -> None:
    validator = TaskValidator(
        profiles=builtin_profiles(), workspace_root=tmp_path, max_depth=1,
        background_enabled=False,
    )
    seen = []

    def assign(spec, number, excluded):
        assignment = _assignment(spec, number, f"model-{len(seen)}")
        seen.append((spec.task_id, assignment.assignment_id))
        return AttemptBinding(new_attempt_id(), assignment)

    async def execute(spec, assignment, packet):
        return TaskResult(task_id=spec.task_id, status="succeeded", summary="done")

    child = build_compiled_profile_subagent(
        name="implementer", description="Implement bounded work.",
        profile=builtin_profiles()["implementer"], validator=validator,
        run_id=new_run_id(), workspace_revision="git:abc", assign=assign,
        execute=execute, gate=ChildRunGate(3), leases=WorkspaceLeaseManager(),
    )
    lead_model = ScriptedChatModel(responses=[
        parallel_tool_call_message([
            ("task", {"description": "first", "subagent_type": "implementer"}, "one"),
            ("task", {"description": "second", "subagent_type": "implementer"}, "two"),
        ]),
        AIMessage(content="combined"),
    ])
    lead = build_lead_agent(lead_model, subagents=[child])
    result = await lead.ainvoke({"messages": [{"role": "user", "content": "delegate"}]})

    assert result["messages"][-1].content == "combined"
    assert len({task_id for task_id, _ in seen}) == 2
    assert len({assignment_id for _, assignment_id in seen}) == 2
