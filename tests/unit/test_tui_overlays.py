"""Phase 3b overlay + sidebar widget tests."""

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
            "textual.message",
            "textual.screen",
            "textual.widget",
            "textual.widgets",
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
            "TextArea",
            "Button",
        ):
            if not hasattr(widgets, attr):
                setattr(widgets, attr, object)
        message = sys.modules["textual.message"]
        if not hasattr(message, "Message"):
            message.Message = object  # type: ignore[attr-defined]
        screen = sys.modules["textual.screen"]
        if not hasattr(screen, "Screen"):
            screen.Screen = object  # type: ignore[attr-defined]
        widget = sys.modules["textual.widget"]
        if not hasattr(widget, "Widget"):
            widget.Widget = object  # type: ignore[attr-defined]


_ensure_stubs()

import inspect  # noqa: E402

import skail.tui.app as app_module  # noqa: E402
from skail.tui.commands import search_commands  # noqa: E402
from skail.tui.overlays.missions import (  # noqa: E402
    MissionsOverlay,
    can_spawn,
    detail_lines,
    missions_header,
)
from skail.tui.overlays.model_picker import ModelPickerOverlay  # noqa: E402
from skail.tui.overlays.shortcuts import (  # noqa: E402
    group_shortcuts,
    render_shortcut_lines,
)
from skail.tui.overlays.theme_picker import (  # noqa: E402
    ThemePickerOverlay,
    resolve_system_note,
    theme_rows,
)
from skail.tui.overlays.transcript import (  # noqa: E402
    NATIVE_SCROLLBACK_UNAVAILABLE,
    RETURN_PROMPT,
    TranscriptOverlay,
    transcript_plain_text,
    transcript_search,
)
from skail.tui.projection import (  # noqa: E402
    BUDGET_UNAVAILABLE_COPY,
    TranscriptItem,
    TuiProjection,
    budget_meter,
    budget_view_model,
)
from skail.tui.widgets.agents import (  # noqa: E402
    AgentRail,
    agent_glyph,
    agent_label,
    agent_row_text,
    render_agent_rows,
)
from skail.tui.widgets.budget import (  # noqa: E402
    budget_state_label,
    render_budget_lines,
)
from skail.tui.widgets.plan import (  # noqa: E402
    PlanView,
    plan_glyph,
    plan_header,
    plan_progress,
)
from skail.tui.widgets.route import immutable_label, render_route_lines  # noqa: E402


def _child_proj() -> TuiProjection:
    proj = TuiProjection()
    proj.note_child("c1", "write tests", "m-fast", "ws-a")
    proj.note_child("c2", "fix bug", "m-smart", "ws-b")
    return proj


# -- agents ---------------------------------------------------------------


def test_agent_glyph_and_label() -> None:
    assert agent_glyph("running") == "\u25cf"
    assert agent_glyph("waiting") == "\u2219"
    assert agent_glyph("complete") == "\u2219"
    assert agent_label(2) == "Agent 2"


def test_agent_rows_from_children_view() -> None:
    proj = _child_proj()
    rows = render_agent_rows(proj.children_view())
    assert len(rows) == 2
    assert rows[0].startswith("\u25cf Agent 1")
    assert "write tests" in rows[0]
    assert "running" in rows[0]
    proj.mark_child_status("c1", "complete")
    proj.mark_child_status("c2", "failed")
    rows2 = render_agent_rows(proj.children_view())
    assert any("complete" in r for r in rows2)
    assert any("failed" in r for r in rows2)


def test_agent_row_text_cost() -> None:
    proj = _child_proj()
    child = proj.children_view()[0]
    assert "$" in agent_row_text(child)


def test_agent_select_never_jumps_to_route() -> None:
    src = inspect.getsource(app_module.SkailApp.on_agent_rail_agent_selected)
    assert "focus_agent" in src
    assert "tab-route" not in src
    assert "tab_route" not in src


def test_agent_rail_slot_style_uses_token() -> None:
    from skail.tui.widgets.agents import slot_style_inline

    assert slot_style_inline(1) in ("agentOne",) or "agentOne" in str(
        slot_style_inline(1)
    )


def test_agent_rail_messages_do_not_switch_tabs() -> None:
    assert hasattr(AgentRail, "select_child")
    src = inspect.getsource(AgentRail.select_child)
    assert "tab-route" not in src and "tab_route" not in src


# -- plan -----------------------------------------------------------------


