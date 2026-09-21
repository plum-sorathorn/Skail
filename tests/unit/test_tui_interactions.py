"""Unit and pilot interaction tests for TUI composer, slash commands, and overlays."""

from __future__ import annotations

import threading
from typing import Any

import pytest
from textual.widgets import Button, Static, TabbedContent

from skail.cli.main import RuntimeModelSet
from skail.providers.fake import DeterministicFakeChatModel, FakeProviderAdapter
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
    app = SkailApp(bootstrap={"fake_provider": True})
    async with app.run_test() as pilot:
        await pilot.click("#composer-input")
        await pilot.press("h", "e", "l", "l", "o")
        await pilot.press("enter")
        area = app.query_one("#composer-input", ComposerTextArea)
        assert area.text == ""
        assert len(app.projection.transcript_items) >= 1
        assert app.projection.transcript_items[-1].content == "hello"


@pytest.mark.asyncio
async def test_composer_enter_dispatches_model_slash_command() -> None:
    app = SkailApp(bootstrap={"fake_provider": True})
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
    app = SkailApp(bootstrap={"fake_provider": True})
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
    app = SkailApp(bootstrap={"fake_provider": True})
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
    app = SkailApp(bootstrap={"fake_provider": True})
    async with app.run_test() as pilot:
        await pilot.click("#composer-input")
        for ch in "/model custom-gpt":
            await pilot.press(ch)
        await pilot.press("enter")
        assert app.projection.model_for_future() == "custom-gpt"


@pytest.mark.asyncio
async def test_view_slash_commands_switch_tabs() -> None:
    app = SkailApp(bootstrap={"fake_provider": True})
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
    app = SkailApp(bootstrap={"fake_provider": True})
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
    app = SkailApp(bootstrap={"fake_provider": True})
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
        providers={"fake": FakeProviderAdapter(model)},
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
            "fake_provider": True,
            "workspace": str(tmp_path),
            "session_id": session_id,
        },
        session_service=service,
        session_id=session_id,
        journal=journal,
        checkpoints=checkpoints,
        redaction=RedactionRegistry(),
    )
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
            "fake_provider": True,
            "workspace": str(tmp_path),
            "session_id": session_id,
        },
        session_service=service,
        session_id=session_id,
        journal=journal,
        checkpoints=checkpoints,
        redaction=RedactionRegistry(),
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert app.app_state == "selection_required"
        assert isinstance(app.screen_stack[-1], ModelPickerOverlay)
        assert "lead-model" in app.screen_stack[-1].models


@pytest.mark.asyncio
async def test_composer_enter_and_send_button_drive_real_controller(tmp_path: Any) -> None:
    from skail.domain.ids import SessionId
    from skail.providers.fake import DeterministicFakeChatModel
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
        overlay = ModelPickerOverlay(["model-a"], current="model-a")
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
        assert "model-2" not in overlay.enabled
        await overlay.on_key(Key("ctrl+space", None))
        assert len(overlay.enabled) == 20
        await overlay.on_key(Key("ctrl+shift+a", None))
        await pilot.pause()
        assert len(overlay.enabled) == 0
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
    assert overlay.enabled == {"model-a", "model-b", "model-c"}
    assert "[x] model-a" in overlay.rows()[0]

    # Space unticks highlighted model-a
    overlay.toggle_tick()
    assert "model-a" not in overlay.enabled
    assert "[ ] model-a" in overlay.rows()[0]

    # Space re-ticks highlighted model-a
    overlay.toggle_tick()
    assert "model-a" in overlay.enabled
    assert "[x] model-a" in overlay.rows()[0]

    # 'a' toggles all off
    overlay.toggle_all()
    assert len(overlay.enabled) == 0
    assert "[ ] model-a" in overlay.rows()[0]

    # 'a' toggles all back on
    overlay.toggle_all()
    assert overlay.enabled == {"model-a", "model-b", "model-c"}
    assert "[x] model-a" in overlay.rows()[0]


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

    overlay = ModelPickerOverlay(["m1", "m2", "m3"], current="m1")
    overlay._test_app = _MockApp()
    overlay.index = 1
    overlay.toggle_tick()  # untick m2
    committed = overlay.commit()
    assert committed == "m2"
    assert calls["future"] == "m2"
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
    app = SkailApp(runtime_factory=lambda: None, bootstrap={})
    async with app.run_test(size=(120, 40)) as pilot:
        assert app.onboarding_state.step == "welcome"
        assert not app.query_one("#prompt-composer").visible

        # Advance to provider
        await pilot.press("enter")
        assert app.onboarding_state.step == "provider"

        # Down arrow cycles provider options
        await pilot.press("down")
        assert app.onboarding_state.provider == "openai"
        await pilot.press("down")
        assert app.onboarding_state.provider == "anthropic"
        await pilot.press("down")
        assert app.onboarding_state.provider == "fake"

        # Enter on fake provider advances to trust
        await pilot.press("enter")
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
