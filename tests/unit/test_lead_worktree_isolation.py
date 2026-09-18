"""Lead worktree isolation (offline, fake models only).

In ``workspace_mode="worktree"`` the lead must not write directly to the
canonical root: its write-capable tools (``edit_file``/``write_file``/
``execute``) are unbound and stale calls fail closed with a blocked message
directing mutations through ``task`` children. Shared mode intentionally
allows lead-direct writes (T3).
"""

from __future__ import annotations

import hashlib
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from fakes.models import (
    ScriptedChatModel,
    parallel_tool_call_message,
)
from langchain_core.messages import AIMessage, ToolMessage

from skail.agents.lead import LeadControls
from skail.domain.events import DiagnosticPayload
from skail.domain.ids import TaskId, new_session_id
from skail.domain.tasks import ArtifactRef, TaskResult, VerificationResult
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
    (workspace / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(workspace, "add", "tracked.txt")
    _git(workspace, "commit", "-m", "initial")
    return workspace


def _direct_decision(objective: str) -> dict[str, object]:
    return {
        "mode": "direct",
        "objective": objective,
        "constraints": [],
        "reason": "The requested work is bounded.",
    }


def _changesets(journal: Journal) -> list[tuple[str]]:
    with sqlite3.connect(journal.path) as connection:
        rows = connection.execute("SELECT status FROM change_sets").fetchall()
    return [(row[0],) for row in rows]


def _lead_controller(
    workspace: Path,
    journal: Journal,
    session_id: object,
    lead_model: ScriptedChatModel,
    tmp_path: Path,
    workspace_mode: str,
) -> RunController:
    return RunController(
        session_id=session_id,  # type: ignore[arg-type]
        workspace=workspace,
        journal=journal,
        models={"lead-model": lead_model, "implementer-model": lead_model},
        workspace_mode=workspace_mode,
        workspace_manager=WorkspaceManager(tmp_path / "skail-data"),
    )


@pytest.mark.asyncio
async def test_lead_direct_edit_blocked_in_worktree_mode(
    tmp_path: Path,
) -> None:
    """T1: lead-direct edit in worktree mode is blocked with a clear message.

    The write-capable tools are unbound from the lead, so the stale
    ``edit_file`` call fails closed: canonical stays unchanged, zero
    changesets are recorded, and the tool result directs through ``task``.
    """
    workspace = _repository(tmp_path)
    journal = _journal(tmp_path / "state")
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id),
        title="Lead direct edit",
        created_at=datetime.now(UTC),
    )
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [
                    (
                        "execution_decision",
                        _direct_decision("Update the tracked file"),
                        "decision-1",
                    ),
                    (
                        "edit_file",
                        {
                            "file_path": "tracked.txt",
                            "old_string": "base\n",
                            "new_string": "lead-direct\n",
                        },
                        "edit-1",
                    ),
                ]
            ),
            AIMessage(content="Updated the tracked file directly."),
        ],
    )
    controller = _lead_controller(workspace, journal, session_id, lead_model, tmp_path, "worktree")

    result = await controller.run_instruction("Update the tracked file directly")

    assert (workspace / "tracked.txt").read_text(encoding="utf-8") == "base\n"
    assert _changesets(journal) == []
    assert {"edit_file", "write_file", "execute"} & lead_model.bound_tool_names == set()
    assert {"read_file", "grep", "glob", "ls", "task"} <= lead_model.bound_tool_names
    blocked = [
        message
        for message in result.messages
        if isinstance(message, ToolMessage) and message.tool_call_id == "edit-1"
    ]
    assert blocked, "expected a blocked tool result for the stale edit_file call"
    assert blocked[0].status == "error"
    assert "worktree mode" in str(blocked[0].content)
    assert "task" in str(blocked[0].content)


