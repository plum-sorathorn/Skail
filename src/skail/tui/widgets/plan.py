"""Plan sidebar: header, rows, proposed/rejected cards, revisions, integrations, receipts."""

from __future__ import annotations

import re
from typing import Any

from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Input, Static

from skail.tui.projection import PlanNodeViewItem, WorkspaceIntegrationItem

GLYPH_DONE = "\u2713"
GLYPH_CURRENT = "\u258c"
GLYPH_TODO = "\u2219"

DONE_STATES = ("succeeded", "complete", "done", "verified", "integrated")
CURRENT_STATES = ("running", "executing", "ready", "launching")
PROPOSED_TITLE = "PROPOSED PLAN"
PROPOSED_ACTS = (
    "[underline]Accept[/underline] A / [underline]Reject[/underline] R"
    " / [underline]Change[/underline] C"
)
CHANGE_NOTE_PLACEHOLDER = "optional change note\u2026"
REJECTED_TITLE = "REJECTED"

# Receipts are the only history carrier in the projection: when none matches the
# "r1 -> r2" shape (either arrow) the REVISIONS section shows just the current
# revision rather than inventing history.
REVISION_HISTORY = re.compile(r"r\d+\s*(?:\u2192|->)\s*r\d+")

# WorkspaceIntegrationItem.status (projection.py) -> display glyph; rendered next to
# the status word, so the pairing is never colour-only.
INTEGRATION_GLYPHS: dict[str, str] = {
    "captured": GLYPH_TODO,
    "applying": GLYPH_CURRENT,
    "integrated": GLYPH_DONE,
    "in_doubt": "?",
    "blocked": "\u2715",
}


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


def plan_header_spaced(total_done: int, total: int) -> str:
    """ATELIER variant of plan_header: only the PLAN word is letterspaced."""
    word, separator, rest = plan_header(total_done, total).partition(" ")
    return " ".join(word) + separator + rest


def plan_header_state(total_done: int, total: int, state: str) -> str:
    """ATELIER header: letterspaced PLAN, the counts, then the current plan state.

    The header carries the state word (e.g. ``accepted``) next to the counts; when no
    state is known (``none``) the counts stand alone instead of inventing one.
    """
    base = plan_header_spaced(total_done, total)
    word = (state or "").strip().lower()
    if not word or word == "none":
        return base
    return f"{base} \u00b7 {word}"


def render_plan_rows(items: dict[str, PlanNodeViewItem]) -> list[str]:
    ordered = sorted(items.values(), key=lambda i: i.local_id)
    rows: list[str] = []
    for item in ordered:
        row = f"{plan_glyph(item.state)} {item.local_id} {item.objective}"
        if item.task_id:
            row += f" [textFaint]\u00b7 {item.task_id}[/]"
        rows.append(row)
    return rows


def section_head(label: str) -> str:
    """ATELIER hairline head: letterspaced label between hairline runs."""
    return "\u2500\u2500  " + " ".join(label) + "  \u2500\u2500"


def integration_glyph(status: str) -> str:
    """Status glyph for an integration row; paired with the status word, never colour-only."""
    return INTEGRATION_GLYPHS.get(status.strip().lower(), GLYPH_TODO)


def integration_lines(integrations: dict[str, WorkspaceIntegrationItem]) -> list[str]:
    """INTEGRATIONS rows, ATELIER form: glyph, then name, then status; [] when none.

    The design's mock dot-joins integration names (``pytest · rtk · apply_patch``);
    WorkspaceIntegrationItem carries no integration name, so ``task_id`` (the changeset
    id when unnamed) stands in and the status rides the glyph + word. Nothing invented.
    """
    lines: list[str] = []
    for changeset_id, integration in integrations.items():
        who = integration.task_id or changeset_id
        row = f"{integration_glyph(integration.status)} {who} \u00b7 {integration.status}"
        if integration.error:
            row += f" \u00b7 {integration.error}"
        lines.append(row)
    return lines


def receipt_lines(receipts: list[str]) -> list[str]:
    """RECEIPTS rows, ATELIER 2-line receipt: bold primary + faint indented continuation.

    A receipt's first line becomes the checked primary row; any remaining lines become
    the faint, indented continuation. Single-line receipts render the primary line only
    (the continuation is never invented); [] when none.
    """
    lines: list[str] = []
    for receipt in receipts:
        parts = receipt.splitlines() or [receipt]
        lines.append(f"[b]{GLYPH_DONE} {parts[0]}[/]")
        lines.extend(f"[textFaint]  {part}[/]" for part in parts[1:])
    return lines


