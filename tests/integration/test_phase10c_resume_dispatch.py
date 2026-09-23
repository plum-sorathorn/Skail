"""Phase 10c: resume must dispatch admitted plan work exactly once.

Deterministic offline fakes only: ScriptedChatModel leads/children, real
journal/checkpoint sqlite files, and a shared ApprovalStore file for the
exact one-shot approval flow. No live providers, no secrets.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from skail.agents.lead import LeadControls
from skail.domain.decisions import ExecutionDecision
from skail.domain.ids import new_run_id, new_session_id
from skail.domain.plans import (
    ExecutionPlan,
    PlanNode,
    PlanNodeKind,
    PlanNodeState,
)
from skail.domain.tasks import TaskId, TaskResult
from skail.runtime.decisions import DecisionAdmissionError, ExecutionDecisionGate
from skail.runtime.errors import FrameworkContractError
from skail.runtime.interrupts import QuestionStore
from skail.runtime.run_controller import RunController
from skail.sessions import CheckpointStore, Journal
from skail.tools.approvals import ApprovalChoice, ApprovalStore
from skail.tools.execution import CommandRequest
from tests.fakes.models import (
    ScriptedChatModel,
    parallel_tool_call_message,
    tool_call_message,
)

EVIDENCE_NAME = "planned-evidence.txt"
EVIDENCE_TEXT = "planned dispatch evidence\n"


def _stores(tmp_path: Path, name: str):
    journal = Journal(tmp_path / f"{name}-journal.sqlite")
    journal.migrate()
    checkpoints = CheckpointStore(tmp_path / f"{name}-checkpoints.sqlite")
    questions = QuestionStore(tmp_path / f"{name}-questions.sqlite")
    approvals = ApprovalStore(tmp_path / f"{name}-approvals.sqlite")
    return journal, checkpoints, questions, approvals


def _session(journal: Journal) -> str:
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="phase10c", created_at=datetime.now(UTC)
    )
    return str(session_id)


def _evidence(tmp_path: Path) -> str:
    path = tmp_path / EVIDENCE_NAME
    path.write_text(EVIDENCE_TEXT, encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _child_success(summary: str, digest: str) -> AIMessage:
    import json as _json

    return AIMessage(
        content=_json.dumps(
            {
                "status": "succeeded",
                "summary": summary,
                "verification": [
                    {
                        "criterion": "dispatch evidence",
                        "passed": True,
                        "evidence": "planned-evidence.txt:1",
                        "evidence_ref": {
                            "kind": "file",
                            "path": "planned-evidence.txt",
                            "digest": digest,
                        },
                    }
                ],
            }
        )
    )


def _write_planned_evidence(tmp_path: Path) -> str:
    path = tmp_path / "planned-evidence.txt"
    path.write_text("planned dispatch evidence\n", encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _agent_node(local_id: str, objective: str, depends_on: tuple[str, ...] = ()) -> dict:
    node: dict = {
        "local_id": local_id,
        "kind": "agent",
        "objective": objective,
        "effect_scope": "read",
        "acceptance_criteria": ["dispatch evidence"],
        "task_features": {"profile": "explorer"},
    }
    if depends_on:
        node["depends_on"] = list(depends_on)
    return node


def _agent_plan_node(local_id: str, objective: str, depends_on: tuple[str, ...] = ()):
    return PlanNode(
        local_id=local_id,
        kind=PlanNodeKind.AGENT,
        objective=objective,
        depends_on=depends_on,
        acceptance_criteria=("dispatch evidence",),
        task_features={"profile": "explorer"},
    )


def _planned_decision(nodes: list[dict]) -> dict:
    return {
        "mode": "planned",
        "objective": "Inspect before reporting",
        "constraints": ["read only"],
        "reason": "The work has an explicit dependency graph.",
        "plan": {
            "schema_version": 1,
            "policy_version": "adaptive-v1",
            "revision": 1,
            "nodes": nodes,
        },
    }


def _planned_plan_object(nodes: list[PlanNode]) -> ExecutionPlan:
    return ExecutionPlan(
        schema_version=1,
        policy_version="adaptive-v1",
        revision=1,
        nodes=tuple(nodes),
    )


def _controller(
    tmp_path: Path,
    session_id: str,
    journal: Journal,
    checkpoints: CheckpointStore,
    questions: QuestionStore,
    approvals: ApprovalStore,
    models: dict,
    profile_models: dict | None = None,
) -> RunController:
    return RunController(
        session_id=session_id,  # type: ignore[arg-type]
        workspace=tmp_path,
        journal=journal,
        checkpoints=checkpoints,
        question_store=questions,
        approvals=approvals,
        models=models,
        profile_models=profile_models or {},
    )


@pytest.mark.asyncio
async def test_question_interrupt_resume_dispatches_plan_once(tmp_path: Path) -> None:
    """(a) Interrupt first, admit a valid plan on resume, run the child once."""
    digest = _evidence(tmp_path)
    journal, checkpoints, questions, approvals = _stores(tmp_path, "a")
    session_id = _session(journal)
    lead = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            tool_call_message(
                "ask_user",
                {"prompt": "Proceed?", "reason": "confirmation"},
                call_id="ask-1",
            )
        ],
    )
    controller = _controller(
        tmp_path, session_id, journal, checkpoints, questions, approvals,
        {"lead-model": lead},
    )
    first = await controller.run_instruction(
        "Inspect before reporting", controls=LeadControls(max_children=1)
    )
    assert first.status == "blocked"
    assert first.interrupted is True
    first_assignment = first.lead_assignment
    assert first_assignment is not None

    child = ScriptedChatModel(
        model_name="implementer-model", responses=[_child_success("inspect done", digest)]
    )
    resumed_lead = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [
                    (
                        "execution_decision",
                        _planned_decision(
                            [_agent_node("inspect", "Inspect the evidence file")]
                        ),
                        "decision-1",
                    )
                ]
            ),
            AIMessage(content="Planned work finished."),
        ],
    )
    resumed = _controller(
        tmp_path,
        session_id,
        journal,
        checkpoints,
        questions,
        approvals,
        {"lead-model": resumed_lead, "implementer-model": child},
        profile_models={"explorer": "implementer-model"},
    )
    assert resumed.restore_interrupted() is True
    result = await resumed.resume_interrupted("yes")

    assert result.status == "completed"
    assert len(child.calls) == 1
    assert result.lead_assignment is not None
    assert (
        result.lead_assignment.assignment_id == first_assignment.assignment_id
    )
    plan = journal.plans_for_run(str(result.run_id))[0]
    assert plan.node_states == {"inspect": PlanNodeState.SUCCEEDED}
    persisted = journal.get_execution_decision(str(result.run_id))
    assert persisted is not None
    assert persisted.mode == "planned"


@pytest.mark.asyncio
async def test_new_instruction_cannot_consume_a_pending_question_as_context(
    tmp_path: Path,
) -> None:
    journal, checkpoints, questions, approvals = _stores(tmp_path, "pending-question")
    session_id = _session(journal)
    lead = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            tool_call_message(
                "ask_user",
                {"prompt": "Which output should I create?", "reason": "The path is missing."},
                call_id="pending-question",
            )
        ],
    )
    controller = _controller(
        tmp_path,
        session_id,
        journal,
        checkpoints,
        questions,
        approvals,
        {"lead-model": lead},
    )

    first = await controller.run_instruction("Create the requested output.")
    pending = questions.pending(f"{session_id}:{first.run_id}:lead")
    assert first.status == "blocked"
    assert len(pending) == 1

    with pytest.raises(RuntimeError, match="run.pending_interrupt"):
        await controller.run_instruction("Write a different file instead.")

    snapshot = journal.get_session_snapshot(session_id)
    assert len(snapshot.runs) == 1
    assert questions.pending(f"{session_id}:{first.run_id}:lead") == pending


@pytest.mark.asyncio
async def test_approval_interrupt_resume_runs_approved_command_once(
    tmp_path: Path,
) -> None:
    """(b) Direct decision + approval-worthy pwsh command resumes to one real effect."""
    journal, checkpoints, questions, approvals = _stores(tmp_path, "b")
    session_id = _session(journal)
    lead = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [
                    (
                        "execution_decision",
                        {
                            "mode": "direct",
                            "objective": "Write the marker file",
                            "constraints": [],
                            "reason": "The command is bounded and requires approval.",
                        },
                        "decision-1",
                    ),
                    (
                        "execute",
                        {
                            "command": "pwsh",
                            "arguments": [
                                "-Command",
                                "Set-Content -Path marker.txt -Value approved-once",
                            ],
                        },
                        "exec-1",
                    ),
                ]
            ),
            AIMessage(content="Approved command completed."),
        ],
    )
    controller = _controller(
        tmp_path, session_id, journal, checkpoints, questions, approvals,
        {"lead-model": lead},
    )
    first = await controller.run_instruction("Write the marker file")
    assert first.status == "blocked"
    assert first.interrupted is True
    interrupt = first.pending_interrupt
    assert interrupt is not None
    assert interrupt.get("command") == "pwsh"

    approved = CommandRequest(
        str(interrupt["command"]),
        tuple(interrupt["arguments"]),
        Path(str(interrupt["cwd"])),
        session_id=str(interrupt["session_id"]),
        run_id=str(interrupt["run_id"]),
        task_id=str(interrupt["task_id"]),
        action_id=str(interrupt["action_id"]),
    )
    approvals.decide(approved, ApprovalChoice.ALLOW_ONCE)

    resumed_lead = ScriptedChatModel(
        model_name="lead-model",
        responses=[AIMessage(content="Approved command completed.")],
    )
    resumed = _controller(
        tmp_path, session_id, journal, checkpoints, questions, approvals,
        {"lead-model": resumed_lead},
    )
    assert resumed.restore_interrupted() is True
    result = await resumed.resume_interrupted("approved")

    assert result.status == "completed"
    marker = tmp_path / "marker.txt"
    assert marker.exists()
    assert marker.read_text(encoding="utf-8").strip() == "approved-once"
    assert approvals.is_allowed(approved) is False


@pytest.mark.asyncio
async def test_plan_tool_approval_resume_runs_exact_command_once(tmp_path: Path) -> None:
    journal, checkpoints, questions, approvals = _stores(tmp_path, "plan-tool")
    session_id = _session(journal)
    decision = {
        "mode": "planned",
        "objective": "Write the plan marker",
        "constraints": [],
        "reason": "The command is a bounded plan tool.",
        "plan": {
            "schema_version": 1,
            "policy_version": "adaptive-v1",
            "revision": 1,
            "nodes": [
                {
                    "local_id": "write-marker",
                    "kind": "tool",
                    "objective": "Write the marker",
                    "effect_scope": "workspace_write",
                    "task_features": {
                        "tool": "execute",
                        "command": "pwsh",
                        "arguments": [
                            "-Command",
                            "Set-Content -Path plan-marker.txt -Value approved-once",
                        ],
                    },
                }
            ],
        },
    }
    controller = _controller(
        tmp_path,
        session_id,
        journal,
        checkpoints,
        questions,
        approvals,
        {
            "lead-model": ScriptedChatModel(
                model_name="lead-model",
                responses=[
                    parallel_tool_call_message(
                        [("execution_decision", decision, "decision-1")]
                    ),
                    AIMessage(content="Plan command queued."),
                ],
            )
        },
    )

    first = await controller.run_instruction(
        "Write the plan marker", controls=LeadControls(write_allowed=True)
    )
    assert first.interrupted is True
    interrupt = first.pending_interrupt
    assert interrupt is not None
    request = CommandRequest(
        str(interrupt["command"]),
        tuple(interrupt["arguments"]),
        Path(str(interrupt["cwd"])),
        session_id=str(interrupt["session_id"]),
        run_id=str(interrupt["run_id"]),
        task_id=str(interrupt["task_id"]),
        action_id=str(interrupt["action_id"]),
    )
    approvals.decide(request, ApprovalChoice.ALLOW_ONCE)

    restarted = _controller(
        tmp_path,
        session_id,
        journal,
        checkpoints,
        questions,
        approvals,
        {"lead-model": ScriptedChatModel(model_name="lead-model", responses=[])},
    )
    assert restarted.restore_interrupted() is True
    result = await restarted.resume_interrupted("approved")

    assert result.status == "completed"
    assert (tmp_path / "plan-marker.txt").read_text(encoding="utf-8").strip() == "approved-once"
    assert approvals.is_allowed(request) is False


@pytest.mark.asyncio
async def test_restarted_controller_restores_persisted_decision(
    tmp_path: Path,
) -> None:
    """(c) A restarted controller reloads the accepted decision, not an empty gate."""
    journal, checkpoints, questions, approvals = _stores(tmp_path, "c")
    session_id = _session(journal)
    lead = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [
                    (
                        "execution_decision",
                        {
                            "mode": "direct",
                            "objective": "Bounded direct work",
                            "constraints": [],
                            "reason": "The work is bounded.",
                        },
                        "decision-1",
                    ),
                    (
                        "ask_user",
                        {"prompt": "Proceed?", "reason": "confirmation"},
                        "ask-1",
                    ),
                ]
            ),
        ],
    )
    controller = _controller(
        tmp_path, session_id, journal, checkpoints, questions, approvals,
        {"lead-model": lead},
    )
    first = await controller.run_instruction("Do bounded work")
    assert first.status == "blocked"
    assert first.lead_assignment is not None

    restarted = _controller(
        tmp_path, session_id, journal, checkpoints, questions, approvals,
        {
            "lead-model": ScriptedChatModel(
                model_name="lead-model",
                responses=[AIMessage(content="Recovered execution completed.")],
            )
        },
    )
    assert restarted.restore_interrupted() is True
    restored = restarted.restored_decision
    assert restored is not None
    assert restored.mode == "direct"
    persisted = journal.get_execution_decision(str(first.run_id))
    assert persisted is not None
    assert persisted.mode == "direct"

    result = await restarted.resume_interrupted("yes")
    assert result.status == "completed"
    assert result.lead_assignment is not None
    assert result.lead_assignment.assignment_id == first.lead_assignment.assignment_id


@pytest.mark.asyncio
async def test_new_run_does_not_inherit_cancelled_plan_checkpoint_messages(
    tmp_path: Path,
) -> None:
    journal, checkpoints, questions, approvals = _stores(tmp_path, "new-run-thread")
    session_id = _session(journal)
    second_call_started = asyncio.Event()
    release_second_call = asyncio.Event()
    call_number = 0

    async def pause_second_call(_: ScriptedChatModel, __) -> None:
        nonlocal call_number
        call_number += 1
        if call_number == 2:
            second_call_started.set()
            await release_second_call.wait()

    previous_instruction = "Inspect the old work and prepare a plan."
    lead = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            tool_call_message(
                "execution_decision",
                _planned_decision(
                    [
                        {
                            "local_id": "review",
                            "kind": "checkpoint",
                            "objective": "Review evidence before implementation",
                        }
                    ]
                ),
                call_id="cancelled-plan-decision",
            ),
            AIMessage(content="This continuation is cancelled."),
            parallel_tool_call_message(
                [
                    (
                        "execution_decision",
                        {
                            "mode": "direct",
                            "objective": "Write the new output file",
                            "constraints": [],
                            "reason": "The new instruction is independent.",
                        },
                        "new-run-direct-decision",
                    ),
                    (
                        "write_file",
                        {"file_path": "new-output.txt", "content": "new run\n"},
                        "new-run-write",
                    ),
                ]
            ),
            AIMessage(content="The new output file was written."),
        ],
        async_call_hook=pause_second_call,
    )
    controller = _controller(
        tmp_path,
        session_id,
        journal,
        checkpoints,
        questions,
        approvals,
        {"lead-model": lead},
    )

    cancelled = asyncio.create_task(controller.run_instruction(previous_instruction))
    await asyncio.wait_for(second_call_started.wait(), timeout=5)
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled

    first_snapshot = journal.get_session_snapshot(session_id)
    first_run = first_snapshot.runs[-1]
    first_plans = journal.plans_for_run(first_run.run_id)
    checkpoint = checkpoints.latest_valid(session_id)
    assert first_run.status == "cancelled"
    assert len(first_plans) == 1
    assert checkpoint is not None
    assert checkpoint.payload["run_id"] == first_run.run_id
    assert checkpoint.thread_id == f"{session_id}:{first_run.run_id}"
    assert questions.pending(f"{session_id}:{first_run.run_id}:lead") == ()

    result = await controller.run_instruction("Write new-output.txt directly.")

    assert result.status == "completed"
    assert result.run_id != first_run.run_id
    assert (tmp_path / "new-output.txt").read_text(encoding="utf-8") == "new run\n"
    second_decision = journal.get_execution_decision(str(result.run_id))
    assert second_decision is not None
    assert second_decision.mode.value == "direct"
    assert journal.plans_for_run(str(result.run_id)) == ()
    second_run_input = lead.calls[2]
    assert not any(
        getattr(message, "content", None) == previous_instruction
        for message in second_run_input
    )


@pytest.mark.asyncio
async def test_recovery_dispatches_persisted_ready_work(tmp_path: Path) -> None:
    """(d) READY work persisted before the crash dispatches after recovery."""
    digest = _evidence(tmp_path)
    journal, checkpoints, questions, approvals = _stores(tmp_path, "d")
    session_id = _session(journal)
    lead = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            tool_call_message(
                "ask_user",
                {"prompt": "Proceed?", "reason": "confirmation"},
                call_id="ask-1",
            )
        ],
    )
    controller = _controller(
        tmp_path, session_id, journal, checkpoints, questions, approvals,
        {"lead-model": lead},
    )
    first = await controller.run_instruction(
        "Survey before reporting", controls=LeadControls(max_children=1)
    )
    assert first.status == "blocked"

    journal.admit_plan(
        run_id=str(first.run_id),
        plan=_planned_plan_object(
            [
                PlanNode(
                    local_id="survey",
                    kind=PlanNodeKind.AGENT,
                    objective="Survey the evidence file",
                    acceptance_criteria=("dispatch evidence",),
                    task_features={"profile": "explorer"},
                )
            ]
        ),
    )

    child = ScriptedChatModel(
        model_name="implementer-model", responses=[_child_success("survey done", digest)]
    )
    resumed = _controller(
        tmp_path,
        session_id,
        journal,
        checkpoints,
        questions,
        approvals,
        {
            "lead-model": ScriptedChatModel(
                model_name="lead-model",
                responses=[AIMessage(content="Recovered survey completed.")],
            ),
            "implementer-model": child,
        },
        profile_models={"explorer": "implementer-model"},
    )
    assert resumed.restore_interrupted() is True
    result = await resumed.resume_interrupted("yes")

    assert result.status == "completed"
    assert len(child.calls) == 1
    plan = journal.plans_for_run(str(result.run_id))[0]
    assert plan.node_states == {"survey": PlanNodeState.SUCCEEDED}


@pytest.mark.asyncio
async def test_crash_recovery_dispatches_ready_work_from_running_run(
    tmp_path: Path,
) -> None:
    """A process crash leaves a running run recoverable without replaying the lead."""
    digest = _evidence(tmp_path)
    journal, checkpoints, questions, approvals = _stores(tmp_path, "running")
    session_id = _session(journal)
    controller = _controller(
        tmp_path,
        session_id,
        journal,
        checkpoints,
        questions,
        approvals,
        {
            "lead-model": ScriptedChatModel(
                model_name="lead-model",
                responses=[
                    tool_call_message(
                        "ask_user",
                        {"prompt": "Proceed?", "reason": "confirmation"},
                        call_id="ask-1",
                    )
                ],
            )
        },
    )
    first = await controller.run_instruction(
        "Survey before reporting", controls=LeadControls(max_children=1)
    )
    assert first.status == "blocked"
    plan = _planned_plan_object(
        [_agent_plan_node("survey", "Survey the evidence file")]
    )
    journal.admit_plan(
        run_id=str(first.run_id),
        plan=plan,
    )
    journal.record_execution_decision(
        run_id=str(first.run_id),
        decision=ExecutionDecision.model_validate(
            {
                "mode": "planned",
                "objective": "Survey before reporting",
                "constraints": [],
                "reason": "The work has a persisted execution plan.",
                "plan": plan.model_dump(mode="json"),
            }
        ),
    )
    journal.update_run_status(run_id=str(first.run_id), status="running")

    child = ScriptedChatModel(
        model_name="implementer-model", responses=[_child_success("survey done", digest)]
    )
    resumed = _controller(
        tmp_path,
        session_id,
        journal,
        checkpoints,
        questions,
        approvals,
        {
            "lead-model": ScriptedChatModel(model_name="lead-model", responses=[]),
            "implementer-model": child,
        },
        profile_models={"explorer": "implementer-model"},
    )

    assert resumed.restore_interrupted() is True
    result = await resumed.resume_interrupted("")

    assert result.status == "completed"
    assert len(child.calls) == 1
    plan = journal.plans_for_run(str(result.run_id))[0]
    assert plan.node_states == {"survey": PlanNodeState.SUCCEEDED}


@pytest.mark.asyncio
async def test_recovery_never_replays_launched_or_settled_work(
    tmp_path: Path,
) -> None:
    """(e) LAUNCHING/RUNNING/settled work is never replayed after recovery."""
    digest = _evidence(tmp_path)
    journal, checkpoints, questions, approvals = _stores(tmp_path, "e")
    session_id = _session(journal)
    lead = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            tool_call_message(
                "ask_user",
                {"prompt": "Proceed?", "reason": "confirmation"},
                call_id="ask-1",
            )
        ],
    )
    controller = _controller(
        tmp_path, session_id, journal, checkpoints, questions, approvals,
        {"lead-model": lead},
    )
    first = await controller.run_instruction(
        "Survey before reporting", controls=LeadControls(max_children=1)
    )
    assert first.status == "blocked"

    admitted = journal.admit_plan(
        run_id=str(first.run_id),
        plan=_planned_plan_object(
            [
                _agent_plan_node("launched", "Already launched survey work"),
                _agent_plan_node("settled", "Already settled survey work"),
                _agent_plan_node(
                    "after", "Follow-up survey work", depends_on=("launched",)
                ),
            ]
        ),
    )
    launched_id = admitted.node_ids["launched"]
    settled_id = admitted.node_ids["settled"]
    journal.transition_plan_node_state(
        plan_id=admitted.plan_id,
        node_id=launched_id,
        expected=PlanNodeState.READY,
        target=PlanNodeState.LAUNCHING,
    )
    journal.begin_plan_node_execution(
        node_id=launched_id, execution_key="task:already-launched"
    )
    journal.transition_plan_node_state(
        plan_id=admitted.plan_id,
        node_id=settled_id,
        expected=PlanNodeState.READY,
        target=PlanNodeState.LAUNCHING,
    )
    journal.begin_plan_node_execution(
        node_id=settled_id, execution_key="task:already-settled"
    )
    journal.transition_plan_node_state(
        plan_id=admitted.plan_id,
        node_id=settled_id,
        expected=PlanNodeState.LAUNCHING,
        target=PlanNodeState.RUNNING,
    )
    journal.settle_plan_node_execution(
        node_id=settled_id, result={"status": "succeeded", "summary": "done before crash"}
    )
    journal.transition_plan_node_state(
        plan_id=admitted.plan_id,
        node_id=settled_id,
        expected=PlanNodeState.RUNNING,
        target=PlanNodeState.SUCCEEDED,
    )

    child = ScriptedChatModel(
        model_name="implementer-model", responses=[_child_success("must not run", digest)]
    )
    resumed = _controller(
        tmp_path,
        session_id,
        journal,
        checkpoints,
        questions,
        approvals,
        {
            "lead-model": ScriptedChatModel(
                model_name="lead-model",
                responses=[AIMessage(content="Recovered without replay.")],
            ),
            "implementer-model": child,
        },
        profile_models={"explorer": "implementer-model"},
    )
    assert resumed.restore_interrupted() is True
    result = await resumed.resume_interrupted("yes")

    assert result.status == "blocked"
    assert len(child.calls) == 0
    plan = journal.plans_for_run(str(result.run_id))[0]
    assert plan.node_states["launched"] is PlanNodeState.BLOCKED
    assert plan.node_states["settled"] is PlanNodeState.SUCCEEDED
    assert plan.node_states["after"] is PlanNodeState.BLOCKED


def test_stale_revision_rejected(tmp_path: Path) -> None:
    """(f) Stale/mismatched decision revisions are rejected as revision_conflict."""
    nodes = [_agent_node("inspect", "Inspect the evidence file")]
    initial = _planned_decision(nodes)
    revised_nodes = [*nodes, _agent_node("report", "Report the conclusion")]
    revised_plan = {**initial["plan"], "revision": 2, "nodes": revised_nodes}
    revision = {
        "expected_revision": 1,
        "added_nodes": [revised_nodes[-1]],
        "justification": "Evidence supports the follow-up.",
        "evidence_refs": ["artifact:evidence"],
    }

    gate = ExecutionDecisionGate(admit_plan=lambda plan: None, revise_plan=lambda rev, plan: None)
    gate.admit(initial)
    with pytest.raises(DecisionAdmissionError, match="revision_conflict"):
        # Mismatched revision metadata: plan claims r3 but metadata expects r1.
        gate.admit(
            {
                "mode": "planned",
                "objective": "Mismatched follow-up",
                "constraints": [],
                "reason": "Mismatched revision must not apply.",
                "plan": {**initial["plan"], "revision": 3, "nodes": revised_nodes},
                "revision": revision,
            }
        )

    gate2 = ExecutionDecisionGate(
        admit_plan=lambda plan: None, revise_plan=lambda rev, plan: None
    )
    gate2.admit(initial)
    gate2.admit(
        {
            "mode": "planned",
            "objective": "Report the conclusion",
            "constraints": [],
            "reason": "Evidence resolved the follow-up.",
            "plan": revised_plan,
            "revision": revision,
        }
    )
    with pytest.raises(DecisionAdmissionError, match="revision_conflict"):
        gate2.admit(
            {
                "mode": "planned",
                "objective": "Stale follow-up",
                "constraints": [],
                "reason": "Stale revision must not apply.",
                "plan": revised_plan,
                "revision": revision,
            }
        )

    restored_gate = ExecutionDecisionGate(
        admit_plan=lambda plan: None, revise_plan=lambda rev, plan: None
    )
    restored_gate.restore(ExecutionDecision.model_validate(initial))
    assert restored_gate.decision is not None
    assert restored_gate.decision.mode == "planned"
    with pytest.raises(DecisionAdmissionError, match="revision_conflict"):
        restored_gate.admit(
            {
                "mode": "planned",
                "objective": "Mismatched follow-up",
                "constraints": [],
                "reason": "Mismatched revision must not apply.",
                "plan": {**initial["plan"], "revision": 3, "nodes": revised_nodes},
                "revision": revision,
            }
        )

    journal = Journal(tmp_path / "f-journal.sqlite")
    journal.migrate()
    session_f = str(new_session_id())
    run_f = str(new_run_id())
    journal.create_session(
        session_id=session_f, title="revision", created_at=datetime.now(UTC)
    )
    journal.create_run(
        run_id=run_f,
        session_id=session_f,
        status="running",
        budget_limit_usd=None,
        created_at=datetime.now(UTC),
    )
    admitted = journal.admit_plan(
        run_id=run_f,
        plan=ExecutionPlan(
            schema_version=1,
            policy_version="adaptive-v1",
            revision=1,
            nodes=(
                PlanNode(local_id="inspect", kind=PlanNodeKind.AGENT, objective="Inspect"),
            ),
        ),
    )
    good_revision = {
        "expected_revision": 1,
        "added_nodes": [
            {
                "local_id": "report",
                "kind": "agent",
                "objective": "Report",
            }
        ],
        "justification": "Evidence supports the follow-up.",
        "evidence_refs": ["artifact:evidence"],
    }
    good_plan = ExecutionPlan(
        schema_version=1,
        policy_version="adaptive-v1",
        revision=2,
        nodes=(
            PlanNode(local_id="inspect", kind=PlanNodeKind.AGENT, objective="Inspect"),
            PlanNode(local_id="report", kind=PlanNodeKind.AGENT, objective="Report"),
        ),
    )
    from skail.domain.plans import PlanRevision as PlanRevisionModel

    journal.revise_plan(
        plan_id=admitted.plan_id,
        revision=PlanRevisionModel.model_validate(good_revision),
        plan=good_plan,
    )
    with pytest.raises(FrameworkContractError, match="revision_conflict"):
        journal.revise_plan(
            plan_id=admitted.plan_id,
            revision=PlanRevisionModel.model_validate(good_revision),
            plan=good_plan,
        )


class _D3PumpController(RunController):
    """Minimal harness for ``_dispatch_admitted_plan_agents``: journal + events.

    Tool execution and agent admission are overridden so the pump's dispatch,
    settle, and cleanup paths run against a real journal without any lead or
    child model machinery.
    """

    def __init__(self, journal: Journal, *, fail_node_id: str | None = None) -> None:
        self.journal = journal
        self.events = SimpleNamespace(publish_persisted_nowait=lambda event: None)
        self._planned_node_dispatches: list[object] = []
        self._plan_revision_evidence: dict[str, frozenset[str]] = {}
        self._plan_revision_checkpoints: dict[str, str] = {}
        self._fail_node_id = fail_node_id

    def _admit_ready_plan_agents(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    async def _run_plan_tool_node(
        self,
        *,
        run_id: object,
        node_id: str,
        node: object,
        controls: object,
        leases: object,
        scheduler: object,
    ) -> TaskResult:
        del run_id, node, controls, leases, scheduler
        if node_id == self._fail_node_id:
            raise RuntimeError("d3-simulated tool crash")
        await asyncio.sleep(0.05)
        return TaskResult(
            task_id=TaskId(str(new_run_id())),
            status="succeeded",
            summary="d3 probe",
            verification_authority="runtime",
        )


def _d3_journal(tmp_path: Path, name: str) -> tuple[Journal, str]:
    journal = Journal(tmp_path / f"d3-{name}.sqlite")
    journal.migrate()
    session_id = _session(journal)
    run_id = str(new_run_id())
    journal.create_run(
        run_id=run_id,
        session_id=session_id,
        status="running",
        budget_limit_usd=Decimal("2.00"),
        created_at=datetime.now(UTC),
    )
    return journal, run_id


def _d3_tool_plan() -> ExecutionPlan:
    return ExecutionPlan(
        schema_version=1,
        policy_version="adaptive-v1",
        revision=1,
        nodes=(
            PlanNode(local_id="probe_a", kind=PlanNodeKind.TOOL, objective="Probe A"),
            PlanNode(local_id="probe_b", kind=PlanNodeKind.TOOL, objective="Probe B"),
        ),
    )


def _d3_dispatch_kwargs(run_id: str) -> dict[str, object]:
    return {
        "run_id": run_id,
        "workspace_revision": "r0",
        "leases": None,
        "gate": None,
        "scheduler": None,
        "controls": None,
        "delegation_approved": True,
        "lead_assignment": None,
        "lead_agent": None,
        "lead_attempt_id": None,
        "invoke_config": None,
        "recorded_child_results": [],
    }


def test_d3_cancel_of_never_launched_node_is_a_noop(tmp_path: Path) -> None:
    """Cancelling a plan node that never launched completes without raising."""
    journal, run_id = _d3_journal(tmp_path, "cancel")
    admitted = journal.admit_plan(run_id=run_id, plan=_d3_tool_plan())
    controller = _D3PumpController(journal)
    unlaunched = admitted.node_ids["probe_a"]

    controller._cancel_plan_node(admitted.plan_id, unlaunched)

    plan = journal.get_plan(admitted.plan_id)
    assert plan.node_states["probe_a"] is PlanNodeState.READY
    execution = journal.begin_plan_node_execution(
        node_id=unlaunched, execution_key=f"tool:{unlaunched}"
    )
    assert execution.status == "running"


@pytest.mark.asyncio
async def test_d3_pump_failure_exit_settles_running_nodes(tmp_path: Path) -> None:
    """A pump exit via a failed task must not leave detached running nodes."""
    journal, run_id = _d3_journal(tmp_path, "failure-exit")
    admitted = journal.admit_plan(run_id=run_id, plan=_d3_tool_plan())
    probe_a = admitted.node_ids["probe_a"]
    probe_b = admitted.node_ids["probe_b"]
    controller = _D3PumpController(journal, fail_node_id=probe_a)

    with pytest.raises(RuntimeError, match="d3-simulated tool crash"):
        await controller._dispatch_admitted_plan_agents(**_d3_dispatch_kwargs(run_id))

    plan = journal.get_plan(admitted.plan_id)
    assert plan.node_states == {
        "probe_a": PlanNodeState.CANCELLED,
        "probe_b": PlanNodeState.CANCELLED,
    }
    for node_id in (probe_a, probe_b):
        execution = journal.begin_plan_node_execution(
            node_id=node_id, execution_key=f"tool:{node_id}"
        )
        assert execution.status == "settled"
        assert execution.result == {"status": "cancelled"}


@pytest.mark.asyncio
async def test_d3_pump_cancelled_exit_settles_running_nodes(tmp_path: Path) -> None:
    """A cancelled pump exit drains its running tasks and settles their nodes."""
    journal, run_id = _d3_journal(tmp_path, "cancelled-exit")
    admitted = journal.admit_plan(run_id=run_id, plan=_d3_tool_plan())
    controller = _D3PumpController(journal)
    pump = asyncio.create_task(
        controller._dispatch_admitted_plan_agents(**_d3_dispatch_kwargs(run_id))
    )

    await asyncio.sleep(0.01)
    pump.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pump

    plan = journal.get_plan(admitted.plan_id)
    assert plan.node_states == {
        "probe_a": PlanNodeState.CANCELLED,
        "probe_b": PlanNodeState.CANCELLED,
    }
    for node_id in admitted.node_ids.values():
        execution = journal.begin_plan_node_execution(
            node_id=node_id, execution_key=f"tool:{node_id}"
        )
        assert execution.status == "settled"
        assert execution.result == {"status": "cancelled"}


@pytest.mark.asyncio
async def test_recovery_dispatches_independent_ready_despite_bound_sibling(
    tmp_path: Path,
) -> None:
    """(g) Mixed frontier: bound/unsafe sibling never replays, independent READY dispatches."""
    digest = _evidence(tmp_path)
    journal, checkpoints, questions, approvals = _stores(tmp_path, "g")
    session_id = _session(journal)
    lead = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            tool_call_message(
                "ask_user",
                {"prompt": "Proceed?", "reason": "confirmation"},
                call_id="ask-1",
            )
        ],
    )
    controller = _controller(
        tmp_path, session_id, journal, checkpoints, questions, approvals,
        {"lead-model": lead},
    )
    first = await controller.run_instruction(
        "Survey before reporting", controls=LeadControls(max_children=1)
    )
    assert first.status == "blocked"

    admitted = journal.admit_plan(
        run_id=str(first.run_id),
        plan=_planned_plan_object(
            [
                _agent_plan_node("bound", "Already launched survey work"),
                _agent_plan_node("fresh", "Independent survey work"),
            ]
        ),
    )
    bound_id = admitted.node_ids["bound"]
    fresh_id = admitted.node_ids["fresh"]
    run_id = str(first.run_id)
    bound_task_id = f"task-{bound_id}"
    bound_attempt_id = f"attempt-{bound_id}"
    now = datetime.now(UTC)
    journal.create_task(
        task_id=bound_task_id,
        run_id=run_id,
        description="Already launched survey work",
        status="queued",
        idempotency_key=f"task:{bound_task_id}",
        created_at=now,
    )
    journal.create_attempt(
        attempt_id=bound_attempt_id,
        task_id=bound_task_id,
        number=1,
        status="assigned",
        idempotency_key=f"attempt:{bound_attempt_id}",
        created_at=now,
    )
    journal.transition_plan_node_state(
        plan_id=admitted.plan_id,
        node_id=bound_id,
        expected=PlanNodeState.READY,
        target=PlanNodeState.LAUNCHING,
    )
    journal.begin_plan_node_execution(
        node_id=bound_id, execution_key=f"task:{bound_task_id}"
    )
    journal.bind_plan_node_task(
        node_id=bound_id,
        task_id=bound_task_id,
        attempt_id=bound_attempt_id,
    )

    child = ScriptedChatModel(
        model_name="implementer-model", responses=[_child_success("fresh done", digest)]
    )
    resumed = _controller(
        tmp_path,
        session_id,
        journal,
        checkpoints,
        questions,
        approvals,
        {
            "lead-model": ScriptedChatModel(
                model_name="lead-model",
                responses=[AIMessage(content="Recovered mixed frontier.")],
            ),
            "implementer-model": child,
        },
        profile_models={"explorer": "implementer-model"},
    )
    assert resumed.restore_interrupted() is True
    result = await resumed.resume_interrupted("yes")

    assert result.status == "blocked"
    assert len(child.calls) == 1
    plan = journal.plans_for_run(str(result.run_id))[0]
    assert plan.node_states["bound"] is PlanNodeState.BLOCKED
    assert plan.node_states["fresh"] is PlanNodeState.SUCCEEDED
    bound_binding = journal.plan_node_task_binding(bound_id)
    assert bound_binding is not None
    assert bound_binding.task_id == bound_task_id
    fresh_binding = journal.plan_node_task_binding(fresh_id)
    assert fresh_binding is not None
    assert fresh_binding.task_id != bound_task_id


@pytest.mark.asyncio
async def test_interrupt_between_admission_and_launch_blocks_unlaunched_node(
    tmp_path: Path,
) -> None:
    """D-3: an interrupt after admission blocks the unlaunched agent idempotently.

    The lead admits a planned AGENT node and then asks a question, so the
    dispatch pump never runs.  The blocked exit must persist the node as
    BLOCKED (not LAUNCHING) with exactly one plan.node_blocked, and the
    resume must not sweep it again, re-admit it, or mint new attempts.
    """
    journal, checkpoints, questions, approvals = _stores(tmp_path, "d3-exit")
    session_id = _session(journal)
    lead = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [
                    (
                        "execution_decision",
                        _planned_decision([_agent_node("inspect", "Inspect the evidence file")]),
                        "decision-1",
                    ),
                    (
                        "ask_user",
                        {"prompt": "Proceed?", "reason": "confirmation"},
                        "ask-1",
                    ),
                ]
            ),
        ],
    )
    controller = _controller(
        tmp_path,
        session_id,
        journal,
        checkpoints,
        questions,
        approvals,
        {"lead-model": lead},
        profile_models={"explorer": "implementer-model"},
    )
    first = await controller.run_instruction("Inspect before reporting")
    assert first.status == "blocked"
    assert first.interrupted is True

    plan = journal.plans_for_run(str(first.run_id))[0]
    assert plan.node_states == {"inspect": PlanNodeState.BLOCKED}
    blocked = [
        event
        for event in journal.events_after(run_id=str(first.run_id))
        if event.type == "plan.node_blocked"
    ]
    assert len(blocked) == 1
    attempts = journal.plans_for_run(str(first.run_id))  # the node keeps its binding
    binding = journal.plan_node_task_binding(
        attempts[0].node_ids["inspect"]
    )
    assert binding is not None

    resumed_lead = ScriptedChatModel(
        model_name="lead-model",
        responses=[AIMessage(content="No further work needed.")],
    )
    resumed = _controller(
        tmp_path,
        session_id,
        journal,
        checkpoints,
        questions,
        approvals,
        {"lead-model": resumed_lead},
        profile_models={"explorer": "implementer-model"},
    )
    assert resumed.restore_interrupted() is True
    result = await resumed.resume_interrupted("yes")

    # Nothing launches: the reconciled node stays BLOCKED, no LAUNCHING
    # orphans, no duplicate plan.node_blocked, and the child cap holds.
    assert result.status == "blocked"
    assert result.child_peak_active <= 3
    plan = journal.plans_for_run(str(result.run_id))[0]
    assert plan.node_states == {"inspect": PlanNodeState.BLOCKED}
    still = [
        event
        for event in journal.events_after(run_id=str(result.run_id))
        if event.type == "plan.node_blocked"
    ]
    assert len(still) == 1
