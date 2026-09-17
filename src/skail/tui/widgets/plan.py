"""Plan sidebar: header, rows, proposed/rejected cards, receipts."""

from __future__ import annotations

from typing import Any

from textual.containers import VerticalScroll
from textual.message import Message
from textual.widgets import Static

from skail.tui.projection import PlanNodeViewItem

GLYPH_DONE = "\u2713"
GLYPH_CURRENT = "\u25cf"
GLYPH_TODO = "\u2219"

DONE_STATES = ("succeeded", "complete", "done", "verified", "integrated")
CURRENT_STATES = ("running", "executing", "ready", "launching")
PROPOSED_TITLE = "PROPOSED PLAN"
REJECTED_TITLE = "REJECTED"


def plan_row_kind(state: str) -> str:
    """Map a node state to done/current/todo."""
    text = state.strip().lower()
    if text in DONE_STATES:
        return "done"
    if text in CURRENT_STATES:
        return "current"
    return "todo"


def plan_glyph(state: str) -> str:
    kind = plan_row_kind(state)
    if kind == "done":
        return GLYPH_DONE
    if kind == "current":
        return GLYPH_CURRENT
    return GLYPH_TODO


def plan_progress(items: dict[str, PlanNodeViewItem]) -> tuple[int, int]:
    """Return (done, total) counting done states."""
    total = len(items)
    done = sum(1 for item in items.values() if plan_row_kind(item.state) == "done")
    return done, total


def plan_header(total_done: int, total: int) -> str:
    return f"PLAN \u00b7 {total_done}/{total}"


def render_plan_rows(items: dict[str, PlanNodeViewItem]) -> list[str]:
    ordered = sorted(items.values(), key=lambda i: i.local_id)
    rows: list[str] = []
    for item in ordered:
        rows.append(f"{plan_glyph(item.state)} {item.local_id} {item.objective}")
    return rows


class PlanView(VerticalScroll):
    """Plan panel with proposed/rejected cards and receipts."""

    DEFAULT_CSS = """
    PlanView {
        width: 100%;
        height: 100%;
        padding: 0 1;
        scrollbar-size: 1 1;
    }
    PlanView:focus-within {
        outline: solid $focusRing;
    }
    .plan-header {
        text-style: bold;
        color: $accent;
        padding-bottom: 1;
    }
    .plan-proposed {
        border: round $approval;
        background: $approvalSurface;
        padding: 1;
    }
    .plan-proposed:focus-within {
        outline: solid $focusRing;
    }
    .plan-rejected {
        border-left: solid $border;
        opacity: 60%;
        padding: 1;
    }
    .plan-row:focus-within {
        outline: solid $focusRing;
    }
    """

    class PlanAccepted(Message):
        pass

    class PlanRejected(Message):
        pass

    class PlanChangesRequested(Message):
        pass

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.plan_items: dict[str, PlanNodeViewItem] = {}
        self.plan_id: str | None = None
        self.revision: int | None = None
        self.integrations: dict[str, Any] = {}
        self.plan_state: str = "none"
        self.receipts: list[str] = []
        self.rejected_collapsed: bool = True

    def update_plan(
        self,
        plan_items: dict[str, PlanNodeViewItem],
        plan_id: str | None = None,
        revision: int | None = None,
        integrations: dict[str, Any] | None = None,
        plan_state: str = "none",
        receipts: list[str] | None = None,
    ) -> None:
        self.plan_items = plan_items
        self.plan_id = plan_id
        self.revision = revision
        self.integrations = integrations or {}
        self.plan_state = plan_state
        self.receipts = list(receipts or [])
        self._render()

    def _render(self) -> None:
        try:
            self.remove_children()
        except Exception:
            return
        done, total = plan_progress(self.plan_items)
        try:
            self.mount(Static(plan_header(done, total), classes="plan-header"))
            state = (self.plan_state or "none").strip().lower()
            if state == "proposed":
                self.mount(
                    Static(
                        "PROPOSED PLAN\n[A] Accept [R] Reject [E] Request changes",
                        classes="plan-proposed",
                    )
                )
                for row in render_plan_rows(self.plan_items):
                    self.mount(Static(row))
            elif state == "rejected":
                self.mount(Static("REJECTED", classes="plan-rejected"))
                if not self.rejected_collapsed:
                    for row in render_plan_rows(self.plan_items):
                        self.mount(Static(row))
            else:
                for row in render_plan_rows(self.plan_items):
                    self.mount(Static(row))
                for receipt in self.receipts:
                    self.mount(Static(receipt))
            if not self.plan_items and state == "none":
                self.mount(Static("[dim]No execution plan active[/dim]"))
        except Exception:
            pass

    def accept(self) -> None:
        self.plan_state = "accepted"
        self.post_message(self.PlanAccepted())

    def reject(self) -> None:
        self.plan_state = "rejected"
        self.rejected_collapsed = True
        self.post_message(self.PlanRejected())

    def request_changes(self) -> None:
        self.post_message(self.PlanChangesRequested())

    async def on_key(self, event: Any) -> None:
        if (self.plan_state or "").strip().lower() != "proposed":
            return
        key = getattr(event, "key", "")
        if key in ("a", "A"):
            self.accept()
            try:
                event.stop()
            except Exception:
                pass
        elif key in ("r", "R"):
            self.reject()
            try:
                event.stop()
            except Exception:
                pass
        elif key in ("e", "E"):
            self.request_changes()
            try:
                event.stop()
            except Exception:
                pass
        elif key == "enter":
            self.accept()
            try:
                event.stop()
            except Exception:
                pass


__all__ = [
    "PlanView",
    "plan_glyph",
    "plan_header",
    "plan_progress",
    "plan_row_kind",
    "render_plan_rows",
]