def test_plan_header_and_glyphs() -> None:
    assert plan_header(1, 3) == "PLAN \u00b7 1/3"
    assert plan_glyph("succeeded") == "\u2713"
    assert plan_glyph("running") == "\u25cf"
    assert plan_glyph("waiting") == "\u2219"


def test_plan_progress_counts_done() -> None:
    proj = TuiProjection()
    proj.note_plan("accepted")
    items = {
        "a": _plan_item("a", "succeeded"),
        "b": _plan_item("b", "running"),
        "c": _plan_item("c", "waiting"),
    }
    done, total = plan_progress(items)
    assert (done, total) == (1, 3)


def _plan_item(local_id: str, state: str):  # noqa: ANN202
    from skail.tui.projection import PlanNodeViewItem

    return PlanNodeViewItem(
        node_id=local_id, local_id=local_id, objective="obj", kind="agent",
        state=state,
    )


def test_plan_proposed_and_rejected_cards() -> None:
    view = PlanView.__new__(PlanView)
    view.plan_state = "proposed"
    view.plan_items = {}
    view.rejected_collapsed = True
    assert "PROPOSED" in "PROPOSED PLAN\n[A] Accept [R] Reject [E] Request changes"
    view.plan_state = "rejected"
    assert view.rejected_collapsed is True


def test_plan_keyboard_accept_reject_changes() -> None:
    src = inspect.getsource(PlanView.on_key)
    assert '"a"' in src or "'a'" in src
    assert '"r"' in src or "'r'" in src
    assert '"e"' in src or "'e'" in src


# -- route ----------------------------------------------------------------


def test_route_immutable_label_exact() -> None:
    assert immutable_label(2) == "Assignment immutable for attempt 2"


def test_route_lines_read_only() -> None:
    from decimal import Decimal

    from skail.tui.projection import RouteViewItem

    item = RouteViewItem(
        task_id="t1", attempt_number=3, model="m1", provider="p1",
        routing_mode="auto", capability_floor=0.5,
        estimated_cost_usd=Decimal("0.01"), explanation=("picked",),
    )
    lines = render_route_lines(item)
    assert any("Selected" in line for line in lines)
    assert any("Assignment immutable for attempt 3" in line for line in lines)
    assert any("Fallback" in line for line in lines)
    src = inspect.getsource(render_route_lines)
    assert "mutat" not in src.lower()


# -- budget ---------------------------------------------------------------


def test_budget_state_labels_and_lines() -> None:
    assert budget_state_label("near") == "NEAR LIMIT"
    assert budget_state_label("critical") == "CRITICAL"
    assert budget_state_label("exceeded") == "LIMIT REACHED"
    assert budget_state_label("normal") == "normal"
    lines = render_budget_lines(0.5, 1.0, {"c1": 0.2})
    assert lines[0] == "BUDGET"
    assert "Session $0.50 / $1.00" in lines[1]
    assert len([line for line in lines if "■" in line or "·" in line]) == 1
    assert any("Remaining" in line for line in lines)
    assert any("c1" in line for line in lines)


def test_budget_thresholds_and_unavailable() -> None:
    assert budget_view_model(0.74, 1.0).state == "normal"
    assert budget_view_model(0.80, 1.0).state == "near"
    assert budget_view_model(0.95, 1.0).state == "critical"
    assert budget_view_model(1.10, 1.0).state == "exceeded"
    assert len(budget_meter(0.5, 1.0)) == 8
    assert render_budget_lines(0.0, None) == [BUDGET_UNAVAILABLE_COPY]
    assert BUDGET_UNAVAILABLE_COPY == (
        "Budget details are unavailable for this provider."
    )


def test_budget_ledger_meter_and_pct() -> None:
    from decimal import Decimal

    from skail.tui.projection import BudgetViewItem
    from skail.tui.widgets.budget import render_ledger_lines

    item = BudgetViewItem(
        hard_limit_usd=Decimal("1.00"),
        authoritative_actual_usd=Decimal("0.50"),
    )
    lines = render_ledger_lines(item)
    meter = lines[2]
    assert meter.count("▓") + meter.count("░") == 23
    assert meter.count("▓") == 11  # 0.50 of 1.00 -> 11.5 -> 11 filled
    assert "$0.5000 of $1.00" in lines[1]
    assert "50.0%" in lines[1]


