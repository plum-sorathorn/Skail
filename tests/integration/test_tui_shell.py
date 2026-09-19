from __future__ import annotations

from decimal import Decimal

import pytest
from textual.widgets import Input, Static, TabbedContent

from skail.domain.changesets import ChangeSet, ChangeSetPath, ChangeSetStatus, ContentImage
from skail.domain.events import (
    BudgetPayload,
    EventEnvelope,
    PlanPayload,
    ToolPayload,
)
from skail.domain.ids import new_event_id, new_run_id, new_session_id, new_task_id
from skail.domain.plans import EffectScope, ExecutionPlan, PlanNode, PlanNodeKind, PlanNodeState
from skail.sessions.journal import (
    PersistedChangeSet,
    PersistedPlan,
    RunSnapshot,
    SessionSnapshot,
    UsageSnapshot,
)
from skail.tui.app import SkailApp
from skail.tui.projection import RouteViewItem, TuiProjection
from skail.tui.widgets.budget import BudgetView
from skail.tui.widgets.chat import TranscriptItemWidget
from skail.tui.widgets.plan import PlanView
from skail.tui.widgets.route import RouteView


@pytest.mark.asyncio
async def test_tui_shell_mounts_and_renders() -> None:
    app = SkailApp()
    async with app.run_test(size=(120, 40)):
        assert app.query_one("#chat-transcript") is not None
        assert app.query_one("#prompt-composer") is not None
        assert app.query_one("#agent-rail") is not None
        assert app.query_one("#plan-view") is not None
        assert app.query_one("#route-view") is not None
        assert app.query_one("#budget-view") is not None
        assert not app.query_one("#main-container").has_class("narrow")


@pytest.mark.asyncio
async def test_tui_shell_responsive_narrow_fallback() -> None:
    app = SkailApp()
    async with app.run_test(size=(80, 40)):
        # Width 80 < 100 triggers .narrow class
        assert app.query_one("#main-container").has_class("narrow")


@pytest.mark.asyncio
async def test_tui_shell_transcript_collapse_click() -> None:
    proj = TuiProjection()
    sid = new_session_id()
    rid = new_run_id()
    tid = new_task_id()

    # Add collapsible tool item
    proj.apply_event(
        EventEnvelope(
            event_id=new_event_id(),
            session_id=sid,
            run_id=rid,
            task_id=tid,
            sequence=1,
            type="tool.completed",
            payload=ToolPayload(tool="read_file", status="completed"),
        )
    )

    app = SkailApp(projection=proj)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        widget = app.query_one(TranscriptItemWidget)
        assert widget.item.can_collapse is True
        assert widget.item.collapsed is True

        # Click to uncollapse
        await pilot.click(TranscriptItemWidget)
        await pilot.pause()
        assert widget.item.collapsed is False

        # Click again to collapse
        await pilot.click(TranscriptItemWidget)
        await pilot.pause()
        assert widget.item.collapsed is True


@pytest.mark.asyncio
async def test_tui_shell_keyboard_navigation_and_prompt_submit() -> None:
    app = SkailApp()
    async with app.run_test(size=(120, 40)) as pilot:
        # Check tab navigation keybindings
        await pilot.press("ctrl+b")
        assert app.query_one("#tabs", TabbedContent).active == "tab-budget"

        await pilot.press("ctrl+a")
        assert app.query_one("#tabs", TabbedContent).active == "tab-agents"

        await pilot.press("ctrl+r")
        assert app.query_one("#tabs", TabbedContent).active == "tab-route"

        # Submit a user prompt through composer
        inp = app.query_one("#composer-input", Input)
        inp.value = "Test task instruction"
        inp.focus()
        await pilot.press("enter")

        # Verify prompt appeared in transcript
        items = app.projection.transcript_items
        assert any(i.role == "user" and i.content == "Test task instruction" for i in items)


@pytest.mark.asyncio
async def test_tui_shell_plan_navigation_ctrl_p_and_slash() -> None:
    app = SkailApp()
    async with app.run_test(size=(120, 40)) as pilot:
        # ctrl+p navigates to Plan tab
        await pilot.press("ctrl+p")
        assert app.query_one("#tabs", TabbedContent).active == "tab-plan"

        # ctrl+b navigates to Budget tab
        await pilot.press("ctrl+b")
        assert app.query_one("#tabs", TabbedContent).active == "tab-budget"

        # slash command /plan switches to tab-plan
        inp = app.query_one("#composer-input", Input)
        inp.value = "/plan"
        inp.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert app.query_one("#tabs", TabbedContent).active == "tab-plan"

        # slash command /help lists /plan
        inp.value = "/help"
        inp.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert any("/plan" in item.content for item in app.projection.transcript_items)


