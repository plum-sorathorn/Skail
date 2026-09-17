"""Phase 2 approval tests: keyboard, typing guard, dedupe, terminal states."""

from __future__ import annotations

from skail.tui.projection import InterruptItem
from skail.tui.widgets.interrupts import (
    ApprovalDecision,
    approval_keyboard_action,
    is_typing_guard_active,
    should_render_buttons,
)


def _pending(approval_id: str = "ap-1") -> InterruptItem:
    return InterruptItem(
        approval_id=approval_id, task_id=None, question="Run git status?",
        status="pending",
    )


def test_keyboard_a_approves_when_pending() -> None:
    action = approval_keyboard_action("a", _pending(), typing=False)
    assert action == ApprovalDecision.APPROVED


def test_keyboard_r_rejects_when_pending() -> None:
    action = approval_keyboard_action("r", _pending(), typing=False)
    assert action == ApprovalDecision.REJECTED


def test_keyboard_e_requests_instruction() -> None:
    action = approval_keyboard_action("e", _pending(), typing=False)
    assert action == ApprovalDecision.INSTRUCTION


def test_typing_guard_blocks_single_letter_keys() -> None:
    assert is_typing_guard_active(typing=True) is True
    assert is_typing_guard_active(typing=False) is False
    action = approval_keyboard_action("a", _pending(), typing=True)
    assert action is None


def test_enter_never_decides_without_focus() -> None:
    action = approval_keyboard_action("enter", _pending(), typing=False)
    assert action is None


def test_escape_is_neutral() -> None:
    action = approval_keyboard_action("escape", _pending(), typing=False)
    assert action == ApprovalDecision.DISMISSED


def test_terminal_states_hide_buttons() -> None:
    approved = InterruptItem(
        approval_id="x", task_id=None, question="q?", status="approved"
    )
    rejected = InterruptItem(
        approval_id="y", task_id=None, question="q?", status="rejected"
    )
    assert should_render_buttons(_pending()) is True
    assert should_render_buttons(approved) is False
    assert should_render_buttons(rejected) is False


def test_dedupe_same_approval_id_single_widget() -> None:
    from skail.tui.widgets.interrupts import dedupe_interrupts

    items = [_pending("same"), _pending("same"), _pending("other")]
    deduped = dedupe_interrupts(items)
    assert [i.approval_id for i in deduped] == ["same", "other"]


def test_decided_item_disables_further_input() -> None:
    from skail.tui.widgets.interrupts import is_decision_terminal

    assert is_decision_terminal("approved") is True
    assert is_decision_terminal("rejected") is True
    assert is_decision_terminal("pending") is False


def test_interrupts_module_has_no_hardcoded_hex() -> None:
    import pathlib
    import re

    src = pathlib.Path("src/skail/tui/widgets/interrupts.py").read_text(
        encoding="utf-8"
    )
    assert re.search(r"#[0-9A-Fa-f]{6}", src) is None
