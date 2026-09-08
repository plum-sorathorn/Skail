import asyncio
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

import pytest
from fakes.barriers import AsyncStartBarrier
from fakes.models import ScriptedChatModel, parallel_tool_call_message, tool_call_message
from langchain_core.messages import AIMessage

from rudder.agents.lead import LeadControls
from rudder.domain.ids import new_session_id
from rudder.domain.plans import PlanNodeState
from rudder.domain.tasks import AttemptStatus, TaskResult, TaskStatus
from rudder.runtime.run_controller import RunController
from rudder.sessions.journal import Journal
from rudder.tools.execution import ExecutionPolicy, ExecutionResult


def _journal(tmp_path: Path) -> Journal:
    j = Journal(tmp_path / "journal.sqlite")
    j.migrate()
    return j


@pytest.mark.asyncio
async def test_delegation_off_removes_task_tool_and_forces_direct_work(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Delegation off", created_at=datetime.now(UTC)
    )

    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[AIMessage(content="I worked directly because task tool is unavailable.")],
    )

    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model},
    )

    result = await controller.run_instruction(
        "Try to delegate", controls=LeadControls(delegation="off")
    )

    # In "off" mode, the task tool is not registered on the lead agent
    assert "task" not in lead_model.bound_tool_names
    assert "worked directly" in result.output
    assert len(result.child_results) == 0


@pytest.mark.asyncio
async def test_delegation_off_rejects_a_hallucinated_task_without_admission(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Delegation off task", created_at=datetime.now(UTC)
    )
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [
                    ("execution_decision", _direct_decision("Bounded work"), "decision-1"),
                    (
                        "task",
                        {"description": "Do not admit", "subagent_type": "implementer"},
                        "task-1",
                    ),
                ]
            ),
            AIMessage(content="I completed the bounded work directly."),
        ],
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model},
    )

    await controller.run_instruction(
        "Do this directly", controls=LeadControls(delegation="off")
    )

    snapshot = journal.get_session_snapshot(str(session_id))
    assert len(snapshot.tasks) == 1  # The lead task only.
    assert len(snapshot.attempts) == 1


@pytest.mark.asyncio
async def test_task_before_decision_is_not_admitted_or_assigned(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Task before decision", created_at=datetime.now(UTC)
    )
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [
                    (
                        "task",
                        {"description": "Do not admit", "subagent_type": "implementer"},
                        "task-1",
                    ),
                    ("execution_decision", _direct_decision("Bounded work"), "decision-1"),
                ]
            ),
            AIMessage(content="The task was rejected before admission."),
        ],
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model},
    )

    await controller.run_instruction("Do bounded work")

    snapshot = journal.get_session_snapshot(str(session_id))
    assert len(snapshot.tasks) == 1  # The lead task only.
    assert len(snapshot.attempts) == 1


@pytest.mark.asyncio
async def test_read_only_controls_reject_write_capable_task_before_admission(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Read-only task", created_at=datetime.now(UTC)
    )
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [
                    ("execution_decision", _direct_decision("Inspect only"), "decision-1"),
                    (
                        "task",
                        {"description": "Modify a file", "subagent_type": "implementer"},
                        "task-1",
                    ),
                ]
            ),
            AIMessage(content="The write-capable task was rejected."),
        ],
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model},
    )

    await controller.run_instruction(
        "Inspect only", controls=LeadControls(write_allowed=False)
    )

    snapshot = journal.get_session_snapshot(str(session_id))
    assert len(snapshot.tasks) == 1  # The lead task only.
    assert len(snapshot.attempts) == 1


