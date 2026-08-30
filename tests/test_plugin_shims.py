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
    for ev in ("PreToolUse", "PostToolUse", "Stop"):
        assert ev in hooks
        # at least one entry whose command contains autoconduck hook
        found = any(
            "autoconduck hook claude" in str(h.get("command", ""))
            for entry in hooks[ev]
            for h in (entry.get("hooks") or [])
        )
        assert found, f"missing hook command for {ev}"
    # marker present
    assert data.get("autoconduck", {}).get("hooks_enabled") is True


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
                        assert "autoconduck hook claude" not in str(h.get("command", ""))


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
                        assert "autoconduck hook claude" not in str(h.get("command", ""))


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
        "autoconduck hook claude" in str(h.get("command", ""))
        for entries in (data.get("hooks") or {}).values()
        if isinstance(entries, list)
        for entry in entries
        for h in (entry.get("hooks") or [])
    )


# ---------------------------------------------------------------------------
# Pi stub
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
    assert "pi.registerProvider" in text
    # not enabled → flag false
    assert text.count("AUTOCONDUCK_HOOKS_ENABLED") >= 1


def test_pi_template_flag_true_when_pi_enabled(tmp_path, monkeypatch):
    import pathlib
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    from autoconduck.config.models import Config
    from autoconduck.harnesses.pi import PiAdapter

    cfg = Config()
    cfg.plugins.enabled = True
    cfg.plugins.pi_enabled = True
    adapter = PiAdapter()
    adapter.patch(cfg)
    ext = tmp_path / ".pi" / "agent" / "extensions" / "autoconduck.ts"
    text = ext.read_text(encoding="utf-8")
    assert "const AUTOCONDUCK_HOOKS_ENABLED = true;" in text


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
