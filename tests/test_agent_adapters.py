"""Coding agent adapters unit tests for Pi, Claude Code, OpenCode, and all supported tools."""

import json
from pathlib import Path

from autoconduck.harnesses import all_adapters, all_harnesses, binary_name_for
from autoconduck.harnesses.claude_code import ClaudeCodeAdapter
from autoconduck.harnesses.opencode import OpenCodeAdapter
from autoconduck.harnesses.pi import PiAdapter
from autoconduck.cli.cli_launch import resolve_agent_ids
from autoconduck.config import Config
from autoconduck.launcher import shim_script, shim_script_win
from autoconduck.presets.model_presets import curated_model_catalog, discover_models
from autoconduck.presets.presets_data import PRESETS


def test_all_adapters_registered():
    adapters = all_adapters()
    ids = {a.id for a in adapters}
    expected = {
        "claude_code",
        "opencode",
        "pi",
        "omp",
    }
    assert ids == expected
    assert binary_name_for("claude_code") == "claude"
    assert binary_name_for("opencode") == "opencode"
    assert binary_name_for("pi") == "pi"


def test_harnesses_module_alias():
    import autoconduck.harnesses as harnesses
    adapters = harnesses.all_harnesses()
    ids = {a.id for a in adapters}
    assert ids == {"claude_code", "opencode", "pi", "omp"}


