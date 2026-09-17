"""Keyboard-accessible interrupt and approval cards.

Draft source: docs/skail/TUI_REVAMP_DRAFT.md section 5.4.
Phase 2: token styling, focusable A/R/E keyboard with typing guard,
Tab/Shift+Tab focus movement, Enter activates, Esc leaves pending,
disable-after-submit, APPROVED/REJECTED terminal states, optional
instruction preserved. Styling uses theme tokens only; no hardcoded hex.
"""

from __future__ import annotations

from enum import StrEnum

from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Input, Static

from skail.tui.projection import InterruptItem


class ApprovalDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    INSTRUCTION = "instruction"
    DISMISSED = "dismissed"


TERMINAL_STATUSES = ("approved", "rejected")


def is_decision_terminal(status: str) -> bool:
    """True once an approval reached APPROVED or REJECTED."""
    return status.strip().lower() in TERMINAL_STATUSES


def is_typing_guard_active(typing: bool) -> bool:
    """Single-letter shortcuts are disabled while typing a comment."""
    return bool(typing)


def should_render_buttons(item: InterruptItem) -> bool:
    """Buttons exist only while the interrupt is still pending."""
    return not is_decision_terminal(item.status)


def dedupe_interrupts(items: list[InterruptItem]) -> list[InterruptItem]:
    """Collapse duplicates by approval_id, keeping first occurrence."""
    seen: set[str] = set()
    result: list[InterruptItem] = []
    for item in items:
        if item.approval_id in seen:
            continue
        seen.add(item.approval_id)
        result.append(item)
    return result


def approval_keyboard_action(
    key: str, item: InterruptItem, typing: bool = False
) -> ApprovalDecision | None:
    """Map a key press to an approval decision (pure, unit-testable).

    Esc never decides: it returns DISMISSED so the caller can blur/close
    without resolving. Enter without explicit focus returns None.
    """
    name = key.strip().lower()
    if name == "escape":
        return ApprovalDecision.DISMISSED
    if is_decision_terminal(item.status):
        return None
    if name == "enter":
        return None
    if typing and name in ("a", "r", "e"):
        return None
    if name == "a":
        return ApprovalDecision.APPROVED
    if name == "r":
        return ApprovalDecision.REJECTED
    if name == "e":
        return ApprovalDecision.INSTRUCTION
    return None