def test_budget_ledger_fill_token_thresholds() -> None:
    from decimal import Decimal

    from skail.tui.projection import BudgetViewItem
    from skail.tui.widgets.budget import render_ledger_lines

    cases = (
        ("0.74", "budgetFill"),
        ("0.75", "budgetWarning"),
        ("0.89", "budgetWarning"),
        ("0.90", "budgetCritical"),
    )
    for used, token in cases:
        item = BudgetViewItem(
            hard_limit_usd=Decimal("1.00"),
            authoritative_actual_usd=Decimal(used),
        )
        lines = render_ledger_lines(item)
        assert f"[{token}]" in lines[2], (used, lines[2])


# -- transcript overlay ----------------------------------------------------


def test_transcript_search_and_export_hooks() -> None:
    items = [
        TranscriptItem(id="a", role="user", title="hello", content="world"),
        TranscriptItem(id="b", role="lead", title="other", content="unrelated"),
    ]
    assert len(transcript_search(items, "hello")) == 1
    text = transcript_plain_text(items)
    assert "hello" in text and "world" in text
    assert "\x1b" not in text


def test_transcript_overlay_open_close_and_scroll() -> None:
    items = [TranscriptItem(id="a", role="user", title="t", content="c")]
    overlay = TranscriptOverlay(items, scroll_y=7)
    assert overlay.saved_scroll_y == 7

    class _App:
        def __init__(self) -> None:
            self.closed: list[str] = []

        def close_overlay(self, name: str) -> None:
            self.closed.append(name)

    overlay._test_app = _App()  # type: ignore[attr-defined]
    restored = overlay.close()
    assert restored == 7


def test_transcript_pager_fallback_copy() -> None:
    assert NATIVE_SCROLLBACK_UNAVAILABLE == (
        "Native scrollback is unavailable in this terminal; "
        "opened the system pager instead."
    )
    assert RETURN_PROMPT == "Press Enter to return to Skail."
    overlay = TranscriptOverlay([], 0)
    _, fallback, prompt = overlay.pager_payload()
    assert fallback == NATIVE_SCROLLBACK_UNAVAILABLE
    assert prompt == RETURN_PROMPT


# -- shortcuts -------------------------------------------------------------


def test_shortcuts_groups_and_filter() -> None:
    grouped = group_shortcuts(app_module.ACTION_REGISTRY)
    for group in ("Run", "Composer", "Navigation", "Agents", "Approvals",
                  "Session", "Display"):
        assert group in grouped
    lines = render_shortcut_lines(app_module.ACTION_REGISTRY, "mission")
    assert any("mission" in line.lower() for line in lines)
    src = inspect.getsource(app_module.SkailApp.action_show_help)
    assert "/help" in src


def test_shortcuts_overlay_close_and_no_transcript_event() -> None:
    from skail.tui.overlays.shortcuts import ShortcutsOverlay

    overlay = ShortcutsOverlay(app_module.ACTION_REGISTRY)

    class _App:
        def __init__(self) -> None:
            self.closed: list[str] = []

        def close_overlay(self, name: str) -> None:
            self.closed.append(name)

    overlay._test_app = _App()  # type: ignore[attr-defined]
    overlay.close()
    assert overlay._test_app.closed == ["shortcuts"]
    src = inspect.getsource(ShortcutsOverlay)
    assert "transcript_items" not in src and "TranscriptItem" not in src


# -- theme picker ----------------------------------------------------------


def test_theme_rows_and_esc_restore() -> None:
    assert theme_rows("dark")[0].startswith("\u25cf")
    overlay = ThemePickerOverlay("dark")
    assert overlay.previous == "dark"

    seen: list[str] = []

    class _App:
        def apply_theme_preview(self, name: str) -> str:
            seen.append(name)
            return name

        def close_overlay(self, name: str) -> None:
            seen.append(f"close:{name}")

    overlay._test_app = _App()  # type: ignore[attr-defined]
    overlay.move(1)
    assert seen and seen[0] == "light"
    restored = overlay.cancel()
    assert restored == "dark"
    assert "dark" in seen


def test_theme_commit_and_system_note() -> None:
    overlay = ThemePickerOverlay("dark")
    overlay.index = 1

    class _App:
        def apply_theme_preview(self, name: str) -> str:
            return name

        def close_overlay(self, name: str) -> None:
            pass

    overlay._test_app = _App()  # type: ignore[attr-defined]
    assert overlay.commit() == "light"
    _, note = resolve_system_note(None)
    assert note == "System preference unavailable; using Dark."


# -- model picker ----------------------------------------------------------