@pytest.mark.asyncio
async def test_explicit_plan_does_not_allow_task_to_bypass_plan_admission(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Explicit plan task", created_at=datetime.now(UTC)
    )
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [
                    (
                        "execution_decision",
                        {
                            "mode": "planned",
                            "objective": "Make a bounded change",
                            "constraints": [],
                            "reason": "The work has explicit dependencies.",
                            "plan": {
                                "schema_version": 1,
                                "policy_version": "adaptive-v1",
                                "revision": 1,
                                "nodes": [
                                    {
                                        "local_id": "implement",
                                        "kind": "agent",
                                        "objective": "Make the bounded change",
                                        "effect_scope": "workspace_write",
                                    }
                                ],
                            },
                        },
                        "decision-1",
                    ),
                    (
                        "task",
                        {"description": "Bypass the plan", "subagent_type": "implementer"},
                        "task-1",
                    ),
                ]
            ),
            AIMessage(content="The plan was recorded for the coordinator."),
        ],
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model},
    )

    result = await controller.run_instruction("Make a bounded change")

    snapshot = journal.get_session_snapshot(str(session_id))
    assert len(journal.plans_for_run(str(result.run_id))) == 1
    assert len(snapshot.tasks) == 2  # Lead plus the admitted plan node, never the bypass call.
    assert len(snapshot.attempts) == 3  # The admitted node may use its bounded retry.


@pytest.mark.asyncio
async def test_planned_ready_agent_nodes_use_the_admitted_child_lifecycle(tmp_path: Path) -> None:
    evidence_path = tmp_path / "planned-evidence.txt"
    evidence_path.write_text("planned dispatch evidence\n", encoding="utf-8")
    evidence_digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Planned agent dispatch", created_at=datetime.now(UTC)
    )
    child_model = ScriptedChatModel(
        model_name="implementer-model",
        responses=[
            _child_success("first complete", evidence_digest),
            _child_success("second complete", evidence_digest),
            _child_success("dependent complete", evidence_digest),
        ],
    )
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [("execution_decision", _planned_decision(), "decision-1")]
            ),
            AIMessage(content="The planned work has been dispatched."),
        ],
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model, "implementer-model": child_model},
        profile_models={"implementer": "implementer-model"},
    )

    result = await controller.run_instruction("Inspect two independent files")

    plan = journal.plans_for_run(str(result.run_id))[0]
    assert len(child_model.calls) == 3
    assert [child.status for child in result.child_results] == [
        "succeeded",
        "succeeded",
        "succeeded",
    ]
    assert plan.node_states == {
        "first": PlanNodeState.SUCCEEDED,
        "second": PlanNodeState.SUCCEEDED,
        "after_first": PlanNodeState.SUCCEEDED,
    }
    snapshot = journal.get_session_snapshot(str(session_id))
    assert len(snapshot.tasks) == 4  # Lead plus three plan-owned child tasks.
    assert len(snapshot.attempts) == 4
    bindings = [
        journal.plan_node_task_binding(plan.node_ids[local_id])
        for local_id in ("first", "second", "after_first")
    ]
    assert {binding.task_id for binding in bindings if binding is not None} == {
        str(child.task_id) for child in result.child_results
    }
    assert {binding.attempt_id for binding in bindings if binding is not None} <= {
        attempt.attempt_id for attempt in snapshot.attempts
    }


