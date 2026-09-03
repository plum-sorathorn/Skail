from __future__ import annotations

import pytest
from textual.widgets import Input, TabbedContent

from rudder.domain.events import (
    EventEnvelope,
    ToolPayload,
)
from rudder.domain.ids import new_event_id, new_run_id, new_session_id, new_task_id
from rudder.tui.app import RudderApp
from rudder.tui.projection import TuiProjection
from rudder.tui.widgets.chat import TranscriptItemWidget


@pytest.mark.asyncio
async def test_tui_shell_mounts_and_renders() -> None:
    app = RudderApp()
    async with app.run_test(size=(120, 40)):
        assert app.query_one("#chat-transcript") is not None
        assert app.query_one("#prompt-composer") is not None
        assert app.query_one("#agent-rail") is not None
        assert app.query_one("#route-view") is not None
        assert app.query_one("#budget-view") is not None
        assert not app.query_one("#main-container").has_class("narrow")


@pytest.mark.asyncio
async def test_tui_shell_responsive_narrow_fallback() -> None:
    app = RudderApp()
    async with app.run_test(size=(80, 40)):
        # Width 80 < 100 triggers .narrow class
        assert app.query_one("#main-container").has_class("narrow")


@pytest.mark.asyncio
async def test_tui_shell_transcript_collapse_click() -> None:
    proj = TuiProjection()
    sid = new_session_id()
    rid = new_run_id()
    tid = new_task_id()

    # Add collapsible tool item
    proj.apply_event(
        EventEnvelope(
            event_id=new_event_id(),
            session_id=sid,
            run_id=rid,
            task_id=tid,
            sequence=1,
            type="tool.completed",
            payload=ToolPayload(tool="read_file", status="completed"),
        )
    )

    app = RudderApp(projection=proj)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        widget = app.query_one(TranscriptItemWidget)
        assert widget.item.can_collapse is True
        assert widget.item.collapsed is True

        # Click to uncollapse
        await pilot.click(TranscriptItemWidget)
        await pilot.pause()
        assert widget.item.collapsed is False

        # Click again to collapse
        await pilot.click(TranscriptItemWidget)
        await pilot.pause()
        assert widget.item.collapsed is True


@pytest.mark.asyncio
async def test_tui_shell_keyboard_navigation_and_prompt_submit() -> None:
    app = RudderApp()
    async with app.run_test(size=(120, 40)) as pilot:
        # Check tab navigation keybindings
        await pilot.press("ctrl+b")
        assert app.query_one("#tabs", TabbedContent).active == "tab-budget"

        await pilot.press("ctrl+a")
        assert app.query_one("#tabs", TabbedContent).active == "tab-agents"

        await pilot.press("ctrl+r")
        assert app.query_one("#tabs", TabbedContent).active == "tab-route"

        # Submit a user prompt through composer
        inp = app.query_one("#composer-input", Input)
        inp.value = "Test task instruction"
        inp.focus()
        await pilot.press("enter")

        # Verify prompt appeared in transcript
        items = app.projection.transcript_items
        assert any(i.role == "user" and i.content == "Test task instruction" for i in items)
