from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Input, Static

from rudder.tui.projection import InterruptItem


class InterruptWidget(Widget):
    """Inline interaction widget for pending questions and approvals."""

    DEFAULT_CSS = """
    InterruptWidget {
        width: 100%;
        height: auto;
        border: heavy #eab308;
        background: #18150a;
        padding: 1;
        margin: 1 0;
    }
    .interrupt-title {
        text-style: bold;
        color: #eab308;
    }
    .interrupt-question {
        margin: 1 0;
        color: white;
    }
    .interrupt-actions {
        width: 100%;
        height: auto;
        margin-top: 1;
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

    def __init__(self, interrupt: InterruptItem) -> None:
        super().__init__()
        self.interrupt = interrupt

    def compose(self) -> ComposeResult:
        title_text = f"APPROVAL REQUIRED [{self.interrupt.approval_id}]"
        with Vertical():
            yield Static(title_text, classes="interrupt-title")
            yield Static(self.interrupt.question, classes="interrupt-question")
            with Horizontal(classes="interrupt-actions"):
                yield Button("Approve", id="btn-approve", variant="success")
                yield Button("Reject", id="btn-reject", variant="error")
                yield Input(placeholder="Optional answer or comment...", id="interrupt-input")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        inp = self.query_one("#interrupt-input", Input)
        comment = inp.value.strip() or "yes"
        if event.button.id == "btn-approve":
            self.post_message(self.Approved(self.interrupt.approval_id, comment))
        elif event.button.id == "btn-reject":
            self.post_message(self.Rejected(self.interrupt.approval_id))