@pytest.mark.asyncio
async def test_discovery_checkpoint_wakes_lead_and_dispatches_revision(
    tmp_path: Path,
) -> None:
    evidence_path = tmp_path / "planned-evidence.txt"
    evidence_path.write_text("planned dispatch evidence\n", encoding="utf-8")
    evidence_digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    evidence_ref = f"file:planned-evidence.txt:{evidence_digest}"
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Discovery checkpoint", created_at=datetime.now(UTC)
    )
    child_model = ScriptedChatModel(
        model_name="implementer-model",
        responses=[
            _child_success("discovery complete", evidence_digest),
            _child_success("revised follow-up complete", evidence_digest),
        ],
    )
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [("execution_decision", _discovery_decision(), "decision-1")]
            ),
            AIMessage(content="Discovery is running."),
            parallel_tool_call_message(
                [
                    (
                        "execution_decision",
                        _revised_discovery_decision(evidence_ref),
                        "decision-2",
                    )
                ]
            ),
            AIMessage(content="The evidence-backed revision completed."),
        ],
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model, "implementer-model": child_model},
    )

    result = await controller.run_instruction("Discover, reconsider, then report")

    plan = journal.plans_for_run(str(result.run_id))[0]
    assert result.status == "completed", (
        plan.plan.revision,
        [getattr(message, "content", "") for message in result.messages],
    )
    assert result.output == "The evidence-backed revision completed."
    assert len(lead_model.calls) == 4
    assert len(child_model.calls) == 2
    assert plan.plan.revision == 2
    assert plan.node_states == {
        "inspect": PlanNodeState.SUCCEEDED,
        "reconsider": PlanNodeState.SUCCEEDED,
        "report": PlanNodeState.SUCCEEDED,
    }
    assert [child.summary for child in result.child_results] == [
        "discovery complete",
        "revised follow-up complete",
    ]


@pytest.mark.asyncio
async def test_discovery_checkpoint_rejects_unavailable_revision_evidence(
    tmp_path: Path,
) -> None:
    evidence_path = tmp_path / "planned-evidence.txt"
    evidence_path.write_text("planned dispatch evidence\n", encoding="utf-8")
    evidence_digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Invalid revision evidence", created_at=datetime.now(UTC)
    )
    child_model = ScriptedChatModel(
        model_name="implementer-model",
        responses=[_child_success("discovery complete", evidence_digest)],
    )
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [("execution_decision", _discovery_decision(), "decision-1")]
            ),
            AIMessage(content="Discovery is running."),
            parallel_tool_call_message(
                [
                    (
                        "execution_decision",
                        _revised_discovery_decision("artifact:invented"),
                        "decision-2",
                    )
                ]
            ),
            AIMessage(content="I could not admit the revision."),
        ],
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model, "implementer-model": child_model},
    )

    result = await controller.run_instruction("Discover without inventing evidence")

    plan = journal.plans_for_run(str(result.run_id))[0]
    assert result.status == "blocked"
    assert plan.plan.revision == 1
    assert plan.node_states == {
        "inspect": PlanNodeState.SUCCEEDED,
        "reconsider": PlanNodeState.BLOCKED,
    }
    assert any(
        "decision.plan_refused" in str(getattr(message, "content", ""))
        for message in result.messages
    )
    assert len(child_model.calls) == 1


@pytest.mark.asyncio
async def test_planned_agent_nodes_obey_the_shared_child_limit(tmp_path: Path) -> None:
    evidence_path = tmp_path / "planned-evidence.txt"
    evidence_path.write_text("planned dispatch evidence\n", encoding="utf-8")
    evidence_digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    barrier = AsyncStartBarrier()

    async def block_child(_: ScriptedChatModel, messages) -> None:
        prompt = str(messages[-1].content)
        label = (
            "first" if "Inspect the first file" in prompt
            else "second" if "Inspect the second file" in prompt
            else "after-first"
        )
        await barrier.worker(label)

    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Planned child cap", created_at=datetime.now(UTC)
    )
    child_model = ScriptedChatModel(
        model_name="implementer-model",
        responses=[
            _child_success("first complete", evidence_digest),
            _child_success("second complete", evidence_digest),
            _child_success("dependent complete", evidence_digest),
        ],
        async_call_hook=block_child,
    )
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [("execution_decision", _planned_decision(), "decision-1")]
            ),
            AIMessage(content="The planned work has been dispatched."),
        ],
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model, "implementer-model": child_model},
        profile_models={"implementer": "implementer-model"},
    )

    run = asyncio.create_task(
        controller.run_instruction(
            "Inspect two independent files", controls=LeadControls(max_children=2)
        )
    )
    await barrier.wait_for_started(2)
    assert set(barrier.started) == {"first", "second"}
    barrier.release("first")
    await asyncio.wait_for(barrier.wait_for_started(3), timeout=1)
    assert barrier.started[-1] == "after-first"
    barrier.release("second")
    barrier.release("after-first")

    result = await run

    assert result.child_peak_active == 2
    assert [child.status for child in result.child_results] == [
        "succeeded", "succeeded", "succeeded"
    ]


