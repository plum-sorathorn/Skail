"""Unit and pilot interaction tests for TUI composer, slash commands, and overlays."""

from __future__ import annotations

from typing import Any

import pytest
from textual.widgets import Button, TabbedContent

from skail.tui.app import SkailApp
from skail.tui.commands import command_requires_args
from skail.tui.overlays.model_picker import ModelPickerOverlay
from skail.tui.overlays.theme_picker import ThemePickerOverlay
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
async def test_cycle_mode_keybinding() -> None:
    app = SkailApp(bootstrap={"fake_provider": True})
    async with app.run_test(size=(120, 40)) as pilot:
        initial_mode = (app.projection.footer_data.routing_mode or "auto").lower()
        await pilot.press("shift+tab")
        next_mode = (app.projection.footer_data.routing_mode or "").lower()
        assert next_mode != initial_mode
        assert next_mode == "quality"
        await pilot.press("shift+tab")
        assert (app.projection.footer_data.routing_mode or "").lower() == "economy"


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
