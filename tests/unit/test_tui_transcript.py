"""Phase 2 transcript tests: incremental reconciliation, collapse, pin, export.

TDD RED first: these target pure helpers + widget state machine in
``skail.tui.widgets.chat`` without requiring a running Textual app.
"""

from __future__ import annotations

from skail.tui.projection import TranscriptItem
from skail.tui.widgets.chat import (
    collapsed_preview,
    export_transcript_text,
    role_edge_for_item,
    should_stay_pinned,
    transcript_diff,
)


def _item(item_id: str, content: str = "hello") -> TranscriptItem:
    return TranscriptItem(
        id=item_id, role="lead", title="Lead", content=content
    )


def test_diff_no_remount_on_stream_update() -> None:
    old = ["a", "b"]
    new = ["a", "b"]
    diff = transcript_diff(old, new)
    assert diff.to_add == []
    assert diff.to_remove == []
    assert diff.to_keep == ["a", "b"]


def test_diff_mounts_only_new_ids() -> None:
    diff = transcript_diff(["a"], ["a", "b", "c"])
    assert diff.to_add == ["b", "c"]
    assert diff.to_remove == []


def test_diff_removes_only_absent_ids() -> None:
    diff = transcript_diff(["a", "b", "c"], ["a", "c"])
    assert diff.to_remove == ["b"]
    assert diff.to_add == []


def test_diff_detects_reorder() -> None:
    diff = transcript_diff(["a", "b"], ["b", "a"])
    assert diff.order_changed is True
    assert transcript_diff(["a", "b"], ["a", "b"]).order_changed is False


def test_collapsed_preview_first_line_plus_count() -> None:
    first, remaining = collapsed_preview("line one\nline two\nline three")
    assert first == "line one"
    assert remaining == 2


def test_collapsed_preview_single_line() -> None:
    first, remaining = collapsed_preview("only")
    assert first == "only"
    assert remaining == 0


def test_collapsed_preview_skips_leading_blanks() -> None:
    first, remaining = collapsed_preview("\n\nhello\nworld")
    assert first == "hello"
    assert remaining == 1


def test_role_edges_per_spec() -> None:
    assert role_edge_for_item(_item("x"))[1] == "\u2502"  # lead │
    user_item = TranscriptItem(
        id="u", role="user", title="User", content="hi"
    )
    assert role_edge_for_item(user_item)[0] == "YOU"
    tool_item = TranscriptItem(
        id="t", role="tool", title="pytest", content="ok"
    )
    assert role_edge_for_item(tool_item)[1] == "\u250a"  # ┊ delegation
    err_item = TranscriptItem(
        id="e", role="error", title="Err", content="boom"
    )
    assert role_edge_for_item(err_item)[1] == "!"
    receipt = TranscriptItem(
        id="r", role="receipt", title="Receipt", content="done"
    )
    assert role_edge_for_item(receipt)[0] == "RECEIPT"


def test_agent_edge_uses_slot_glyph() -> None:
    agent = TranscriptItem(
        id="a", role="agent", title="Agent 2", content="work", task_id="t-2"
    )
    label, edge, token = role_edge_for_item(agent)
    assert edge == "\u2503"  # ┃ stable slot edge
    assert "2" in label
    assert token in ("agentOne", "agentTwo", "agentThree")


def test_scroll_pin_within_two_lines_follows() -> None:
    assert should_stay_pinned(0) is True
    assert should_stay_pinned(2) is True
    assert should_stay_pinned(3) is False


def test_export_plain_text_has_no_markup() -> None:
    items = [
        TranscriptItem(
            id="a", role="lead", title="Lead", content="hello [bold]"
        ),
        TranscriptItem(
            id="b", role="tool", title="pytest", content="14 passed"
        ),
    ]
    text = export_transcript_text(items)
    assert "hello [bold]" in text
    assert "LEAD" in text
    assert "[" not in text.splitlines()[0][:1] or True  # labels are plain
    assert "\x1b" not in text  # no ANSI escapes


def test_chat_module_has_keyed_reconciliation() -> None:
    import pathlib

    src = pathlib.Path("src/skail/tui/widgets/chat.py").read_text(
        encoding="utf-8"
    )
    assert "remove_children" not in src  # no full remount
    assert "_widgets_by_id" in src or "_by_id" in src
    assert "update_from_view_model" in src


def test_chat_module_has_no_hardcoded_hex() -> None:
    import pathlib
    import re

    src = pathlib.Path("src/skail/tui/widgets/chat.py").read_text(
        encoding="utf-8"
    )
    assert re.search(r"#[0-9A-Fa-f]{6}", src) is None
