# Phase 3 — Harness Shims Report

Date: 2026-08-30
Branch: two-plane
Commits: phase 2 `3eb786b`, phase 3 (this phase) pending

## Scope
Per `TWO_PLANE_PLAN.md` Phase 3 — per-harness shims, thin and toggled by `plugins.enabled`:
- Claude Code hook shim shipped (observe-only, fails inert).
- Pi / OpenCode stubbed behind disabled flags.

## Files

| File | Action | Notes |
|---|---|---|
| `autoconduck/cli/hook.py` | **new** | `cmd_hook` — stdin JSON (tool_name/session_id) → `~/.autoconduck/run/plugin_spool.jsonl` append (`O_APPEND`, single write), always exit 0. No config load / network / daemon call. Honest scope note in docstring: interpreter startup (~30-80ms) outside <10ms handler budget; handler itself <10ms. |
| `autoconduck/cli/cli.py` | edit | Import `cmd_hook`, register `autoconduck hook <harness> <event>` subparser. Follows existing `sub.add_parser(...).set_defaults(handler=...)` pattern. |
| `autoconduck/plugin/spool.py` | **new** | `SpoolTailer` async tailer — polls `plugin_spool.jsonl` by byte offset, robust to truncate/rotation (size < offset or inode change → reset 0). Converts each JSONL line to in-memory telemetry `ledger.count_in_memory(session_id, "hook:<event>")` + `"hook"`. Telemetry-only (not durable). Fail-soft: all errors log+continue. `start_tailer()` only when `plugins.enabled`. Daemon lifecycle wired via `server_streaming._build()` lifespan (`ledger.start()` + `start_tailer()` on startup, `stop_tailer()` + `ledger.stop()` on shutdown). |
| `autoconduck/server/server_streaming.py` | edit | Install async lifespan that starts ledger flusher + spool tailer when enabled, stops both on shutdown. Never blocks app construction. |
| `autoconduck/harnesses/claude_code.py` | edit | `patch()` now adds `hooks` block inside managed `autoconduck` marker only when `cfg.plugins.enabled && cfg.plugins.claude_enabled`. `hooks = {PreToolUse, PostToolUse, Stop: [{matcher:"", hooks:[{type:"command", command:"autoconduck hook claude <Event>"}]}]}` — observe-only. Merge is idempotent, preserves user hooks (strips old managed entries before re-adding). `previous_hooks` snapshotted on first takeover. `revert()` restores `previous_hooks` or strips managed entries. When flags off → hooks block absent (byte-identical to pre-plugin for never-enabled installs). Respects existing `backups_dir("claude_code")` + marker invariant. |
| `autoconduck/harnesses/pi.py` | edit | `_render_extension(hooks_enabled)` now emits `const AUTOCONDUCK_HOOKS_ENABLED = false;` (default) + inert `if (AUTOCONDUCK_HOOKS_ENABLED) { /* planned tool.execute hook */ }` block. Provider registration unchanged. `patch()` sets flag true only when `plugins.enabled && plugins.pi_enabled`; regeneration flips it. Documents that wiring is deferred. |
| `autoconduck/plugin/shims/README-opencode.md` | **new** | Document-only stub: planned `tool.execute` hook plugin → spool append, disabled behind `plugins.opencode_enabled=false`, no install changes (`OpenCodeAdapter.patch()` untouched). Marker/backup invariant noted. |
| `tests/test_plugin_shims.py` | **new** | Hook handler: stdin JSON→spool line, empty stdin→exit 0+valid line, malformed JSON→exit 0, spool under `run_dir`, CLI wiring `autoconduck hook claude <Event>`, spool-error still exit 0, unknown args still exit 0. Tailer: writes→counted telemetry, truncate robustness, disabled→no tailer (async). Claude patch: hooks present when enabled (inside markers), absent when disabled, revert cleans. Pi: inert gated section false/true. OpenCode doc exists & mentions `tool.execute` + flag. |

## Hook overhead note

`autoconduck hook claude <Event>` handler budget:
- Interpreter startup is **outside** the <10ms handler budget (OS spawn + Python import ~30-80ms; unavoidable for a Python CLI hook, bounded to one `open(O_APPEND)+write` syscall).
- Handler-internal work (read stdin, parse JSON, `os.open(O_APPEND)+os.write`) is <10ms on warm FS (single syscall-append, no config load, no network, no daemon call).
- Hook never needs the daemon → fails inert by construction (spool file is the decoupling point; hook appends and returns 0 even if daemon down; tailer later drains on daemon start). PreToolUse nonzero would block tool execution in Claude Code — handler never does.

## Spool-file design rationale

- Hook must never block tool execution → avoid localhost HTTP/queue with timeout.
- File append (`O_APPEND`) is atomic on POSIX/Win, no daemon dependency, bounded cost, crash-safe.
- Daemon tailer drains lazily (poll 0.5s) → hook latency decoupled from ledger/bias/LLM.
- Rotation/truncate robust (size<offset or inode change → reset), malformed lines skipped, telemetry-only (not durable) so spool loss does not affect recovery.

## Shim contracts (Phase 4 smoke)

- **Claude Code:** `autoconduck install claude_code` with `plugins.enabled && plugins.claude_enabled` → `~/.claude/settings.json` contains `hooks.{PreToolUse,PostToolUse,Stop}` each with `autoconduck hook claude <Event>` command inside `autoconduck` marker section; `autoconduck reset` / `ClaudeCodeAdapter.revert()` removes them cleanly, restores `previous_hooks` snapshot (backups preserved). Flags off → hooks absent.
- **Pi:** `autoconduck install pi` always registers provider; extension `autoconduck.ts` contains `const AUTOCONDUCK_HOOKS_ENABLED = <bool>` — `false` in v1, `true` after Phase 4 when `plugins.pi_enabled` flips (regeneration). Provider block unchanged.
- **OpenCode:** No code change in Phase 3; doc `autoconduck/plugin/shims/README-opencode.md` describes planned `tool.execute` → spool plugin behind `plugins.opencode_enabled` false.

## Pytest tail (expected)

```
python -m pytest -q
# 244 inherited + ~16 new in test_plugin_shims.py + prior phase 2 suite
# all green
```

Actual tail recorded after run (see verification below).

## Verification

- [x] `python -m pytest` — 262 passed, 4 skipped, 1 warning (15.5s).
- [x] `autoconduck hook claude PostToolUse` with/without stdin JSON → spool line + exit 0.
- [x] `graphify update .` attempted.

## Design decisions

- Spool path via `config.paths.run_dir()` (respects `AUTOCONDUCK_HOME`) with fallback to `~/.autoconduck/run`.
- Hook record schema minimal: `{ts,harness,event,tool_name?,session_id?}` — extensible, no prompt content (privacy).
- Tailer offset initialized to current file size on daemon start (no replay of ancient spool on restart; only new lines counted).
- Ledger telemetry path: `count_in_memory` (per-session `hook:<event>` + `hook`) — not `enqueue` durable kinds.

## Blockers

None.
