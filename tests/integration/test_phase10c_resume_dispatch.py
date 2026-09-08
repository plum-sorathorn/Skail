"""Phase 10c: resume must dispatch admitted plan work exactly once.

Deterministic offline fakes only: ScriptedChatModel leads/children, real
journal/checkpoint sqlite files, and a shared ApprovalStore file for the
exact one-shot approval flow. No live providers, no secrets.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from rudder.agents.lead import LeadControls
from rudder.domain.decisions import ExecutionDecision
from rudder.domain.ids import new_run_id, new_session_id
from rudder.domain.plans import (
    ExecutionPlan,
    PlanNode,
    PlanNodeKind,
    PlanNodeState,
)
from rudder.runtime.decisions import DecisionAdmissionError, ExecutionDecisionGate
from rudder.runtime.errors import FrameworkContractError
from rudder.runtime.interrupts import QuestionStore
from rudder.runtime.run_controller import RunController
from rudder.sessions import CheckpointStore, Journal
from rudder.tools.approvals import ApprovalChoice, ApprovalStore
from rudder.tools.execution import CommandRequest
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

    assert result.status == "completed"
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
    from rudder.domain.plans import PlanRevision as PlanRevisionModel

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

    assert result.status == "completed"
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
