"""Keyboard-accessible interrupt and approval cards.

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

    # ATELIER: the interrupt renders as the single tinted full-bleed band.
    # The mock's 2px focus/edge inset is a 1-cell `heavy` border (TCSS has no
    # 1px hairline) — documented fidelity delta, IMPLEMENTATION_PLAN §7.1.
    DEFAULT_CSS = """
    InterruptWidget {
        width: 100%;
        height: auto;
        background: $approvalSurface;
        border: none;
        border-left: heavy $approval;
        padding: 1 2;
    }
    InterruptWidget:focus-within {
        border-left: heavy $focusRing;
    }
    InterruptWidget.rejected {
        opacity: 60%;
        color: $textMuted;
    }
    InterruptWidget.approved {
        color: $text;
    }
    .interrupt-title-row {
        width: 100%;
        height: 1;
    }
    .interrupt-title {
        text-style: bold;
        color: $approval;
    }
    .interrupt-esc {
        width: 1fr;
        text-align: right;
        color: $textMuted;
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
    #interrupt-input {
        border: none;
        border-bottom: dashed $borderStrong;
        background: $approvalSurface;
        padding: 0 1;
        height: 1;
    }
    #btn-approve,
    #btn-reject,
    #btn-instruct {
        border: none;
        background: transparent;
        color: $accent;
        margin-right: 2;
        min-width: 0;
        height: 1;
        text-style: underline;
    }
    #btn-approve:focus,
    #btn-reject:focus,
    #btn-instruct:focus {
        text-style: bold;
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
            with Horizontal(classes="interrupt-title-row"):
                yield Static(title_text, classes="interrupt-title")
                yield Static("esc keeps pending", classes="interrupt-esc")
            yield Static(self.interrupt.question, classes="interrupt-question")
            if should_render_buttons(self.interrupt) and not self._submitted:
                yield Input(
                    placeholder="Optional answer or comment...",
                    id="interrupt-input",
                )
                with Horizontal(classes="interrupt-actions"):
                    yield Button("Approve A", id="btn-approve")
                    yield Button("Reject R", id="btn-reject")
                    yield Button("Add instruction E", id="btn-instruct")
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
                inp = self.query_one("#interrupt-input", Input)
            except Exception:
                return
            if focused is approve:
                self._submit_approve()
                event.stop()
            elif focused is reject:
                self._submit_reject()
                event.stop()
            elif focused is inp:
                self._submit_approve()
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

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit_approve()


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
