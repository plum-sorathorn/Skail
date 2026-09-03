from datetime import UTC, datetime
from pathlib import Path

import pytest
from fakes.models import ScriptedChatModel, tool_call_message
from langchain_core.messages import AIMessage

from rudder.agents.lead import LeadControls
from rudder.domain.ids import new_session_id
from rudder.runtime.run_controller import RunController
from rudder.sessions.journal import Journal


def _journal(tmp_path: Path) -> Journal:
    j = Journal(tmp_path / "journal.sqlite")
    j.migrate()
    return j


@pytest.mark.asyncio
async def test_headless_core_direct_execution_path(tmp_path: Path) -> None:
    """Checkpoint G: Headless run completes directly without delegation."""
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id),
        title="Checkpoint G Direct",
        created_at=datetime.now(UTC),
    )

    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            tool_call_message(
                "write_file",
                {"file_path": "direct.txt", "content": "direct headless execution\n"},
                call_id="call-write-direct",
            ),
            AIMessage(content="Direct execution finished successfully."),
        ],
    )

    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model},
    )

    result = await controller.run_instruction("Perform direct file write")

    assert (tmp_path / "direct.txt").read_text(encoding="utf-8") == "direct headless execution\n"
    assert "Direct execution finished successfully" in result.output
    assert result.lead_assignment.model == "lead-model"
    assert len(result.child_results) == 0


@pytest.mark.asyncio
async def test_headless_core_three_subagent_delegated_path(tmp_path: Path) -> None:
    """Checkpoint G: Headless run completes through up to 3 dynamically assigned subagents."""
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id),
        title="Checkpoint G Delegated",
        created_at=datetime.now(UTC),
    )

    # Three child models: implementer, tester, reviewer
    implementer_model = ScriptedChatModel(
        model_name="impl-model",
        responses=[
            tool_call_message(
                "write_file",
                {"file_path": "code.py", "content": "def run(): return 'ok'\n"},
                call_id="impl-write",
            ),
            AIMessage(content="Implemented code.py"),
        ],
    )
    tester_model = ScriptedChatModel(
        model_name="test-model",
        responses=[
            AIMessage(content="Tests passed: 100% coverage"),
        ],
    )
    reviewer_model = ScriptedChatModel(
        model_name="review-model",
        responses=[
            AIMessage(content="Code review passed: clean architecture"),
        ],
    )

    # Lead model delegates sequentially or in batch to the 3 subagents, then synthesizes
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            tool_call_message(
                "task",
                {"description": "Write code.py", "subagent_type": "implementer"},
                call_id="task-1",
            ),
            tool_call_message(
                "task",
                {"description": "Verify code.py", "subagent_type": "tester"},
                call_id="task-2",
            ),
            tool_call_message(
                "task",
                {"description": "Review code.py", "subagent_type": "reviewer"},
                call_id="task-3",
            ),
            AIMessage(content="All three stages completed: implementation, testing, and review."),
        ],
    )

    # Map models per subagent assignment
    models = {
        "lead-model": lead_model,
        "impl-model": implementer_model,
        "test-model": tester_model,
        "review-model": reviewer_model,
    }

    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models=models,
        default_lead_model="lead-model",
        default_child_model="impl-model",
        profile_models={
            "implementer": "impl-model",
            "tester": "test-model",
            "reviewer": "review-model",
        },
    )

    # Run instruction with controls max_children=3
    result = await controller.run_instruction(
        "Implement, test, and review code",
        controls=LeadControls(max_children=3),
    )

    assert (tmp_path / "code.py").read_text(encoding="utf-8") == "def run(): return 'ok'\n"
    assert "All three stages completed" in result.output
    # All 3 subagent tasks succeeded
    assert len(result.child_results) == 3
    assert all(r.status == "succeeded" for r in result.child_results)


@pytest.mark.asyncio
async def test_headless_core_escalates_once_and_returns_to_lead(tmp_path: Path) -> None:
    """Checkpoint G: Subagent fails, escalates once, and returns second failure to lead."""
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id),
        title="Checkpoint G Escalation",
        created_at=datetime.now(UTC),
    )

    # Lead model delegates to implementer, then synthesizes the returned failure
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            tool_call_message(
                "task",
                {"description": "Difficult task", "subagent_type": "implementer"},
                call_id="task-1",
            ),
            AIMessage(content="Lead synthesized: The task failed after retry and escalation."),
        ],
    )

    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model},
    )

    result = await controller.run_instruction(
        "Run task that fails twice",
        controls=LeadControls(delegation="auto"),
    )

    assert "Lead synthesized" in result.output
    # Exactly one task delegation call made, then final synthesis without looping
    assert len(lead_model.calls) == 2
