from __future__ import annotations

from typing import Any

from rich.panel import Panel
from rich.table import Table
from textual.containers import VerticalScroll
from textual.widgets import Static

from rudder.tui.projection import RouteViewItem


class RouteView(VerticalScroll):
    """Panel displaying recorded model routing decisions, constraints, and lineage."""

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
        self.remove_children()
        self.mount(Static("ROUTE DECISIONS", classes="route-header"))

        if not routes:
            self.mount(Static("[dim]No routing decisions recorded yet[/dim]"))
            return

        target_item: RouteViewItem | None = None
        if selected_task_id and selected_task_id in routes:
            target_item = routes[selected_task_id]
        elif "lead" in routes:
            target_item = routes["lead"]
        elif routes:
            target_item = next(iter(routes.values()))

        if not target_item:
            self.mount(Static("[dim]Select a task to view route decision[/dim]"))
            return

        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("Key", style="bold cyan", width=18)
        table.add_column("Value")

        table.add_row("Task ID", target_item.task_id)
        table.add_row("Attempt", str(target_item.attempt_number))
        table.add_row("Selected Model", f"{target_item.provider}:{target_item.model}")
        table.add_row("Routing Mode", target_item.routing_mode)
        table.add_row("Capability Floor", f"{target_item.capability_floor:.2f}")
        table.add_row("Estimated Cost", f"${target_item.estimated_cost_usd:.4f}")
        table.add_row(
            "Constraint",
            target_item.binding_constraint or "[dim]None (policy select)[/dim]",
        )

        expl_text = "\n".join(f"• {e}" for e in target_item.explanation) or "[dim]None[/dim]"
        table.add_row("Explanation", expl_text)

        lineage_text = (
            " -> ".join(target_item.lineage) if target_item.lineage else "[dim]direct[/dim]"
        )
        table.add_row("Lineage", lineage_text)

        self.mount(Static(Panel(table, title=f"Route: {target_item.task_id}", border_style="blue")))
