import hashlib
import json
import os
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
    (tmp_path / "brief.txt").write_text("requirements\n", encoding="utf-8")
    code_digest = hashlib.sha256(
        ("def run(): return 'ok'" + os.linesep).encode()
    ).hexdigest()

    # Three child models: implementer, tester, reviewer
    implementer_model = ScriptedChatModel(
        model_name="impl-model",
        responses=[
            tool_call_message(
                "write_file",
                {"file_path": "code.py", "content": "def run(): return 'ok'\n"},
                call_id="impl-write",
            ),
            AIMessage(
                content=(
                    '{"status":"succeeded","summary":"Implemented code.py",'
                    '"changed_paths":["code.py"],"verification":[{'
                    '"criterion":"Provide evidence for the completed task",'
                    '"passed":true,"evidence":"code.py digest",'
                    f'"evidence_ref":{{"kind":"file","path":"code.py","digest":"{code_digest}"}}}}]}}'
                )
            ),
        ],
    )
    tester_model = ScriptedChatModel(
        model_name="test-model",
        responses=[
            AIMessage(
                content=(
                    '{"status":"succeeded","summary":"Tests passed",'
                    '"verification":[{"criterion":"Provide evidence for the completed task",'
                    '"passed":true,"evidence":"brief.txt:1"}]}'
                )
            ),
        ],
    )
    reviewer_model = ScriptedChatModel(
        model_name="review-model",
        responses=[
            AIMessage(
                content=(
                    '{"status":"succeeded","summary":"Review passed",'
                    '"verification":[{"criterion":"Provide evidence for the completed task",'
                    '"passed":true,"evidence":"brief.txt:1"}]}'
                )
            ),
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
    event_types = [event.type for event in journal.get_session_snapshot(str(session_id)).events]
    assert "task.proposed" in event_types
    assert "task.started" in event_types
    assert "task.succeeded" in event_types
    assert "tool.started" in event_types
    assert "tool.completed" in event_types
    snapshot = journal.get_session_snapshot(str(session_id))
    lead_allowances = [
        reservation
        for reservation in snapshot.budget_reservations
        if reservation.task_id is None
    ]
    assert len(lead_allowances) == 3
    assert all(reservation.status == "released" for reservation in lead_allowances)
    assignment_attempts = {assignment.attempt_id for assignment in snapshot.assignments}
    assert all(
        event.attempt_id is None or str(event.attempt_id) in assignment_attempts
        for event in snapshot.events
        if event.type == "model.started"
    )
    with journal._connect() as connection:
        persisted_results = connection.execute(
            "SELECT payload_json FROM task_results ORDER BY rowid"
        ).fetchall()
    assert len(persisted_results) == 3
    terminal_results = [json.loads(row["payload_json"]) for row in persisted_results]
    assert all(item["status"] == "succeeded" for item in terminal_results)
    assert all(item["attempts"] for item in terminal_results)
    assert all(item["verification"] for item in terminal_results)


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


@pytest.mark.asyncio
async def test_live_child_failure_monitor_escalates_repeated_tool_calls(
    tmp_path: Path,
) -> None:
    (tmp_path / "input.txt").write_text("input", encoding="utf-8")
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id),
        title="Failure monitor",
        created_at=datetime.now(UTC),
    )
    repeated = tool_call_message(
        "read_file",
        {"file_path": "input.txt"},
        call_id="read-1",
    )
    first_child = ScriptedChatModel(
        model_name="child-one",
        responses=[
            repeated,
            repeated.model_copy(
                update={"tool_calls": [{**repeated.tool_calls[0], "id": "read-2"}]}
            ),
            repeated.model_copy(
                update={"tool_calls": [{**repeated.tool_calls[0], "id": "read-3"}]}
            ),
        ],
    )
    second_child = ScriptedChatModel(
        model_name="child-two",
        responses=[
            tool_call_message(
                "read_file", {"file_path": "input.txt"}, call_id="read-recovery"
            ),
            AIMessage(
                content=(
                    '{"status":"succeeded","summary":"Recovered",'
                    '"verification":[{"criterion":"Provide evidence for the completed task",'
                    '"passed":true,"evidence":"input.txt digest",'
                    '"evidence_ref":{"kind":"file","path":"input.txt",'
                    '"digest":"c96c6d5be8d08a12e7b5cdc1b207fa6b2430974c86803d8891675e76fd992c20"}}]}'
                )
            )
        ],
    )
    lead = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            tool_call_message(
                "task",
                {"description": "Inspect input", "subagent_type": "implementer"},
                call_id="task-monitor",
            ),
            AIMessage(content="Recovered child result synthesized."),
        ],
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={
            "lead-model": lead,
            "child-one": first_child,
            "child-two": second_child,
        },
        default_lead_model="lead-model",
        default_child_model="child-one",
        profile_models={"implementer": "child-one"},
    )

    result = await controller.run_instruction("Delegate inspection")
    snapshot = journal.get_session_snapshot(str(session_id))

    assert result.child_results and result.child_results[-1].status == "succeeded", (
        snapshot.attempts,
        snapshot.assignments,
    )
    child_attempts = [attempt for attempt in snapshot.attempts if attempt.number in (1, 2)][1:]
    assert [attempt.number for attempt in child_attempts] == [1, 2]
    assert child_attempts[0].status.value == "failed"
    assert child_attempts[1].status.value == "succeeded"