def revision_lines(
    plan_id: str | None,
    revision: int | None,
    plan_state: str,
    receipts: list[str],
) -> list[str]:
    """REVISIONS rows: the current revision + state, plus receipt-carried history.

    History: receipts are the only carrier of revision transitions in the projection,
    so when no receipt matches the ``r1 -> r2`` (or unicode-arrow) shape we render just
    the current revision instead of inventing history; [] when nothing is stored.
    """
    word = (plan_state or "none").strip().lower()
    if not plan_id and word == "none":
        return []
    parts: list[str] = []
    if plan_id:
        parts.append(plan_id)
    if revision is not None:
        parts.append(f"r{revision}")
    if word != "none":
        parts.append(word)
    lines: list[str] = [" \u00b7 ".join(parts)]
    for receipt in receipts:
        match = REVISION_HISTORY.search(receipt)
        if match:
            lines.append(f"[textFaint]  {' '.join(match.group(0).split())}[/]")
    return lines


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
        border-bottom: solid $border;
    }
    .sec-head {
        color: $textFaint;
    }
    .sec-row {
        color: $textMuted;
    }
    .plan-proposed {
        background: $approvalSurface;
        border: none;
        border-left: heavy $approval;
        padding: 1;
    }
    .plan-proposed:focus-within {
        border-left: heavy $focusRing;
    }
    .plan-proposed-title {
        text-style: bold;
        color: $text;
    }
    .plan-acts {
        color: $textMuted;
    }
    #plan-change-note {
        border: none;
        border-bottom: dashed $borderStrong;
        background: $approvalSurface;
        padding: 0 1;
        height: 1;
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
        """Request changes, carrying the note typed in #plan-change-note."""

        def __init__(self, note: str = "") -> None:
            super().__init__()
            self.note = note

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
        self._refresh()

    def _refresh(self) -> None:
        try:
            self.remove_children()
        except Exception:
            return
        done, total = plan_progress(self.plan_items)
        try:
            state = (self.plan_state or "none").strip().lower()
            self.mount(Static(plan_header_state(done, total, state), classes="plan-header"))
            if state == "proposed":
                self.mount(
                    Vertical(
                        Static(PROPOSED_TITLE, classes="plan-proposed-title"),
                        Static(PROPOSED_ACTS, classes="plan-acts"),
                        Input(
                            placeholder=CHANGE_NOTE_PLACEHOLDER,
                            id="plan-change-note",
                        ),
                        classes="plan-proposed",
                    )
                )
                for row in render_plan_rows(self.plan_items):
                    self.mount(Static(row, classes="plan-row"))
            elif state == "rejected":
                self.mount(Static(REJECTED_TITLE, classes="plan-rejected"))
                if not self.rejected_collapsed:
                    for row in render_plan_rows(self.plan_items):
                        self.mount(Static(row, classes="plan-row"))
            else:
                for row in render_plan_rows(self.plan_items):
                    self.mount(Static(row, classes="plan-row"))
            if not self.plan_items and state == "none":
                self.mount(Static("[dim]No execution plan active[/dim]"))
            revisions = revision_lines(self.plan_id, self.revision, self.plan_state, self.receipts)
            if revisions:
                self.mount(Static(section_head("REVISIONS"), classes="sec-head"))
                for line in revisions:
                    self.mount(Static(line, classes="sec-row"))
            integrations = integration_lines(self.integrations)
            if integrations:
                self.mount(Static(section_head("INTEGRATIONS"), classes="sec-head"))
                for line in integrations:
                    self.mount(Static(line, classes="sec-row"))
            if self.receipts:
                self.mount(Static(section_head("RECEIPTS"), classes="sec-head"))
                for line in receipt_lines(self.receipts):
                    self.mount(Static(line, classes="sec-row"))
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
        try:
            note = self.query_one("#plan-change-note", Input).value.strip()
        except Exception:
            note = ""
        self.post_message(self.PlanChangesRequested(note=note))

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

    def on_input_submitted(self, event: Any) -> None:
        self.request_changes()


__all__ = [
    "PROPOSED_ACTS",
    "PlanView",
    "integration_glyph",
    "integration_lines",
    "plan_glyph",
    "plan_header",
    "plan_header_spaced",
    "plan_header_state",
    "plan_progress",
    "plan_row_kind",
    "receipt_lines",
    "render_plan_rows",
    "revision_lines",
    "section_head",
]
