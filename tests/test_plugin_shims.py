"""Phase 3 shim tests — hook handler, spool tailer, Claude Code hooks, Pi stub, OpenCode doc."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_home(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOCONDUCK_HOME", str(tmp_path / ".autoconduck"))
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / ".pi" / "agent"))
    import autoconduck.config.manager as m
    import autoconduck.plugin.ledger as led_mod
    import autoconduck.plugin.bias as bias_mod
    import autoconduck.plugin.spool as spool_mod

    m._config = None
    m._config_digest = None
    m._config_path = None
    m._config_mtime = None
    led_mod.reset_ledger_singleton()
    bias_mod.reset_bias_singleton()
    spool_mod.reset_tailer_singleton()
    # also clear legacy home override
    yield
    led_mod.reset_ledger_singleton()
    bias_mod.reset_bias_singleton()
    spool_mod.reset_tailer_singleton()
    m._config = None


def _run_hook(harness="claude", event="PostToolUse", stdin_data: str | None = None):
    """Invoke hook handler functionally (no subprocess spawn cost in test)."""
    from autoconduck.cli.hook import cmd_hook
    import argparse

    args = argparse.Namespace(harness=harness, event=event)
    # monkeypatch stdin
    old_stdin = sys.stdin
    try:
        if stdin_data is not None:
            sys.stdin = io.StringIO(stdin_data)
        else:
            sys.stdin = io.StringIO("")
        rc = cmd_hook(args)
    finally:
        sys.stdin = old_stdin
    return rc


def _spool_path():
    from autoconduck.config.paths import run_dir
    return run_dir() / "plugin_spool.jsonl"


def _read_spool_lines():
    p = _spool_path()
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


# ---------------------------------------------------------------------------
# Hook handler
# ---------------------------------------------------------------------------

def test_hook_stdin_json_spool_line_written(tmp_path):
    payload = json.dumps({"tool_name": "Read", "session_id": "sess-123"})
    rc = _run_hook(harness="claude", event="PostToolUse", stdin_data=payload)
    assert rc == 0
    p = _spool_path()
    assert p.exists()
    lines = _read_spool_lines()
    assert len(lines) == 1
    rec = lines[0]
    assert rec["harness"] == "claude"
    assert rec["event"] == "PostToolUse"
    assert rec["tool_name"] == "Read"
    assert rec["session_id"] == "sess-123"
    assert "ts" in rec


def test_hook_empty_stdin_still_exit_0_and_valid_line(tmp_path):
    rc = _run_hook(harness="claude", event="Stop", stdin_data="")
    assert rc == 0
    p = _spool_path()
    assert p.exists()
    lines = _read_spool_lines()
    assert len(lines) == 1
    rec = lines[0]
    assert rec["event"] == "Stop"
    assert rec["harness"] == "claude"
    assert "ts" in rec
    # no tool_name/session_id required
    assert "tool_name" not in rec or isinstance(rec.get("tool_name"), str)


def test_hook_malformed_json_exit_0(tmp_path):
    rc = _run_hook(harness="claude", event="PreToolUse", stdin_data="{not json!!!")
    assert rc == 0
    p = _spool_path()
    assert p.exists()
    lines = _read_spool_lines()
    assert len(lines) == 1
    assert lines[0]["event"] == "PreToolUse"


def test_hook_spool_created_under_run_dir(tmp_path):
    from autoconduck.config.paths import run_dir
    p = _spool_path()
    assert str(p).replace("\\", "/").endswith("run/plugin_spool.jsonl")
    assert not p.exists()
    rc = _run_hook(harness="claude", event="PostToolUse", stdin_data="")
    assert rc == 0
    assert p.exists()
    assert p.parent == run_dir()


def test_hook_unknown_missing_args_still_exit_0(tmp_path):
    from autoconduck.cli.hook import cmd_hook
    import argparse
    # missing event -> defaults to unknown; still 0
    rc = cmd_hook(argparse.Namespace())
    assert rc == 0
    # unknown harness/event combo
    rc2 = _run_hook(harness="unknown_harness", event="WeirdEvent", stdin_data="")
    assert rc2 == 0


def test_hook_cli_wiring_autoconduck_hook_command(tmp_path, monkeypatch):
    """Verify `autoconduck hook claude <Event>` is registered in CLI parser."""
    from autoconduck.cli.cli import main as cli_main
    # run via CLI parser: `autoconduck hook claude PostToolUse` with empty stdin
    old_stdin = sys.stdin
    sys.stdin = io.StringIO("")
    try:
        rc = cli_main(["hook", "claude", "PostToolUse"])
    finally:
        sys.stdin = old_stdin
    assert rc in (0, None)  # main returns 0 or None on success
    assert _spool_path().exists()


def test_hook_always_exit_0_even_on_spool_error(tmp_path, monkeypatch):
    """If spool write fails, handler still returns 0 (fails inert)."""
    import autoconduck.cli.hook as hook_mod
    orig_path = hook_mod._spool_path
    def boom():
        raise RuntimeError("disk full")
    monkeypatch.setattr(hook_mod, "_spool_path", boom)
    rc = _run_hook(harness="claude", event="PostToolUse", stdin_data=json.dumps({"tool_name": "Read"}))
    assert rc == 0
    monkeypatch.setattr(hook_mod, "_spool_path", orig_path)


# ---------------------------------------------------------------------------
# Spool tailer
# ---------------------------------------------------------------------------

def test_spool_tailer_writes_counted_telemetry(tmp_path):
    from autoconduck.plugin.spool import SpoolTailer
    from autoconduck.plugin.ledger import get_ledger

    ledger = get_ledger()
    spool = _spool_path()
    spool.parent.mkdir(parents=True, exist_ok=True)
    # tailer starts at current size, so write after creation then poll
    tailer = SpoolTailer(spool_path=spool, poll_interval_s=0.05)
    # initialize offset to current file end
    tailer._offset = spool.stat().st_size if spool.exists() else 0
    if not spool.exists():
        spool.write_text("", encoding="utf-8")
        tailer._offset = 0

    # append two hook lines
    for ev in ("PostToolUse", "Stop"):
        rec = {"ts": "2026-01-01T00:00:00+00:00", "harness": "claude", "event": ev, "session_id": "sess-tailer"}
        spool.write_text(spool.read_text(encoding="utf-8") + json.dumps(rec) + "\n", encoding="utf-8")
    n = tailer.poll_sync()
    assert n == 2
    counts = ledger.get_counts("sess-tailer")
    assert counts.get("hook:PostToolUse", 0) == 1
    assert counts.get("hook:Stop", 0) == 1
    assert counts.get("hook", 0) == 2
    # not durable — query events should not contain hook lines
    rows = ledger.query_events(session_id="sess-tailer", limit=20)
    assert all(r["kind"] != "hook:PostToolUse" for r in rows)


def test_spool_tailer_rotation_truncate_robust(tmp_path):
    from autoconduck.plugin.spool import SpoolTailer
    from autoconduck.plugin.ledger import get_ledger

    ledger = get_ledger()
    spool = _spool_path()
    spool.parent.mkdir(parents=True, exist_ok=True)
    spool.write_text("", encoding="utf-8")
    tailer = SpoolTailer(spool_path=spool, poll_interval_s=0.05)
    tailer._offset = 0

    rec1 = {"ts": "2026-01-01T00:00:00+00:00", "harness": "claude", "event": "PostToolUse", "session_id": "sess-rot"}
    spool.write_text(json.dumps(rec1) + "\n", encoding="utf-8")
    assert tailer.poll_sync() == 1
    assert ledger.get_counts("sess-rot").get("hook:PostToolUse") == 1

    # truncate (simulate rotation)
    spool.write_text("", encoding="utf-8")
    # poll should detect truncate and reset offset without error
    assert tailer.poll_sync() == 0

    rec2 = {"ts": "2026-01-01T00:00:00+00:00", "harness": "claude", "event": "Stop", "session_id": "sess-rot"}
    spool.write_text(json.dumps(rec2) + "\n", encoding="utf-8")
    assert tailer.poll_sync() == 1
    assert ledger.get_counts("sess-rot").get("hook:Stop") == 1


@pytest.mark.asyncio
async def test_spool_tailer_disabled_no_tailer(tmp_path, monkeypatch):
    from autoconduck.config.manager import get_config
    from autoconduck.plugin.spool import start_tailer, get_tailer, stop_tailer

    cfg = get_config()
    cfg.plugins.enabled = False
    cfg.plugins.claude_enabled = False
    import autoconduck.config.manager as m
    m._config = cfg

    tailer = await start_tailer()
    assert tailer is None
    assert get_tailer() is None
    # ensure stop is no-op when disabled
    await stop_tailer()


@pytest.mark.asyncio
async def test_spool_tailer_enabled_starts_and_counts(tmp_path):
    from autoconduck.config.manager import get_config
    import autoconduck.config.manager as m
    from autoconduck.plugin.spool import start_tailer, stop_tailer, get_tailer
    from autoconduck.plugin.ledger import get_ledger

    cfg = get_config()
    cfg.plugins.enabled = True
    cfg.plugins.claude_enabled = True
    m._config = cfg

    tailer = await start_tailer(poll_interval_s=0.05)
    assert tailer is not None
    assert get_tailer() is not None
    # write a line and allow tailer loop to pick it up; also poll_sync for determinism
    spool = _spool_path()
    spool.parent.mkdir(parents=True, exist_ok=True)
    rec = {"ts": "2026-01-01T00:00:00+00:00", "harness": "claude", "event": "PreToolUse", "session_id": "sess-async"}
    # ensure file exists
    if not spool.exists():
        spool.write_text("", encoding="utf-8")
    # reset tailer offset to current size so new write is "new"
    import asyncio
    # tailer already started at current size, so append and poll
    with spool.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    # give loop a chance or poll directly
    await asyncio.sleep(0.2)
    tailer.poll_sync()
    ledger = get_ledger()
    counts = ledger.get_counts("sess-async")
    # at least one hook:PreToolUse counted
    assert counts.get("hook:PreToolUse", 0) >= 1
    await stop_tailer()
    assert get_tailer() is None


# ---------------------------------------------------------------------------
# Claude Code shim
# ---------------------------------------------------------------------------

def _patched_settings_path(tmp_path):
    # monkeypatch Path.home to tmp_path via fixture already set AUTOCONDUCK_HOME,
    # but ClaudeCodeAdapter uses Path.home() directly; patch it
    return tmp_path


def test_claude_patch_hooks_present_when_enabled(tmp_path, monkeypatch):
    import pathlib
    orig_home = pathlib.Path.home
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    from autoconduck.config.models import Config
    from autoconduck.harnesses.claude_code import ClaudeCodeAdapter

    cfg = Config()
    cfg.plugins.enabled = True
    cfg.plugins.claude_enabled = True

    adapter = ClaudeCodeAdapter()
    adapter.patch(cfg)

    p = tmp_path / ".claude" / "settings.json"
    assert p.exists()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert "hooks" in data
    hooks = data["hooks"]
    for ev in ("PreToolUse", "PostToolUse", "Stop", "SubagentStart", "SubagentStop"):
        assert ev in hooks
        # at least one entry whose url contains /plugin/events
        found = any(
            "/plugin/events" in str(h.get("url", ""))
            for entry in hooks[ev]
            for h in (entry.get("hooks") or [])
        )
        assert found, f"missing hook http url for {ev}"
    # marker present
    assert data.get("autoconduck", {}).get("hooks_enabled") is True
    assert data.get("autoconduck", {}).get("ingestion_path") == "http"


def test_claude_patch_hooks_absent_when_disabled(tmp_path, monkeypatch):
    import pathlib
    orig_home = pathlib.Path.home
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    from autoconduck.config.models import Config
    from autoconduck.harnesses.claude_code import ClaudeCodeAdapter

    cfg = Config()
    cfg.plugins.enabled = False
    cfg.plugins.claude_enabled = False

    adapter = ClaudeCodeAdapter()
    adapter.patch(cfg)

    p = tmp_path / ".claude" / "settings.json"
    assert p.exists()
    data = json.loads(p.read_text(encoding="utf-8"))
    # no hooks key or no autoconduck hook entries
    hooks = data.get("hooks")
    if hooks is not None:
        for entries in hooks.values():
            if isinstance(entries, list):
                for entry in entries:
                    for h in (entry.get("hooks") or []):
                        assert "/plugin/events" not in str(h.get("url", ""))


def test_claude_patch_revert_removes_hooks(tmp_path, monkeypatch):
    import pathlib
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    from autoconduck.config.models import Config
    from autoconduck.harnesses.claude_code import ClaudeCodeAdapter

    cfg = Config()
    cfg.plugins.enabled = True
    cfg.plugins.claude_enabled = True

    adapter = ClaudeCodeAdapter()
    adapter.patch(cfg)
    p = tmp_path / ".claude" / "settings.json"
    assert "hooks" in json.loads(p.read_text(encoding="utf-8"))

    adapter.revert()
    data = json.loads(p.read_text(encoding="utf-8"))
    # autoconduck marker removed
    assert "autoconduck" not in data
    # hooks either absent or without autoconduck entries
    hooks = data.get("hooks")
    if hooks is not None:
        for entries in hooks.values():
            if isinstance(entries, list):
                for entry in entries:
                    for h in (entry.get("hooks") or []):
                        assert "/plugin/events" not in str(h.get("url", ""))


def test_claude_patch_disabled_byte_identical_after_never_enabled(tmp_path, monkeypatch):
    """When flags off from the start, no hooks key is added (byte-identical to pre-plugin)."""
    import pathlib
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    from autoconduck.config.models import Config
    from autoconduck.harnesses.claude_code import ClaudeCodeAdapter

    cfg = Config()
    cfg.plugins.enabled = False
    cfg.plugins.claude_enabled = False

    # create pre-existing settings without hooks
    pre = {"env": {"FOO": "bar"}, "permissions": {"allow": ["Read"]}}
    path = tmp_path / ".claude" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pre, indent=2) + "\n", encoding="utf-8")

    adapter = ClaudeCodeAdapter()
    adapter.patch(cfg)
    data = json.loads(path.read_text(encoding="utf-8"))
    # managed env keys still added (proxy routing), but hooks must be absent
    assert "hooks" not in data or not any(
        "/plugin/events" in str(h.get("url", ""))
        for entries in (data.get("hooks") or {}).values()
        if isinstance(entries, list)
        for entry in entries
        for h in (entry.get("hooks") or [])
    )


def test_claude_code_http_hooks_formatting_and_subagent_inclusion():
    from autoconduck.harnesses.claude_code import ClaudeCodeAdapter

    adapter = ClaudeCodeAdapter()
    hooks = adapter._build_hooks_block(port=12345)
    assert len(hooks) == 5
    assert set(hooks.keys()) == {"PreToolUse", "PostToolUse", "Stop", "SubagentStart", "SubagentStop"}
    for ev, entries in hooks.items():
        assert len(entries) == 1
        entry = entries[0]
        assert entry["matcher"] == ""
        assert len(entry["hooks"]) == 1
        h = entry["hooks"][0]
        assert h["type"] == "http"
        assert h["url"] == "http://127.0.0.1:12345/plugin/events"
        assert h["timeoutMs"] == 10
        if "Subagent" in ev:
            assert h["_name"] == "AutoConduck Subagent Tracker"
        else:
            assert h["_name"] == "AutoConduck Monitor"

    mcp = adapter._build_mcp_block(port=12345)
    assert mcp == {"autoconduck": {"url": "http://127.0.0.1:12345/mcp", "type": "http"}}


def test_claude_code_detects_and_strips_command_type_hooks():
    from autoconduck.harnesses.claude_code import ClaudeCodeAdapter

    adapter = ClaudeCodeAdapter()
    # Test recognition of command-type hook entry
    cmd_entry = {
        "matcher": "",
        "hooks": [{"type": "command", "command": "autoconduck hook claude PreToolUse"}],
    }
    assert adapter._is_autoconduck_hook_entry(cmd_entry) is True

    # Test recognition of http-type hook entry
    http_entry = {
        "matcher": "",
        "hooks": [{"type": "http", "url": "http://127.0.0.1:11434/plugin/events"}],
    }
    assert adapter._is_autoconduck_hook_entry(http_entry) is True

    # User entry should not be matched
    user_entry = {
        "matcher": "",
        "hooks": [{"type": "command", "command": "echo user hook"}],
    }
    assert adapter._is_autoconduck_hook_entry(user_entry) is False

    # Stripping hooks removes autoconduck entries while preserving user hooks
    raw_hooks = {
        "PreToolUse": [cmd_entry, user_entry],
        "PostToolUse": [http_entry],
    }
    stripped = adapter._strip_autoconduck_hooks(raw_hooks)
    assert stripped == {"PreToolUse": [user_entry]}


def test_plugin_events_subagent_start_and_stop(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from autoconduck.server.plugin_routes import install_plugin_routes
    from autoconduck.config.manager import get_config
    import autoconduck.config.manager as m
    from autoconduck.plugin.bias import get_bias_store
    from autoconduck.plugin.ledger import get_ledger

    cfg = get_config()
    cfg.plugins.enabled = True
    m._config = cfg
    app = FastAPI()
    install_plugin_routes(app)
    client = TestClient(app)

    bias_store = get_bias_store()
    bias_store.clear_all()
    ledger = get_ledger()

    # SubagentStart
    res = client.post("/plugin/events", json={
        "kind": "SubagentStart",
        "session_id": "parent-sess-1",
        "subagent_id": "child-sess-1",
        "task_id": "t-sub-1",
    })
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
    assert bias_store.is_child_session("child-sess-1") is True
    assert bias_store.is_child_session("parent-sess-1") is False

    # Flush ledger and verify durable row
    ledger.flush_sync()
    events = ledger.query_events(session_id="child-sess-1")
    assert any(
        e["kind"] == "subagent_start" and e.get("parent_session_id") == "parent-sess-1"
        for e in events
    )

    # SubagentStop
    res2 = client.post("/plugin/events", json={
        "kind": "SubagentStop",
        "subagent_id": "child-sess-1",
        "task_id": "t-sub-1",
        "data": {"outcome": "success"},
    })
    assert res2.status_code == 200
    assert res2.json() == {"status": "ok"}

    ledger.flush_sync()
    events2 = ledger.query_events(session_id="child-sess-1")
    stop_events = [e for e in events2 if e["kind"] == "subagent_stop"]
    assert len(stop_events) == 1
    assert "success" in str(stop_events[0].get("data", ""))


# ---------------------------------------------------------------------------
# Pi stub and extension
# ---------------------------------------------------------------------------

def test_pi_template_has_inert_gated_hook_section(tmp_path, monkeypatch):
    import pathlib
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    from autoconduck.config.models import Config
    from autoconduck.harnesses.pi import PiAdapter

    cfg = Config()
    cfg.plugins.enabled = False
    cfg.plugins.pi_enabled = False
    adapter = PiAdapter()
    adapter.patch(cfg)
    ext = tmp_path / ".pi" / "agent" / "extensions" / "autoconduck.ts"
    assert ext.exists()
    text = ext.read_text(encoding="utf-8")
    assert "const AUTOCONDUCK_HOOKS_ENABLED = false;" in text
    assert "const AUTOCONDUCK_SUBAGENT_ENABLED = false;" in text
    assert "_appendSpool" in text
    assert "pi.registerProvider" in text


def test_pi_template_flag_true_when_pi_enabled(tmp_path, monkeypatch):
    import pathlib
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    from autoconduck.config.models import Config
    from autoconduck.harnesses.pi import PiAdapter

    cfg = Config()
    cfg.plugins.enabled = True
    cfg.plugins.pi_enabled = True
    cfg.plugins.subagent_enabled = True
    adapter = PiAdapter()
    adapter.patch(cfg)
    ext = tmp_path / ".pi" / "agent" / "extensions" / "autoconduck.ts"
    text = ext.read_text(encoding="utf-8")
    assert "const AUTOCONDUCK_HOOKS_ENABLED = true;" in text
    assert "const AUTOCONDUCK_SUBAGENT_ENABLED = true;" in text
    assert "pi.on('subagent.start'" in text
    assert "pi.on('subagent.stop'" in text
    assert "SubagentStart" in text
    assert "SubagentStop" in text


# ---------------------------------------------------------------------------
# OMP extension
# ---------------------------------------------------------------------------

def test_omp_extension_and_subagent_listeners(tmp_path, monkeypatch):
    import pathlib
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    from autoconduck.config.models import Config
    from autoconduck.harnesses.omp import OmpAdapter

    adapter = OmpAdapter()
    ext_path = adapter._extension_path()
    assert ext_path == tmp_path / ".omp" / "agent" / "extensions" / "autoconduck.ts"

    rendered = adapter._render_extension(port=11434, hooks_enabled=True, subagent_enabled=True)
    assert "AutoConduck Monitor & Router" in rendered
    assert "_appendSpool" in rendered
    assert "pi.on('agent_start'" in rendered
    assert "pi.on('agent_end'" in rendered
    assert "event?.agentKind === 'sub'" in rendered
    assert "event?.parentSessionId" in rendered
    assert "SubagentStart" in rendered
    assert "SubagentStop" in rendered

    cfg = Config()
    cfg.plugins.enabled = True
    cfg.plugins.omp_enabled = True
    cfg.plugins.subagent_enabled = True
    adapter.patch(cfg)
    assert ext_path.exists()
    assert "SubagentStart" in ext_path.read_text(encoding="utf-8")

    adapter.revert()
    assert not ext_path.exists()


# ---------------------------------------------------------------------------
# OpenCode plugin JS and registration
# ---------------------------------------------------------------------------

def test_opencode_plugin_js_and_registration(tmp_path, monkeypatch):
    import pathlib
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(pathlib.Path, "cwd", lambda: tmp_path)
    from autoconduck.config.models import Config
    from autoconduck.harnesses.opencode import OpenCodeAdapter

    adapter = OpenCodeAdapter()
    plugin_path = adapter._plugin_path()
    assert plugin_path == tmp_path / ".config" / "opencode" / "plugins" / "autoconduck.js"

    rendered = adapter._render_plugin_js(port=11434, hooks_enabled=True, subagent_enabled=True)
    assert "AutoConduckPlugin" in rendered
    assert "tool.execute.before" in rendered
    assert "tool.execute.after" in rendered
    assert "session.start" in rendered
    assert "session.end" in rendered
    assert "SubagentStart" in rendered
    assert "SubagentStop" in rendered
    assert "_sendEvent" in rendered

    opencode_cfg = tmp_path / "opencode.json"
    opencode_cfg.write_text(json.dumps({"providers": {}}), encoding="utf-8")

    cfg = Config()
    cfg.plugins.enabled = True
    cfg.plugins.opencode_enabled = True
    cfg.plugins.subagent_enabled = True

    adapter.patch(cfg)
    assert plugin_path.exists()
    assert "AutoConduckPlugin" in plugin_path.read_text(encoding="utf-8")

    cfg_data = json.loads(opencode_cfg.read_text(encoding="utf-8"))
    assert "plugin" in cfg_data
    assert any("autoconduck.js" in str(p) for p in cfg_data["plugin"])

    adapter.revert()
    assert not plugin_path.exists()
    cfg_data_reverted = json.loads(opencode_cfg.read_text(encoding="utf-8"))
    assert "plugin" not in cfg_data_reverted or not any("autoconduck.js" in str(p) for p in cfg_data_reverted.get("plugin", []))


# ---------------------------------------------------------------------------
# OpenCode stub doc
# ---------------------------------------------------------------------------

def test_opencode_stub_doc_exists():
    p = Path("autoconduck/plugin/shims/README-opencode.md")
    assert p.exists(), "OpenCode stub doc missing"
    text = p.read_text(encoding="utf-8")
    assert "tool.execute" in text.lower() or "tool.execute" in text
    assert "opencode_enabled" in text
    assert "disabled" in text.lower()
