from __future__ import annotations

import asyncio
import json
from collections import deque
from decimal import Decimal

import pytest
from fakes.barriers import AsyncStartBarrier
from fakes.models import ScriptedChatModel, parallel_tool_call_message
from langchain_core.messages import AIMessage

from skail.agents.profiles import builtin_profiles
from skail.agents.task_graph import (
    AttemptBinding,
    build_compiled_profile_subagent,
    build_task_graph,
    decode_task_request,
)
from skail.domain.ids import (
    AssignmentId,
    ReservationId,
    new_assignment_id,
    new_attempt_id,
    new_run_id,
    new_task_id,
)
from skail.domain.plans import PlanNode, PlanNodeKind
from skail.domain.routing import RoutingMode, TaskAssignment
from skail.domain.tasks import TaskRequest, TaskResult, VerificationResult
from skail.routing.selector import RouteFailure
from skail.runtime.deepagents_adapter import ChildRunGate, build_lead_agent
from skail.runtime.leases import WorkspaceLeaseManager
from skail.runtime.run_controller import _task_request_for_plan_node
from skail.runtime.scheduler import ChildScheduler
from skail.runtime.task_validation import TaskValidationError, TaskValidator


def _spec(tmp_path, *, profile: str = "implementer"):
    return TaskValidator(
        profiles=builtin_profiles(), workspace_root=tmp_path, max_depth=1,
        background_enabled=False,
    ).create_spec(
        TaskRequest(description=f"Run {profile} work", profile=profile),
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


def test_standard_task_description_decodes_structured_skail_fields() -> None:
    dependency = new_task_id()
    request = decode_task_request(
        json.dumps(
            {
                "description": "Verify the parser",
                "success_criteria": ["focused test passes"],
                "depends_on": [str(dependency)],
                "write_scope": ["src/skail"],
                "budget_usd": "0.25",
                "priority": 7,
                "prerequisite_artifacts": ["artifact:parser-report"],
                "source_revisions": ["plan:parse:revision:2"],
            }
        ),
        profile="implementer",
    )

    assert request.description == "Verify the parser"
    assert request.success_criteria == ("focused test passes",)
    assert request.depends_on == (dependency,)
    assert request.write_scope == ("src/skail",)
    assert request.budget_usd == Decimal("0.25")
    assert request.priority == 7
    assert request.prerequisite_artifacts == ("artifact:parser-report",)
    assert request.source_revisions == ("plan:parse:revision:2",)


def test_plain_task_description_requires_evidence_by_default() -> None:
    request = decode_task_request("Inspect the implementation", profile="reviewer")

    assert request.description == "Inspect the implementation"
    assert request.success_criteria == ("Provide evidence for the completed task",)


def test_plan_node_request_carries_declared_artifact_and_source_references() -> None:
    request = _task_request_for_plan_node(
        PlanNode(
            local_id="review",
            kind=PlanNodeKind.AGENT,
            objective="Review parser changes",
            artifact_refs=("artifact:parser-report", "file:docs/parser.md"),
            inputs=("workspace:abc123",),
        )
    )

    assert request.prerequisite_artifacts == (
        "artifact:parser-report",
        "file:docs/parser.md",
    )
    assert request.source_revisions == ("workspace:abc123",)


def test_task_validator_rejects_unsafe_context_file_references(tmp_path) -> None:
    validator = TaskValidator(
        profiles=builtin_profiles(), workspace_root=tmp_path, max_depth=1,
        background_enabled=False,
    )

    for reference in ("file:../secret.txt", "artifact:../secret"):
        with pytest.raises(TaskValidationError, match="task.context_reference_invalid"):
            validator.create_spec(
                TaskRequest(
                    description="Read outside the workspace",
                    profile="reviewer",
                    prerequisite_artifacts=(reference,),
                ),
                run_id=new_run_id(), parent_task_id=None, parent_depth=0,
                workspace_revision="git:abc",
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
async def test_task_graph_passes_bounded_artifact_and_revision_references_to_workers(
    tmp_path,
) -> None:
    validator = TaskValidator(
        profiles=builtin_profiles(), workspace_root=tmp_path, max_depth=1,
        background_enabled=False,
    )
    spec = validator.create_spec(
        TaskRequest(
            description="Verify revised parser work",
            profile="reviewer",
            prerequisite_artifacts=("artifact:parser-report", "file:docs/parser.md"),
            source_revisions=("plan:parser:revision:2", "workspace:abc123"),
        ),
        run_id=new_run_id(), parent_task_id=None, parent_depth=0,
        workspace_revision="git:abc",
    )
    assignment = _assignment(spec, 1, "reviewer-model")
    packets = []

    def assign(task, number, excluded):
        assert task.task_id == spec.task_id
        assert number == 1
        assert excluded == ()
        return AttemptBinding(new_attempt_id(), assignment)

    async def execute(task, assigned, packet):
        assert task == spec
        assert assigned == assignment
        return TaskResult(
            task_id=spec.task_id,
            status="succeeded",
            summary="verified",
            verification=(
                VerificationResult(
                    criterion="context references available",
                    passed=True,
                    evidence="bounded packet persisted",
                ),
            ),
        )

    graph = build_task_graph(
        profile=builtin_profiles()["reviewer"],
        assign=assign,
        execute=execute,
        persist_context=packets.append,
        gate=ChildRunGate(3),
        leases=WorkspaceLeaseManager(),
    )
    state = await graph.ainvoke({"spec": spec})

    assert state["result"].status == "succeeded"
    assert len(packets) == 1
    by_label = {component.label: component for component in packets[0].components}
    assert {"prerequisite-artifacts", "source-revisions", "authorized-retrieval"} <= set(by_label)
    assert "lead-transcript" not in by_label
    assert by_label["prerequisite-artifacts"].content == (
        "artifact:parser-report\nfile:docs/parser.md"
    )
    assert by_label["source-revisions"].content == "plan:parser:revision:2\nworkspace:abc123"
    assert by_label["authorized-retrieval"].disposition == "reference"


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
async def test_task_graph_converts_execution_error_to_bounded_escalation(tmp_path) -> None:
    spec = _spec(tmp_path)
    assignments = [_assignment(spec, 1, "economy"), _assignment(spec, 2, "quality")]
    assigned: list[int] = []

    def assign(task, number, excluded):
        assigned.append(number)
        return AttemptBinding(new_attempt_id(), assignments[number - 1])

    async def execute(*args):
        raise RuntimeError("provider unavailable")

    graph = build_task_graph(
        profile=builtin_profiles()["implementer"],
        assign=assign,
        execute=execute,
        gate=ChildRunGate(3),
        leases=WorkspaceLeaseManager(),
    )

    state = await graph.ainvoke({"spec": spec})
    assert assigned == [1, 2]
    assert state["result"].status == "returned_to_lead"
    assert "provider unavailable" in state["result"].summary


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
        return TaskResult(
            task_id=spec.task_id,
            status="succeeded",
            summary="done",
            verification=(
                VerificationResult(
                    criterion="Provide evidence for the completed task",
                    passed=True,
                    evidence="bounded child execution completed",
                ),
            ),
        )

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


@pytest.mark.asyncio
async def test_malformed_task_packet_returns_structured_failure_without_execution(
    tmp_path,
) -> None:
    validator = TaskValidator(
        profiles=builtin_profiles(),
        workspace_root=tmp_path,
        max_depth=1,
        background_enabled=False,
    )
    assigned: list[object] = []

    def assign(*args):
        assigned.append(args)
        raise AssertionError("malformed task must not be assigned")

    async def execute(*args):
        raise AssertionError("malformed task must not execute")

    child = build_compiled_profile_subagent(
        name="implementer",
        description="Implement bounded work.",
        profile=builtin_profiles()["implementer"],
        validator=validator,
        run_id=new_run_id(),
        workspace_revision="git:abc",
        assign=assign,
        execute=execute,
        gate=ChildRunGate(3),
        leases=WorkspaceLeaseManager(),
    )
    state = await child["runnable"].ainvoke(
        {"messages": [{"role": "user", "content": '{"description":'}]}
    )
    result = json.loads(state["messages"][-1].content)

    assert result["status"] == "blocked"
    assert "task.description_packet_invalid" in result["summary"]
    assert assigned == []


@pytest.mark.asyncio
async def test_dependency_waits_for_verified_success_before_release(tmp_path) -> None:
    validator = TaskValidator(
        profiles=builtin_profiles(), workspace_root=tmp_path, max_depth=1,
        background_enabled=False,
    )
    run_id = new_run_id()
    parent = validator.create_spec(
        TaskRequest(
            description="Parent",
            profile="implementer",
            success_criteria=("recorded verification",),
        ),
        run_id=run_id, parent_task_id=None, parent_depth=0,
        workspace_revision="git:abc",
    )
    child = validator.create_spec(
        TaskRequest(
            description="Child", profile="implementer", depends_on=(parent.task_id,)
        ),
        run_id=run_id, parent_task_id=None, parent_depth=0,
        workspace_revision="git:abc",
    )
    scheduler = ChildScheduler(max_children=2)
    scheduler.submit(str(parent.task_id), priority=1)
    scheduler.submit(str(child.task_id), priority=1, depends_on=(str(parent.task_id),))
    child_executed = False

    def assign(spec, number, excluded):
        return AttemptBinding(new_attempt_id(), _assignment(spec, number, f"model-{number}"))

    async def parent_execute(spec, assignment, packet):
        return TaskResult(task_id=spec.task_id, status="succeeded", summary="unsupported")

    async def child_execute(spec, assignment, packet):
        nonlocal child_executed
        child_executed = True
        return TaskResult(task_id=spec.task_id, status="succeeded", summary="ran")

    parent_graph = build_task_graph(
        profile=builtin_profiles()["implementer"], assign=assign,
        execute=parent_execute, gate=scheduler.gate, leases=WorkspaceLeaseManager(),
        scheduler=scheduler,
    )
    child_graph = build_task_graph(
        profile=builtin_profiles()["implementer"], assign=assign,
        execute=child_execute, gate=scheduler.gate, leases=WorkspaceLeaseManager(),
        scheduler=scheduler,
    )
    parent_state, child_state = await asyncio.gather(
        parent_graph.ainvoke({"spec": parent}), child_graph.ainvoke({"spec": child})
    )

    assert parent_state["result"].status == "returned_to_lead"
    assert child_state["result"].status == "blocked"
    assert child_executed is False


@pytest.mark.asyncio
async def test_cancelled_writer_keeps_lease_until_operation_stops(tmp_path) -> None:
    spec = _spec(tmp_path)
    leases = WorkspaceLeaseManager()
    started = asyncio.Event()
    release = asyncio.Event()

    def assign(task, number, excluded):
        return AttemptBinding(new_attempt_id(), _assignment(task, number, "model"))

    async def execute(task, assignment, packet):
        started.set()
        await release.wait()
        return TaskResult(
            task_id=task.task_id,
            status="succeeded",
            summary="done",
            verification=(
                VerificationResult(
                    criterion="Provide evidence for the completed task",
                    passed=True,
                    evidence="operation completed",
                ),
            ),
        )

    graph = build_task_graph(
        profile=builtin_profiles()["implementer"],
        assign=assign,
        execute=execute,
        gate=ChildRunGate(1),
        leases=leases,
    )
    running = asyncio.create_task(graph.ainvoke({"spec": spec}))
    await started.wait()
    running.cancel()
    await asyncio.sleep(0)

    assert leases.holder == str(spec.task_id)
    assert not running.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert leases.holder is None


@pytest.mark.asyncio
async def test_writer_waiting_for_lease_does_not_occupy_a_child_slot(tmp_path) -> None:
    first_writer = _spec(tmp_path)
    waiting_writer = _spec(tmp_path)
    reader = _spec(tmp_path, profile="explorer")
    barrier = AsyncStartBarrier()
    gate = ChildRunGate(2)
    leases = WorkspaceLeaseManager()

    def assign(spec, number, excluded):
        return AttemptBinding(new_attempt_id(), _assignment(spec, number, "model"))

    async def execute(spec, assignment, packet):
        del assignment, packet
        task_id = str(spec.task_id)
        await barrier.worker(task_id)
        return TaskResult(
            task_id=spec.task_id,
            status="succeeded",
            summary="completed",
            verification=(
                VerificationResult(
                    criterion="Provide evidence for the completed task",
                    passed=True,
                    evidence="deterministic barrier released",
                ),
            ),
        )

    def graph_for(spec):
        return build_task_graph(
            profile=builtin_profiles()[spec.request.profile],
            assign=assign,
            execute=execute,
            gate=gate,
            leases=leases,
        )

    first = asyncio.create_task(graph_for(first_writer).ainvoke({"spec": first_writer}))
    await barrier.wait_for_started(1)
    waiting = asyncio.create_task(
        graph_for(waiting_writer).ainvoke({"spec": waiting_writer})
    )
    await asyncio.sleep(0)
    reading = asyncio.create_task(graph_for(reader).ainvoke({"spec": reader}))
    await barrier.wait_for_started(2)

    assert str(reader.task_id) in barrier.started
    assert gate.active == 2
    barrier.release(str(reader.task_id))
    barrier.release(str(first_writer.task_id))
    await barrier.wait_for_started(3)
    barrier.release(str(waiting_writer.task_id))

    await asyncio.gather(first, waiting, reading)
    assert gate.peak_active == 2
