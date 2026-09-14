from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Input


class PromptComposer(Widget):
    """Input bar for prompts and slash commands."""

    DEFAULT_CSS = """
    PromptComposer {
        width: 100%;
        height: auto;
        padding: 0 1;
        background: $surface;
        border-top: solid $primary;
    }
    Horizontal {
        width: 100%;
        height: auto;
    }
    Input {
        width: 1fr;
        border: none;
    }
    Button {
        width: auto;
        min-width: 10;
        margin-left: 1;
    }
    """

    class PromptSubmitted(Message):
        """Dispatched when user submits a prompt or command."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Input(
                placeholder="Type a prompt or slash command (/help, /agents, /budget, /quit)...",
                id="composer-input",
            )
            yield Button("Send", id="composer-send", variant="primary")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        val = event.value.strip()
        if val:
            self.post_message(self.PromptSubmitted(val))
            event.input.value = ""

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "composer-send":
            inp = self.query_one("#composer-input", Input)
            val = inp.value.strip()
            if val:
                self.post_message(self.PromptSubmitted(val))
                inp.value = ""