def test_claude_code_adapter_patch_and_revert(tmp_path, monkeypatch):
    settings_file = tmp_path / ".claude" / "settings.json"
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(
        json.dumps(
            {
                "env": {"EXISTING": "val"},
                "permissions": {"allow": ["Notebook", "Task", "Read", "Write", "Edit"]},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    adapter = ClaudeCodeAdapter()
    cfg = Config(port=11434)
    adapter.patch(cfg, port=11434)

    # Check that settings were patched
    data = json.loads(settings_file.read_text(encoding="utf-8"))
    assert "ANTHROPIC_BASE_URL" in data["env"]
    assert "http://127.0.0.1:11434" in data["env"]["ANTHROPIC_BASE_URL"]
    overrides = data.get("modelOverrides", {})
    assert "autoconduck" in overrides
    # modelOverrides values must be strings (provider model IDs), not objects.
    for pseudo_name in ("autoconduck", "autoconduck-budget", "autoconduck-expensive"):
        assert overrides[pseudo_name] == pseudo_name
        assert isinstance(overrides[pseudo_name], str)

    # Revert restores original state
    adapter.revert()
    data_reverted = json.loads(settings_file.read_text(encoding="utf-8"))
    assert "ANTHROPIC_BASE_URL" not in data_reverted.get("env", {})
    assert data_reverted.get("env", {}).get("EXISTING") == "val"


def test_pi_adapter_patch_install_features_and_revert(tmp_path, monkeypatch):
    pi_dir = tmp_path / ".pi" / "agent"
    pi_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(pi_dir))

    adapter = PiAdapter()
    cfg = Config(port=11434)
    adapter.patch(cfg, port=11434)

    ext = pi_dir / "extensions" / "autoconduck.ts"
    assert ext.exists()
    assert "autoconduck" in ext.read_text(encoding="utf-8")

    # Check provider configuration in settings.json
    settings_file = pi_dir / "settings.json"
    assert settings_file.exists()
    settings_data = json.loads(settings_file.read_text(encoding="utf-8"))
    assert settings_data.get("defaultProvider") == "autoconduck"

    # Test install_features hook
    installed = adapter.install_features()
    assert isinstance(installed, list)

    adapter.revert()
    assert not ext.exists()
    data_reverted = json.loads(settings_file.read_text(encoding="utf-8"))
    assert data_reverted.get("defaultProvider") is None


def test_opencode_adapter_patch_and_revert(tmp_path, monkeypatch):
    opencode_cfg = tmp_path / "opencode.json"
    opencode_cfg.write_text(json.dumps({"providers": {}}), encoding="utf-8")
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)

    adapter = OpenCodeAdapter()
    cfg = Config(port=11434)
    adapter.patch(cfg, port=11434)

    data = json.loads(opencode_cfg.read_text(encoding="utf-8"))
    assert "autoconduck" in data.get("providers", {})
    assert "autoconduck" in data.get("provider", {})
    assert data.get("model") == "autoconduck/autoconduck"

    adapter.revert()
    data_reverted = json.loads(opencode_cfg.read_text(encoding="utf-8"))
    assert "autoconduck" not in data_reverted.get("providers", {})
    assert "autoconduck" not in data_reverted.get("provider", {})


def test_launcher_shims_generation():
    real_bin = "/usr/local/bin/agent_mock"
    for agent_id in (
        "claude_code",
        "opencode",
        "pi",
        "omp",
    ):
        bash = shim_script(agent_id, real_bin)
        assert "ensure --port" in bash
        assert "release --port" in bash

        win = shim_script_win(agent_id, real_bin)
        assert "ensure --port" in win
        assert "release --port" in win


def test_agent_alias_resolution():
    assert resolve_agent_ids(["claude"]) == ["claude_code"]
    assert resolve_agent_ids(["open-code"]) == ["opencode"]
    assert resolve_agent_ids(["pi"]) == ["pi"]
    assert resolve_agent_ids(["omp"]) == ["omp"]
    assert resolve_agent_ids(["ohmypi"]) == ["omp"]
    assert resolve_agent_ids(["all"]) == [a.id for a in all_adapters()]


def test_all_provider_presets_resolve():
    for provider in (
        "openai",
        "anthropic",
        "google",
        "mistral",
        "deepseek",
        "groq",
        "openrouter",
        "together",
        "xai",
        "llmgateway",
        "devpass",
    ):
        assert provider in PRESETS
        models = PRESETS[provider]
        assert len(models) >= 1
        for m in models:
            assert "id" in m
            assert "provider" in m
            assert "price_in" in m
            assert "price_out" in m

    discovered = discover_models(
        preset_keys=[
            "openai",
            "anthropic",
            "google",
            "mistral",
            "deepseek",
            "groq",
            "openrouter",
            "together",
            "xai",
        ]
    )
    assert len(discovered) >= 40
    catalog = curated_model_catalog()
    assert len(catalog) >= 100

    # Verify grok models presence in xai and devpass
    assert any(m["id"] in ("grok-4-6", "grok-4.6") for m in PRESETS["xai"])
    assert any(m["id"] in ("grok-4.5", "grok-4.6", "grok-4-5", "grok-4-6") for m in PRESETS["devpass"])


def test_claude_code_sanitizes_legacy_object_model_overrides(tmp_path, monkeypatch):
    """Ensure legacy object modelOverrides values are sanitized into strings."""
    settings_file = tmp_path / ".claude" / "settings.json"
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(
        json.dumps(
            {
                "env": {"EXISTING": "val"},
                "modelOverrides": {
                    "autoconduck": {"contextWindow": 1000000},
                    "autoconduck-budget": {"contextWindow": 1000000},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    adapter = ClaudeCodeAdapter()
    cfg = Config(port=11434)
    adapter.patch(cfg, port=11434)

    data = json.loads(settings_file.read_text(encoding="utf-8"))
    overrides = data.get("modelOverrides", {})
    for pseudo_name in ("autoconduck", "autoconduck-budget", "autoconduck-expensive"):
        assert overrides[pseudo_name] == pseudo_name
        assert isinstance(overrides[pseudo_name], str)


def test_onboarding_configure_selected_agents(tmp_path, monkeypatch):
    from autoconduck.tui.onboarding.helpers import configure_selected_agents

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / ".pi" / "agent"))

    configured = configure_selected_agents(["claude_code", "pi", "omp"])
    assert "claude_code" in configured
    assert "pi" in configured
    assert "omp" in configured


def test_claude_code_adapter_rag_mcp_patch_and_revert(tmp_path, monkeypatch):
    from autoconduck.config.models import PluginConfig

    settings_file = tmp_path / ".claude" / "settings.json"
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    adapter = ClaudeCodeAdapter()
    cfg = Config(port=11434, plugins=PluginConfig(enabled=True, claude_enabled=True, rag_enabled=True))
    adapter.patch(cfg, port=11434)

    data = json.loads(settings_file.read_text(encoding="utf-8"))
    assert "mcpServers" in data
    assert data["mcpServers"]["autoconduck"]["url"] == "http://127.0.0.1:11434/mcp"
    assert data["mcpServers"]["autoconduck"]["type"] == "http"

    # Revert removes mcpServers block
    adapter.revert()
    data_reverted = json.loads(settings_file.read_text(encoding="utf-8"))
    assert "mcpServers" not in data_reverted


def test_opencode_adapter_rag_mcp_patch_and_revert(tmp_path, monkeypatch):
    from autoconduck.config.models import PluginConfig

    opencode_cfg = tmp_path / "opencode.json"
    opencode_cfg.write_text(json.dumps({"providers": {}}), encoding="utf-8")
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    adapter = OpenCodeAdapter()
    cfg = Config(port=11434, plugins=PluginConfig(enabled=True, opencode_enabled=True, rag_enabled=True))
    adapter.patch(cfg, port=11434)

    data = json.loads(opencode_cfg.read_text(encoding="utf-8"))
    assert "mcp" in data
    assert data["mcp"]["autoconduck"]["url"] == "http://127.0.0.1:11434/mcp"
    assert data["mcp"]["autoconduck"]["type"] == "http"

    # Check plugin JS contains autoconduck_search
    plugin_js = (tmp_path / ".config" / "opencode" / "plugins" / "autoconduck.js").read_text(encoding="utf-8")
    assert "AUTOCONDUCK_RAG_ENABLED = true" in plugin_js
    assert "tool.autoconduck_search" in plugin_js
    assert "/mcp/tools/call" in plugin_js

    # Revert cleans up mcp block
    adapter.revert()
    data_reverted = json.loads(opencode_cfg.read_text(encoding="utf-8"))
    assert "mcp" not in data_reverted


def test_pi_and_omp_extension_rag_register_tool(tmp_path, monkeypatch):
    from autoconduck.config.models import PluginConfig
    from autoconduck.harnesses.omp import OmpAdapter

    pi_dir = tmp_path / ".pi" / "agent"
    pi_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(pi_dir))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    # Test Pi Adapter with RAG enabled
    pi_adapter = PiAdapter()
    cfg_pi = Config(port=11434, plugins=PluginConfig(enabled=True, pi_enabled=True, rag_enabled=True))
    pi_adapter.patch(cfg_pi, port=11434)

    pi_ext = (pi_dir / "extensions" / "autoconduck.ts").read_text(encoding="utf-8")
    assert "const AUTOCONDUCK_RAG_ENABLED = true" in pi_ext
    assert "pi.registerTool('autoconduck_search'" in pi_ext
    assert "http://127.0.0.1:11434/mcp/tools/call" in pi_ext

    # Test OMP Adapter with RAG enabled
    omp_adapter = OmpAdapter()
    cfg_omp = Config(port=11434, plugins=PluginConfig(enabled=True, omp_enabled=True, rag_enabled=True))
    omp_adapter.patch(cfg_omp, port=11434)

    omp_ext = (tmp_path / ".omp" / "agent" / "extensions" / "autoconduck.ts").read_text(encoding="utf-8")
    assert "const AUTOCONDUCK_RAG_ENABLED = true" in omp_ext
    assert "pi.registerTool('autoconduck_search'" in omp_ext
    assert "http://127.0.0.1:11434/mcp/tools/call" in omp_ext


def test_all_adapters_install_plugin_visibility_safe(tmp_path, monkeypatch):
    from autoconduck.config.models import PluginConfig
    from autoconduck.harnesses import all_adapters
    from autoconduck.harnesses.base import GenericAdapter

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / ".pi" / "agent"))

    adapters = [*all_adapters(), GenericAdapter()]
    cfg_enabled = Config(port=11434, plugins=PluginConfig(enabled=True, claude_enabled=True, pi_enabled=True, omp_enabled=True, opencode_enabled=True, rag_enabled=True))
    cfg_disabled = Config(port=11434, plugins=PluginConfig(enabled=False))

    for adapter in adapters:
        # Should run without error on enabled config
        adapter.install_plugin_visibility(cfg_enabled)
        # Should run without error on disabled config
        adapter.install_plugin_visibility(cfg_disabled)