class InterruptWidget(Widget):
    """Inline approval card with full keyboard support."""

    can_focus = True

    DEFAULT_CSS = """
    InterruptWidget {
        width: 100%;
        height: auto;
        border: round $approval;
        background: $approvalSurface;
        padding: 1;
        margin: 1 0;
    }
    InterruptWidget:focus-within {
        border: round $focusRing;
    }
    InterruptWidget.rejected {
        opacity: 60%;
        color: $textMuted;
    }
    InterruptWidget.approved {
        color: $text;
    }
    .interrupt-title {
        text-style: bold;
        color: $approval;
    }
    .interrupt-question {
        margin: 1 0;
        color: $text;
    }
    .interrupt-actions {
        width: 100%;
        height: auto;
        margin-top: 1;
    }
    .interrupt-hint {
        color: $textMuted;
    }
    InterruptWidget #btn-approve:focus-within,
    InterruptWidget #btn-reject:focus-within,
    InterruptWidget #btn-instruct:focus-within,
    InterruptWidget #interrupt-input:focus-within {
        outline: solid $focusRing;
    }
    Button {
        margin-right: 1;
    }
    """

    class Approved(Message):
        def __init__(self, approval_id: str, response: str = "yes") -> None:
            super().__init__()
            self.approval_id = approval_id
            self.response = response

    class Rejected(Message):
        def __init__(self, approval_id: str) -> None:
            super().__init__()
            self.approval_id = approval_id

    class InstructionRequested(Message):
        def __init__(self, approval_id: str) -> None:
            super().__init__()
            self.approval_id = approval_id

    class Dismissed(Message):
        def __init__(self, approval_id: str) -> None:
            super().__init__()
            self.approval_id = approval_id

    def __init__(self, interrupt: InterruptItem) -> None:
        super().__init__()
        self.interrupt = interrupt
        self._submitted = is_decision_terminal(interrupt.status)
        self._focus_index = 0
        self._update_state_class()

    def _update_state_class(self) -> None:
        try:
            self.remove_class("approved")
            self.remove_class("rejected")
        except Exception:
            pass
        status = self.interrupt.status.strip().lower()
        if status in TERMINAL_STATUSES:
            try:
                self.add_class(status)
            except Exception:
                pass

    def _instruction_text(self) -> str:
        try:
            field = self.query_one("#interrupt-input", Input)
            return field.value.strip()
        except Exception:
            return ""

    def _is_typing(self) -> bool:
        try:
            return self.app.focused is self.query_one("#interrupt-input", Input)
        except Exception:
            return False

    def _focusables(self) -> list[Widget]:
        items: list[Widget] = []
        for selector in ("#btn-approve", "#btn-reject", "#btn-instruct",
                         "#interrupt-input"):
            try:
                items.append(self.query_one(selector))
            except Exception:
                continue
        return items

    def compose(self) -> ComposeResult:
        title_text = f"APPROVAL REQUIRED [{self.interrupt.approval_id}]"
        with Vertical():
            yield Static(title_text, classes="interrupt-title")
            yield Static(self.interrupt.question, classes="interrupt-question")
            if should_render_buttons(self.interrupt) and not self._submitted:
                with Horizontal(classes="interrupt-actions"):
                    yield Button("Approve", id="btn-approve", variant="success")
                    yield Button("Reject", id="btn-reject", variant="error")
                    yield Button("Add instruction", id="btn-instruct")
                yield Input(
                    placeholder="Optional answer or comment...",
                    id="interrupt-input",
                )
                yield Static(
                    "[A] Approve  [R] Reject  [E] Add instruction  Esc keeps pending",
                    classes="interrupt-hint",
                )
            else:
                status = self.interrupt.status.strip().upper() or "RESOLVED"
                yield Static(f"{status} — awaiting confirmation",
                             classes="interrupt-hint")

    def update_interrupt(self, item: InterruptItem) -> None:
        """Refresh from projection; pending stays visible until confirmed."""
        if item.approval_id != self.interrupt.approval_id:
            return
        previous_instruction = self._instruction_text()
        self.interrupt = item
        self._submitted = is_decision_terminal(item.status)
        self._update_state_class()
        try:
            self.query_one(".interrupt-question", Static).update(item.question)
        except Exception:
            pass
        if self._submitted and should_render_buttons(item) is False:
            # Rebuild to terminal state: buttons gone, dimmed when rejected.
            try:
                for child in list(self.query("Button, Input")):
                    child.remove()
            except Exception:
                pass
        elif previous_instruction:
            try:
                self.query_one("#interrupt-input", Input).value = previous_instruction
            except Exception:
                pass
        self.refresh(layout=True)

    def _submit_approve(self) -> None:
        if self._submitted or is_decision_terminal(self.interrupt.status):
            return
        self._submitted = True
        comment = self._instruction_text() or "yes"
        self.post_message(self.Approved(self.interrupt.approval_id, comment))
        self._disable_inputs()

    def _submit_reject(self) -> None:
        if self._submitted or is_decision_terminal(self.interrupt.status):
            return
        self._submitted = True
        self.post_message(self.Rejected(self.interrupt.approval_id))
        self._disable_inputs()

    def _disable_inputs(self) -> None:
        try:
            for button in self.query(Button):
                button.disabled = True
            self.query_one("#interrupt-input", Input).disabled = True
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-approve":
            self._submit_approve()
        elif event.button.id == "btn-reject":
            self._submit_reject()
        elif event.button.id == "btn-instruct":
            if not self._submitted:
                self.post_message(
                    self.InstructionRequested(self.interrupt.approval_id)
                )
                try:
                    self.query_one("#interrupt-input", Input).focus()
                except Exception:
                    pass

    async def on_key(self, event: events.Key) -> None:
        key = event.key.lower()
        if key == "tab":
            focusables = self._focusables()
            if focusables:
                self._focus_index = (self._focus_index + 1) % len(focusables)
                try:
                    focusables[self._focus_index].focus()
                except Exception:
                    pass
                event.stop()
            return
        if key == "shift+tab":
            focusables = self._focusables()
            if focusables:
                self._focus_index = (self._focus_index - 1) % len(focusables)
                try:
                    focusables[self._focus_index].focus()
                except Exception:
                    pass
                event.stop()
            return
        if key == "escape":
            # Esc leaves pending: never decides, only blurs/dismisses focus.
            self.post_message(self.Dismissed(self.interrupt.approval_id))
            event.stop()
            return
        if key == "enter":
            try:
                focused = self.app.focused
            except Exception:
                focused = None
            try:
                approve = self.query_one("#btn-approve", Button)
                reject = self.query_one("#btn-reject", Button)
            except Exception:
                return
            if focused is approve:
                self._submit_approve()
                event.stop()
            elif focused is reject:
                self._submit_reject()
                event.stop()
            return
        decision = approval_keyboard_action(key, self.interrupt, self._is_typing())
        if decision == ApprovalDecision.APPROVED:
            self._submit_approve()
            event.stop()
        elif decision == ApprovalDecision.REJECTED:
            self._submit_reject()
            event.stop()
        elif decision == ApprovalDecision.INSTRUCTION:
            try:
                self.query_one("#interrupt-input", Input).focus()
            except Exception:
                pass
            event.stop()


__all__ = [
    "ApprovalDecision",
    "InterruptWidget",
    "TERMINAL_STATUSES",
    "approval_keyboard_action",
    "dedupe_interrupts",
    "is_decision_terminal",
    "is_typing_guard_active",
    "should_render_buttons",
]
