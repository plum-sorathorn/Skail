"""Incremental transcript rendering with keyed reconciliation.

Draft source: docs/skail/TUI_REVAMP_DRAFT.md sections 5.2, 6.
Phase 2: replace full-remount with keyed reconciliation,
focusable collapsible headers, role edges, scroll pin, streaming updates,
plain-text export, and search hooks. All styling uses theme tokens via
Textual CSS variables; no hardcoded hex values in this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rich.text import Text
from textual import events
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from skail.tui.projection import TranscriptItem
from skail.tui.theme import agent_slot_token

PIN_THRESHOLD_LINES = 2
SPINNER_CELLS = 5
SPINNER_GLYPH = "\u273b"  # ✻
SPINNER_INTERVAL_MS = 90
SPINNER_MAX_MS = 150

SPINNER_LABELS: tuple[str, ...] = (
    "CONNECTING",
    "THINKING",
    "DELEGATING",
    "COMPACTING",
)


@dataclass
class TranscriptDiff:
    """Ordered-ID diff between the mounted set and the new projection."""

    to_add: list[str] = field(default_factory=list)
    to_remove: list[str] = field(default_factory=list)
    to_keep: list[str] = field(default_factory=list)
    order_changed: bool = False


def transcript_diff(old_ids: list[str], new_ids: list[str]) -> TranscriptDiff:
    """Compare ordered item IDs without touching the DOM."""
    old_set = set(old_ids)
    new_set = set(new_ids)
    to_add = [item_id for item_id in new_ids if item_id not in old_set]
    to_remove = [item_id for item_id in old_ids if item_id not in new_set]
    to_keep = [item_id for item_id in new_ids if item_id in old_set]
    kept_old_order = [item_id for item_id in old_ids if item_id in new_set]
    kept_new_order = [item_id for item_id in new_ids if item_id in old_set]
    return TranscriptDiff(
        to_add=to_add,
        to_remove=to_remove,
        to_keep=to_keep,
        order_changed=kept_old_order != kept_new_order,
    )


def collapsed_preview(content: str) -> tuple[str, int]:
    """Return (first non-empty line, remaining line count) for collapsed view."""
    lines = content.splitlines()
    non_empty = [line for line in lines if line.strip()]
    if not non_empty:
        return "", 0
    first = non_empty[0].strip()
    remaining = max(len(non_empty) - 1, 0)
    return first, remaining


def role_edge_for_item(item: TranscriptItem) -> tuple[str, str, str]:
    """Return (label, edge glyph, theme token) per draft section 5.2."""
    role = item.role.lower()
    if role == "user":
        return ("YOU", "\u2502", "accent")
    if role == "lead":
        return ("LEAD", "\u2502", "accent")
    if role == "agent":
        slot = _slot_from_item(item)
        label = f"AGENT {slot}"
        return (label, "\u2503", agent_slot_token(slot))
    if role in ("task", "system"):
        return ("TASK", "\u2502", "modeManual")
    if role == "tool":
        return (f"TOOL \u25b8 {item.title}", "\u250a", "delegation")
    if role == "error":
        return ("ERROR", "!", "error")
    if role == "approval":
        return ("APPROVAL REQUIRED", "\u2502", "approval")
    if role == "receipt":
        return ("RECEIPT", "\u2502", "textMuted")
    return (item.title.upper() or "ITEM", "\u2502", "textMuted")


def _slot_from_item(item: TranscriptItem) -> int:
    title = f"{item.title} {item.task_id or ''}"
    for slot in (1, 2, 3):
        if str(slot) in title:
            return slot
    return 1


def should_stay_pinned(lines_from_bottom: int) -> bool:
    """Stay pinned when within two lines of the bottom."""
    return lines_from_bottom <= PIN_THRESHOLD_LINES


def export_transcript_text(items: list[TranscriptItem]) -> str:
    """Plain-text export for scrollback: no markup, no ANSI escapes."""
    chunks: list[str] = []
    for item in items:
        label, edge, _ = role_edge_for_item(item)
        chunks.append(f"{label} {edge} {item.title}")
        chunks.append(item.content)
        chunks.append("")
    return "\n".join(chunks).rstrip("\n")


def filter_transcript(items: list[TranscriptItem], query: str) -> list[TranscriptItem]:
    """Search hook: case-insensitive substring filter over title+content."""
    needle = query.strip().lower()
    if not needle:
        return list(items)
    return [
        item
        for item in items
        if needle in item.title.lower() or needle in item.content.lower()
    ]


def spinner_frame(tick: int, reduced_motion: bool = False) -> str:
    """Render one 5-cell ping-pong spinner frame (pure, unit-testable)."""
    if reduced_motion:
        cells = [f"[{SPINNER_GLYPH}]" if i == 0 else "[ ]" for i in range(SPINNER_CELLS)]
        return " ".join(cells)
    period = SPINNER_CELLS * 2 - 2
    pos = tick % period
    if pos >= SPINNER_CELLS:
        pos = period - pos
    cells = [f"[{SPINNER_GLYPH}]" if i == pos else "[ ]" for i in range(SPINNER_CELLS)]
    return " ".join(cells)


class TranscriptItemWidget(Widget):
    """Focusable single transcript item with collapse toggling."""

    can_focus = True

    DEFAULT_CSS = """
    TranscriptItemWidget {
        width: 100%;
        height: auto;
        margin-bottom: 1;
        padding: 0 1;
        border-left: solid $border;
    }
    TranscriptItemWidget:focus-within {
        border-left: heavy $focusRing;
    }
    TranscriptItemWidget.role-user {
        border-left: solid $accent;
    }
    TranscriptItemWidget.role-lead {
        border-left: solid $accent;
    }
    TranscriptItemWidget.role-agent {
        border-left: heavy $accent;
    }
    TranscriptItemWidget.role-task {
        border-left: solid $modeManual;
    }
    TranscriptItemWidget.role-tool {
        border-left: solid $delegation;
    }
    TranscriptItemWidget.role-error {
        border-left: heavy $error;
        background: $errorSurface;
    }
    TranscriptItemWidget.role-approval {
        border: round $approval;
        background: $approvalSurface;
    }
    TranscriptItemWidget.role-receipt {
        border-left: solid $textMuted;
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
        self._collapsed = item.collapsed
        if self._collapsed:
            self.add_class("collapsed")

    def toggle_collapse(self) -> None:
        if not self.item.can_collapse:
            return
        self._collapsed = not self._collapsed
        self.item.collapsed = self._collapsed
        if self._collapsed:
            self.add_class("collapsed")
        else:
            self.remove_class("collapsed")
        self.refresh()
        self.post_message(self.ItemToggled(self.item.id))

    def collapse(self) -> None:
        if self.item.can_collapse and not self._collapsed:
            self.toggle_collapse()

    def expand_item(self) -> None:
        if self.item.can_collapse and self._collapsed:
            self.toggle_collapse()

    def update_body(self, content: str) -> None:
        """Streaming in-place body update; never remounts the widget."""
        self.item.content = content
        self.refresh()

    def render(self) -> Text:
        item = self.item
        label, edge, _ = role_edge_for_item(item)
        text = Text()
        indicator = "\u25be " if self._collapsed else "\u25b8 "
        if item.can_collapse:
            text.append(indicator, style="dim")
        text.append(f"{label} ", style="bold")
        text.append(f"{edge} ", style="dim")
        if self._collapsed:
            first, remaining = collapsed_preview(item.content)
            text.append(first, style="white")
            if remaining:
                text.append(f"  {remaining} lines", style="dim italic")
        else:
            text.append(item.content, style="white")
        return text

    async def on_key(self, event: events.Key) -> None:
        if event.key in ("enter", "space"):
            self.toggle_collapse()
            event.stop()
        elif event.key == "left":
            self.collapse()
            event.stop()
        elif event.key == "right":
            self.expand_item()
            event.stop()

    def on_click(self, event: object = None) -> None:
        _ = event
        self.toggle_collapse()


class ActivitySpinner(Static):
    """Global/child activity indicator: 5-cell ping-pong at 90ms."""

    DEFAULT_CSS = """
    ActivitySpinner {
        width: auto;
        height: 1;
        color: $accent;
    }
    """

    def __init__(self, label: str = "THINKING", **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.spinner_label = label if label in SPINNER_LABELS else "THINKING"
        self._tick = 0
        self._timer: object | None = None

    def on_mount(self) -> None:
        self._timer = self.set_interval(
            SPINNER_INTERVAL_MS / 1000.0, self._advance
        )

    def _advance(self) -> None:
        reduced = self.app.reduced_motion if hasattr(self.app, "reduced_motion") else False
        self._tick += 1
        self.update(f"{self.spinner_label} {spinner_frame(self._tick, bool(reduced))}")


class ChatTranscript(VerticalScroll):
    """Scrollable transcript with keyed reconciliation (no full remount)."""

    DEFAULT_CSS = """
    ChatTranscript {
        width: 100%;
        height: 1fr;
        padding: 1;
        scrollbar-size: 1 1;
    }
    ChatTranscript:focus-within {
        outline: solid $focusRing;
    }
    #transcript-new-events {
        dock: bottom;
        width: 100%;
        height: 1;
        background: $surfaceRaised;
        color: $accent;
        text-align: center;
    }
    """

    can_focus = True

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._widgets_by_id: dict[str, TranscriptItemWidget] = {}
        self._order: list[str] = []
        self._pinned = True
        self._pending_new = 0

    def _distance_from_bottom(self) -> int:
        try:
            max_y = self.max_scroll_y
            return int(max_y - self.scroll_y)
        except Exception:
            return 0

    def update_from_view_model(self, items: list[TranscriptItem]) -> None:
        """Keyed reconciliation: mount new, update changed, drop absent."""
        new_ids = [item.id for item in items]
        diff = transcript_diff(self._order, new_ids)
        by_id = {item.id: item for item in items}

        for item_id in diff.to_remove:
            widget = self._widgets_by_id.pop(item_id, None)
            if widget is not None:
                try:
                    widget.remove()
                except Exception:
                    pass

        for item_id in diff.to_add:
            widget = TranscriptItemWidget(by_id[item_id])
            self._widgets_by_id[item_id] = widget
            try:
                self.mount(widget)
            except Exception:
                pass

        for item_id in diff.to_keep:
            widget = self._widgets_by_id.get(item_id)
            fresh = by_id[item_id]
            if widget is not None and widget.item.content != fresh.content:
                widget.update_body(fresh.content)

        self._order = list(new_ids)

        if diff.to_add:
            if should_stay_pinned(self._distance_from_bottom()):
                self._pending_new = 0
                try:
                    self.scroll_end(animate=False)
                except Exception:
                    pass
            else:
                self._pending_new += len(diff.to_add)
                self._show_new_events_hint()
        else:
            self.refresh(layout=True)

    def update_items(self, items: list[TranscriptItem]) -> None:
        """Legacy entry point preserved for Phase 1 callers."""
        self.update_from_view_model(items)

    def _show_new_events_hint(self) -> None:
        try:
            existing = self.query_one("#transcript-new-events", Static)
            existing.update(f"\u2193 {self._pending_new} new events  (End)")
        except Exception:
            try:
                self.mount(
                    Static(
                        f"\u2193 {self._pending_new} new events  (End)",
                        id="transcript-new-events",
                    )
                )
            except Exception:
                pass

    async def on_key(self, event: events.Key) -> None:
        if event.key == "end":
            self._pending_new = 0
            try:
                for hint in self.query("#transcript-new-events"):
                    await hint.remove()
            except Exception:
                pass
            try:
                self.scroll_end(animate=False)
            except Exception:
                pass
            event.stop()


__all__ = [
    "ActivitySpinner",
    "ChatTranscript",
    "PIN_THRESHOLD_LINES",
    "SPINNER_INTERVAL_MS",
    "SPINNER_LABELS",
    "TranscriptDiff",
    "TranscriptItemWidget",
    "collapsed_preview",
    "export_transcript_text",
    "filter_transcript",
    "role_edge_for_item",
    "should_stay_pinned",
    "spinner_frame",
    "transcript_diff",
]
