"""Route sidebar: read-only assignment display."""

from __future__ import annotations

from typing import Any

from textual.containers import VerticalScroll
from textual.widgets import Static

from skail.tui.projection import RouteViewItem
from skail.tui.widgets.plan import section_head


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


def role_floor_line(item: RouteViewItem) -> str:
    """One ROLE FLOORS row: which role, which capability floor."""
    slot = item.task_id or "lead"
    return f"{slot} \u00b7 floor {item.capability_floor:.2f}"


def shadow_section(item: RouteViewItem) -> tuple[str, list[str]]:
    """ELIGIBLE/EXCLUDED survey from the routing shadow.

    Returns (head, lines); ('', []) when the snapshot carries no shadow
    recommendation. Sufficient evidence elects the candidate, otherwise it is
    excluded together with its reasons. Nothing invented.
    """
    if not item.shadow_recommendation:
        return "", []
    sufficient = (item.evidence_status or "").strip().lower() == "sufficient"
    if not sufficient:
        lines = [f"SHADOW: {item.shadow_recommendation}"]
        lines.extend(f"\u00b7 {reason}" for reason in item.shadow_reasons)
        return "EXCLUDED", lines
    detail = f"SHADOW: {item.shadow_recommendation}"
    if item.evidence_revision:
        detail += f" (evidence {item.evidence_revision})"
    return "ELIGIBLE", [detail]


class RouteView(VerticalScroll):
    """Read-only route display; changes go through commands/runtime only."""

    DEFAULT_CSS = """
    RouteView {
        width: 100%;
        height: 100%;
        padding: 0 1;
        scrollbar-size: 1 1;
    }
    RouteView:focus-within {
        outline: solid $focusRing;
    }
    .route-header {
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
            self.mount(Static(" ".join("ROUTE"), classes="route-header"))
            target = self._target()
            lines = render_route_lines(target)
            for line in lines[:3]:
                self.mount(Static(line))
            if target is not None:
                self.mount(Static(section_head("ASSIGNMENT"), classes="sec-head"))
                for line in lines[3:]:
                    self.mount(Static(line))
                self.mount(Static(section_head("ROLE FLOORS"), classes="sec-head"))
                self.mount(Static(role_floor_line(target), classes="sec-row"))
                head, shadow = shadow_section(target)
                if head:
                    self.mount(Static(section_head(head), classes="sec-head"))
                    for line in shadow:
                        self.mount(Static(line, classes="sec-row"))
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


__all__ = [
    "RouteView",
    "immutable_label",
    "render_route_lines",
    "role_floor_line",
    "shadow_section",
]
