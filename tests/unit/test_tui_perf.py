"""Phase 4 transcript perf + agent-select focus retention tests (fast, no sleeps)."""

from __future__ import annotations

import inspect

import skail.tui.app as app_module
from skail.tui.projection import TranscriptItem
from skail.tui.widgets.agents import AgentRail
from skail.tui.widgets.chat import (
    ChatTranscript,
    TranscriptItemWidget,
    transcript_diff,
)


def _items(count: int) -> list[TranscriptItem]:
    return [
        TranscriptItem(
            id=f"item-{i:04d}",
            role="lead",
            title=f"Lead {i}",
            content=f"body {i}",
            can_collapse=(i % 2 == 0),
            collapsed=(i % 2 == 0),
        )
        for i in range(count)
    ]


def test_stream_update_changes_one_body() -> None:
    items = _items(1000)
    transcript = ChatTranscript.__new__(ChatTranscript)
    transcript._widgets_by_id = {item.id: _WidgetStub(item) for item in items}
    transcript._order = [item.id for item in items]
    transcript._pinned = True
    transcript._pending_new = 0

    streaming = TranscriptItem(
        id="stream-1", role="lead", title="Streaming", content="chunk 0"
    )
    items_plus_stream = [*items, streaming]
    diff = transcript_diff(transcript._order, [i.id for i in items_plus_stream])
    assert diff.to_add == ["stream-1"]
    assert diff.to_remove == []

    # Simulate mounting the single streaming widget once.
    transcript._widgets_by_id["stream-1"] = _WidgetStub(streaming)
    mounted = len(transcript._widgets_by_id)
    assert mounted == 1001

    # A streaming content update keeps every mount; only one body changes.
    updated = TranscriptItem(
        id="stream-1", role="lead", title="Streaming", content="chunk 1"
    )
    widget = transcript._widgets_by_id["stream-1"]
    widget.update_body(updated.content)
    assert widget.updates == 1
    assert len(transcript._widgets_by_id) == mounted
    others = sum(w.updates for k, w in transcript._widgets_by_id.items() if k != "stream-1")
    assert others == 0


def test_scroll_stable_with_collapsed_tools() -> None:
    items = _items(1000)
    tool = TranscriptItem(
        id="tool-1",
        role="tool",
        title="pytest",
        content="line1\nline2\nline3",
        can_collapse=True,
        collapsed=True,
    )
    full = [*items, tool, TranscriptItem(
        id="stream-1", role="lead", title="S", content="live",
    )]
    transcript = ChatTranscript.__new__(ChatTranscript)
    transcript._widgets_by_id = {item.id: _WidgetStub(item) for item in full}
    transcript._order = [item.id for item in full]
    assert transcript._order[-2] == "tool-1"
    assert transcript._order[-1] == "stream-1"
    # Collapsed tool row stays mounted and ordered before the stream.
    assert len(transcript._widgets_by_id) == 1002


def test_agent_select_focus_retention_no_tab_switch() -> None:
    assert hasattr(AgentRail, "select_child")
    src = inspect.getsource(AgentRail.select_child)
    assert "tab-route" not in src and "tab_route" not in src
    src_app = inspect.getsource(app_module.SkailApp.on_agent_rail_agent_selected)
    assert "focus_agent" in src_app
    assert "tab-route" not in src_app
    assert "tab_route" not in src_app
    detail_src = inspect.getsource(
        app_module.SkailApp.on_agent_rail_agent_detail_requested
    )
    assert "tab-route" not in detail_src
    assert "tab_route" not in detail_src


class _WidgetStub(TranscriptItemWidget):
    """Mount-count stub: counts body updates without touching the DOM."""

    def __init__(self, item: TranscriptItem) -> None:
        # Bypass Widget init; only the state machine matters here.
        self.item = item
        self._collapsed = item.collapsed
        self.updates = 0

    def update_body(self, content: str) -> None:
        self.item.content = content
        self.updates += 1
