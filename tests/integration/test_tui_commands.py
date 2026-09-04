from decimal import Decimal
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from rudder.domain.ids import SessionId, new_session_id
from rudder.domain.routing import RoutingMode
from rudder.providers.fake import DeterministicFakeChatModel
from rudder.runtime.interrupts import QuestionStore
from rudder.runtime.run_controller import RunController
from rudder.sessions.checkpoints import CheckpointStore
from rudder.sessions.journal import Journal
from rudder.sessions.service import SessionService
from rudder.tools.approvals import ApprovalStore
from rudder.tools.execution import CommandRequest
from rudder.tui.app import RudderApp
from rudder.tui.commands import dispatch_slash_command, parse_slash_command
from rudder.tui.projection import InterruptItem, TuiProjection
from rudder.tui.widgets.composer import PromptComposer
from rudder.tui.widgets.interrupts import InterruptWidget
from tests.fakes.models import ScriptedChatModel, tool_call_message


def test_parse_slash_command() -> None:
    assert parse_slash_command("not a command") == ("", [])
    assert parse_slash_command("/help") == ("help", [])
    assert parse_slash_command("/mode economy") == ("mode", ["economy"])
    assert parse_slash_command("/steer task-1 please fix formatting") == (
        "steer",
        ["task-1", "please", "fix", "formatting"],
    )


def test_dispatch_all_required_slash_commands() -> None:
    proj = TuiProjection()

    # /help
    res_help = dispatch_slash_command("/help", proj)
    assert res_help.action == "message"
    assert "Available Slash Commands" in (res_help.output_message or "")

    # /agents
    res_agents = dispatch_slash_command("/agents", proj)
    assert res_agents.action == "view"
    assert res_agents.target_view == "agents"

    # /agent <id>
    res_agent = dispatch_slash_command("/agent task-42", proj)
    assert res_agent.action == "view"
    assert res_agent.target_id == "task-42"
    assert proj.focused_agent_id == "task-42"

    # /tasks
    res_tasks = dispatch_slash_command("/tasks", proj)
    assert res_tasks.action == "view"
    assert res_tasks.target_view == "agents"

    # /route
    res_route = dispatch_slash_command("/route task-42", proj)
    assert res_route.action == "view"
    assert res_route.target_id == "task-42"

    # /budget
    res_budget = dispatch_slash_command("/budget", proj)
    assert res_budget.action == "view"
    assert res_budget.target_view == "budget"

    # /mode
    res_mode = dispatch_slash_command("/mode economy", proj)
    assert res_mode.action == "message"
    assert proj.footer_data.routing_mode == "economy"

    # /model
    res_model = dispatch_slash_command("/model fake:fast-model", proj)
    assert res_model.action == "message"
    assert proj.footer_data.lead_model == "fake:fast-model"

    # /resume, /compact, /trust, /config, /quit
    assert dispatch_slash_command("/resume", proj).action == "resume"
    assert dispatch_slash_command("/compact", proj).action == "compact"
    assert dispatch_slash_command("/trust", proj).action == "message"
    assert dispatch_slash_command("/config", proj).action == "message"
    assert dispatch_slash_command("/quit", proj).action == "quit"


def test_cancellation_and_steering_background_gating() -> None:
    proj = TuiProjection()

    # Foreground run cancellation (without args) is always safe
    res_cancel_all = dispatch_slash_command("/cancel", proj, background_supported=False)
    assert res_cancel_all.action == "cancel"
    assert res_cancel_all.target_id is None

    # Individual task cancellation without background adapter returns clear error
    res_cancel_ind = dispatch_slash_command(
        "/cancel task-1", proj, background_supported=False
    )
    assert res_cancel_ind.action == "error"
    assert "background adapter" in (res_cancel_ind.output_message or "").lower()

    # Individual task cancellation WITH background adapter succeeds
    res_cancel_bg = dispatch_slash_command(
        "/cancel task-1", proj, background_supported=True
    )
    assert res_cancel_bg.action == "cancel"
    assert res_cancel_bg.target_id == "task-1"

    # Steering without background adapter returns error
    res_steer_err = dispatch_slash_command(
        "/steer task-1 do this", proj, background_supported=False
    )
    assert res_steer_err.action == "error"
    assert "background adapter" in (res_steer_err.output_message or "").lower()

    # Steering WITH background adapter succeeds
    res_steer_ok = dispatch_slash_command(
        "/steer task-1 do this", proj, background_supported=True
    )
    assert res_steer_ok.action == "steer"
    assert res_steer_ok.target_id == "task-1"
    assert res_steer_ok.payload["message"] == "do this"


