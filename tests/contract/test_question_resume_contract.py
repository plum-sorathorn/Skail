from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from skail.domain.ids import new_session_id
from skail.runtime.interrupts import QuestionStore
from skail.runtime.run_controller import RunController
from skail.sessions import CheckpointStore, Journal
from skail.tools.approvals import ApprovalStore
from tests.fakes.models import ScriptedChatModel, parallel_tool_call_message, tool_call_message


@pytest.mark.asyncio
async def test_answered_question_writes_only_selected_json_exporter_and_focused_test(
    tmp_path: Path,
) -> None:
    journal = Journal(tmp_path / "journal.sqlite")
    journal.migrate()
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Question resume contract", created_at=datetime.now(UTC)
    )
    checkpoints = CheckpointStore(tmp_path / "checkpoints.sqlite")
    questions = QuestionStore(tmp_path / "questions.sqlite")
    approvals = ApprovalStore(tmp_path / "approvals.sqlite")
    lead = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            tool_call_message(
                "ask_user",
                {
                    "prompt": "Choose JSON or CSV.",
                    "reason": "The export format is required.",
                    "options": ["JSON", "CSV"],
                },
                call_id="ask-format",
            )
        ],
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        checkpoints=checkpoints,
        question_store=questions,
        approvals=approvals,
        models={"lead-model": lead},
    )

    first = await controller.run_instruction(
        "Ask me to choose JSON or CSV before editing. Do not write files until I answer."
    )
    assert first.status == "blocked"
    assert first.interrupted is True
    assert not (tmp_path / "exporter.py").exists()
    assert not (tmp_path / "test_exporter.py").exists()

    exporter = "import json\n\n" "def export_json(data):\n" "    return json.dumps(data)\n"
    focused_test = (
        "from exporter import export_json\n\n"
        "def test_export_json():\n"
        "    assert export_json({'format': 'json'}) == '{\"format\": \"json\"}'\n"
    )
    resumed_lead = ScriptedChatModel(
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
                        {"file_path": "exporter.py", "content": exporter},
                        "write-exporter-after-answer",
                    ),
                    (
                        "write_file",
                        {"file_path": "test_exporter.py", "content": focused_test},
                        "write-test-after-answer",
                    ),
                ]
            ),
            AIMessage(content="Created the JSON exporter and focused test after your selection."),
        ],
    )
    resumed = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        checkpoints=checkpoints,
        question_store=questions,
        approvals=approvals,
        models={"lead-model": resumed_lead},
    )
    assert resumed.restore_interrupted() is True

    result = await resumed.resume_interrupted("JSON")

    assert result.status == "completed"
    assert "focused test" in result.output
    assert (tmp_path / "exporter.py").read_text(encoding="utf-8") == exporter
    assert (tmp_path / "test_exporter.py").read_text(encoding="utf-8") == focused_test
    assert {path.name for path in tmp_path.glob("*.py")} == {"exporter.py", "test_exporter.py"}
    assert not tuple(tmp_path.glob("*.csv"))
    focused = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "test_exporter.py"],
        cwd=tmp_path,
        capture_output=True,
        check=False,
        text=True,
    )
    assert focused.returncode == 0, focused.stdout + focused.stderr
    assert "1 passed" in focused.stdout
    events = journal.events_after(run_id=str(result.run_id))
    assert any(event.type == "user.question" for event in events)
    assert any(event.type == "user.answer" for event in events)
    assert sum(
        event.type == "tool.completed" and getattr(event.payload, "tool", None) == "write_file"
        for event in events
    ) == 2
    assert sum(event.type == "run.completed" for event in events) == 1
