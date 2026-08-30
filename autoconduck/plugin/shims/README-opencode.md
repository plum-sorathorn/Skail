# OpenCode shim — planned hook integration (Phase 3 stub)

Status: **document-only** this phase. No code changes to `autoconduck/harnesses/opencode.py`
are shipped in Phase 3 (`opencode patch()` untouched).

## Plan (deferred to a later phase)

- OpenCode exposes a hook/plugin surface (`tool.execute` lifecycle hook) via its
  plugin config (`opencode.json` → `plugin` / `hooks` field, exact key TBD against
  shipped OpenCode docs at implementation time).
- The shim will register a single hook plugin entry:

  ```json
  {
    "plugin": "autoconduck-hook",
    "entry": "~/.autoconduck/run/opencode-hook.mjs",
    "config": { "endpoint": "plugin_spool.jsonl" }
  }
  ```

  The plugin itself appends one JSONL line to `~/.autoconduck/run/plugin_spool.jsonl`
  per tool execution (observe-only, 5–10ms timeout, drop on failure), mirroring the
  Claude Code hook handler contract.

- The hook is **disabled behind a flag**:

  ```yaml
  plugins:
    enabled: false
    opencode_enabled: false
  ```

  Both must be `true` for the `patch()` to inject the plugin field; otherwise the
  generated `opencode.json` is byte-identical to the current Phase 2 output
  (marker-bounded managed section respected, backups preserved).

- Hook events are **telemetry-only** (in-memory counts via `ledger.count_in_memory`),
  not durable ledger rows — same as Claude Code hook events in v1.

## Non-goals this phase

- No runtime hook file is written.
- No change to `OpenCodeAdapter.patch()` / `revert()` behavior.
- No extra dependency.

## Verification (when implemented)

- `autoconduck install opencode` with `plugins.enabled && plugins.opencode_enabled`
  injects the plugin block inside `# BEGIN/END AUTOCONDUCK` markers; `revert()` removes it.
- Disabled → byte-identical to Phase 2 install.
- Daemon down → hook plugin silently no-ops (drop).
