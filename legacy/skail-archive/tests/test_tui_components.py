from datetime import datetime, timedelta, timezone

from skail.tui.dashboard_widgets import (
    _format_box_lines,
    build_dashboard_snapshot,
    render_log_rows,
)
from skail.tui.keymap import KEYMAP, QUIT_KEY
from skail.tui.onboarding_models import filter_catalog


def test_keymap_has_quit_and_navigation():
    assert QUIT_KEY == "ctrl+c"
    assert "down" in KEYMAP and "up" in KEYMAP


def test_dashboard_helpers_render_bounded_rows():
    rendered = render_log_rows([{"time": "now", "route": "fast", "model": "m", "prompt": "hello"}], 0)
    assert "now fast m hello" in rendered
    lines = _format_box_lines("Title", ["one", "two"], width=20)
    assert len(lines) == 4
    assert all(len(line) == 20 for line in lines)


def _stats_record(
    event_id: str,
    session_id: str | None,
    *,
    model: str = "openai/qwen",
    minutes_ago: int = 1,
    cost: float | None = 0.01,
    selection: dict | None = None,
):
    record = {
        "event_id": event_id,
        "ts": (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat(),
        "upstream_model": model,
        "pseudo_model": "skail",
        "path": "FAST",
        "prompt_tokens": 10,
        "completion_tokens": 5,
    }
    if session_id is not None:
        record["session_id"] = session_id
    if cost is not None:
        record["cost"] = cost
    if selection is not None:
        record["selection"] = selection
    return record


def test_dashboard_snapshot_keeps_unknown_session_separate_from_global_and_legacy_usage():
    snapshot = build_dashboard_snapshot(
        [
            _stats_record("legacy", None, model="legacy/local", cost=None),
            _stats_record("session-a", "session-a", model="openai/qwen"),
        ],
        session_id=None,
        window="1h",
        plugins_enabled=False,
    )

    assert snapshot["all_time"]["totals"]["calls"] == 2
    assert snapshot["window"]["totals"]["calls"] == 2
    assert snapshot["session"]["status"] == "Unknown session"
    assert snapshot["session"]["usage"] is None
    assert snapshot["session"]["decisions"] == []
    assert snapshot["plugin_status"] == "Disabled"


def test_dashboard_snapshot_uses_only_selected_session_for_session_facts_and_decisions():
    selected = _stats_record(
        "session-a",
        "session-a",
        selection={
            "task_type": "refactor",
            "binding_constraint": "capability",
            "min_capability_score_applied": 0.55,
            "oma": {"outcomes": ["started", "completed"], "reason": "completed"},
        },
    )
    selected["latency_ms"] = 24.0
    selected["cache_read_tokens"] = 8
    snapshot = build_dashboard_snapshot(
        [selected, _stats_record("session-b", "session-b", model="openai/other")],
        session_id="session-a",
        window="1h",
        plugins_enabled=True,
    )

    assert snapshot["all_time"]["totals"]["calls"] == 2
    assert snapshot["session"]["status"] == "session-a"
    assert snapshot["session"]["usage"]["calls"] == 1
    assert list(snapshot["session"]["models"]) == ["openai/qwen"]
    assert [record["event_id"] for record in snapshot["session"]["decisions"]] == ["session-a"]
    assert snapshot["session"]["evidence"]["floor"] == 0.55
    assert snapshot["session"]["oma"]["outcomes"] == {"started": 1, "completed": 1}
    assert snapshot["session"]["evidence"]["cache_reported"] is True
    assert snapshot["session"]["evidence"]["latency_reported"] is True


def test_dashboard_snapshot_marks_empty_and_zero_cost_usage_as_explicit_unknowns():
    empty = build_dashboard_snapshot([], session_id="session-a", window="1h", plugins_enabled=False)
    zero_cost = build_dashboard_snapshot(
        [_stats_record("session-a", "session-a", cost=0.0)],
        session_id="session-a",
        window="1h",
        plugins_enabled=True,
    )

    assert empty["all_time"]["totals"]["calls"] == 0
    assert empty["session"]["status"] == "session-a"
    assert empty["plugin_status"] == "Disabled"
    assert zero_cost["session"]["evidence"]["cost_known"] is False


def test_dashboard_screen_renders_persisted_session_evidence_and_window_controls(monkeypatch):
    import skail.config as config_module
    from skail import stats
    from skail.config import Config
    from skail.tui.dashboard import DashboardScreen

    record = _stats_record(
        "session-a",
        "session-a",
        selection={
            "task_type": "debug",
            "binding_constraint": "capability",
            "min_capability_score_applied": 0.4,
            "oma": {"outcomes": ["not_eligible"], "reason": "complexity_below_threshold"},
        },
    )
    record["latency_ms"] = 30.0
    record["cache_write_tokens"] = 4
    monkeypatch.setattr(stats, "load_records", lambda *args, **kwargs: [record])
    monkeypatch.setattr(config_module, "get_config", lambda: Config())

    unknown_session = DashboardScreen()
    unknown_session._update_stats()
    assert "Unknown session" in unknown_session._stats_summary()
    assert "Plugin runtime: [bold]Disabled[/bold]" in unknown_session._telemetry_cards()

    screen = DashboardScreen(session_id="session-a")
    screen._update_stats()

    assert "Current session: [bold]session-a[/bold]" in screen._stats_summary()
    assert "openai/qwen" in screen._stats_summary()
    assert "Floor: 0.40" in screen._telemetry_cards()
    assert "OMA: not_eligible=1" in screen._telemetry_cards()
    assert screen.selected_window == "1h"
    screen.action_next_window()
    assert screen.selected_window == "1d"
    screen.action_previous_window()
    assert screen.selected_window == "1h"


def test_catalog_filter_matches_provider_capability_context_and_fuzzy_term():
    models = [
        {"id": "Acme/Reasoner-Pro", "provider": "acme", "context_window": 128000, "is_reasoning": True, "supports_tools": True},
        {"id": "other/basic", "provider": "other", "context_window": 8000},
    ]
    result = filter_catalog(models, term="reasoner pro", provider="acme", capabilities={"thinking", "tool use"}, min_context=100000)
    assert [row["id"] for row in result] == ["Acme/Reasoner-Pro"]


def test_model_catalog_screen_can_be_constructed():
    from skail.tui.onboarding.screens_models import ModelCatalogScreen
    assert ModelCatalogScreen() is not None


async def test_all_tui_screens_mount_and_render_without_markup_errors():
    import asyncio
    from textual.app import App
    from skail.tui.dashboard import MainMenuScreen, DashboardScreen
    from skail.tui.dashboard_screens import UpdateScreen, LaunchAgentScreen, DrillDownScreen
    from skail.tui.settings import SettingsScreen
    from skail.tui.onboarding.screens import OnboardingScreen, ModelSourceScreen, ModelSelectionScreen
    from skail.tui.onboarding.screens_custom import ApiKeyScreen, CustomProvidersScreen
    from skail.tui.onboarding.screens_extra import ProviderFormScreen, LauncherIntegrationScreen
    from skail.tui.onboarding.screens_plugin import PluginSetupScreen
    from skail.tui.onboarding.screens_slm import SLMSetupScreen
    from skail.tui.onboarding.screens_models import ModelCatalogScreen

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
    from skail.tui.onboarding.screens_plugin import PluginSetupScreen
    from skail.config import get_config, save_config

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


