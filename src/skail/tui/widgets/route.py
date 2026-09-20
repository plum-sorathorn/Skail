"""Route sidebar: read-only assignment display."""

from __future__ import annotations

from typing import Any, Final

from textual.containers import VerticalScroll
from textual.widgets import Static

from skail.tui.projection import RouteViewItem
from skail.tui.widgets.plan import section_head

CAPABILITY_FLOOR_DEFAULT: Final = 0.50


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


def policy_lead_line(item: RouteViewItem) -> str:
    """Policy lead row (README #39): routing mode then slot, under a 'policy' label."""
    slot = item.task_id or "lead"
    return f"policy: {item.routing_mode} \u2192 {slot}"


def role_floor_line(item: RouteViewItem) -> str:
    """One ROLE FLOORS row: which role, which capability floor."""
    slot = item.task_id or "lead"
    return f"{slot} \u00b7 floor {item.capability_floor:.2f}"


def role_floor_lines(routes: dict[str, RouteViewItem]) -> list[str]:
    """ROLE FLOORS rows: one per carried floor across the whole route table.

    The projection defaults capability_floor to 0.50 when the routing snapshot
    supplies none, so 0.50 reads as 'not carried' here (nothing invented);
    every other carried value gets its own row.
    """
    return [
        role_floor_line(item)
        for item in routes.values()
        if item.capability_floor != CAPABILITY_FLOOR_DEFAULT
    ]


def shadow_section(item: RouteViewItem) -> tuple[str, list[str]]:
    """ELIGIBLE/EXCLUDED survey from the routing shadow.

    Returns (head, lines); ('', []) when the snapshot carries no shadow
    recommendation. The single detail line keeps the README #40 exclusion
    shape: the candidate, then its reasons (or the evidence marker when
    elected) joined by the panel's middle-dot separator. Nothing invented.
    """
    rec = item.shadow_recommendation
    if not rec:
        return "", []
    sufficient = (item.evidence_status or "").strip().lower() == "sufficient"
    if sufficient:
        detail = rec
        if item.evidence_revision:
            detail = f"{rec} \u00b7 evidence {item.evidence_revision}"
        return "ELIGIBLE", [detail]
    detail = " \u00b7 ".join((rec, *item.shadow_reasons))
    return "EXCLUDED", [detail]


class RouteView(VerticalScroll):
    """Read-only route display; changes go through commands/runtime only."""

    can_focus = False

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
            if target is not None:
                # The policy lead row replaces the reversed Selected copy;
                # Reason/Model/immutable/Fallback stay the guaranteed lines.
                self.mount(Static(policy_lead_line(target)))
                lines = render_route_lines(target)
                for line in lines[1:3]:
                    self.mount(Static(line))
                self.mount(Static(section_head("ASSIGNMENT"), classes="sec-head"))
                for line in lines[3:]:
                    self.mount(Static(line))
                head, shadow = shadow_section(target)
                if head:
                    self.mount(Static(section_head(head), classes="sec-head"))
                    for line in shadow:
                        self.mount(Static(line, classes="sec-row"))
                # Floors last: one row per carried floor, omitted when none.
                floors = role_floor_lines(routes)
                if floors:
                    self.mount(Static(section_head("ROLE FLOORS"), classes="sec-head"))
                    for line in floors:
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
    "policy_lead_line",
    "render_route_lines",
    "role_floor_line",
    "role_floor_lines",
    "shadow_section",
]