@pytest.mark.asyncio
async def test_tui_shell_early_events_before_mount() -> None:
    sid = new_session_id()
    rid = new_run_id()
    plan_id = "00000000-0000-4000-8000-000000000001"
    node_id = "00000000-0000-4000-8000-000000000002"

    early_events = [
        EventEnvelope(
            event_id=new_event_id(),
            session_id=sid,
            run_id=rid,
            sequence=1,
            type="plan.admitted",
            payload=PlanPayload(action="admitted", plan_id=plan_id, revision=1),
        ),
        EventEnvelope(
            event_id=new_event_id(),
            session_id=sid,
            run_id=rid,
            sequence=2,
            type="budget.reserved",
            payload=BudgetPayload(action="reserved", amount_usd=Decimal("2.50")),
        ),
        EventEnvelope(
            event_id=new_event_id(),
            session_id=sid,
            run_id=rid,
            sequence=3,
            type="plan.node_running",
            payload=PlanPayload(
                action="node_running", plan_id=plan_id, revision=1, node_id=node_id
            ),
        ),
    ]

    app = SkailApp()
    # Apply early events BEFORE mounting
    for ev in early_events:
        app.apply_event(ev)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        plan_view = app.query_one("#plan-view", PlanView)
        assert node_id in plan_view.plan_items
        assert plan_view.plan_items[node_id].state == "running"

        budget_view = app.query_one("#budget-view", BudgetView)
        assert budget_view.item.reserved_usd == Decimal("2.50")

        # Mode in status strip shows [planned]
        status_text = app._render_status_strip()
        assert "[planned]" in status_text


@pytest.mark.asyncio
async def test_tui_shell_real_projection_updates() -> None:
    app = SkailApp()
    sid = new_session_id()
    rid = new_run_id()
    plan_id = "00000000-0000-4000-8000-000000000001"
    node_id = "00000000-0000-4000-8000-000000000002"

    async with app.run_test(size=(120, 40)) as pilot:
        # Admit plan and run node live while mounted
        app.apply_event(
            EventEnvelope(
                event_id=new_event_id(),
                session_id=sid,
                run_id=rid,
                sequence=1,
                type="plan.admitted",
                payload=PlanPayload(action="admitted", plan_id=plan_id, revision=1),
            )
        )
        app.apply_event(
            EventEnvelope(
                event_id=new_event_id(),
                session_id=sid,
                run_id=rid,
                sequence=2,
                type="plan.node_running",
                payload=PlanPayload(
                    action="node_running", plan_id=plan_id, revision=1, node_id=node_id
                ),
            )
        )
        await pilot.pause()

        plan_view = app.query_one("#plan-view", PlanView)
        assert node_id in plan_view.plan_items
        assert plan_view.plan_items[node_id].state == "running"

        # Complete node live
        app.apply_event(
            EventEnvelope(
                event_id=new_event_id(),
                session_id=sid,
                run_id=rid,
                sequence=3,
                type="plan.node_succeeded",
                payload=PlanPayload(
                    action="node_succeeded", plan_id=plan_id, revision=1, node_id=node_id
                ),
            )
        )
        app.apply_event(
            EventEnvelope(
                event_id=new_event_id(),
                session_id=sid,
                run_id=rid,
                sequence=4,
                type="budget.charged",
                payload=BudgetPayload(action="charged", amount_usd=Decimal("0.45")),
            )
        )
        await pilot.pause()

        assert plan_view.plan_items[node_id].state == "succeeded"
        budget_view = app.query_one("#budget-view", BudgetView)
        assert budget_view.item.authoritative_actual_usd == Decimal("0.45")


