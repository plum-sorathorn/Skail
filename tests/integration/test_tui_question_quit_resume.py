"""Mounted TUI coverage for quitting and resuming a durable question interrupt."""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from langchain_core.messages import AIMessage

from skail.domain.ids import new_session_id
from skail.runtime.interrupts import QuestionStore
from skail.runtime.run_controller import RunController
from skail.sessions import CheckpointStore, Journal
from skail.tools.approvals import ApprovalStore
from skail.tui.app import SkailApp
from skail.tui.widgets.interrupts import InterruptWidget
from tests.fakes.models import ScriptedChatModel, parallel_tool_call_message, tool_call_message


async def test_ctrl_c_quits_with_pending_question_and_fresh_tui_resumes_it(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    journal = Journal(tmp_path / "journal.sqlite")
    journal.migrate()
    checkpoints = CheckpointStore(tmp_path / "checkpoints.sqlite")
    questions = QuestionStore(tmp_path / "questions.sqlite")
    approvals = ApprovalStore(tmp_path / "approvals.sqlite")
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="TUI question resume", created_at=datetime.now(UTC)
    )

    first_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            tool_call_message(
                "ask_user",
                {
                    "prompt": "Choose JSON or CSV.",
                    "reason": "The exporter format is required.",
                    "options": ["JSON", "CSV"],
                },
                call_id="ask-format",
            )
        ],
    )
    controller = RunController(
        session_id=session_id,
        workspace=workspace,
        journal=journal,
        checkpoints=checkpoints,
        question_store=questions,
        approvals=approvals,
        models={"lead-model": first_model},
    )
    app = SkailApp(controller=controller, session_id=session_id)

    async with app.run_test() as pilot:
        composer = app.query_one("#composer-input")
        composer.focus()
        composer.text = (
            "Before editing exporter.py, ask me to choose JSON or CSV. "
            "Do not write until I answer."
        )
        await pilot.press("enter")
        durable_question_found = False
        durable_checkpoint_found = False
        pending = None
        for _ in range(100):
            await pilot.pause(0.05)
            pending = app.projection.pending_interrupt
            if pending is None:
                continue
            question_graph_id = app._question_graph_id(pending.payload)
            durable_question_found = any(
                question.question_id == pending.approval_id
                for question in questions.pending(question_graph_id)
            )
            current_snapshot = journal.get_session_snapshot(str(session_id))
            current_run_id = (
                current_snapshot.runs[-1].run_id if current_snapshot.runs else None
            )
            checkpoint = checkpoints.latest_valid(str(session_id))
            durable_checkpoint_found = (
                checkpoint is not None
                and checkpoint.session_id == str(session_id)
                and checkpoint.status == "interrupted"
                and checkpoint.payload.get("run_id") == current_run_id
            )
            if durable_question_found and durable_checkpoint_found:
                break
        assert pending is not None
        question_id = pending.approval_id
        assert pending.kind.value == "question"
        assert durable_question_found
        assert durable_checkpoint_found
        first_snapshot = journal.get_session_snapshot(str(session_id))
        assert first_snapshot.runs
        initial_run = first_snapshot.runs[-1]
        assert initial_run.status != "completed"
        assert not (workspace / "exporter.py").exists()
        await pilot.press("ctrl+c")
        assert app.app_state == "quitting"

    quit_snapshot = journal.get_session_snapshot(str(session_id))
    quit_run = next(run for run in quit_snapshot.runs if run.run_id == initial_run.run_id)
    assert quit_run.status != "completed"
    assert not any(
        event.type == "run.completed" and str(event.run_id) == initial_run.run_id
        for event in quit_snapshot.events
    )
    assert len(first_model.calls) == 1

    resumed_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [
                    (
                        "execution_decision",
                        {
                            "mode": "direct",
                            "objective": "Create the JSON exporter and focused test",
                            "reason": "The accepted answer selected JSON.",
                        },
                        "decision-after-answer",
                    ),
                    (
                        "write_file",
                        {
                            "file_path": "exporter.py",
                            "content": (
                                "import json\n\ndef export_json(data):\n"
                                "    return json.dumps(data)\n"
                            ),
                        },
                        "write-exporter-after-answer",
                    ),
                    (
                        "write_file",
                        {
                            "file_path": "test_exporter.py",
                            "content": (
                                "from exporter import export_json\n\n"
                                "def test_export_json():\n"
                                "    assert export_json({'format': 'json'}) "
                                "== '{\"format\": \"json\"}'\n"
                            ),
                        },
                        "write-test-after-answer",
                    ),
                ]
            ),
            AIMessage(content="Created and verified the JSON exporter and focused test."),
        ],
    )
    resumed_journal = Journal(tmp_path / "journal.sqlite")
    resumed_journal.migrate()
    resumed_checkpoints = CheckpointStore(tmp_path / "checkpoints.sqlite")
    resumed_questions = QuestionStore(tmp_path / "questions.sqlite")
    resumed_approvals = ApprovalStore(tmp_path / "approvals.sqlite")
    resumed_controller = RunController(
        session_id=session_id,
        workspace=workspace,
        journal=resumed_journal,
        checkpoints=resumed_checkpoints,
        question_store=resumed_questions,
        approvals=resumed_approvals,
        models={"lead-model": resumed_model},
    )
    assert resumed_controller.restore_interrupted() is True
    assert resumed_controller.pending_interrupt is not None
    assert resumed_controller.pending_interrupt["question_id"] == question_id
    resumed_app = SkailApp(
        controller=resumed_controller,
        session_id=session_id,
        initial_snapshot=resumed_journal.get_session_snapshot(str(session_id)),
    )

    async with resumed_app.run_test() as pilot:
        restored = resumed_app.projection.pending_interrupt
        assert restored is not None
        assert restored.approval_id == question_id
        answer_input = resumed_app.query_one(InterruptWidget).query_one("#interrupt-input")
        await pilot.click(answer_input)
        for char in "JSON":
            await pilot.press(char)
        await pilot.press("enter")
        for _ in range(100):
            await pilot.pause(0.1)
            if not resumed_app._run_active:
                break

    assert (workspace / "exporter.py").exists()
    assert (workspace / "test_exporter.py").exists()
    assert {path.name for path in workspace.glob("*.py")} == {"exporter.py", "test_exporter.py"}
    focused = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "test_exporter.py"],
        cwd=workspace,
        capture_output=True,
        check=False,
        text=True,
    )
    assert focused.returncode == 0, focused.stdout + focused.stderr
    assert "1 passed" in focused.stdout
    final_snapshot = resumed_journal.get_session_snapshot(str(session_id))
    assert final_snapshot.runs
    final_run = final_snapshot.runs[-1]
    assert final_run.run_id == initial_run.run_id
    assert final_run.status == "completed"
    run_events = resumed_journal.events_after(run_id=initial_run.run_id)
    assert any(event.type == "user.answer" for event in run_events)
    assert any(event.type == "run.completed" for event in run_events)
    assert len(resumed_model.calls) == 2
