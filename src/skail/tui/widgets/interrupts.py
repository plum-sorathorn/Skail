"""Keyboard-accessible interrupt and approval cards.

Phase 2: token styling, focusable A/R/E keyboard with typing guard,
Tab/Shift+Tab focus movement, Enter activates, Esc leaves pending,
disable-after-submit, APPROVED/REJECTED terminal states, optional
instruction preserved. Styling uses theme tokens only; no hardcoded hex.
"""

from __future__ import annotations

from dataclasses import replace
from enum import StrEnum

from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Input, Static

from skail.domain.events import InterruptKind
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
    return item.status.strip().lower() == "pending"


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
    if item.kind is not InterruptKind.APPROVAL:
        return None
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
        max-height: 5;
        overflow-y: auto;
    }
    .interrupt-owner {
        color: $textMuted;
        text-style: dim;
        height: 1;
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

    class QuestionAnswered(Message):
        def __init__(self, question_id: str, response: str) -> None:
            super().__init__()
            self.question_id = question_id
            self.response = response

    class QuestionCancelled(Message):
        def __init__(self, question_id: str) -> None:
            super().__init__()
            self.question_id = question_id

    def __init__(self, interrupt: InterruptItem) -> None:
        super().__init__()
        self.interrupt = replace(interrupt)
        self._submitted = not should_render_buttons(interrupt)
        self._focus_index = 0
        self._update_state_class()

    def on_mount(self) -> None:
        if self.interrupt.kind is InterruptKind.QUESTION and not self._submitted:
            self.query_one("#interrupt-input", Input).focus()

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
        selectors = (
            ("#interrupt-input", "#btn-answer", "#btn-cancel-question")
            if self.interrupt.kind is InterruptKind.QUESTION
            else ("#btn-approve", "#btn-reject", "#btn-instruct", "#interrupt-input")
        )
        for selector in selectors:
            try:
                items.append(self.query_one(selector))
            except Exception:
                continue
        return items

    def compose(self) -> ComposeResult:
        is_question = self.interrupt.kind is InterruptKind.QUESTION
        title_text = (
            "QUESTION · Your answer is needed"
            if is_question
            else f"APPROVAL REQUIRED [{self.interrupt.approval_id}]"
        )
        with Vertical():
            with Horizontal(classes="interrupt-title-row"):
                yield Static(title_text, classes="interrupt-title")
                yield Static("esc keeps pending", classes="interrupt-esc")
            owner = self._owner_text()
            if owner:
                yield Static(owner, id="interrupt-owner", classes="interrupt-owner")
            yield Static(self.interrupt.question, classes="interrupt-question")
            options = self.interrupt.payload.get("options", ())
            if is_question and options:
                option_text = " · ".join(str(option) for option in options)
                yield Static(f"Options: {option_text}")
            if should_render_buttons(self.interrupt) and not self._submitted:
                placeholder = (
                    "Type your answer..."
                    if is_question
                    else "Optional answer or comment..."
                )
                yield Input(
                    placeholder=placeholder,
                    id="interrupt-input",
                )
                with Horizontal(classes="interrupt-actions"):
                    if is_question:
                        yield Button("Answer", id="btn-answer")
                        yield Button("Cancel run", id="btn-cancel-question")
                    else:
                        yield Button("Approve A", id="btn-approve")
                        yield Button("Reject R", id="btn-reject")
                        yield Button("Add instruction E", id="btn-instruct")
            else:
                yield Static(self._status_hint(), classes="interrupt-hint")

    def _owner_text(self) -> str:
        parts = []
        for label, key in (("Session", "session_id"), ("Run", "run_id"), ("Plan", "plan_id")):
            value = self.interrupt.payload.get(key)
            if isinstance(value, str) and value:
                parts.append(f"{label} {value[-8:]}")
        return " · ".join(parts)

    def _status_hint(self) -> str:
        status = self.interrupt.status.strip().lower()
        if self.interrupt.kind is InterruptKind.QUESTION:
            if status == "answering":
                return "ANSWER SENT · Waiting for the run"
            if status == "cancelling":
                return "CANCELLATION REQUESTED · Waiting for confirmation"
            return f"{status.upper()} · Waiting for confirmation"
        return f"{status.upper() or 'RESOLVED'} — awaiting confirmation"

    def update_interrupt(self, item: InterruptItem) -> None:
        """Refresh from projection; pending stays visible until confirmed."""
        if item.approval_id != self.interrupt.approval_id:
            return
        previous_instruction = self._instruction_text()
        self.interrupt = replace(item)
        self._submitted = not should_render_buttons(item)
        self._update_state_class()
        try:
            self.query_one(".interrupt-question", Static).update(item.question)
        except Exception:
            pass
        owner = self._owner_text()
        try:
            owner_widget = self.query_one("#interrupt-owner", Static)
            if owner:
                owner_widget.update(owner)
            else:
                owner_widget.remove()
        except Exception:
            if owner:
                self.mount(Static(owner, id="interrupt-owner", classes="interrupt-owner"))
        if self._submitted:
            # Keep the card visible without controls until the owning run acknowledges it.
            try:
                for child in list(self.query("Button, Input")):
                    child.remove()
            except Exception:
                pass
            try:
                self.query_one(".interrupt-hint", Static).update(self._status_hint())
            except Exception:
                self.mount(Static(self._status_hint(), classes="interrupt-hint"))
        elif previous_instruction:
            try:
                self.query_one("#interrupt-input", Input).value = previous_instruction
            except Exception:
                pass
        self.refresh(layout=True)

    def _submit_question_answer(self) -> None:
        if self._submitted or self.interrupt.status != "pending":
            return
        response = self._instruction_text()
        self._submitted = True
        self.post_message(self.QuestionAnswered(self.interrupt.approval_id, response))
        self.update_interrupt(replace(self.interrupt, status="answering"))

    def _submit_question_cancel(self) -> None:
        if self._submitted or self.interrupt.status != "pending":
            return
        self._submitted = True
        self.post_message(self.QuestionCancelled(self.interrupt.approval_id))
        self.update_interrupt(replace(self.interrupt, status="cancelling"))

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
        if self.interrupt.kind is InterruptKind.QUESTION:
            if event.button.id == "btn-answer":
                self._submit_question_answer()
            elif event.button.id == "btn-cancel-question":
                self._submit_question_cancel()
            return
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
            if self.interrupt.kind is InterruptKind.QUESTION:
                try:
                    focused = self.app.focused
                    answer_button = self.query_one("#btn-answer", Button)
                    cancel_button = self.query_one("#btn-cancel-question", Button)
                    input_field = self.query_one("#interrupt-input", Input)
                except Exception:
                    return
                if focused is input_field or focused is answer_button:
                    self._submit_question_answer()
                    event.stop()
                elif focused is cancel_button:
                    self._submit_question_cancel()
                    event.stop()
                return
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
        if self.interrupt.kind is InterruptKind.QUESTION:
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
        if self.interrupt.kind is InterruptKind.QUESTION:
            self._submit_question_answer()
        else:
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
