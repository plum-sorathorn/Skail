from __future__ import annotations

from typing import Any

from rich.table import Table
from rich.text import Text
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widgets import Static

from rudder.tui.projection import AgentRailItem


class AgentRail(VerticalScroll):
    """Side panel displaying the agent/task rail, true states, and costs."""

    DEFAULT_CSS = """
    AgentRail {
        width: 100%;
        height: 100%;
        padding: 0 1;
        scrollbar-size: 1 1;
    }
    .rail-header {
        text-style: bold;
        color: $accent;
        padding-bottom: 1;
    }
    """

    class AgentSelected(Message):
        def __init__(self, task_id: str) -> None:
            super().__init__()
            self.task_id = task_id

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.items: list[AgentRailItem] = []
        self.focused_task_id: str | None = None

    def update_items(self, items: list[AgentRailItem], focused_id: str | None = None) -> None:
        self.items = items
        self.focused_task_id = focused_id
        self.remove_children()
        self.mount(Static("AGENT RAIL", classes="rail-header"))

        if not items:
            self.mount(Static("[dim]No active agents[/dim]"))
            return

        table = Table(
            expand=True,
            show_header=True,
            header_style="bold cyan",
            box=None,
            padding=(0, 1),
        )
        table.add_column("Task ID", style="bold")
        table.add_column("Profile")
        table.add_column("Model")
        table.add_column("Status")
        table.add_column("Elapsed")
        table.add_column("Cost (Act/Est)")

        for item in items:
            prefix = "▶ " if item.task_id == focused_id else "  "
            display_id = f"{prefix}..{item.task_id_suffix}"

            # Distinct status styling
            st_text = Text()
            st = item.status.lower().strip()
            if st in ("executing", "running", "started"):
                st_text.append(st, style="bold cyan")
            elif st == "planned":
                st_text.append(st, style="blue")
            elif st == "queued":
                st_text.append(st, style="dim")
            elif st in ("waiting_approval", "waiting approval", "awaiting_approval"):
                st_text.append(st, style="bold yellow")
            elif st == "verified":
                st_text.append(st, style="bold green")
            elif st == "integrated":
                st_text.append(st, style="bold magenta")
            elif st in ("complete", "succeeded"):
                st_text.append(st, style="green")
            elif st == "failed":
                st_text.append(st, style="bold red")
            elif st == "blocked":
                st_text.append(st, style="bold red reverse")
            elif st == "escalated":
                st_text.append(st, style="bold magenta")
            elif st == "returned_to_lead":
                st_text.append(st, style="bold yellow")
            elif st == "cancelled":
                st_text.append(st, style="dim red")
            else:
                st_text.append(st, style="white")

            elapsed_str = f"{item.elapsed_sec:.1f}s" if item.elapsed_sec > 0 else "--"
            cost_str = f"${item.cost_authoritative_usd:.2f} / ${item.cost_estimated_usd:.2f}"

            table.add_row(
                display_id,
                item.profile or "unknown",
                item.model or "unassigned",
                st_text,
                elapsed_str,
                cost_str,
            )

        self.mount(Static(table))