@pytest.mark.asyncio
async def test_child_write_integrates_with_changeset_and_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T2 (GREEN): delegated child path integrates via a changeset."""
    workspace = _repository(tmp_path)
    (workspace / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    journal = _journal(tmp_path / "state")
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id),
        title="Child isolated write",
        created_at=datetime.now(UTC),
    )
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [
                    (
                        "execution_decision",
                        _direct_decision("Delegate safely"),
                        "decision-1",
                    ),
                    (
                        "task",
                        {
                            "description": (
                                '{"description":"Update the tracked file",'
                                '"success_criteria":["Provide evidence for the '
                                'completed task"],'
                                '"write_scope":["tracked.txt"]}'
                            ),
                            "subagent_type": "implementer",
                        },
                        "task-1",
                    ),
                ]
            ),
            AIMessage(content="The worker completed its isolated task."),
        ],
    )
    child_roots: list[Path] = []

    class ChildAgent:
        def __init__(self, root: Path, task_id: str) -> None:
            self.root = root
            self.task_id = task_id

        async def ainvoke(self, state: object) -> dict[str, object]:
            del state
            child_roots.append(self.root)
            assert self.root != workspace
            (self.root / "tracked.txt").write_bytes(b"integrated\n")
            return {
                "messages": [
                    AIMessage(
                        content=TaskResult(
                            task_id=cast(TaskId, self.task_id),
                            status="succeeded",
                            summary="updated in isolated workspace",
                            verification=(
                                VerificationResult(
                                    criterion="Provide evidence for the completed task",
                                    passed=True,
                                    evidence="tracked.txt:1",
                                    evidence_ref=ArtifactRef(
                                        kind="file",
                                        path="tracked.txt",
                                        digest=hashlib.sha256(b"integrated\n").hexdigest(),
                                    ),
                                ),
                            ),
                        ).model_dump_json()
                    )
                ]
            }

    def build_child(*args: object, **kwargs: object) -> ChildAgent:
        del args
        assert isinstance(kwargs["workspace"], Path)
        assert isinstance(kwargs["task_id"], str)
        return ChildAgent(kwargs["workspace"], kwargs["task_id"])

    monkeypatch.setattr("skail.runtime.run_controller.build_default_agent", build_child)
    controller = _lead_controller(workspace, journal, session_id, lead_model, tmp_path, "worktree")

    result = await controller.run_instruction("Delegate this change")

    assert result.child_results, result
    assert result.child_results[0].status == "succeeded", result.child_results
    assert (workspace / "tracked.txt").read_text(encoding="utf-8") == ("integrated\n")
    assert _changesets(journal) == [("integrated",)]
    assert child_roots and child_roots[0] != workspace
    assert not child_roots[0].exists(), "isolated worktree was not cleaned up"


@pytest.mark.asyncio
async def test_lead_direct_edit_lands_in_shared_mode(tmp_path: Path) -> None:
    """T3 (GREEN): shared mode intentionally allows lead-direct writes."""
    workspace = _repository(tmp_path)
    journal = _journal(tmp_path / "state")
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id),
        title="Lead direct edit shared",
        created_at=datetime.now(UTC),
    )
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [
                    (
                        "execution_decision",
                        _direct_decision("Update the tracked file"),
                        "decision-1",
                    ),
                    (
                        "edit_file",
                        {
                            "file_path": "tracked.txt",
                            "old_string": "base\n",
                            "new_string": "lead-direct\n",
                        },
                        "edit-1",
                    ),
                ]
            ),
            AIMessage(content="Updated the tracked file directly."),
        ],
    )
    controller = _lead_controller(workspace, journal, session_id, lead_model, tmp_path, "shared")

    await controller.run_instruction("Update the tracked file directly")

    assert (workspace / "tracked.txt").read_text(encoding="utf-8") == ("lead-direct\n")


@pytest.mark.asyncio
async def test_delegation_off_worktree_falls_back_to_shared_with_diagnostic(
    tmp_path: Path,
) -> None:
    """T4: delegation-off + worktree is contradictory, so fall back to shared.

    With no ``task`` tool and no lead writes nothing could write; the run
    instead uses shared selection and emits the fallback reason through the
    existing ``diagnostic.workspace`` event path.
    """
    workspace = _repository(tmp_path)
    journal = _journal(tmp_path / "state")
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id),
        title="Delegation off worktree fallback",
        created_at=datetime.now(UTC),
    )
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[AIMessage(content="I worked directly because task tool is unavailable.")],
    )
    controller = _lead_controller(workspace, journal, session_id, lead_model, tmp_path, "worktree")

    result = await controller.run_instruction(
        "Try to delegate", controls=LeadControls(delegation="off")
    )

    assert controller.workspace_selection.mode.value == "shared"
    assert controller.workspace_selection.reason == (
        "workspace.isolation_unavailable: delegation-off"
    )
    assert controller._workspace_snapshot is None
    events = journal.events_after(run_id=str(result.run_id))
    diagnostics = [event for event in events if event.type == "diagnostic.workspace"]
    assert diagnostics, "expected a diagnostic.workspace selection event"
    assert any(
        isinstance(event.payload, DiagnosticPayload)
        and event.payload.code == "workspace.isolation_unavailable: delegation-off"
        and event.payload.details.get("mode") == "shared"
        for event in diagnostics
    )
    assert "task" not in lead_model.bound_tool_names
    assert {"edit_file", "write_file"} <= lead_model.bound_tool_names
    assert "execute" not in lead_model.bound_tool_names  # custom execute tool needs subagents
    assert "worked directly" in result.output