@pytest.mark.asyncio
async def test_interactive_approval_flow_in_app() -> None:
    proj = TuiProjection()
    proj.pending_interrupt = InterruptItem(
        approval_id="app-test-99",
        task_id="task-99",
        question="Execute rm -rf on build directory?",
        status="pending",
    )

    app = RudderApp(projection=proj)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        # Verify interrupt widget is mounted
        assert app.query_one(InterruptWidget) is not None

        # Click approve
        await pilot.click("#btn-approve")
        await pilot.pause()

        # Verify interrupt cleared and user answer added to transcript
        assert app.projection.pending_interrupt is None
        assert any(
            i.role == "user" and "yes" in i.content
            for i in app.projection.transcript_items
        )


@pytest.mark.asyncio
async def test_tui_prompt_submission_executes_controller(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "journal.sqlite")
    journal.migrate()
    checkpoints = CheckpointStore(tmp_path / "checkpoints.sqlite")
    checkpoints.initialize()
    session_service = SessionService(
        journal=journal,
        checkpoints=checkpoints,
        sessions_dir=tmp_path / "sessions",
    )
    session = session_service.create_session(title="Test TUI Session")
    sid = SessionId(session.session_id)

    fake_model = DeterministicFakeChatModel(
        model_name="lead-model",
        response_text="Hello from Rudder lead!",
    )
    controller = RunController(
        session_id=sid,
        workspace=tmp_path,
        journal=journal,
        checkpoints=checkpoints,
        models={"lead-model": fake_model, "implementer-model": fake_model},
        default_lead_model="lead-model",
        default_child_model="implementer-model",
        budget_limit_usd=Decimal("10.00"),
    )

    app = RudderApp(
        controller=controller,
        session_service=session_service,
        session_id=sid,
        max_children=1,
        delegation="off",
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        app.projection.footer_data.routing_mode = "quality"
        # Submit a prompt
        app.on_prompt_composer_prompt_submitted(
            PromptComposer.PromptSubmitted("Build a small feature")
        )
        # Wait for worker to finish
        if app._active_worker is not None:
            await app._active_worker.wait()
        await pilot.pause()

        roles = [i.role for i in app.projection.transcript_items]
        assert "user" in roles
        assert "lead" in roles
        assert any("Hello from Rudder lead!" in i.content for i in app.projection.transcript_items)
        snapshot = journal.get_session_snapshot(str(sid))
        assert snapshot.assignments[0].payload["routing_mode"] == RoutingMode.QUALITY.value


@pytest.mark.asyncio
async def test_tui_slash_commands_integration(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "journal.sqlite")
    journal.migrate()
    checkpoints = CheckpointStore(tmp_path / "checkpoints.sqlite")
    checkpoints.initialize()
    session_service = SessionService(
        journal=journal,
        checkpoints=checkpoints,
        sessions_dir=tmp_path / "sessions",
    )
    session = session_service.create_session(title="TUI Slash Session")
    sid = SessionId(session.session_id)

    app = RudderApp(
        session_service=session_service,
        session_id=sid,
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        # Test /resume
        app.on_prompt_composer_prompt_submitted(PromptComposer.PromptSubmitted("/resume"))
        await pilot.pause()
        assert any("resume" in i.title.lower() for i in app.projection.transcript_items)

        # Test /compact
        app.on_prompt_composer_prompt_submitted(PromptComposer.PromptSubmitted("/compact"))
        await pilot.pause()
        assert any("compact" in i.title.lower() for i in app.projection.transcript_items)


@pytest.mark.asyncio
async def test_tui_approval_store_and_question_store_integration(tmp_path: Path) -> None:
    q_store = QuestionStore(tmp_path / "questions.sqlite")
    app_store = ApprovalStore(tmp_path / "approvals.sqlite")
    sid = new_session_id()

    # Ask a question in store
    q = q_store.ask(
        graph_id="lead",
        task_id=None,
        prompt="Confirm database migration?",
        reason="destructive",
        blocking_scope="task",
        idempotency_key="q-test-1",
    )

    proj = TuiProjection()
    proj.pending_interrupt = InterruptItem(
        approval_id=q.question_id,
        task_id=None,
        question="Confirm database migration?",
        status="pending",
    )

    app = RudderApp(
        projection=proj,
        question_store=q_store,
        approval_store=app_store,
        session_id=sid,
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert app.query_one(InterruptWidget) is not None

        # Click approve
        await pilot.click("#btn-approve")
        await pilot.pause()

        # Verify question answered in QuestionStore
        assert app.projection.pending_interrupt is None
        answered = q_store.pending("lead")
        assert len(answered) == 0


@pytest.mark.asyncio
async def test_tui_answer_resumes_the_interrupted_controller(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "journal.sqlite")
    journal.migrate()
    checkpoints = CheckpointStore(tmp_path / "checkpoints.sqlite")
    checkpoints.initialize()
    session_service = SessionService(
        journal=journal,
        checkpoints=checkpoints,
        sessions_dir=tmp_path / "sessions",
    )
    session = session_service.create_session(title="TUI Resume Session")
    sid = SessionId(session.session_id)
    questions = QuestionStore(tmp_path / "questions.sqlite")
    model = ScriptedChatModel(
        responses=[
            tool_call_message(
                "ask_user",
                {"prompt": "Proceed?", "reason": "confirmation"},
                call_id="ask-1",
            ),
            AIMessage(content="Continued after the answer."),
        ]
    )
    controller = RunController(
        session_id=sid,
        workspace=tmp_path,
        journal=journal,
        checkpoints=checkpoints,
        models={"lead-model": model, "implementer-model": model},
        default_lead_model="lead-model",
        default_child_model="implementer-model",
        question_store=questions,
    )
    app = RudderApp(
        controller=controller,
        session_service=session_service,
        session_id=sid,
        question_store=questions,
    )

    async with app.run_test(size=(120, 40)) as pilot:
        app.on_prompt_composer_prompt_submitted(PromptComposer.PromptSubmitted("Ask first"))
        assert app._active_worker is not None
        await app._active_worker.wait()
        await pilot.pause()
        assert app.projection.pending_interrupt is not None, [
            item.content for item in app.projection.transcript_items
        ]

        await pilot.click("#btn-approve")
        assert app._active_worker is not None
        await app._active_worker.wait()
        await pilot.pause()

        assert questions.pending("lead") == ()
        assert any(
            "Continued after the answer." in item.content
            for item in app.projection.transcript_items
        ), [item.content for item in app.projection.transcript_items]
        assert journal.get_session_snapshot(str(sid)).runs[-1].status == "completed"


@pytest.mark.asyncio
async def test_tui_command_approval_executes_once_and_resumes(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "journal.sqlite")
    journal.migrate()
    checkpoints = CheckpointStore(tmp_path / "checkpoints.sqlite")
    checkpoints.initialize()
    session_service = SessionService(
        journal=journal,
        checkpoints=checkpoints,
        sessions_dir=tmp_path / "sessions",
    )
    session = session_service.create_session(title="TUI Command Approval")
    sid = SessionId(session.session_id)
    approvals = ApprovalStore(tmp_path / "approvals.sqlite")
    request = CommandRequest("pwsh", ("-Command", "Write-Output approved"), tmp_path)
    model = ScriptedChatModel(
        responses=[
            tool_call_message(
                "execute",
                {"command": request.executable, "arguments": list(request.arguments)},
                call_id="exec-1",
            ),
            AIMessage(content="Approved command completed."),
        ]
    )
    controller = RunController(
        session_id=sid,
        workspace=tmp_path,
        journal=journal,
        checkpoints=checkpoints,
        models={"lead-model": model, "implementer-model": model},
        default_lead_model="lead-model",
        default_child_model="implementer-model",
        approvals=approvals,
    )
    app = RudderApp(
        controller=controller,
        session_service=session_service,
        session_id=sid,
        approval_store=approvals,
    )

    async with app.run_test(size=(120, 40)) as pilot:
        app.on_prompt_composer_prompt_submitted(PromptComposer.PromptSubmitted("Run command"))
        assert app._active_worker is not None
        await app._active_worker.wait()
        await pilot.pause()
        assert app.projection.pending_interrupt is not None

        await pilot.click("#btn-approve")
        assert app._active_worker is not None
        await app._active_worker.wait()
        await pilot.pause()

        assert any(
            "Approved command completed." in item.content
            for item in app.projection.transcript_items
        )
        assert not approvals.is_allowed(request)


@pytest.mark.asyncio
async def test_tui_rejection_blocks_the_interrupted_run(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "journal.sqlite")
    journal.migrate()
    checkpoints = CheckpointStore(tmp_path / "checkpoints.sqlite")
    checkpoints.initialize()
    session_service = SessionService(
        journal=journal,
        checkpoints=checkpoints,
        sessions_dir=tmp_path / "sessions",
    )
    session = session_service.create_session(title="TUI Rejection")
    sid = SessionId(session.session_id)
    questions = QuestionStore(tmp_path / "questions.sqlite")
    model = ScriptedChatModel(
        responses=[
            tool_call_message(
                "ask_user",
                {"prompt": "Proceed?", "reason": "confirmation"},
                call_id="ask-reject",
            )
        ]
    )
    controller = RunController(
        session_id=sid,
        workspace=tmp_path,
        journal=journal,
        checkpoints=checkpoints,
        models={"lead-model": model, "implementer-model": model},
        default_lead_model="lead-model",
        default_child_model="implementer-model",
        question_store=questions,
    )
    app = RudderApp(
        controller=controller,
        session_service=session_service,
        session_id=sid,
        question_store=questions,
    )

    async with app.run_test(size=(120, 40)) as pilot:
        app.on_prompt_composer_prompt_submitted(PromptComposer.PromptSubmitted("Ask first"))
        assert app._active_worker is not None
        await app._active_worker.wait()
        await pilot.pause()
        await pilot.click("#btn-reject")
        await pilot.pause()

        assert questions.pending("lead") == ()
        assert journal.get_session_snapshot(str(sid)).runs[-1].status == "blocked"