@pytest.mark.asyncio
async def test_authorized_tool_node_settles_before_releasing_agent_without_a_model_call(
    tmp_path: Path,
) -> None:
    evidence_path = tmp_path / "planned-evidence.txt"
    evidence_path.write_text("planned dispatch evidence\n", encoding="utf-8")
    evidence_digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Plan tool node", created_at=datetime.now(UTC)
    )
    child_model = ScriptedChatModel(
        model_name="implementer-model",
        responses=[_child_success("dependent complete", evidence_digest)],
    )
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [
                    (
                        "execution_decision",
                        {
                            "mode": "planned",
                            "objective": "Run a known local check",
                            "constraints": [],
                            "reason": "The check has one bounded follow-up.",
                            "plan": {
                                "schema_version": 1,
                                "policy_version": "adaptive-v1",
                                "revision": 1,
                                "nodes": [
                                    {
                                        "local_id": "check",
                                        "kind": "tool",
                                        "objective": "Check ruff version",
                                        "effect_scope": "read",
                                        "task_features": {
                                            "tool": "execute",
                                            "command": "python",
                                            "arguments": ["-m", "ruff", "--version"],
                                        },
                                    },
                                    {
                                        "local_id": "report",
                                        "kind": "agent",
                                        "objective": "Report the completed local check",
                                        "depends_on": ["check"],
                                        "effect_scope": "workspace_write",
                                        "task_features": {"profile": "implementer"},
                                    },
                                ],
                            },
                        },
                        "decision-1",
                    )
                ]
            ),
            AIMessage(content="The local tool check and dependent report completed."),
        ],
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model, "implementer-model": child_model},
        profile_models={"implementer": "implementer-model"},
    )

    controller.project_trusted = True
    result = await controller.run_instruction("Run the known check")

    plan = journal.plans_for_run(str(result.run_id))[0]
    assert plan.node_states == {
        "check": PlanNodeState.SUCCEEDED,
        "report": PlanNodeState.SUCCEEDED,
    }
    assert len(child_model.calls) == 1
    assert len(lead_model.calls) == 2


@pytest.mark.asyncio
async def test_tool_and_agent_nodes_share_the_three_child_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence_path = tmp_path / "planned-evidence.txt"
    evidence_path.write_text("planned dispatch evidence\n", encoding="utf-8")
    evidence_digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    barrier = AsyncStartBarrier()
    tool_started = Event()
    release_tool = Event()

    def block_tool(*args, **kwargs) -> ExecutionResult:
        del args, kwargs
        tool_started.set()
        assert release_tool.wait(timeout=2)
        return ExecutionResult("completed", returncode=0)

    monkeypatch.setattr(ExecutionPolicy, "run", block_tool)

    async def block_child(model: ScriptedChatModel, _) -> None:
        await barrier.worker(f"agent-{len(model.calls)}")

    decision = _planned_decision()
    plan = decision["plan"]
    assert isinstance(plan, dict)
    nodes = plan["nodes"]
    assert isinstance(nodes, list)
    nodes.append(
        {
            "local_id": "tool",
            "kind": "tool",
            "objective": "Run the bounded local check",
            "effect_scope": "read",
            "task_features": {"tool": "execute", "command": "python", "arguments": []},
        }
    )
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Mixed child cap", created_at=datetime.now(UTC)
    )
    child_model = ScriptedChatModel(
        model_name="implementer-model",
        responses=[
            _child_success("first complete", evidence_digest),
            _child_success("second complete", evidence_digest),
            _child_success("dependent complete", evidence_digest),
        ],
        async_call_hook=block_child,
    )
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message([("execution_decision", decision, "decision-1")]),
            AIMessage(content="Mixed work completed."),
        ],
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model, "implementer-model": child_model},
        project_trusted=True,
    )
    run = asyncio.create_task(controller.run_instruction("Run mixed planned work"))

    assert await asyncio.to_thread(tool_started.wait, 3)
    await barrier.wait_for_started(2)
    release_tool.set()
    for agent in barrier.started:
        barrier.release(agent)
    await barrier.wait_for_started(3)
    barrier.release(barrier.started[-1])

    result = await run

    assert result.child_peak_active == 3


