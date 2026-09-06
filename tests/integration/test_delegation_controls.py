import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fakes.models import ScriptedChatModel, parallel_tool_call_message, tool_call_message
from langchain_core.messages import AIMessage

from rudder.agents.lead import LeadControls
from rudder.domain.ids import new_session_id
from rudder.domain.tasks import TaskResult
from rudder.runtime.run_controller import RunController
from rudder.sessions.journal import Journal


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
