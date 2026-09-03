from __future__ import annotations

import pytest

from rudder.tui.app import RudderApp
from rudder.tui.commands import dispatch_slash_command, parse_slash_command
from rudder.tui.projection import InterruptItem, TuiProjection
from rudder.tui.widgets.interrupts import InterruptWidget


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