@pytest.mark.asyncio
async def test_unverified_agent_success_does_not_release_its_plan_dependent(tmp_path: Path) -> None:
    decision = _planned_decision()
    plan_payload = decision["plan"]
    assert isinstance(plan_payload, dict)
    nodes = plan_payload["nodes"]
    assert isinstance(nodes, list)
    nodes[:] = [nodes[0], nodes[2]]
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Unverified planned result", created_at=datetime.now(UTC)
    )
    child_model = ScriptedChatModel(
        model_name="implementer-model",
        responses=[
            AIMessage(content='{"status":"succeeded","summary":"No evidence."}'),
            AIMessage(content='{"status":"succeeded","summary":"Still no evidence."}'),
        ],
    )
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message([("execution_decision", decision, "decision-1")]),
            AIMessage(content="The unverified result was retained as a failure."),
        ],
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model, "implementer-model": child_model},
    )

    result = await controller.run_instruction("Run an unverified plan")

    plan = journal.plans_for_run(str(result.run_id))[0]
    assert plan.node_states == {
        "first": PlanNodeState.BLOCKED,
        "after_first": PlanNodeState.BLOCKED,
    }
    assert len(child_model.calls) == 1
    assert result.status == "blocked"
    snapshot = journal.get_session_snapshot(str(session_id))
    assert snapshot.runs[0].status == "blocked"
    assert "run.completed" not in {event.type for event in snapshot.events}
    assert "run.blocked" in {event.type for event in snapshot.events}


@pytest.mark.asyncio
async def test_cancelling_planned_work_marks_inflight_nodes_terminal(tmp_path: Path) -> None:
    evidence_path = tmp_path / "planned-evidence.txt"
    evidence_path.write_text("planned dispatch evidence\n", encoding="utf-8")
    evidence_digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    barrier = AsyncStartBarrier()

    async def block_child(_: ScriptedChatModel, messages) -> None:
        prompt = str(messages[-1].content)
        await barrier.worker("first" if "Inspect the first file" in prompt else "second")

    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Cancel planned work", created_at=datetime.now(UTC)
    )
    child_model = ScriptedChatModel(
        model_name="implementer-model",
        responses=[
            _child_success("first complete", evidence_digest),
            _child_success("second complete", evidence_digest),
        ],
        async_call_hook=block_child,
    )
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [("execution_decision", _planned_decision(), "decision-1")]
            ),
            AIMessage(content="The planned work has been dispatched."),
        ],
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model, "implementer-model": child_model},
    )
    run = asyncio.create_task(controller.run_instruction("Cancel planned work"))
    await barrier.wait_for_started(2)
    run.cancel()

    with pytest.raises(asyncio.CancelledError):
        await run

    snapshot = journal.get_session_snapshot(str(session_id))
    plan = journal.plans_for_run(snapshot.runs[0].run_id)[0]
    assert plan.node_states == {
        "first": PlanNodeState.CANCELLED,
        "second": PlanNodeState.CANCELLED,
        "after_first": PlanNodeState.BLOCKED,
    }
    assert snapshot.runs[0].status == "cancelled"
    lead_task = next(task for task in snapshot.tasks if task.description == "Cancel planned work")
    assert lead_task.status is TaskStatus.RETURNED_TO_LEAD
    lead_attempt = next(
        attempt for attempt in snapshot.attempts if attempt.task_id == lead_task.task_id
    )
    assert lead_attempt.status is AttemptStatus.INTERRUPTED


