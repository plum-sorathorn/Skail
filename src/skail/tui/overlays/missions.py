"""Mission Control overlay: children capped at 3 with cancel confirm."""

from __future__ import annotations

from typing import Any

try:
    from textual.screen import Screen
except Exception:  # pragma: no cover
    Screen = object  # type: ignore[assignment,misc]

from skail.tui.overlays.shell import OVERLAY_CSS, ovl_foot, ovl_head, ovl_rule_strong
from skail.tui.projection import ChildView
from skail.tui.theme import agent_slot_token


def _app_for(host: object) -> Any:
    test_app = getattr(host, "_test_app", None)
    if test_app is not None:
        return test_app
    try:
        return getattr(host, "app", None)
    except Exception:
        return None


MAX_CHILDREN = 3
AT_CAP_MESSAGE = (
    "Mission capacity reached (3/3). Finish or cancel a mission first."
)
CONFIRM_PROMPT = "Confirm cancel? [y/N]"
MISSIONS_FOOT = "Cancel requires confirmation; at most 3 concurrent children."


def missions_header(children: list[ChildView]) -> str:
    return f"MISSION CONTROL \u2014 children {len(children)}/{MAX_CHILDREN}"


def missions_rows(children: list[ChildView]) -> list[str]:
    ordered = sorted(children, key=lambda c: (c.slot, c.id))
    rows: list[str] = []
    for child in ordered:
        token = agent_slot_token(child.slot)
        rows.append(
            f"[{token}]Agent {child.slot}[/{token}] {child.id} "
            f"{child.status} ${float(child.cost):.2f}"
        )
    return rows


def can_spawn(children: list[ChildView]) -> tuple[bool, str]:
    """Cap check: never allow a 4th child."""
    if len(children) >= MAX_CHILDREN:
        return False, AT_CAP_MESSAGE
    return True, ""


def detail_lines(child: ChildView, attempt: int = 1) -> list[str]:
    return [
        f"Assignment: {child.task}",
        f"Model: {child.model}",
        f"immutable for this attempt (attempt {int(attempt)})",
        f"Workspace lock: {child.workspace_lock or 'none'}",
        f"Last event: {child.last_event or child.status}",
    ]


class MissionsOverlay(Screen):  # type: ignore[type-arg]
    """Enter details, C requests cancel then confirm dialog, Esc closes."""

    DEFAULT_CSS = OVERLAY_CSS

    def __init__(
        self,
        children: list[ChildView] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.overlay_children: list[ChildView] = list(children or [])
        self.index = 0
        self.confirming: str | None = None

    def header(self) -> str:
        return missions_header(self.overlay_children)

    def rows(self) -> list[str]:
        return missions_rows(self.overlay_children)

    def current(self) -> ChildView | None:
        if not self.overlay_children:
            return None
        ordered = sorted(self.overlay_children, key=lambda c: (c.slot, c.id))
        return ordered[self.index % len(ordered)]

    def request_cancel(self, child_id: str) -> str:
        """C requests cancel; confirmation is required before acting."""
        self.confirming = child_id
        return CONFIRM_PROMPT

    def confirm_cancel(self, yes: bool) -> str | None:
        """Complete the pending cancel only on explicit confirmation."""
        if self.confirming is None:
            return None
        child_id = self.confirming
        self.confirming = None
        if not yes:
            return None
        try:
            app = _app_for(self)
            if app is not None and hasattr(app, "request_child_cancel"):
                app.request_child_cancel(child_id)
        except Exception:
            pass
        return child_id

    def try_spawn(self) -> tuple[bool, str]:
        return can_spawn(self.overlay_children)

    def close(self) -> None:
        try:
            app = _app_for(self)
            if app is not None and hasattr(app, "close_overlay"):
                app.close_overlay("missions")
        except Exception:
            pass

    def compose(self) -> Any:
        try:
            from textual.widgets import Static

            yield ovl_head("MISSION CONTROL", hint="C cancels \u00b7 esc closes")
            yield ovl_rule_strong()
            yield Static(self.header())
            for row in self.rows():
                yield Static(row)
            yield ovl_foot(MISSIONS_FOOT)
        except Exception:
            return
            yield  # pragma: no cover

    async def on_key(self, event: Any) -> None:
        key = getattr(event, "key", "")
        if key == "escape":
            if self.confirming is not None:
                self.confirming = None
            else:
                self.close()
            try:
                event.stop()
            except Exception:
                pass
        elif key == "enter":
            try:
                event.stop()
            except Exception:
                pass
        elif key in ("c", "C"):
            current = self.current()
            if current is not None:
                self.request_cancel(current.id)
            try:
                event.stop()
            except Exception:
                pass


__all__ = [
    "AT_CAP_MESSAGE",
    "CONFIRM_PROMPT",
    "MAX_CHILDREN",
    "MISSIONS_FOOT",
    "MissionsOverlay",
    "can_spawn",
    "detail_lines",
    "missions_header",
    "missions_rows",
]
