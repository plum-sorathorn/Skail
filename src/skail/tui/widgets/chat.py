from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widget import Widget

from skail.tui.projection import TranscriptItem


class TranscriptItemWidget(Widget):
    """Widget for a single transcript item, supporting collapse toggling."""

    DEFAULT_CSS = """
    TranscriptItemWidget {
        width: 100%;
        height: auto;
        margin-bottom: 1;
        padding: 0 1;
    }
    TranscriptItemWidget.role-user {
        border-left: wide #3b82f6;
    }
    TranscriptItemWidget.role-lead {
        border-left: wide #10b981;
    }
    TranscriptItemWidget.role-task {
        border-left: wide #f59e0b;
    }
    TranscriptItemWidget.role-tool {
        border-left: wide #8b5cf6;
    }
    TranscriptItemWidget.role-error {
        border: heavy #ef4444;
        background: #1f1215;
    }
    TranscriptItemWidget.role-approval {
        border: heavy #eab308;
        background: #1f1d12;
    }
    TranscriptItemWidget.collapsed {
        opacity: 70%;
    }
    """

    class ItemToggled(Message):
        def __init__(self, item_id: str) -> None:
            super().__init__()
            self.item_id = item_id

    def __init__(self, item: TranscriptItem) -> None:
        super().__init__(classes=f"role-{item.role}")
        self.item = item
        if item.collapsed:
            self.add_class("collapsed")

    def render(self) -> Text:
        item = self.item
        text = Text()

        # Prefix icon & role tag
        if item.role == "error":
            text.append("ERROR ", style="bold red reverse")
            text.append(f" {item.title}\n", style="bold red")
            text.append(item.content, style="red")
            return text

        if item.role == "approval":
            text.append("APPROVAL REQUIRED ", style="bold yellow reverse")
            text.append(f" {item.title}\n", style="bold yellow")
            text.append(item.content, style="bold white")
            return text

        # Collapsible indicator
        if item.can_collapse:
            icon = "▶ " if item.collapsed else "▼ "
            text.append(icon, style="dim")
        else:
            text.append("• ", style="cyan")

        # Role styling
        if item.role == "user":
            text.append("[User] ", style="bold blue")
            text.append(item.content, style="white")
        elif item.role == "lead":
            text.append("[Lead] ", style="bold green")
            text.append(item.content, style="white")
        elif item.role == "task":
            text.append(f"[Task: {item.title}] ", style="bold yellow")
            if not item.collapsed:
                text.append(f"\n{item.content}", style="dim")
            else:
                text.append("(click to expand)", style="dim italic")
        elif item.role == "tool":
            text.append(f"[Tool: {item.title}] ", style="bold magenta")
            if not item.collapsed:
                text.append(f"\n{item.content}", style="dim")
            else:
                text.append("(click to expand)", style="dim italic")
        else:
            text.append(f"[{item.title}] ", style="bold white")
            text.append(item.content, style="white")

        return text

    def on_click(self, event: Any = None) -> None:
        if self.item.can_collapse:
            self.item.collapsed = not self.item.collapsed
            if self.item.collapsed:
                self.add_class("collapsed")
            else:
                self.remove_class("collapsed")
            self.refresh()
            self.post_message(self.ItemToggled(self.item.id))


class ChatTranscript(VerticalScroll):
    """Scrollable container for conversation transcript and events."""

    DEFAULT_CSS = """
    ChatTranscript {
        width: 100%;
        height: 1fr;
        padding: 1;
        scrollbar-size: 1 1;
    }
    """

    def update_items(self, items: list[TranscriptItem]) -> None:
        self.remove_children()
        for item in items:
            self.mount(TranscriptItemWidget(item))
        self.scroll_end(animate=False)
