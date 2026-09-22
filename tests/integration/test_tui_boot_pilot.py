"""Phase 1 TUI pilot boot tests (draft section 13.3, items 1-10)."""

from __future__ import annotations

import pytest

from skail.tui.app import SkailApp
from skail.tui.widgets.onboarding import OnboardingPanel

pytestmark = pytest.mark.asyncio


def _bootstrap(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {"workspace": ".", "session_id": "01JPILOT"}
    base.update(overrides)
    return base


async def test_no_credential_boot_mounts_onboarding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for var in ("LLMGATEWAY_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    app = SkailApp(runtime_factory=lambda: None, bootstrap=_bootstrap())
    async with app.run_test() as pilot:
        assert app.app_state == "onboarding"
        assert app.controller is None
        panels = app.query(OnboardingPanel)
        assert len(panels) == 1
        await pilot.pause()


async def test_welcome_step_is_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("LLMGATEWAY_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    app = SkailApp(runtime_factory=lambda: None, bootstrap=_bootstrap())
    async with app.run_test() as pilot:
        panel = app.query_one(OnboardingPanel)
        assert "Welcome to Skail." in panel.render_step().plain
        await pilot.pause()


async def test_fake_provider_path_reaches_ready_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for var in ("LLMGATEWAY_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    app = SkailApp(runtime_factory=lambda: None, bootstrap=_bootstrap())
    async with app.run_test() as pilot:
        app.onboarding_choose_fake()
        assert app.onboarding_state.provider == "fake"
        app.onboarding_confirm()
        app.onboarding_trust_folder()
        app.onboarding_state.theme = "dark"
        app.onboarding_confirm()
        assert app.onboarding_state.step == "ready"
        panel = app.query_one(OnboardingPanel)
        text = panel.render_step().plain
        assert "READY" in text
        assert "Fake provider" in text
        assert "skail -r 01JPILOT" in text
        await pilot.pause()


async def test_provider_validation_shows_loading_then_advances(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for var in ("LLMGATEWAY_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    app = SkailApp(runtime_factory=lambda: None, bootstrap=_bootstrap())
    async with app.run_test() as pilot:
        app.onboarding_confirm()
        assert app.onboarding_state.step == "provider"
        app.onboarding_credentials.set_key("long-enough-test-key")
        app.validate_onboarding_key()
        assert app.onboarding_state.validating is True
        await pilot.pause()
        assert app.onboarding_state.validating is False
        assert app.onboarding_state.step == "trust"


async def test_validation_failure_stays_and_allows_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for var in ("LLMGATEWAY_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    app = SkailApp(runtime_factory=lambda: None, bootstrap=_bootstrap())
    async with app.run_test() as pilot:
        app.onboarding_confirm()
        app.onboarding_credentials.set_key("bad")
        app.validate_onboarding_key()
        await pilot.pause()
        assert app.onboarding_state.step == "provider"
        assert app.onboarding_state.validation_error is not None
        assert "Validation failed." in app.onboarding_state.validation_error
        app.onboarding_credentials.set_key("long-enough-retry-key")
        app.validate_onboarding_key()
        await pilot.pause()
        assert app.onboarding_state.step == "trust"


async def test_key_field_is_masked(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("LLMGATEWAY_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    app = SkailApp(runtime_factory=lambda: None, bootstrap=_bootstrap())
    async with app.run_test() as pilot:
        app.onboarding_confirm()
        await pilot.pause()
        key_inputs = app.query("#onboarding-key")
        assert len(key_inputs) == 1
        assert key_inputs.first().password is True


async def test_trust_and_theme_steps_are_keyboard_operable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for var in ("LLMGATEWAY_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    app = SkailApp(runtime_factory=lambda: None, bootstrap=_bootstrap())
    async with app.run_test() as pilot:
        app.onboarding_state.step = "trust"
        app.onboarding_trust_folder()
        assert app.onboarding_state.trusted is True
        assert app.onboarding_state.step == "theme"
        app.onboarding_state.theme = "light"
        app.preview_theme("light")
        assert app.current_theme_name == "light"
        app.onboarding_confirm()
        assert app.onboarding_state.step == "ready"
        await pilot.pause()


async def test_theme_preview_restores_on_escape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for var in ("LLMGATEWAY_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    app = SkailApp(runtime_factory=lambda: None, bootstrap=_bootstrap())
    async with app.run_test() as pilot:
        app.onboarding_state.step = "theme"
        app.onboarding_state.theme = "dark"
        app.apply_theme("dark")
        app.preview_theme("light")
        assert app.current_theme_name == "light"
        app.onboarding_back()
        assert app.current_theme_name == "system"
        assert app.onboarding_state.step == "trust"
        await pilot.pause()


async def test_wide_viewport_shows_sidebar(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("LLMGATEWAY_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    app = SkailApp(runtime_factory=lambda: None, bootstrap=_bootstrap())
    async with app.run_test(size=(120, 40)) as pilot:
        container = app.query_one("#main-container")
        assert container.has_class("wide")
        assert not container.has_class("narrow")
        await pilot.pause()


async def test_narrow_viewport_hides_sidebar_but_keeps_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for var in ("LLMGATEWAY_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    app = SkailApp(runtime_factory=lambda: None, bootstrap=_bootstrap())
    async with app.run_test(size=(99, 30)) as pilot:
        container = app.query_one("#main-container")
        assert container.has_class("narrow")
        assert not container.has_class("wide")
        # §8.3: the SCREEN carries narrow/wide; margin hidden, drawer strip shown.
        assert app.screen.has_class("narrow")
        assert not app.screen.has_class("wide")
        await pilot.pause()
        assert not app.query_one("#hairline").visible
        assert app.query_one("#margin-drawer").visible
        app.action_view_agents()
        tabs = app.query_one("#tabs")
        assert tabs.active == "tab-agents"
        # Tab state keeps switching even though the panels stay hidden (§8.3).
        app.action_view_budget()
        await pilot.pause()
        assert tabs.active == "tab-budget"
        app.action_view_budget()
        assert tabs.active == "tab-budget"
        await pilot.pause()


async def test_recoverable_failure_shows_error_screen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLMGATEWAY_API_KEY", "test-key")

    def _failing_factory() -> object:
        raise RuntimeError("connection refused")

    app = SkailApp(runtime_factory=_failing_factory, bootstrap=_bootstrap())
    async with app.run_test() as pilot:
        assert app.app_state in ("initializing", "error")
        await pilot.pause()
        await pilot.pause()
        assert app.app_state == "error"
        assert app.startup_error is not None
        assert "connection refused" in app.startup_error
        app.retry_startup()
        await pilot.pause()
        await pilot.pause()
        assert app.app_state == "error"