@pytest.mark.asyncio
async def test_delegation_ask_blocks_when_unapproved(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id),
        title="Delegation ask unapproved",
        created_at=datetime.now(UTC),
    )

    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [
                    ("execution_decision", _direct_decision("Perform work"), "decision-1"),
                    (
                        "task",
                        {"description": "Perform work", "subagent_type": "implementer"},
                        "task-1",
                    ),
                ]
            ),
            AIMessage(content="Delegation was blocked by user approval requirement."),
        ],
    )

    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model},
    )

    result = await controller.run_instruction(
        "Delegate with ask",
        controls=LeadControls(delegation="ask"),
        delegation_approved=False,
    )

    assert "task" in lead_model.bound_tool_names
    # Child was blocked
    assert "blocked by user approval" in result.output


@pytest.mark.asyncio
async def test_delegation_ask_executes_when_approved(tmp_path: Path) -> None:
    (tmp_path / "approved.txt").write_text("approved evidence\n", encoding="utf-8")
    approved_digest = hashlib.sha256((tmp_path / "approved.txt").read_bytes()).hexdigest()
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Delegation ask approved", created_at=datetime.now(UTC)
    )

    child_model = ScriptedChatModel(
        model_name="implementer-model",
        responses=[
            tool_call_message(
                "read_file", {"file_path": "approved.txt"}, call_id="approved-read"
            ),
            AIMessage(
                content=(
                    '{"status":"succeeded","summary":"Approved child output",'
                    '"verification":[{"criterion":"Provide evidence for the completed task",'
                    '"passed":true,"evidence":"approved.txt digest",'
                    '"evidence_ref":{"kind":"file","path":"approved.txt",'
                    f'"digest":"{approved_digest}"}}}}]}}'
                )
            )
        ],
    )
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [
                    ("execution_decision", _direct_decision("Approved work"), "decision-1"),
                    (
                        "task",
                        {"description": "Approved work", "subagent_type": "implementer"},
                        "task-1",
                    ),
                ]
            ),
            AIMessage(content="Approved delegation completed successfully."),
        ],
    )

    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model, "implementer-model": child_model},
    )

    result = await controller.run_instruction(
        "Delegate with approved ask",
        controls=LeadControls(delegation="ask"),
        delegation_approved=True,
    )

    assert "Approved delegation completed" in result.output
    assert len(result.child_results) == 1
    assert result.child_results[0].verification[0].evidence_ref is not None
    assert controller._validate_evidence_ref(
        result.child_results[0].verification[0].evidence_ref
    )
    assert result.child_results[0].status == "succeeded", result.child_results[0]
    plans = journal.plans_for_run(str(result.run_id))
    assert len(plans) == 1
    assert plans[0].node_states == {"compat-task-1": PlanNodeState.SUCCEEDED}


@pytest.mark.asyncio
async def test_write_allowed_false_removes_mutating_tools(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Write disallowed", created_at=datetime.now(UTC)
    )

    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[AIMessage(content="Read-only mode.")],
    )

    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model},
    )

    await controller.run_instruction(
        "Read only", controls=LeadControls(write_allowed=False)
    )

    assert {"write_file", "edit_file", "execute"}.isdisjoint(lead_model.bound_tool_names)


@pytest.mark.asyncio
async def test_returned_child_failure_is_synthesized_once_without_looping(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Failure synthesis", created_at=datetime.now(UTC)
    )

    # Simulated child failure returned to lead
    def failing_child_assigner(spec, number, excluded):
        return None  # Will be overridden in execute

    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [
                    ("execution_decision", _direct_decision("Impossible task"), "decision-1"),
                    (
                        "task",
                        {"description": "Impossible task", "subagent_type": "implementer"},
                        "task-1",
                    ),
                ]
            ),
            AIMessage(
                content="The delegated task failed after escalation: synthesizing failure report."
            ),
        ],
    )

    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model},
    )

    # Force the child subagent execution to return a returned_to_lead result
    async def mock_execute(spec, assignment, packet):
        return TaskResult(
            task_id=spec.task_id,
            status="failed",
            summary="attempt failed",
        )

    result = await controller.run_instruction("Run impossible task")
    assert "synthesizing failure report" in result.output
    # Lead called exactly 2 times (task tool call, then final synthesis); no resubmission loop
    assert len(lead_model.calls) == 2


