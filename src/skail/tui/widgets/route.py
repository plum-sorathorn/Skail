"""Route sidebar: read-only assignment display."""

from __future__ import annotations

from typing import Any

from textual.containers import VerticalScroll
from textual.widgets import Static

from skail.tui.projection import RouteViewItem


def immutable_label(attempt_number: int) -> str:
    """Exact immutable copy for an attempt number."""
    return f"Assignment immutable for attempt {int(attempt_number)}"


def render_route_lines(item: RouteViewItem | None) -> list[str]:
    """Pure read-only lines: Selected/Reason/Model/immutable/Fallback."""
    if item is None:
        return ["[dim]No routing decisions recorded yet[/dim]"]
    slot = item.task_id or "lead"
    lines = [
        f"Selected (Agent {slot} \u2192 {item.routing_mode})",
        f"Reason: {'; '.join(item.explanation) if item.explanation else 'None'}",
        f"Model: {item.provider}:{item.model}",
        immutable_label(item.attempt_number),
        f"Fallback: {item.binding_constraint or 'None (policy select)'}",
    ]
    return lines


class RouteView(VerticalScroll):
    """Read-only route display; changes go through commands/runtime only."""

    DEFAULT_CSS = """
    RouteView {
        width: 100%;
        height: 100%;
        padding: 0 1;
        scrollbar-size: 1 1;
    }
    .route-header {
        text-style: bold;
        color: $accent;
        padding-bottom: 1;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.routes: dict[str, RouteViewItem] = {}
        self.selected_task_id: str | None = None

    def update_routes(
        self, routes: dict[str, RouteViewItem], selected_task_id: str | None = None
    ) -> None:
        self.routes = routes
        self.selected_task_id = selected_task_id
        try:
            self.remove_children()
            self.mount(Static("ROUTE DECISIONS", classes="route-header"))
            target = self._target()
            for line in render_route_lines(target):
                self.mount(Static(line))
        except Exception:
            pass

    def _target(self) -> RouteViewItem | None:
        if self.selected_task_id and self.selected_task_id in self.routes:
            return self.routes[self.selected_task_id]
        if "lead" in self.routes:
            return self.routes["lead"]
        if self.routes:
            return next(iter(self.routes.values()))
        return None


__all__ = ["RouteView", "immutable_label", "render_route_lines"]
