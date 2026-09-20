"""Agents sidebar: stable slot rows from projection children_view().

Draft Phase 3b: rows from ``TuiProjection.children_view()`` with status
glyphs, ``Agent N`` labels, task text, status word, and cost. Slot colors
come from ``theme.agent_slot_token`` as inline styles (no custom $vars).
Completed/failed rows stay visible. Selecting never switches tabs.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from rich.text import Text
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widgets import Static

from skail.tui.projection import ChildView
from skail.tui.theme import agent_slot_token, lookup

ALLOWED_STATUSES: tuple[str, ...] = (
    "running",
    "waiting",
    "complete",
    "failed",
    "cancelled",
)

GLYPH_RUNNING = "\u25cf"
GLYPH_IDLE = "\u2219"
GLYPH_COMPLETE = "\u2713"
GLYPH_FAILED = "\u2715"
GLYPH_CANCELLED = "\u2298"

LEDGER_GLYPHS: dict[str, str] = {
    "running": GLYPH_RUNNING,
    "waiting": GLYPH_IDLE,
    "complete": GLYPH_COMPLETE,
    "failed": GLYPH_FAILED,
    "cancelled": GLYPH_CANCELLED,
}

LEDGER_ROW_WIDTH = 33


def agent_glyph(status: str) -> str:
    """Return the status glyph: ● for running, ∙ otherwise."""
    if status.strip().lower() == "running":
        return GLYPH_RUNNING
    return GLYPH_IDLE


def agent_label(slot: int) -> str:
    """Return the stable slot label, e.g. ``Agent 2``."""
    return f"Agent {int(slot)}"


def normalize_status(status: str) -> str:
    """Clamp to the allowed sidebar statuses; default to waiting."""
    text = status.strip().lower()
    if text in ALLOWED_STATUSES:
        return text
    return "waiting"


def agent_row_text(child: ChildView) -> str:
    """Pure row text: ``Agent N | task | status | $cost``."""
    status = normalize_status(child.status)
    glyph = agent_glyph(status)
    cost = child.cost if isinstance(child.cost, Decimal) else Decimal(str(child.cost))
    return f"{glyph} {agent_label(child.slot)} | {child.task} | {status} | ${cost:.2f}"


def render_agent_rows(children: list[ChildView]) -> list[str]:
    """Pure helper: one row string per child, slot-sorted."""
    ordered = sorted(children, key=lambda c: (c.slot, c.id))
    return [agent_row_text(c) for c in ordered]


def ledger_status_glyph(status: str) -> str:
    """ATELIER ledger glyph: ● running, ∙ waiting, ✓ complete, ✕ failed, ⊘ cancelled."""
    return LEDGER_GLYPHS[normalize_status(status)]


def render_agent_ledger_row(child: ChildView, width: int = LEDGER_ROW_WIDTH) -> str:
    """Pure ledger line: ``●  AGENT 1  RUNNING       $0.0142`` (cost right-aligned, 4dp)."""
    status = normalize_status(child.status)
    cost = child.cost if isinstance(child.cost, Decimal) else Decimal(str(child.cost))
    cost_text = f"${cost:.4f}"
    lead = f"{ledger_status_glyph(status)}  {agent_label(child.slot).upper()}  {status.upper()}"
    return lead.ljust(max(width - len(cost_text), len(lead) + 1)) + cost_text


def slot_style_inline(slot: int, theme: Any = None) -> str:
    """Inline style color for a slot via ``agent_slot_token``."""
    token = agent_slot_token(slot)
    if theme is None:
        return token
    try:
        return lookup(theme, token)
    except KeyError:
        return token


class AgentRail(VerticalScroll):
    """Side panel: agent rows from ``children_view()`` + legacy rail."""

    DEFAULT_CSS = """
    AgentRail {
        width: 100%;
        height: 100%;
        padding: 0 1;
        scrollbar-size: 1 1;
    }
    AgentRail:focus-within {
        outline: solid $focusRing;
    }
    .rail-header {
        text-style: bold;
        color: $accent;
        padding-bottom: 1;
    }
    .agent-row:focus-within {
        outline: solid $focusRing;
    }
    .ledger-row.selected {
        background: $selection;
    }
    .ledger-hint {
        color: $textMuted;
        padding-top: 1;
    }
    """

    class AgentSelected(Message):
        def __init__(self, task_id: str) -> None:
            super().__init__()
            self.task_id = task_id

    class AgentDetailRequested(Message):
        def __init__(self, task_id: str) -> None:
            super().__init__()
            self.task_id = task_id

    class MissionControlRequested(Message):
        def __init__(self, task_id: str) -> None:
            super().__init__()
            self.task_id = task_id

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.items: list[Any] = []
        self.child_rows: list[ChildView] = []
        self.focused_task_id: str | None = None
        self._selected_index: int = 0

    def update_items(self, items: list[Any], focused_id: str | None = None) -> None:
        """Legacy entry point kept for Phase 1 callers."""
        self.items = items
        self.focused_task_id = focused_id
        self._render_legacy()

    def update_children(
        self, children: list[ChildView], focused_id: str | None = None
    ) -> None:
        """Phase 3b entry point: render rows from ``children_view()``."""
        self.child_rows = sorted(children, key=lambda c: (c.slot, c.id))
        if focused_id is not None:
            self.focused_task_id = focused_id
        self._render_children()

    def _render_legacy(self) -> None:
        try:
            self.remove_children()
            self.mount(Static("A G E N T S", classes="rail-header"))
            if not self.items:
                if not self.child_rows:
                    self.mount(Static("[dim]No active agents[/dim]"))
                    return
            self._mount_child_rows()
        except Exception:
            pass

    def _render_children(self) -> None:
        try:
            self.remove_children()
            self.mount(Static("A G E N T S", classes="rail-header"))
            if not self.child_rows:
                self.mount(Static("[dim]No active agents[/dim]"))
                return
            self._mount_child_rows()
            hint = (
                "[dim]\u23ce detail \u00b7[/dim]"
                " [on $surfaceRaised] M [/] [dim]mission control[/dim]"
            )
            self.mount(Static(hint, classes="ledger-hint"))
        except Exception:
            pass

    def _mount_child_rows(self) -> None:
        for child in self.child_rows:
            status = normalize_status(child.status)
            glyph = ledger_status_glyph(status)
            token = agent_slot_token(child.slot)
            cost = child.cost if isinstance(child.cost, Decimal) else Decimal(str(child.cost))
            label = agent_label(child.slot).upper()
            status_word = status.upper()
            lead = f"{glyph}  {label}  {status_word}"
            cost_text = f"${cost:.4f}"
            pad = " " * max(LEDGER_ROW_WIDTH - len(lead) - len(cost_text), 1)
            text = Text()
            text.append(f"{glyph}  ", style=token)
            text.append(f"{label}  ", style="bold")
            text.append(f"{status_word}{pad}", style="textFaint")
            text.append(cost_text, style="textMuted")
            selected = " selected" if child.id == self.focused_task_id else ""
            row = Static(text, classes=f"ledger-row{selected}")
            try:
                row.styles.border_left = ("solid", token)
            except Exception:
                pass
            self.mount(row)
            task_line = Text(f"   {child.task}", style="textMuted")
            self.mount(Static(task_line, classes="ledger-task"))

    def select_child(self, task_id: str) -> None:
        """Focus a child row; the Agents tab stays active."""
        self.focused_task_id = task_id
        for index, child in enumerate(self.child_rows):
            if child.id == task_id:
                self._selected_index = index
                break
        self.post_message(self.AgentSelected(task_id))

    def open_detail(self, task_id: str) -> None:
        """Enter opens detail (focus detail region)."""
        self.post_message(self.AgentDetailRequested(task_id))

    def open_missions(self, task_id: str) -> None:
        """M opens Mission Control for that child."""
        self.post_message(self.MissionControlRequested(task_id))

    async def on_key(self, event: Any) -> None:
        if not self.child_rows:
            return
        key = getattr(event, "key", "")
        if key == "enter":
            current = self.child_rows[self._selected_index % len(self.child_rows)]
            self.open_detail(current.id)
            try:
                event.stop()
            except Exception:
                pass
        elif key in ("m", "M"):
            current = self.child_rows[self._selected_index % len(self.child_rows)]
            self.open_missions(current.id)
            try:
                event.stop()
            except Exception:
                pass
        elif key in ("up", "down"):
            delta = -1 if key == "up" else 1
            self._selected_index = (self._selected_index + delta) % len(self.child_rows)
            current = self.child_rows[self._selected_index]
            self.select_child(current.id)
            self._render_children()
            try:
                event.stop()
            except Exception:
                pass

    def on_click(self, event: Any = None) -> None:
        """Clicking selects; never switches to the Route tab."""
        _ = event


__all__ = [
    "ALLOWED_STATUSES",
    "LEDGER_ROW_WIDTH",
    "AgentRail",
    "agent_glyph",
    "agent_label",
    "agent_row_text",
    "ledger_status_glyph",
    "normalize_status",
    "render_agent_ledger_row",
    "render_agent_rows",
    "slot_style_inline",
]
