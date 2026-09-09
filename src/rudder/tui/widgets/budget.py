from __future__ import annotations

from typing import Any

from rich.panel import Panel
from rich.table import Table
from textual.containers import VerticalScroll
from textual.widgets import Static

from rudder.tui.projection import BudgetViewItem


class BudgetView(VerticalScroll):
    """Panel displaying authoritative budget, reserves, available balance, and per-agent usage."""

    DEFAULT_CSS = """
    BudgetView {
        width: 100%;
        height: 100%;
        padding: 0 1;
        scrollbar-size: 1 1;
    }
    .budget-header {
        text-style: bold;
        color: $accent;
        padding-bottom: 1;
    }
    .warning-banner {
        background: #eab308;
        color: black;
        text-style: bold;
        padding: 0 1;
        margin-bottom: 1;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.item: BudgetViewItem = BudgetViewItem()

    def update_budget(self, item: BudgetViewItem) -> None:
        self.item = item
        self.remove_children()
        self.mount(Static("BUDGET & USAGE", classes="budget-header"))

        if item.warning_state:
            self.mount(
                Static("⚠ BUDGET WARNING: >=80% of limit consumed", classes="warning-banner")
            )

        summary = Table(show_header=False, box=None, padding=(0, 1))
        summary.add_column("Metric", style="bold cyan", width=22)
        summary.add_column("Value")

        limit_str = (
            f"${item.hard_limit_usd:.2f}"
            if item.hard_limit_usd is not None
            else "[dim]None[/dim]"
        )
        summary.add_row("Hard Limit", limit_str)

        auth_val = f"[bold green]${item.authoritative_actual_usd:.4f}[/bold green]"
        summary.add_row("Authoritative Actual", auth_val)
        summary.add_row("Estimated Actual", f"${item.estimated_actual_usd:.4f}")
        summary.add_row("Active Reserves", f"${item.reserved_usd:.4f}")
        summary.add_row("Unknown Cost", f"${item.unknown_cost_usd:.4f}")

        avail_str = (
            f"${item.available_usd:.4f}"
            if item.available_usd is not None
            else "[dim]Unlimited[/dim]"
        )
        summary.add_row("Available Balance", avail_str)

        allowance_str = (
            f"${item.lead_allowance_usd:.2f}"
            if item.lead_allowance_usd is not None
            else "[dim]Unset[/dim]"
        )
        summary.add_row("Lead Allowance", allowance_str)

        self.mount(Static(Panel(summary, title="Session Accounting", border_style="green")))

        # Per-agent cost breakdown
        if item.per_agent_costs:
            breakdown = Table(
                show_header=True, header_style="bold yellow", box=None, padding=(0, 1)
            )
            breakdown.add_column("Task ID")
            breakdown.add_column("Authoritative Cost", justify="right")

            for tid, cost in sorted(
                item.per_agent_costs.items(), key=lambda x: x[1], reverse=True
            ):
                breakdown.add_row(tid, f"${cost:.4f}")

            self.mount(
                Static(Panel(breakdown, title="Per-Agent Cost Breakdown", border_style="yellow"))
            )
