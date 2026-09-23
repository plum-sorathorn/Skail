"""Unit and pilot interaction tests for TUI composer, slash commands, and overlays."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from typing import Any

import pytest
from fakes.provider import (
    FakeProviderAdapter,
)
from fakes.provider import (
    FakeProviderChatModel as DeterministicFakeChatModel,
)
from textual.widgets import Button, Static, TabbedContent

from skail.cli.main import RuntimeModelSet
from skail.runtime.redaction import RedactionRegistry
from skail.sessions.checkpoints import CheckpointStore
from skail.sessions.journal import Journal
from skail.sessions.service import SessionService
from skail.tui.app import SkailApp
from skail.tui.commands import command_requires_args
from skail.tui.overlays.model_picker import ModelPickerOverlay
from skail.tui.overlays.theme_picker import ThemePickerOverlay
from skail.tui.projection import TuiProjection
from skail.tui.widgets.composer import ComposerTextArea


class _MemoryCredentialStore:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get(self, provider: str, reference: str) -> str | None:
        return self.values.get((provider, reference))

    def set(self, provider: str, reference: str, value: str) -> None:
        self.values[(provider, reference)] = value

    def delete(self, provider: str, reference: str) -> None:
        self.values.pop((provider, reference), None)


class _BlockingController:
    def __init__(self) -> None:
        self.pending_interrupt = None
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls: list[str] = []

    def subscribe_events(self, callback: Any) -> None:
        _ = callback

    async def run_instruction(self, text: str, **kwargs: Any) -> Any:
        _ = kwargs
        self.calls.append(text)
        self.started.set()
        await self.release.wait()
        return SimpleNamespace(pending_interrupt=None, output=f"done: {text}")


def test_command_requires_args_helper() -> None:
    assert command_requires_args("agent") is True
    assert command_requires_args("mode") is True
    assert command_requires_args("steer") is True
    assert command_requires_args("model") is False
    assert command_requires_args("theme") is False
    assert command_requires_args("help") is False
    assert command_requires_args("quit") is False


@pytest.mark.asyncio
async def test_composer_enter_submits_regular_prompt() -> None:
    app = SkailApp()
    async with app.run_test() as pilot:
        await pilot.click("#composer-input")
        await pilot.press("h", "e", "l", "l", "o")
        await pilot.press("enter")
        area = app.query_one("#composer-input", ComposerTextArea)
        assert area.text == ""
        assert len(app.projection.transcript_items) >= 1
        assert app.projection.transcript_items[-1].content == "hello"


@pytest.mark.asyncio
async def test_active_run_shows_running_indicator_until_response_arrives() -> None:
    controller = _BlockingController()
    app = SkailApp(controller=controller)

    async with app.run_test(size=(120, 40)) as pilot:
        area = app.query_one("#composer-input", ComposerTextArea)
        area.text = "long request"
        await pilot.press("enter")
        await asyncio.wait_for(controller.started.wait(), timeout=1)
        await pilot.pause()

        indicator = app.query_one("#activity-spinner", Static)
        assert indicator.display is True
        assert "RUNNING" in str(indicator.render())

        controller.release.set()
        assert app._active_worker is not None
        await app._active_worker.wait()
        await pilot.pause()
        assert indicator.display is False


@pytest.mark.asyncio
async def test_new_prompt_is_rejected_while_an_interrupt_is_pending() -> None:
    controller = _BlockingController()
    app = SkailApp(controller=controller)
    pending = {"question_id": "question-1", "prompt": "Which file?"}
    app.projection.pending_interrupt = pending

    async with app.run_test(size=(120, 40)) as pilot:
        area = app.query_one("#composer-input", ComposerTextArea)
        area.text = "Start a different task"
        await pilot.press("enter")
        await pilot.pause()

        assert controller.calls == []
        assert area.text == "Start a different task"
        assert app.projection.pending_interrupt is pending
        assert any(item.title == "Interrupt pending" for item in app.projection.transcript_items)


def test_interrupt_projection_keeps_run_and_plan_ownership() -> None:
    class PlanJournal:
        def plans_for_run(self, run_id: str) -> tuple[object, ...]:
            assert run_id == "run-1"
            return (SimpleNamespace(plan_id="plan-1"),)

    app = SkailApp(controller=_BlockingController(), journal=PlanJournal(), session_id="session-1")

    app._set_interrupt(
        {"question_id": "question-1", "prompt": "Which output?"}, run_id="run-1"
    )

    pending = app.projection.pending_interrupt
    assert pending is not None
    assert pending.payload["session_id"] == "session-1"
    assert pending.payload["run_id"] == "run-1"
    assert pending.payload["plan_id"] == "plan-1"
    assert app._question_graph_id(pending.payload) == "session-1:run-1:lead"


@pytest.mark.asyncio
async def test_new_run_explains_that_a_cancelled_plan_is_inactive() -> None:
    class CancelledPlanJournal:
        def get_session_snapshot(self, _session_id: str) -> Any:
            return SimpleNamespace(
                runs=[SimpleNamespace(run_id="old-run", status="cancelled")]
            )

        def plans_for_run(self, run_id: str) -> tuple[object, ...]:
            return (object(),) if run_id == "old-run" else ()

    controller = _BlockingController()
    controller.release.set()
    app = SkailApp(controller=controller, journal=CancelledPlanJournal(), session_id="session")

    await app._execute_prompt("Create a new file")

    assert controller.calls == ["Create a new file"]
    notice = next(
        item for item in app.projection.transcript_items if item.title == "Starting a new run"
    )
    assert "previous run was cancelled" in notice.content
    assert "plan is inactive" in notice.content


@pytest.mark.asyncio
async def test_followups_are_visible_and_run_fifo_from_projection_queue() -> None:
    controller = _BlockingController()
    app = SkailApp(controller=controller)

    async with app.run_test(size=(120, 40)) as pilot:
        area = app.query_one("#composer-input", ComposerTextArea)
        area.text = "first"
        await pilot.press("enter")
        await asyncio.wait_for(controller.started.wait(), timeout=1)

        area.text = "second"
        await pilot.press("ctrl+enter")
        await pilot.pause()
        assert app.projection.queue == ["second"]

        area.text = "third"
        await pilot.press("enter")
        await pilot.pause()
        assert app.projection.queue == ["second", "third"]

        controller.release.set()
        for _ in range(20):
            await pilot.pause()
            if controller.calls == ["first", "second", "third"]:
                break
        assert controller.calls == ["first", "second", "third"]
        assert app.projection.queue == []


@pytest.mark.asyncio
async def test_quitting_drops_queued_followups_without_starting_a_coroutine() -> None:
    controller = _BlockingController()
    app = SkailApp(controller=controller)

    async with app.run_test(size=(120, 40)) as pilot:
        area = app.query_one("#composer-input", ComposerTextArea)
        area.text = "first"
        await pilot.press("enter")
        await asyncio.wait_for(controller.started.wait(), timeout=1)

        app.projection.queue_followup("second")
        app._run_active = True
        app.app_state = "quitting"
        app._start_next_queued_prompt()

        assert app.projection.queue == []
        assert app._run_active is False

        controller.release.set()
        if app._active_worker is not None:
            await app._active_worker.wait()


async def _start_run_with_queued_prompt(
    app: SkailApp, controller: _BlockingController, pilot: Any
) -> ComposerTextArea:
    area = app.query_one("#composer-input", ComposerTextArea)
    area.text = "first"
    await pilot.press("enter")
    await asyncio.wait_for(controller.started.wait(), timeout=1)
    area.text = "queued follow-up"
    await pilot.press("ctrl+enter")
    await pilot.pause()
    assert app.projection.queue == ["queued follow-up"]
    return area


@pytest.mark.asyncio
async def test_slash_cancel_discards_queue_without_running_it() -> None:
    controller = _BlockingController()
    app = SkailApp(controller=controller)

    async with app.run_test(size=(120, 40)) as pilot:
        area = await _start_run_with_queued_prompt(app, controller, pilot)
        area.text = "/cancel"
        await pilot.press("enter")
        await pilot.pause()
        if app._active_worker is not None:
            await asyncio.wait_for(app._active_worker.wait(), timeout=1)

        assert controller.calls == ["first"]
        assert app.projection.queue == []
        assert any(item.title == "Queue cleared" for item in app.projection.transcript_items)


@pytest.mark.asyncio
async def test_slash_quit_discards_queue_and_stops_dispatch() -> None:
    controller = _BlockingController()
    app = SkailApp(controller=controller)

    async with app.run_test(size=(120, 40)) as pilot:
        area = await _start_run_with_queued_prompt(app, controller, pilot)
        area.text = "/quit"
        await pilot.press("enter")
        await pilot.pause()

        assert app.app_state == "quitting"
        assert app.projection.queue == []
        assert controller.calls == ["first"]
        assert any(item.title == "Queue cleared" for item in app.projection.transcript_items)


@pytest.mark.asyncio
async def test_ctrl_c_discards_queue_without_starting_follow_up() -> None:
    controller = _BlockingController()
    app = SkailApp(controller=controller)

    async with app.run_test(size=(120, 40)) as pilot:
        await _start_run_with_queued_prompt(app, controller, pilot)
        await pilot.press("ctrl+c")
        await pilot.pause()

        assert app.app_state == "quitting"
        assert app.projection.queue == []
        assert controller.calls == ["first"]
        assert any(item.title == "Queue cleared" for item in app.projection.transcript_items)


@pytest.mark.asyncio
async def test_app_unmount_discards_queue_and_cancels_active_worker() -> None:
    controller = _BlockingController()
    app = SkailApp(controller=controller)

    async with app.run_test(size=(120, 40)) as pilot:
        await _start_run_with_queued_prompt(app, controller, pilot)
        app.exit(0)
        await pilot.pause()

    assert app.app_state == "quitting"
    assert app.projection.queue == []
    assert controller.calls == ["first"]
    assert any(item.title == "Queue cleared" for item in app.projection.transcript_items)


@pytest.mark.asyncio
async def test_queued_prompt_is_not_restored_in_a_new_tui_instance(tmp_path: Any) -> None:
    journal, _, service, session_id = _session_dependencies(tmp_path)
    controller = _BlockingController()
    app = SkailApp(
        controller=controller,
        session_service=service,
        session_id=session_id,
        journal=journal,
    )

    async with app.run_test(size=(120, 40)) as pilot:
        await _start_run_with_queued_prompt(app, controller, pilot)
        app.exit(0)
        await pilot.pause()

    restored = SkailApp(
        controller=_BlockingController(),
        session_service=service,
        session_id=session_id,
        journal=journal,
        initial_snapshot=journal.get_session_snapshot(session_id),
    )

    assert app.projection.queue == []
    assert restored.projection.queue == []
    assert controller.calls == ["first"]


@pytest.mark.asyncio
async def test_composer_enter_dispatches_model_slash_command() -> None:
    app = SkailApp()
    async with app.run_test() as pilot:
        await pilot.click("#composer-input")
        for ch in "/model":
            await pilot.press(ch)
        await pilot.press("enter")
        assert len(app.screen_stack) > 1
        top_screen = app.screen_stack[-1]
        assert isinstance(top_screen, ModelPickerOverlay)
        assert "fake:auto" in top_screen.models or len(top_screen.models) > 0


@pytest.mark.asyncio
async def test_model_slash_command_rejects_unknown_discovered_model() -> None:
    app = SkailApp()
    app.runtime_models = type("RuntimeModels", (), {"models": {"fake:known": object()}})()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.click("#composer-input")
        for char in "/model fake:unknown":
            await pilot.press(char)
        await pilot.press("enter")
        await pilot.pause()
        assert app.projection.model_for_future() == "auto"
        assert any(
            "Unknown or inaccessible model" in item.content
            for item in app.projection.transcript_items
        )


@pytest.mark.asyncio
async def test_composer_enter_dispatches_theme_slash_command() -> None:
    app = SkailApp()
    async with app.run_test() as pilot:
        await pilot.click("#composer-input")
        for ch in "/theme":
            await pilot.press(ch)
        await pilot.press("enter")
        assert len(app.screen_stack) > 1
        top_screen = app.screen_stack[-1]
        assert isinstance(top_screen, ThemePickerOverlay)


@pytest.mark.asyncio
async def test_model_command_with_argument_sets_future_model() -> None:
    app = SkailApp()
    async with app.run_test() as pilot:
        await pilot.click("#composer-input")
        for ch in "/model custom-gpt":
            await pilot.press(ch)
        await pilot.press("enter")
        assert app.projection.model_for_future() == "custom-gpt"


@pytest.mark.asyncio
async def test_view_slash_commands_switch_tabs() -> None:
    app = SkailApp()
    async with app.run_test() as pilot:
        tabs = app.query_one("#tabs", TabbedContent)

        await pilot.click("#composer-input")
        for ch in "/plan":
            await pilot.press(ch)
        await pilot.press("enter")
        assert tabs.active == "tab-plan"

        await pilot.click("#composer-input")
        for ch in "/budget":
            await pilot.press(ch)
        await pilot.press("enter")
        assert tabs.active == "tab-budget"

        await pilot.click("#composer-input")
        for ch in "/agents":
            await pilot.press(ch)
        await pilot.press("enter")
        assert tabs.active == "tab-agents"


@pytest.mark.asyncio
async def test_shift_tab_keybinding_cycles_panels() -> None:
    app = SkailApp()
    async with app.run_test(size=(120, 40)) as pilot:
        tabs = app.query_one("#tabs", TabbedContent)
        composer = app.query_one("#composer-input", ComposerTextArea)
        composer.focus()
        await pilot.press("shift+tab")
        assert tabs.active == "tab-plan"
        assert app.focused is composer
        await pilot.press("shift+tab")
        assert tabs.active == "tab-route"
        assert app.focused is composer


@pytest.mark.asyncio
async def test_send_button_submits_draft() -> None:
    app = SkailApp()
    async with app.run_test(size=(120, 40)) as pilot:
        area = app.query_one("#composer-input", ComposerTextArea)
        area.text = "test from button"
        btn = app.query_one("#composer-send", Button)
        btn.press()
        await pilot.pause()
        assert area.text == ""
        assert len(app.projection.transcript_items) >= 1
        assert app.projection.transcript_items[-1].content == "test from button"


def _runtime_set(model: DeterministicFakeChatModel) -> RuntimeModelSet:
    return RuntimeModelSet(
        models={"lead-model": model},
        lead_model="lead-model",
        child_model="lead-model",
        providers={"injected": FakeProviderAdapter(model)},
    )


def _session_dependencies(tmp_path: Any) -> tuple[Journal, CheckpointStore, SessionService, str]:
    journal = Journal(tmp_path / "journal.sqlite")
    journal.migrate()
    checkpoints = CheckpointStore(tmp_path / "checkpoints.sqlite")
    checkpoints.initialize()
    service = SessionService(
        journal=journal,
        checkpoints=checkpoints,
        sessions_dir=tmp_path / "sessions",
    )
    session = service.create_session(title="pilot")
    return journal, checkpoints, service, session.session_id


def test_runtime_attach_preserves_explicit_lead_model_for_prompt_controls(tmp_path: Any) -> None:
    model = DeterministicFakeChatModel(model_name="lead-model", response_text="booted")
    journal, checkpoints, service, session_id = _session_dependencies(tmp_path)
    app = SkailApp(
        runtime_factory=None,
        bootstrap={"workspace": str(tmp_path), "session_id": session_id},
        session_service=service,
        session_id=session_id,
        journal=journal,
        checkpoints=checkpoints,
        redaction=RedactionRegistry(),
    )
    app._enabled_models = {"lead-model"}

    app._attach_runtime_models(_runtime_set(model))

    assert app.projection.model_for_future() == "lead-model"
    assert app.projection.footer_data.lead_model == "lead-model"


@pytest.mark.asyncio
async def test_composer_submission_during_initialization_is_replayed(tmp_path: Any) -> None:
    started = threading.Event()
    release = threading.Event()
    model = DeterministicFakeChatModel(model_name="lead-model", response_text="booted")
    journal, checkpoints, service, session_id = _session_dependencies(tmp_path)

    def factory() -> RuntimeModelSet:
        started.set()
        assert release.wait(3)
        return _runtime_set(model)

    app = SkailApp(
        runtime_factory=factory,
        bootstrap={
            "workspace": str(tmp_path),
            "session_id": session_id,
        },
        session_service=service,
        session_id=session_id,
        journal=journal,
        checkpoints=checkpoints,
        redaction=RedactionRegistry(),
    )
    app._enabled_models = {"lead-model"}
    app.app_state = "initializing"
    async with app.run_test(size=(120, 40)) as pilot:
        assert started.wait(1)
        await pilot.click("#composer-input")
        for char in "run after boot":
            await pilot.press(char)
        await pilot.press("enter")
        await pilot.pause()
        area = app.query_one("#composer-input", ComposerTextArea)
        assert area.text == "run after boot"

        release.set()
        for _ in range(10):
            await pilot.pause()
        if app._active_worker is not None:
            await app._active_worker.wait()
        assert any(item.content == "booted" for item in app.projection.transcript_items)
        titles = {item.title for item in app.projection.transcript_items}
        assert "Starting" not in titles
        assert "Receipt" not in titles


@pytest.mark.asyncio
async def test_discovered_catalog_without_auto_candidate_opens_model_picker(
    tmp_path: Any,
) -> None:
    model = DeterministicFakeChatModel(model_name="lead-model", response_text="booted")
    journal, checkpoints, service, session_id = _session_dependencies(tmp_path)
    runtime = _runtime_set(model)
    object.__setattr__(runtime, "selection_required", True)

    app = SkailApp(
        runtime_factory=lambda: runtime,
        bootstrap={
            "workspace": str(tmp_path),
            "session_id": session_id,
        },
        session_service=service,
        session_id=session_id,
        journal=journal,
        checkpoints=checkpoints,
        redaction=RedactionRegistry(),
    )
    app.app_state = "initializing"
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert app.app_state == "selection_required"
        assert isinstance(app.screen_stack[-1], ModelPickerOverlay)
        assert "lead-model" in app.screen_stack[-1].models


@pytest.mark.asyncio
async def test_first_runtime_catalog_opens_unticked_model_picker(tmp_path: Any) -> None:
    model = DeterministicFakeChatModel(model_name="lead-model", response_text="booted")
    journal, checkpoints, service, session_id = _session_dependencies(tmp_path)
    runtime = _runtime_set(model)

    app = SkailApp(
        runtime_factory=lambda: runtime,
        bootstrap={
            "workspace": str(tmp_path),
            "session_id": session_id,
        },
        session_service=service,
        session_id=session_id,
        journal=journal,
        checkpoints=checkpoints,
        redaction=RedactionRegistry(),
    )
    app.app_state = "initializing"
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert app.app_state == "selection_required"
        picker = app.screen_stack[-1]
        assert isinstance(picker, ModelPickerOverlay)
        assert picker.enabled == set()


@pytest.mark.asyncio
async def test_composer_enter_and_send_button_drive_real_controller(tmp_path: Any) -> None:
    from skail.domain.ids import SessionId
    from skail.runtime.run_controller import RunController

    journal, checkpoints, service, session_id = _session_dependencies(tmp_path)
    model = DeterministicFakeChatModel(model_name="lead-model", response_text="controller reply")
    controller = RunController(
        session_id=SessionId(session_id),
        workspace=tmp_path,
        journal=journal,
        checkpoints=checkpoints,
        models={"lead-model": model},
        default_lead_model="lead-model",
        default_child_model="lead-model",
    )
    app = SkailApp(
        controller=controller,
        session_service=service,
        session_id=SessionId(session_id),
    )
    async with app.run_test(size=(180, 40)) as pilot:
        await pilot.click("#composer-input")
        for char in "enter path":
            await pilot.press(char)
        await pilot.press("enter")
        if app._active_worker is not None:
            await app._active_worker.wait()
        await pilot.pause()

        area = app.query_one("#composer-input", ComposerTextArea)
        area.text = "button path"
        app.query_one("#composer-send", Button).press()
        if app._active_worker is not None:
            await app._active_worker.wait()
        for _ in range(10):
            await pilot.pause()
            if sum(
                item.content == "controller reply"
                for item in app.projection.transcript_items
            ) == 2:
                break

        user_prompts = [
            item.content
            for item in app.projection.transcript_items
            if item.role == "user"
        ]
        assert user_prompts == ["enter path", "button path"]
        assert (
            sum(item.content == "controller reply" for item in app.projection.transcript_items)
            == 2
        )


@pytest.mark.asyncio
async def test_model_picker_checked_marker_is_visible_after_render() -> None:
    app = SkailApp(projection=TuiProjection())
    async with app.run_test(size=(100, 30)) as pilot:
        overlay = ModelPickerOverlay(
            ["model-a"], current="model-a", enabled={"model-a"}
        )
        app.push_screen(overlay)
        await pilot.pause()
        rendered = app.query_one("#model-list", Static).render()
        renderable = getattr(rendered, "renderable", getattr(rendered, "_renderable", rendered))
        assert "[x] model-a" in str(renderable)


@pytest.mark.asyncio
async def test_model_picker_filters_a_full_catalog_and_restores_composer_focus() -> None:
    app = SkailApp(projection=TuiProjection())
    async with app.run_test(size=(120, 40)) as pilot:
        overlay = ModelPickerOverlay(
            [f"llmgateway:model-{index:03d}" for index in range(300)],
            current="llmgateway:model-000",
        )
        app.open_overlay("model_picker")
        app.push_screen(overlay)
        await pilot.pause()
        assert len(overlay.models) == 300
        assert len(list(overlay.query(".model-row"))) <= 40

        await pilot.click("#model-search")
        for char in "model-299":
            await pilot.press(char)
        await pilot.pause()
        assert len(list(overlay.query(".model-row"))) == 1

        await pilot.press("escape")
        assert getattr(app.focused, "id", None) == "composer-input"


@pytest.mark.asyncio
async def test_model_picker_keeps_filter_focus_and_printable_keys_edit_query() -> None:
    app = SkailApp(projection=TuiProjection())
    async with app.run_test(size=(120, 40)) as pilot:
        overlay = ModelPickerOverlay(["model-a", "model-b", "a model"], current="model-a")
        app.push_screen(overlay)
        await pilot.pause()
        assert getattr(app.focused, "id", None) == "model-search"

        await pilot.press("a", "j", "k", "space")
        assert overlay.filter_text == "ajk "
        assert overlay.index == 0
        assert getattr(app.focused, "id", None) == "model-search"


@pytest.mark.asyncio
async def test_model_picker_chords_navigate_toggle_and_select_without_scrollbars() -> None:
    app = SkailApp(projection=TuiProjection())
    async with app.run_test(size=(60, 12)) as pilot:
        overlay = ModelPickerOverlay([f"model-{i}" for i in range(20)], current="model-0")
        app.open_overlay("model_picker")
        app.push_screen(overlay)
        await pilot.pause()
        await pilot.press("down", "down")
        assert overlay.index == 2
        assert getattr(app.focused, "id", None) == "model-search"
        from textual.events import Key

        await overlay.on_key(Key("ctrl+space", None))
        await pilot.pause()
        assert overlay.enabled == {"model-2"}
        await overlay.on_key(Key("ctrl+space", None))
        assert overlay.enabled == set()
        await overlay.on_key(Key("ctrl+shift+a", None))
        await pilot.pause()
        assert len(overlay.enabled) == 20
        assert not overlay.query("VerticalScroll")
        assert not overlay.query("ScrollBar")
        await overlay.on_key(Key("escape", None))
        await pilot.pause()
        assert getattr(app.focused, "id", None) == "composer-input"


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(120, 40), (99, 30), (60, 12)])
async def test_model_picker_has_no_scroll_widgets_at_supported_viewports(
    size: tuple[int, int],
) -> None:
    app = SkailApp(projection=TuiProjection())
    async with app.run_test(size=size) as pilot:
        overlay = ModelPickerOverlay([f"model-{i}" for i in range(100)])
        app.push_screen(overlay)
        await pilot.pause()
        assert getattr(app.focused, "id", None) == "model-search"
        assert not overlay.query("VerticalScroll")
        assert not overlay.query("ScrollBar")


@pytest.mark.asyncio
async def test_passive_panels_do_not_take_focus_or_switch_tabs() -> None:
    app = SkailApp(projection=TuiProjection())
    async with app.run_test(size=(120, 40)) as pilot:
        composer = app.query_one("#composer-input", ComposerTextArea)
        composer.focus()
        active = app.query_one("#tabs", TabbedContent).active
        await pilot.click("#chat-transcript")
        await pilot.click("#tabs")
        await pilot.pause()
        assert app.focused is composer
        assert app.query_one("#tabs", TabbedContent).active == active


@pytest.mark.asyncio
async def test_shift_tab_cycles_panels_without_leaving_composer() -> None:
    app = SkailApp(projection=TuiProjection())
    async with app.run_test(size=(120, 40)) as pilot:
        composer = app.query_one("#composer-input", ComposerTextArea)
        composer.focus()
        tabs = app.query_one("#tabs", TabbedContent)
        expected = ["tab-plan", "tab-route", "tab-budget", "tab-agents", "tab-plan"]
        for target in expected:
            await pilot.press("shift+tab")
            await pilot.pause()
            assert tabs.active == target
            assert app.focused is composer


@pytest.mark.asyncio
async def test_model_picker_up_down_arrow_navigation() -> None:
    overlay = ModelPickerOverlay(["model-a", "model-b", "model-c"], current="model-a")
    assert overlay.index == 0
    overlay.move(1)
    assert overlay.index == 1
    overlay.move(1)
    assert overlay.index == 2
    overlay.move(-1)
    assert overlay.index == 1


def test_model_picker_tick_space_and_toggle_all() -> None:
    overlay = ModelPickerOverlay(["model-a", "model-b", "model-c"], current="model-a")
    assert overlay.enabled == set()
    assert "[ ] model-a" in overlay.rows()[0]

    # Space ticks highlighted model-a
    overlay.toggle_tick()
    assert "model-a" in overlay.enabled
    assert "[x] model-a" in overlay.rows()[0]

    # Space unticks highlighted model-a
    overlay.toggle_tick()
    assert "model-a" not in overlay.enabled
    assert "[ ] model-a" in overlay.rows()[0]

    # Toggle-all selects the full filtered set.
    overlay.toggle_all()
    assert overlay.enabled == {"model-a", "model-b", "model-c"}
    assert "[x] model-a" in overlay.rows()[0]

    # A second toggle clears it.
    overlay.toggle_all()
    assert overlay.enabled == set()
    assert "[ ] model-a" in overlay.rows()[0]


def test_model_picker_requires_the_selected_lead_to_be_enabled() -> None:
    overlay = ModelPickerOverlay(["model-a", "model-b"], current="model-a")

    assert overlay.commit() is None
    assert overlay.selection_error == "Tick at least the highlighted model before selecting it."

    overlay.toggle_tick()
    assert overlay.commit() == "model-a"


def test_model_picker_commit_with_enabled_models(tmp_path) -> None:
    import tomllib

    from skail.config.persistence import save_user_provider_models

    target_cfg = tmp_path / "config.toml"
    save_user_provider_models("openai", ["gpt-4o", "gpt-4o-mini"], config_path=target_cfg)

    with target_cfg.open("rb") as f:
        data = tomllib.load(f)
    assert data["providers"]["openai"]["models"] == ["gpt-4o", "gpt-4o-mini"]
    assert data["providers"]["openai"]["type"] == "openai-compatible"

    # Verify commit sends enabled models to app
    calls: dict[str, Any] = {}

    class _MockApp:
        def set_future_model(self, name: str) -> None:
            calls["future"] = name

        def set_enabled_models(self, models: list[str]) -> None:
            calls["enabled"] = set(models)

        def close_overlay(self, name: str) -> None:
            calls["closed"] = name

    overlay = ModelPickerOverlay(
        ["m1", "m2", "m3"], current="m1", enabled={"m1", "m2", "m3"}
    )
    overlay._test_app = _MockApp()
    overlay.index = 1
    overlay.toggle_tick()  # untick m2
    overlay.index = 2
    committed = overlay.commit()
    assert committed == "m3"
    assert calls["future"] == "m3"
    assert calls["enabled"] == {"m1", "m3"}
    assert calls["closed"] == "model_picker"


def test_llmgateway_model_persistence_keeps_canonical_base_url(tmp_path) -> None:
    import tomllib

    from skail.config.persistence import save_user_provider_models

    target_cfg = tmp_path / "config.toml"
    save_user_provider_models("llmgateway", ["llmgateway:model-a"], config_path=target_cfg)

    with target_cfg.open("rb") as handle:
        data = tomllib.load(handle)

    assert data["providers"]["llmgateway"]["base_url"] == "https://api.llmgateway.io/v1"


def test_routing_model_persistence_keeps_other_user_config(tmp_path) -> None:
    import tomllib

    from skail.config.persistence import save_user_routing_model

    target_cfg = tmp_path / "config.toml"
    target_cfg.write_text(
        "[providers.llmgateway]\n"
        'type = "openai-compatible"\n'
        'models = ["old-model"]\n'
        "\n[routing]\n"
        'mode = "auto"\n',
        encoding="utf-8",
    )

    save_user_routing_model("llmgateway:new-model", config_path=target_cfg)

    with target_cfg.open("rb") as handle:
        data = tomllib.load(handle)
    assert data["routing"]["lead_model"] == "llmgateway:new-model"
    assert data["providers"]["llmgateway"]["models"] == ["old-model"]



@pytest.mark.asyncio
async def test_onboarding_interactive_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("LLMGATEWAY_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    app = SkailApp(
        runtime_factory=lambda: None,
        bootstrap={"credential_store": _MemoryCredentialStore()},
    )
    async with app.run_test(size=(120, 40)) as pilot:
        assert app.onboarding_state.step == "welcome"
        assert not app.query_one("#prompt-composer").visible
        assert app.projection.transcript_items == []

        # Advance to provider
        await pilot.press("enter")
        assert app.onboarding_state.step == "provider"

        # Down arrow cycles provider options
        await pilot.press("down")
        assert app.onboarding_state.provider == "openai"
        await pilot.press("down")
        assert app.onboarding_state.provider == "anthropic"
        await pilot.press("down")
        assert app.onboarding_state.provider == "llmgateway"

        app.onboarding_credentials.set_key("long-enough-test-key")
        app.validate_onboarding_key()
        await pilot.pause()
        assert app.onboarding_state.step == "trust"

        # T advances to theme
        await pilot.press("t")
        assert app.onboarding_state.step == "theme"

        # Enter advances to ready
        await pilot.press("enter")
        assert app.onboarding_state.step == "ready"

        # Enter completes onboarding and enters cockpit
        await pilot.press("enter")
        await pilot.pause()
        assert len(app.query("OnboardingPanel")) == 0
        assert app.query_one("#prompt-composer").visible
