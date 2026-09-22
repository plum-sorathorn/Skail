"""Phase 3 sidebar tests: slot stability, no Route jump, budget thresholds."""

from __future__ import annotations

import sys
import types


def _ensure_stubs() -> None:
    try:
        import textual  # noqa: F401
    except Exception:
        for name in (
            "textual",
            "textual.app",
            "textual.binding",
            "textual.containers",
            "textual.widgets",
            "textual.message",
        ):
            sys.modules.setdefault(name, types.ModuleType(name))
        containers = sys.modules["textual.containers"]
        if not hasattr(containers, "VerticalScroll"):
            containers.VerticalScroll = object  # type: ignore[attr-defined]
            containers.Container = object  # type: ignore[attr-defined]
            containers.Horizontal = object  # type: ignore[attr-defined]
            containers.Vertical = object  # type: ignore[attr-defined]
        widgets = sys.modules["textual.widgets"]
        for attr in (
            "Static",
            "Footer",
            "Header",
            "Input",
            "TabbedContent",
            "TabPane",
        ):
            if not hasattr(widgets, attr):
                setattr(widgets, attr, object)
        message = sys.modules["textual.message"]
        if not hasattr(message, "Message"):
            message.Message = object  # type: ignore[attr-defined]


_ensure_stubs()

from skail.tui.projection import BudgetViewItem, TuiProjection  # noqa: E402
from skail.tui.theme import (  # noqa: E402
    agent_slot_token,
    budget_token_for_ratio,
    get_theme,
    lookup,
)


def test_agent_slot_colors_stable_by_slot() -> None:
    assert agent_slot_token(1) == "agentOne"
    assert agent_slot_token(2) == "agentTwo"
    assert agent_slot_token(3) == "agentThree"
    dark = get_theme("dark")
    colors = {lookup(dark, agent_slot_token(s)) for s in (1, 2, 3)}
    assert len(colors) == 3


def test_projection_child_slots_stable() -> None:
    p = TuiProjection()
    assert p.child_slot_for("task-a") in (1, 2, 3)
    first = p.child_slot_for("task-a")
    assert p.child_slot_for("task-a") == first
    slots = {p.child_slot_for(f"task-{i}") for i in range(5)}
    assert slots <= {1, 2, 3}
    assert len(p.child_slots) <= 3


def test_projection_completed_children_stay_visible() -> None:
    p = TuiProjection()
    p.note_child("t1", "assignment one", "m1")
    p.note_child("t2", "assignment two", "m2")
    p.mark_child_status("t1", "complete")
    p.mark_child_status("t2", "failed")
    statuses = {c.task_id: c.status for c in p.children_view()}
    assert statuses["t1"] == "complete"
    assert statuses["t2"] == "failed"


def test_budget_threshold_tokens() -> None:
    assert budget_token_for_ratio(0.10) == "budgetFill"
    assert budget_token_for_ratio(0.74) == "budgetFill"
    assert budget_token_for_ratio(0.75) == "budgetWarning"
    assert budget_token_for_ratio(0.89) == "budgetWarning"
    assert budget_token_for_ratio(0.90) == "budgetCritical"
    assert budget_token_for_ratio(1.20) == "budgetCritical"


def test_budget_unavailable_copy() -> None:
    from skail.tui.projection import BUDGET_UNAVAILABLE_COPY

    assert BUDGET_UNAVAILABLE_COPY == "Budget details are unavailable for this provider."


def test_budget_meter_cells() -> None:
    from skail.tui.projection import budget_meter

    assert budget_meter(0.0) == "········"
    assert budget_meter(0.125) == "■·······"
    assert budget_meter(1.0) == "■■■■■■■■"
    assert len(budget_meter(0.18)) == 8


def test_budget_view_model_thresholds() -> None:
    from skail.tui.projection import budget_view_model

    assert budget_view_model(BudgetViewItem()).state == "normal"
    assert budget_view_model(BudgetViewItem(), used_ratio=0.80).state == "NEAR LIMIT"
    assert budget_view_model(BudgetViewItem(), used_ratio=0.95).state == "CRITICAL"
    assert budget_view_model(BudgetViewItem(), used_ratio=1.10).state == "LIMIT REACHED"
    unavailable = budget_view_model(None)
    assert unavailable.unavailable is True
    assert unavailable.copy == "Budget details are unavailable for this provider."


def test_agent_select_does_not_force_route() -> None:
    import inspect

    import skail.tui.app as app_module

    src = inspect.getsource(app_module.SkailApp.on_agent_rail_agent_selected)
    assert "focus_agent" in src