def test_all_adapters_revert_cleans_all_artifacts(tmp_path, monkeypatch):
    """Verify revert cleans up all artifacts across Claude Code, OpenCode, Pi, and OMP."""
    from autoconduck.config.models import PluginConfig
    from autoconduck.harnesses.claude_code import ClaudeCodeAdapter
    from autoconduck.harnesses.opencode import OpenCodeAdapter
    from autoconduck.harnesses.pi import PiAdapter
    from autoconduck.harnesses.omp import OmpAdapter

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    pi_dir = tmp_path / ".pi" / "agent"
    pi_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(pi_dir))

    # Pre-populate empty configurations
    claude_settings = tmp_path / ".claude" / "settings.json"
    claude_settings.parent.mkdir(parents=True, exist_ok=True)
    claude_settings.write_text("{}", encoding="utf-8")

    opencode_cfg = tmp_path / "opencode.json"
    opencode_cfg.write_text(json.dumps({"providers": {}}), encoding="utf-8")

    cfg = Config(
        port=11434,
        plugins=PluginConfig(
            enabled=True,
            claude_enabled=True,
            pi_enabled=True,
            omp_enabled=True,
            opencode_enabled=True,
            subagent_enabled=True,
            rag_enabled=True,
        ),
    )

    claude_adapter = ClaudeCodeAdapter()
    opencode_adapter = OpenCodeAdapter()
    pi_adapter = PiAdapter()
    omp_adapter = OmpAdapter()

    # Patch all adapters
    claude_adapter.patch(cfg, port=11434)
    opencode_adapter.patch(cfg, port=11434)
    pi_adapter.patch(cfg, port=11434)
    omp_adapter.patch(cfg, port=11434)

    # 1. Verify artifacts created
    # Claude Code
    c_data = json.loads(claude_settings.read_text(encoding="utf-8"))
    assert "mcpServers" in c_data
    assert "autoconduck" in c_data["mcpServers"]
    assert "hooks" in c_data
    assert "SubagentStart" in c_data["hooks"]
    assert "autoconduck" in c_data

    # OpenCode
    oc_data = json.loads(opencode_cfg.read_text(encoding="utf-8"))
    assert "mcp" in oc_data
    assert "autoconduck" in oc_data["mcp"]
    assert "plugin" in oc_data
    oc_plugin_file = tmp_path / ".config" / "opencode" / "plugins" / "autoconduck.js"
    assert oc_plugin_file.exists()

    # OMP
    omp_ext = tmp_path / ".omp" / "agent" / "extensions" / "autoconduck.ts"
    assert omp_ext.exists()

    # Pi
    pi_ext = pi_dir / "extensions" / "autoconduck.ts"
    assert pi_ext.exists()

    # 2. Revert all adapters
    claude_adapter.revert()
    opencode_adapter.revert()
    pi_adapter.revert()
    omp_adapter.revert()

    # 3. Verify all artifacts cleaned up
    # Claude Code
    c_rev = json.loads(claude_settings.read_text(encoding="utf-8"))
    assert "autoconduck" not in c_rev
    assert "mcpServers" not in c_rev or "autoconduck" not in c_rev.get("mcpServers", {})
    assert "hooks" not in c_rev or not any(
        "/plugin/events" in str(h.get("url", ""))
        for entries in (c_rev.get("hooks") or {}).values()
        if isinstance(entries, list)
        for entry in entries
        for h in (entry.get("hooks") or [])
    )

    # OpenCode
    oc_rev = json.loads(opencode_cfg.read_text(encoding="utf-8"))
    assert "mcp" not in oc_rev or "autoconduck" not in oc_rev.get("mcp", {})
    assert "plugin" not in oc_rev or not any("autoconduck.js" in str(p) for p in oc_rev.get("plugin", []))
    assert not oc_plugin_file.exists()

    # OMP
    assert not omp_ext.exists()

    # Pi
    assert not pi_ext.exists()



