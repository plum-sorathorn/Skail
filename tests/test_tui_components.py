from autoconduck.tui.dashboard_widgets import _format_box_lines, render_log_rows
from autoconduck.tui.keymap import KEYMAP, QUIT_KEY
from autoconduck.tui.onboarding_models import filter_catalog


def test_keymap_has_quit_and_navigation():
    assert QUIT_KEY == "ctrl+c"
    assert "down" in KEYMAP and "up" in KEYMAP


def test_dashboard_helpers_render_bounded_rows():
    rendered = render_log_rows([{"time": "now", "route": "fast", "model": "m", "prompt": "hello"}], 0)
    assert "now fast m hello" in rendered
    lines = _format_box_lines("Title", ["one", "two"], width=20)
    assert len(lines) == 4
    assert all(len(line) == 20 for line in lines)


def test_catalog_filter_matches_provider_capability_context_and_fuzzy_term():
    models = [
        {"id": "Acme/Reasoner-Pro", "provider": "acme", "context_window": 128000, "is_reasoning": True, "supports_tools": True},
        {"id": "other/basic", "provider": "other", "context_window": 8000},
    ]
    result = filter_catalog(models, term="reasoner pro", provider="acme", capabilities={"thinking", "tool use"}, min_context=100000)
    assert [row["id"] for row in result] == ["Acme/Reasoner-Pro"]


def test_model_catalog_screen_can_be_constructed():
    from autoconduck.tui.onboarding.screens_models import ModelCatalogScreen
    assert ModelCatalogScreen() is not None


async def test_all_tui_screens_mount_and_render_without_markup_errors():
    import asyncio
    from textual.app import App
    from autoconduck.tui.dashboard import MainMenuScreen, DashboardScreen
    from autoconduck.tui.dashboard_screens import UpdateScreen, LaunchAgentScreen, DrillDownScreen
    from autoconduck.tui.settings import SettingsScreen
    from autoconduck.tui.onboarding.screens import OnboardingScreen, ModelSourceScreen, ModelSelectionScreen
    from autoconduck.tui.onboarding.screens_custom import ApiKeyScreen, CustomProvidersScreen
    from autoconduck.tui.onboarding.screens_extra import ProviderFormScreen, LauncherIntegrationScreen
    from autoconduck.tui.onboarding.screens_plugin import PluginSetupScreen
    from autoconduck.tui.onboarding.screens_slm import SLMSetupScreen
    from autoconduck.tui.onboarding.screens_models import ModelCatalogScreen

    screens = [
        MainMenuScreen(),
        DashboardScreen(),
        UpdateScreen(),
        LaunchAgentScreen(),
        DrillDownScreen({"turn": 1, "model": "test-model", "path": "FAST"}),
        SettingsScreen(),
        OnboardingScreen(),
        ModelSourceScreen(),
        ModelSelectionScreen(None, [], "anthropic"),
        ApiKeyScreen(None, [], "anthropic"),
        CustomProvidersScreen(None, []),
        ProviderFormScreen(None, []),
        PluginSetupScreen(None, ["claude_code"]),
        LauncherIntegrationScreen(None, ["claude_code"]),
        SLMSetupScreen(None),
        ModelCatalogScreen(),
    ]

    class RenderTestApp(App):
        async def on_mount(self):
            for screen in screens:
                await self.push_screen(screen)
                await asyncio.sleep(0.01)
                self.pop_screen()
            await self.action_quit()

    app = RenderTestApp()
    await app.run_async(headless=True)


def test_plugin_setup_screen_options_and_config():
    from autoconduck.tui.onboarding.screens_plugin import PluginSetupScreen
    from autoconduck.config import get_config, save_config

    screen = PluginSetupScreen(None, ["claude_code"])
    assert len(screen.OPTIONS) == 3
    assert screen.OPTIONS[0]["id"] == "full"
    assert screen.OPTIONS[0]["plugins_enabled"] is True
    assert screen.OPTIONS[0]["claude_enabled"] is True
    assert screen.OPTIONS[0]["subagent_enabled"] is True
    assert screen.OPTIONS[0]["rag_enabled"] is True

    assert screen.OPTIONS[1]["id"] == "runtime_only"
    assert screen.OPTIONS[1]["plugins_enabled"] is True
    assert screen.OPTIONS[1]["claude_enabled"] is False
    assert screen.OPTIONS[1]["subagent_enabled"] is False
    assert screen.OPTIONS[1]["rag_enabled"] is False

    assert screen.OPTIONS[2]["id"] == "disabled"
    assert screen.OPTIONS[2]["plugins_enabled"] is False
    assert screen.OPTIONS[2]["claude_enabled"] is False
    assert screen.OPTIONS[2]["subagent_enabled"] is False
    assert screen.OPTIONS[2]["rag_enabled"] is False

    # Simulate confirming option 0 (Full recommended)
    screen.selected_idx = 0
    screen._confirm_and_continue()
    cfg = get_config()
    assert cfg.plugins.enabled is True
    assert cfg.plugins.claude_enabled is True
    assert cfg.plugins.subagent_enabled is True
    assert cfg.plugins.rag_enabled is True

    # Simulate confirming option 1 (Runtime only)
    screen.selected_idx = 1
    screen._confirm_and_continue()
    cfg = get_config()
    assert cfg.plugins.enabled is True
    assert cfg.plugins.claude_enabled is False
    assert cfg.plugins.subagent_enabled is False
    assert cfg.plugins.rag_enabled is False

    # Simulate confirming option 2 (Disabled)
    screen.selected_idx = 2
    screen._confirm_and_continue()
    cfg = get_config()
    assert cfg.plugins.enabled is False
    assert cfg.plugins.claude_enabled is False
    assert cfg.plugins.subagent_enabled is False
    assert cfg.plugins.rag_enabled is False


