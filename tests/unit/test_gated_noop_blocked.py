"""Gated no-op runs must terminate blocked, never completed.

Live defect (2026-09-18, HEAD 0e8859e): a run in which EVERY operational
tool call was rejected with ``execution.decision_required`` — no decision
ever admitted, zero tools completed, zero children — still terminated as
``run.completed`` with exit code 0. That false success is forbidden by
the gated-noop contract; blocked work must return the blocked exit code
requires BLOCKED (3) for this case.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fakes.models import (
    ScriptedChatModel,
    parallel_tool_call_message,
    tool_call_message,
)
from langchain_core.messages import AIMessage

from skail.domain.ids import new_session_id
from skail.runtime.run_controller import RunController
from skail.runtime.workspaces import WorkspaceManager
from skail.sessions.journal import Journal


def _journal(tmp_path: Path) -> Journal:
    journal = Journal(tmp_path / "journal.sqlite")
    journal.migrate()
    return journal


def _git(workspace: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    )


def _repository(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _git(workspace, "init")
    _git(workspace, "config", "user.email", "tests@example.invalid")
    _git(workspace, "config", "user.name", "Skail tests")
    (workspace / "notes.txt").write_text("base\n", encoding="utf-8")
    _git(workspace, "add", "notes.txt")
    _git(workspace, "commit", "-m", "initial")
    return workspace


def _direct_decision(objective: str) -> dict[str, object]:
    return {
        "mode": "direct",
        "objective": objective,
        "constraints": [],
        "reason": "The requested work is bounded.",
    }


def _controller(
    workspace: Path,
    journal: Journal,
    session_id: object,
    lead_model: ScriptedChatModel,
    tmp_path: Path,
) -> RunController:
    return RunController(
        session_id=session_id,  # type: ignore[arg-type]
        workspace=workspace,
        journal=journal,
        models={"lead-model": lead_model, "implementer-model": lead_model},
        workspace_mode="shared",
        workspace_manager=WorkspaceManager(tmp_path / "skail-data"),
    )


def _session(tmp_path: Path) -> tuple[Path, Journal, object]:
    workspace = _repository(tmp_path)
    journal = _journal(tmp_path / "state")
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id),
        title="Gated no-op probe",
        created_at=datetime.now(UTC),
    )
    return workspace, journal, session_id


@pytest.mark.asyncio
async def test_gated_noop_run_terminates_blocked(tmp_path: Path) -> None:
    """Live signature: op tool calls rejected (no decision), then final answer.

    Must terminate blocked (exit 3), not completed (exit 0).
    """
    workspace, journal, session_id = _session(tmp_path)
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            tool_call_message(
                "read_file", {"file_path": "notes.txt"}, call_id="call-1"
            ),
            tool_call_message(
                "read_file", {"file_path": "notes.txt"}, call_id="call-2"
            ),
            tool_call_message(
                "read_file", {"file_path": "notes.txt"}, call_id="call-3"
            ),
            AIMessage(content="I could not proceed without an execution decision."),
        ],
    )
    controller = _controller(workspace, journal, session_id, lead_model, tmp_path)

    result = await controller.run_instruction("Read notes.txt and summarize it")

    assert journal.get_execution_decision(str(result.run_id)) is None
    assert result.child_results == []
    assert result.status == "blocked"


@pytest.mark.asyncio
async def test_zero_tool_final_answer_still_completes(tmp_path: Path) -> None:
    """P1 contract: a run with NO tool calls at all stays completed (exit 0)."""
    workspace, journal, session_id = _session(tmp_path)
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[AIMessage(content="Nothing to do.")],
    )
    controller = _controller(workspace, journal, session_id, lead_model, tmp_path)

    result = await controller.run_instruction("Summarize the workspace")

    assert result.status == "completed"


@pytest.mark.asyncio
async def test_explicit_planned_intent_cannot_complete_without_a_decision(
    tmp_path: Path,
) -> None:
    workspace, journal, session_id = _session(tmp_path)
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            AIMessage(
                content=(
                    "The planned execution launched two explorer agents and completed "
                    "the requested audit."
                )
            )
        ],
    )
    controller = _controller(workspace, journal, session_id, lead_model, tmp_path)

    result = await controller.run_instruction(
        "Use planned execution to audit notes.txt."
    )

    assert journal.get_execution_decision(str(result.run_id)) is None
    assert result.status == "blocked"
    assert "explicitly requires mode=planned" in result.output
    assert "launched two explorer agents" not in result.output
    events = journal.events_after(run_id=str(result.run_id))
    assert not any(event.type == "run.completed" for event in events)
    assert any(
        event.type == "diagnostic.error"
        and event.payload.code == "execution.intent_not_satisfied"
        for event in events
    )


@pytest.mark.asyncio
async def test_explicit_question_request_cannot_complete_as_final_prose(
    tmp_path: Path,
) -> None:
    workspace, journal, session_id = _session(tmp_path)
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            AIMessage(content="Please choose JSON or CSV before I create exporter.py.")
        ],
    )
    controller = _controller(workspace, journal, session_id, lead_model, tmp_path)

    result = await controller.run_instruction(
        "Before creating exporter.py, ask me to choose JSON or CSV. "
        "Do not create or edit exporter.py until I answer."
    )

    assert result.status == "blocked"
    assert "requires a user question" in result.output
    events = journal.events_after(run_id=str(result.run_id))
    assert not any(event.type == "run.completed" for event in events)
    assert not any(
        event.type == "user.question"
        for event in events
    )
    assert any(
        event.type == "diagnostic.error"
        and event.payload.code == "execution.question_required"
        for event in events
    )


@pytest.mark.asyncio
async def test_explicit_question_request_blocks_operations_until_ask_user(
    tmp_path: Path,
) -> None:
    workspace, journal, session_id = _session(tmp_path)
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [
                    (
                        "execution_decision",
                        _direct_decision("Read notes.txt"),
                        "premature-decision",
                    ),
                    (
                        "read_file",
                        {"file_path": "notes.txt"},
                        "premature-read",
                    ),
                ]
            ),
            AIMessage(content="I reviewed notes.txt."),
        ],
    )
    controller = _controller(workspace, journal, session_id, lead_model, tmp_path)

    result = await controller.run_instruction(
        "Ask me to choose JSON or CSV before reading notes.txt. "
        "Do not inspect the file until I answer."
    )

    events = journal.events_after(run_id=str(result.run_id))
    assert result.status == "blocked"
    assert "requires a user question" in result.output
    assert any(
        event.type == "diagnostic.error"
        and event.payload.code == "execution.question_required"
        for event in events
    )
    assert not any(
        event.type == "tool.completed"
        and getattr(event.payload, "tool", None) == "read_file"
        for event in events
    )
    assert journal.get_execution_decision(str(result.run_id)) is None


@pytest.mark.asyncio
async def test_admitted_decision_with_completed_tool_still_completes(
    tmp_path: Path,
) -> None:
    """No regression: decision admitted + tool completed stays completed."""
    workspace, journal, session_id = _session(tmp_path)
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [
                    (
                        "execution_decision",
                        _direct_decision("Read notes.txt"),
                        "decision-1",
                    ),
                    (
                        "read_file",
                        {"file_path": "notes.txt"},
                        "read-1",
                    ),
                ]
            ),
            AIMessage(content="Read notes.txt directly."),
        ],
    )
    controller = _controller(workspace, journal, session_id, lead_model, tmp_path)

    result = await controller.run_instruction("Read notes.txt and summarize it")

    assert journal.get_execution_decision(str(result.run_id)) is not None
    assert result.status == "completed"
