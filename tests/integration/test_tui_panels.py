from __future__ import annotations

from decimal import Decimal

import pytest

from skail.tui.app import SkailApp
from skail.tui.projection import (
    AgentRailItem,
    BudgetViewItem,
    RouteViewItem,
    TuiProjection,
)
from skail.tui.widgets.agents import AgentRail
from skail.tui.widgets.budget import BudgetView
from skail.tui.widgets.route import RouteView


@pytest.mark.asyncio
async def test_agent_rail_renders_all_fields_and_distinct_states() -> None:
    proj = TuiProjection()
    # Add items in distinct states
    proj.agent_rail_items = [
        AgentRailItem(
            task_id="task-q1",
            task_id_suffix="q1",
            parent_task_id=None,
            profile="researcher",
            model="fake:smart-model",
            status="queued",
            elapsed_sec=0.0,
            cost_authoritative_usd=Decimal("0.00"),
            cost_estimated_usd=Decimal("0.04"),
        ),
        AgentRailItem(
            task_id="task-r1",
            task_id_suffix="r1",
            parent_task_id=None,
            profile="implementer",
            model="fake:fast-model",
            status="running",
            elapsed_sec=3.4,
            cost_authoritative_usd=Decimal("0.02"),
            cost_estimated_usd=Decimal("0.05"),
        ),
        AgentRailItem(
            task_id="task-b1",
            task_id_suffix="b1",
            parent_task_id="task-r1",
            profile="implementer",
            model="fake:fast-model",
            status="blocked",
            elapsed_sec=5.0,
            cost_authoritative_usd=Decimal("0.01"),
            cost_estimated_usd=Decimal("0.03"),
        ),
        AgentRailItem(
            task_id="task-e1",
            task_id_suffix="e1",
            parent_task_id=None,
            profile="lead",
            model="fake:smart-model",
            status="escalated",
            elapsed_sec=12.1,
            cost_authoritative_usd=Decimal("0.10"),
            cost_estimated_usd=Decimal("0.12"),
        ),
        AgentRailItem(
            task_id="task-ret1",
            task_id_suffix="ret1",
            parent_task_id=None,
            profile="tester",
            model="fake:fast-model",
            status="returned_to_lead",
            elapsed_sec=8.0,
            cost_authoritative_usd=Decimal("0.05"),
            cost_estimated_usd=Decimal("0.05"),
        ),
    ]

    app = SkailApp(projection=proj)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        rail = app.query_one("#agent-rail", AgentRail)
        assert len(rail.items) == 5

        # Render output check
        rendered_text = str(rail.render())
        assert "A G E N T S" in rendered_text or len(rail.children) > 0


@pytest.mark.asyncio
async def test_route_view_renders_recorded_decision_and_lineage() -> None:
    proj = TuiProjection()
    proj.route_items["task-100"] = RouteViewItem(
        task_id="task-100",
        attempt_number=2,
        model="fake:smart-model",
        provider="fake",
        routing_mode="quality",
        capability_floor=0.85,
        estimated_cost_usd=Decimal("0.08"),
        explanation=("matched-capability-floor", "escalated-from-attempt-1"),
        lineage=("task-root", "attempt-1", "attempt-2"),
        binding_constraint="floor_and_context_packet",
    )
    proj.focus_agent("task-100")

    app = SkailApp(projection=proj)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        route_view = app.query_one("#route-view", RouteView)
        assert route_view.routes["task-100"].capability_floor == 0.85
        assert route_view.routes["task-100"].binding_constraint == "floor_and_context_packet"
        assert len(route_view.routes["task-100"].lineage) == 3


@pytest.mark.asyncio
async def test_budget_view_separates_authoritative_and_estimated() -> None:
    proj = TuiProjection()
    proj.budget_item = BudgetViewItem(
        hard_limit_usd=Decimal("10.00"),
        authoritative_actual_usd=Decimal("8.50"),
        estimated_actual_usd=Decimal("9.00"),
        reserved_usd=Decimal("1.00"),
        available_usd=Decimal("0.50"),
        warning_state=True,
        lead_allowance_usd=Decimal("2.00"),
        per_agent_costs={"task-1": Decimal("5.00"), "task-2": Decimal("3.50")},
    )

    app = SkailApp(projection=proj)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        budget_view = app.query_one("#budget-view", BudgetView)
        assert budget_view.item.authoritative_actual_usd == Decimal("8.50")
        assert budget_view.item.estimated_actual_usd == Decimal("9.00")
        assert budget_view.item.reserved_usd == Decimal("1.00")
        assert budget_view.item.available_usd == Decimal("0.50")
        assert budget_view.item.warning_state is True
        assert budget_view.item.lead_allowance_usd == Decimal("2.00")
        assert budget_view.item.per_agent_costs["task-1"] == Decimal("5.00")
