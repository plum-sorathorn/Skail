from __future__ import annotations

from typing import Any

from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Static

from skail.tui.projection import PlanNodeViewItem, WorkspaceIntegrationItem


class PlanView(VerticalScroll):
    """Panel displaying adaptive execution plan nodes, dependencies, and workspace integrations."""

    DEFAULT_CSS = """
    PlanView {
        width: 100%;
        height: 100%;
        padding: 0 1;
        scrollbar-size: 1 1;
    }
    .plan-header {
        text-style: bold;
        color: $accent;
        padding-bottom: 1;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.plan_items: dict[str, PlanNodeViewItem] = {}
        self.plan_id: str | None = None
        self.revision: int | None = None
        self.integrations: dict[str, WorkspaceIntegrationItem] = {}

    def update_plan(
        self,
        plan_items: dict[str, PlanNodeViewItem],
        plan_id: str | None = None,
        revision: int | None = None,
        integrations: dict[str, WorkspaceIntegrationItem] | None = None,
    ) -> None:
        self.plan_items = plan_items
        self.plan_id = plan_id
        self.revision = revision
        self.integrations = integrations or {}
        self.remove_children()
        self.mount(Static("ADAPTIVE PLAN & WORKSPACES", classes="plan-header"))

        if not plan_items and not self.integrations:
            self.mount(Static("[dim]No execution plan active[/dim]"))
            return

        if plan_items:
            table = Table(
                expand=True,
                show_header=True,
                header_style="bold cyan",
                box=None,
                padding=(0, 1),
            )
            table.add_column("Node", style="bold", width=12)
            table.add_column("Kind", width=10)
            table.add_column("Scope", width=16)
            table.add_column("State", width=14)
            table.add_column("Depends On", width=16)
            table.add_column("Objective")

            for item in plan_items.values():
                short_id = item.node_id[:8] if len(item.node_id) > 8 else item.node_id
                node_lbl = item.local_id or short_id
                kind_lbl = item.kind
                scope_lbl = item.effect_scope

                st_text = Text()
                st = item.state.lower().strip()
                if st in ("running", "executing"):
                    st_text.append("running", style="bold yellow")
                elif st == "ready":
                    st_text.append("ready", style="bold cyan")
                elif st in ("succeeded", "complete"):
                    st_text.append("succeeded", style="bold green")
                elif st == "failed":
                    st_text.append("failed", style="bold red")
                elif st == "blocked":
                    st_text.append("blocked", style="bold red reverse")
                elif st == "cancelled":
                    st_text.append("cancelled", style="dim red")
                else:
                    st_text.append(st, style="white")

                deps_lbl = ", ".join(item.depends_on) if item.depends_on else "[dim]none[/dim]"
                table.add_row(node_lbl, kind_lbl, scope_lbl, st_text, deps_lbl, item.objective)

            plan_title = f"Plan: {plan_id or 'active'}"
            if revision is not None:
                plan_title += f" (rev {revision})"
            self.mount(Static(Panel(table, title=plan_title, border_style="cyan")))

        if self.integrations:
            ws_table = Table(
                expand=True,
                show_header=True,
                header_style="bold magenta",
                box=None,
                padding=(0, 1),
            )
            ws_table.add_column("Changeset", style="bold", width=14)
            ws_table.add_column("Task ID", width=14)
            ws_table.add_column("Status", width=14)
            ws_table.add_column("Base Head", width=10)
            ws_table.add_column("Paths")

            for ws_item in self.integrations.values():
                cs_lbl = (
                    ws_item.changeset_id[:12]
                    if len(ws_item.changeset_id) > 12
                    else ws_item.changeset_id
                )
                task_lbl = (
                    ws_item.task_id[:12]
                    if len(ws_item.task_id) > 12
                    else ws_item.task_id
                )

                st_text = Text()
                st = ws_item.status.lower().strip()
                if st == "integrated":
                    st_text.append("integrated", style="bold green")
                elif st == "verified":
                    st_text.append("verified", style="green")
                elif st == "pending":
                    st_text.append("pending", style="bold yellow")
                elif st == "in_doubt":
                    st_text.append("in doubt", style="bold red")
                elif st == "rejected":
                    st_text.append("rejected", style="bold red reverse")
                else:
                    st_text.append(st, style="white")

                base_lbl = ws_item.base_head[:8] if ws_item.base_head else "--"
                paths_lbl = ", ".join(ws_item.paths) if ws_item.paths else "[dim]none[/dim]"
                if ws_item.error:
                    paths_lbl += f" [red]({ws_item.error})[/red]"

                ws_table.add_row(cs_lbl, task_lbl, st_text, base_lbl, paths_lbl)

            ws_panel = Panel(
                ws_table,
                title="Workspace Changesets & Integration",
                border_style="magenta",
            )
            self.mount(Static(ws_panel))