def _direct_decision(objective: str) -> dict[str, object]:
    return {
        "mode": "direct",
        "objective": objective,
        "constraints": [],
        "reason": "The requested work is bounded.",
    }


def _planned_decision() -> dict[str, object]:
    return {
        "mode": "planned",
        "objective": "Inspect independent files",
        "constraints": ["read only"],
        "reason": "The inspections are independent.",
        "plan": {
            "schema_version": 1,
            "policy_version": "adaptive-v1",
            "revision": 1,
            "nodes": [
                {
                    "local_id": "first",
                    "kind": "agent",
                    "objective": "Inspect the first file",
                    "effect_scope": "read",
                    "task_features": {"profile": "explorer"},
                },
                {
                    "local_id": "second",
                    "kind": "agent",
                    "objective": "Inspect the second file",
                    "effect_scope": "read",
                    "task_features": {"profile": "explorer"},
                },
                {
                    "local_id": "after_first",
                    "kind": "agent",
                    "objective": "Inspect the first result",
                    "depends_on": ["first"],
                    "effect_scope": "read",
                    "task_features": {"profile": "explorer"},
                },
            ],
        },
    }


def _discovery_decision() -> dict[str, object]:
    return {
        "mode": "discovery",
        "objective": "Inspect evidence before choosing the follow-up",
        "constraints": ["read only"],
        "reason": "The follow-up depends on repository evidence.",
        "plan": {
            "schema_version": 1,
            "policy_version": "adaptive-v1",
            "revision": 1,
            "nodes": [
                {
                    "local_id": "inspect",
                    "kind": "agent",
                    "objective": "Inspect the evidence file",
                    "effect_scope": "read",
                    "task_features": {"profile": "explorer"},
                },
                {
                    "local_id": "reconsider",
                    "kind": "checkpoint",
                    "objective": "Revise the plan from inspected evidence",
                    "depends_on": ["inspect"],
                    "effect_scope": "read",
                },
            ],
        },
    }


def _revised_discovery_decision(evidence_ref: str) -> dict[str, object]:
    report = {
        "local_id": "report",
        "kind": "agent",
        "objective": "Report the evidence-backed conclusion",
        "depends_on": ["reconsider"],
        "effect_scope": "read",
        "task_features": {"profile": "explorer"},
    }
    initial = _discovery_decision()
    plan = initial["plan"]
    assert isinstance(plan, dict)
    nodes = plan["nodes"]
    assert isinstance(nodes, list)
    return {
        "mode": "planned",
        "objective": "Report the evidence-backed conclusion",
        "constraints": ["use only recorded discovery evidence"],
        "reason": "The discovery evidence resolved the checkpoint.",
        "plan": {
            **plan,
            "revision": 2,
            "nodes": [*nodes, report],
        },
        "revision": {
            "expected_revision": 1,
            "added_nodes": [report],
            "justification": "The recorded discovery evidence supports the follow-up.",
            "evidence_refs": [evidence_ref],
        },
    }


def _child_success(summary: str, evidence_digest: str) -> AIMessage:
    return AIMessage(
        content=(
            '{"status":"succeeded","summary":"' + summary + '",'
            '"verification":[{"criterion":"dispatch evidence","passed":true,'
            '"evidence":"planned-evidence.txt:1",'
            '"evidence_ref":{"kind":"file","path":"planned-evidence.txt",'
            '"digest":"' + evidence_digest + '"}}]}'
        )
    )