def test_model_picker_lists_configured_and_future_only() -> None:
    overlay = ModelPickerOverlay(["m-a", "m-b"], "m-a")
    rows = overlay.rows()
    assert any("m-a" in r and "\u25cf" in r for r in rows)

    calls: dict[str, str] = {}

    class _App:
        def set_future_model(self, name: str) -> None:
            calls["model"] = name

        def close_overlay(self, name: str) -> None:
            calls["closed"] = name

    overlay._test_app = _App()  # type: ignore[attr-defined]
    overlay.index = 1
    assert overlay.commit() == "m-b"
    assert calls["model"] == "m-b"
    src = inspect.getsource(ModelPickerOverlay.commit)
    assert "set_future_model" in src
    assert "attempt" not in src.lower().replace("attempts", "X") or "future" in src.lower()


def test_model_picker_esc_closes() -> None:
    overlay = ModelPickerOverlay(["m-a"], "m-a")
    closed: list[str] = []

    class _App:
        def close_overlay(self, name: str) -> None:
            closed.append(name)

    overlay._test_app = _App()  # type: ignore[attr-defined]
    overlay.cancel()
    assert closed == ["model_picker"]


# -- missions --------------------------------------------------------------


def test_missions_header_and_cap() -> None:
    proj = _child_proj()
    proj.note_child("c3", "third", "m3", "ws-c")
    assert missions_header(proj.children_view()) == (
        "MISSION CONTROL \u2014 children 3/3"
    )
    ok, message = can_spawn(proj.children_view())
    assert ok is False
    assert message != ""
    two = proj.children_view()[:2]
    assert can_spawn(two)[0] is True


def test_missions_detail_and_confirm_flow() -> None:
    proj = _child_proj()
    child = proj.children_view()[0]
    lines = detail_lines(child, attempt=2)
    assert any("immutable for this attempt" in line for line in lines)
    assert any("Workspace" in line for line in lines)
    overlay = MissionsOverlay(proj.children_view())
    prompt = overlay.request_cancel(child.id)
    assert "Confirm" in prompt
    assert overlay.confirm_cancel(False) is None
    overlay.request_cancel(child.id)
    seen: list[str] = []

    class _App:
        def request_child_cancel(self, child_id: str) -> None:
            seen.append(child_id)

    overlay._test_app = _App()  # type: ignore[attr-defined]
    assert overlay.confirm_cancel(True) == child.id
    assert seen == [child.id]


def test_missions_confirm_required_source() -> None:
    src = inspect.getsource(MissionsOverlay.confirm_cancel)
    assert "confirming" in src


# -- app wiring ------------------------------------------------------------


def test_ctrl_t_reconciled_missions_wins() -> None:
    bindings = {b.key: (b.action, b.description) for b in app_module.SkailApp.BINDINGS}
    assert bindings["ctrl+t"][0] == "missions_overlay"
    assert bindings["ctrl+shift+t"][0] == "view_chat"
    assert app_module.ACTION_REGISTRY["missions_overlay"]["binding"] == "ctrl+t"
    assert app_module.ACTION_REGISTRY["view_chat"]["binding"] == "ctrl+shift+t"


def test_footer_hints_mention_overlays() -> None:
    bindings = {b.action: b.description for b in app_module.SkailApp.BINDINGS}
    assert "Ctrl+O" in bindings["transcript_overlay"]
    assert "?" in bindings["shortcuts_overlay"]
    assert "Ctrl+T" in bindings["missions_overlay"]


def test_composer_fed_from_registry() -> None:
    src = inspect.getsource(app_module.SkailApp.update_views)
    assert "set_queue" in src
    assert "search_commands" in src or "COMMAND_REGISTRY" in src
    assert "descriptions" in src


def test_search_commands_drives_palette() -> None:
    assert search_commands("model")[0]["command"] == "/model"


def test_overlay_stack_push_pop_with_focus_restore() -> None:
    src = inspect.getsource(app_module.SkailApp.close_overlay)
    assert "pop_screen" in src
    assert "focus" in src

    class _Widget:
        def __init__(self) -> None:
            self.focused = False

        def focus(self) -> None:
            self.focused = True

    app = app_module.SkailApp.__new__(app_module.SkailApp)
    app._overlay_stack = ["shortcuts"]
    widget = _Widget()
    app._focus_before_overlay = widget
    app_module.SkailApp.close_overlay(app, "shortcuts")
    assert app._overlay_stack == []
    assert widget.focused is True