@pytest.mark.asyncio
async def test_tui_shell_resume_snapshot() -> None:
    sid = "session-resume-tui"
    rid = "run-resume-tui"
    plan_id = "00000000-0000-4000-8000-000000000010"
    node_id = "00000000-0000-4000-8000-000000000011"
    cs_id = "00000000-0000-4000-8000-000000000012"
    tid = "00000000-0000-4000-8000-000000000013"
    aid = "00000000-0000-4000-8000-000000000014"

    plan = ExecutionPlan(
        schema_version=1,
        policy_version="1.0",
        revision=2,
        nodes=(
            PlanNode(
                local_id="step-build",
                kind=PlanNodeKind.AGENT,
                objective="Compile project",
                depends_on=(),
                effect_scope=EffectScope.WORKSPACE_WRITE,
            ),
        ),
    )
    persisted_plan = PersistedPlan(
        plan_id=plan_id,
        run_id=rid,
        plan=plan,
        node_ids={"step-build": node_id},
        node_states={"step-build": PlanNodeState.READY},
    )

    changeset = ChangeSet(
        schema_version=1,
        changeset_id=cs_id,
        task_id=tid,
        attempt_id=aid,
        snapshot_id="a" * 64,
        base_head="b" * 40,
        declared_scope=("src/main.py",),
        paths=(
            ChangeSetPath(
                path="src/main.py",
                effect="added",
                after=ContentImage(digest="c" * 64, size=42, artifact_ref="art-main"),
            ),
        ),
    )
    persisted_cs = PersistedChangeSet(changeset=changeset, status=ChangeSetStatus.INTEGRATED)

    snapshot = SessionSnapshot(
        session_id=sid,
        status="active",
        runs=(RunSnapshot(run_id=rid, status="running", budget_limit_usd=Decimal("15.00")),),
        tasks=(),
        attempts=(),
        assignments=(),
        budget_reservations=(),
        usage_records=(
            UsageSnapshot(
                usage_id="u1",
                task_id=None,
                amount_usd=Decimal("1.10"),
                authoritative=True,
                idempotency_key="k1",
            ),
        ),
        approvals=(),
        events=(),
        plans=(persisted_plan,),
        changesets=(persisted_cs,),
    )

    app = SkailApp(initial_snapshot=snapshot)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        # Check Plan view reconstructed from snapshot
        plan_view = app.query_one("#plan-view", PlanView)
        assert "step-build" in plan_view.plan_items
        assert plan_view.plan_items["step-build"].state == "ready"
        assert cs_id in plan_view.integrations
        assert plan_view.integrations[cs_id].status == "integrated"

        # Check Budget view reconstructed
        budget_view = app.query_one("#budget-view", BudgetView)
        assert budget_view.item.authoritative_actual_usd == Decimal("1.10")

        # Check active_mode
        assert app.projection.footer_data.active_mode == "planned"
        assert "[planned]" in app._render_status_strip()


@pytest.mark.asyncio
async def test_tui_shell_route_shadow_labels() -> None:
    proj = TuiProjection()
    proj.route_items["lead"] = RouteViewItem(
        task_id="lead",
        attempt_number=1,
        provider="fake",
        model="standard-model",
        routing_mode="auto",
        capability_floor=0.7,
        estimated_cost_usd=Decimal("0.05"),
        binding_constraint=None,
        explanation=["Primary auto candidate selected"],
        lineage=["direct"],
        evidence_status="sufficient",
        evidence_revision="rev-9",
        shadow_recommendation="economy",
        shadow_reasons=["Economy candidate is cheaper with verified completion evidence"],
    )

    app = SkailApp(projection=proj)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("ctrl+r")
        await pilot.pause()

        route_view = app.query_one("#route-view", RouteView)
        assert "lead" in route_view.routes
        item = route_view.routes["lead"]
        assert item.shadow_recommendation == "economy"
        assert "Economy candidate is cheaper" in item.shadow_reasons[0]
        assert item.evidence_status == "sufficient"

        panel_widget = route_view.query(Static).last()
        visual = panel_widget.render()
        inner = getattr(visual, "_renderable", visual)
        assert "SHADOW: economy" in str(getattr(inner, "title", inner))


@pytest.mark.asyncio
async def test_tui_shell_cancellation_preserves_state() -> None:
    app = SkailApp()
    async with app.run_test(size=(120, 40)) as pilot:
        # Submit /cancel command
        inp = app.query_one("#composer-input", Input)
        inp.value = "/cancel"
        inp.focus()
        await pilot.press("enter")
        await pilot.pause()

        # Transcript retains cancellation notice and UI is intact
        assert any(
            "Active run cancelled" in item.content
            for item in app.projection.transcript_items
        )
        assert app.query_one("#chat-transcript") is not None
        assert app.query_one("#plan-view") is not None

