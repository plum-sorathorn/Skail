# AutoConduck Plugin Plane — Feature Plan (Revised)

**Status:** Draft v2 — awaiting approval  
**Date:** 2026-08-31  
**Changes from v1:** (1) leaf-agent routing uses tier selection, not dollar cap; (2) RAG on by default when plugin enabled; (3) OMP and OpenCode fully implemented with native extension files — no deferrals.

---

## Overview

Four work streams, all implemented fully across all four harnesses:

1. **Plugin Plane Transport Modernization** — eliminate Python spawn overhead on hooks
2. **Native Subagent Orchestration** — observe and route subagent fan-outs using harness-native extension APIs
3. **RAG-as-MCP Tool** — expose the knowledge subsystem as a local MCP server, on by default
4. **Wiring & Harness Visibility** — end-to-end install, onboarding, and in-harness discoverability for all four harnesses

---

## Part 1 — Plugin Plane Transport Modernization

### Current State

[`ClaudeCodeAdapter`](file:///C:/Users/plum/Documents/Works/AutoConduck/autoconduck/harnesses/claude_code.py#L34) registers hooks that execute `autoconduck hook claude <Event>` — a Python subprocess spawn (~30–80ms per tool call). There is also a dual-ingestion inconsistency: the spool tailer and `POST /plugin/events` are parallel, redundant paths.

### Changes

#### 1.1 Switch Claude Code Hooks from `command` to `http`

Claude Code's native `"type": "http"` hook type posts directly to our daemon with a configurable timeout. Update `_build_hooks_block()` to accept the port and emit HTTP hooks:

```python
HOOK_EVENTS = ("PreToolUse", "PostToolUse", "Stop", "SubagentStart", "SubagentStop")

def _build_hooks_block(self, port: int = 11434) -> dict:
    hooks: dict[str, list[dict]] = {}
    for ev in self.HOOK_EVENTS:
        label = "AutoConduck Subagent Tracker" if "Subagent" in ev else "AutoConduck Monitor"
        hooks[ev] = [{"matcher": "", "hooks": [{
            "type": "http",
            "url": f"http://127.0.0.1:{port}/plugin/events",
            "timeoutMs": 10,
            "_name": label,
        }]}]
    return hooks
```

`timeoutMs: 10` ensures the hook never blocks the agent loop if AutoConduck is down — matching the fail-soft invariant exactly.

**Fallback:** If the user's Claude Code version does not support `"type": "http"`, fall back to `"type": "command"` with `autoconduck hook claude <event>`. The `hook.py` CLI entrypoint is retained; do not delete it.

#### 1.2 Consolidate Ingestion Paths

With HTTP hooks, the spool file is no longer the primary path for Claude Code. The canonical path is:

```
POST /plugin/events → PluginLedger.enqueue() / count_in_memory()
```

- [`SpoolTailer`](file:///C:/Users/plum/Documents/Works/AutoConduck/autoconduck/plugin/spool.py) stays active as the fallback for any harness using CLI-based hooks (old Claude Code, Pi, OMP via extension spool append).
- Add `"ingestion_path": "http" | "spool"` to the `autoconduck` marker object written into each harness config.
- Emit a startup log line per harness showing which path is active.

#### 1.3 Internal Executor Scope Guard

Enforce at the `start_task()` level that the internal executor is a headless evaluation path only, not a production path:

```python
# autoconduck/plugin/runtime.py — top of start_task()
if not getattr(getattr(cfg, "plugins", None), "execute_enabled", False):
    return {"status": "disabled", "error": "execute_enabled must be true to use internal executor."}
```

---

## Part 2 — Native Subagent Orchestration

### Approach: Observe & Route, Not Spawn

AutoConduck does not spawn or manage subagents. Harnesses handle execution. Our value is:

1. **Observability** — record parent–child session relationships in the ledger.
2. **Tier Routing** — automatically route child sessions to a cheaper pseudo-model tier.
3. **Isolated Escalation** — stagnation in a child raises only that child's floor, not the parent's.

### Changes

#### 2.1 Subagent Routing — Tier-Based, Not Dollar-Capped

**The previous plan had a `subagent_budget_cap_mtok: float` config field (a dollar-per-Mtok ceiling). This is removed.**

Instead, child sessions are automatically routed as if they requested `autoconduck-budget`. This maps to the existing tier logic already in [`dispatcher._tier_from_pseudo()`](file:///C:/Users/plum/Documents/Works/AutoConduck/autoconduck/routing/dispatcher.py#L136) — no new concept, just automatic tier selection for known child sessions.

```python
# In dispatcher._select_planned():
effective_pseudo = pseudo_model
if session_id and bias_store.is_child_session(session_id):
    # Downgrade child sessions to budget tier automatically
    effective_pseudo = "autoconduck-budget"
modified_sla = replace(sla, task_type=getattr(plan, "task_type", None))
return pricing.select_for_sla_detailed(modified_sla, config=config, pseudo_model=effective_pseudo)
```

The master coordinator, using `autoconduck` or `autoconduck-expensive`, is unaffected. If a child session stagnates and triggers the escalation bias, `SessionBiasStore.apply_escalation()` raises that child's capability floor — still within the budget tier unless the floor bump forces it up to a better model. This is the correct and safe behavior.

This is O(1), in-memory, on the existing hot path.

#### 2.2 Session Hierarchy in `PluginLedger`

Add `parent_session_id TEXT` column to the SQLite events table via a schema migration. When a `SubagentStart` event arrives at `/plugin/events`:

```python
# autoconduck/server/plugin_routes.py
if kind == "SubagentStart":
    parent_id = str(body.get("session_id") or "")
    child_id = str(body.get("subagent_id") or "")
    if parent_id and child_id:
        bias_store.register_child_session(child_id, parent_id)
        ledger.enqueue(child_id, task_id, "subagent_start",
                       {"parent_session_id": parent_id},
                       parent_session_id=parent_id)
elif kind == "SubagentStop":
    child_id = str(body.get("subagent_id") or body.get("session_id") or "")
    outcome = body.get("data", {}).get("outcome") if isinstance(body.get("data"), dict) else None
    ledger.enqueue(child_id, task_id, "subagent_stop",
                   {"outcome": str(outcome or "unknown")})
```

#### 2.3 `SessionBiasStore` Extensions

Add two methods to [`SessionBiasStore`](file:///C:/Users/plum/Documents/Works/AutoConduck/autoconduck/plugin/bias.py#L16):

```python
def register_child_session(self, child_id: str, parent_id: str) -> None:
    """Register child_id as a child of parent_id. O(1) write, thread-safe."""
    with self._lock:
        self._children[str(child_id)] = str(parent_id)

def is_child_session(self, session_id: str | None) -> bool:
    """Return True if session_id is a known child session. O(1), non-blocking."""
    if not session_id:
        return False
    with self._lock:
        return str(session_id) in self._children
```

Child sessions are cleared from `_children` on `reset_session()`. If daemon restarts, the mapping is lost and children fall back to default routing — safe and correct.

#### 2.4 Claude Code — `SubagentStart` / `SubagentStop` Hooks

Already covered in Part 1.1 by adding those events to `HOOK_EVENTS`. Claude Code's `Task` tool fires them natively. The HTTP hook payload from Claude Code includes `session_id` (parent) and `subagent_id` (child). No further changes needed on the Claude Code adapter.

#### 2.5 Pi — Subagent Lifecycle via Extension EventBus

Update [`PiAdapter._render_extension()`](file:///C:/Users/plum/Documents/Works/AutoConduck/autoconduck/harnesses/pi.py#L98) to emit subagent lifecycle hooks when `subagent_enabled` is true:

```typescript
if (AUTOCONDUCK_SUBAGENT_ENABLED) {
  pi.on('subagent.start', (event: { parentId: string; childId: string }) => {
    _appendSpool({ event: 'SubagentStart', session_id: event.parentId, subagent_id: event.childId });
  });
  pi.on('subagent.stop', (event: { parentId: string; childId: string; outcome?: string }) => {
    _appendSpool({ event: 'SubagentStop', session_id: event.parentId, subagent_id: event.childId, outcome: event.outcome ?? 'unknown' });
  });
}
```

`_appendSpool()` is a small synchronous helper rendered inline in the TS file: opens the spool path with `fs.appendFileSync`, writes one JSON line, catches all errors silently. Exit-0-always pattern, <10ms.

#### 2.6 OMP — Subagent Lifecycle via Extension EventBus

OMP's extension system is an in-process TypeScript EventBus via `pi.on()` (same API as Pi, compatible fork). OMP distinguishes `agent_start`/`agent_end` for subagents.

[`OmpAdapter`](file:///C:/Users/plum/Documents/Works/AutoConduck/autoconduck/harnesses/omp.py) gets a new method: `_extension_path()` returning `~/.omp/agent/extensions/autoconduck.ts`, and the adapter emits a TypeScript extension file on `patch()` (same as Pi does today).

```typescript
// Rendered into ~/.omp/agent/extensions/autoconduck.ts
if (AUTOCONDUCK_SUBAGENT_ENABLED) {
  pi.on('agent_start', (event: { agentKind: string; sessionId: string; parentSessionId?: string }) => {
    if (event.agentKind === 'sub' && event.parentSessionId) {
      _appendSpool({ event: 'SubagentStart', session_id: event.parentSessionId, subagent_id: event.sessionId });
    }
  });
  pi.on('agent_end', (event: { agentKind: string; sessionId: string; parentSessionId?: string; outcome?: string }) => {
    if (event.agentKind === 'sub' && event.parentSessionId) {
      _appendSpool({ event: 'SubagentStop', session_id: event.parentSessionId, subagent_id: event.sessionId, outcome: event.outcome ?? 'unknown' });
    }
  });
}
```

> [!NOTE]
> OMP's docs note that `agentKind` exposure in lifecycle events is under active development. The `if (event.agentKind === 'sub')` guard ensures we only act on subagent events and silently pass on all others. This degrades gracefully if `agentKind` is missing.

#### 2.7 OpenCode — Subagent Lifecycle via Plugin SDK

OpenCode's `@opencode-ai/plugin` SDK supports the `event` hook with session and tool events. OpenCode's subagents are invoked as named agents (`@Scout`, `@Explore`). The SDK surfaces these as `session.start`/`session.end` events with a `parentSessionId` field.

[`OpenCodeAdapter`](file:///C:/Users/plum/Documents/Works/AutoConduck/autoconduck/harnesses/opencode.py) gets a new method: `_plugin_path()` returning `~/.config/opencode/plugins/autoconduck.js` (JS for broadest runtime compat without a TS compile step). The plugin file is emitted on `patch()`.

```javascript
// Rendered into ~/.config/opencode/plugins/autoconduck.js
export const AutoConduckPlugin = async ({ client, $ }) => {
  const ENABLED = AUTOCONDUCK_HOOKS_ENABLED;
  const SUBAGENT = AUTOCONDUCK_SUBAGENT_ENABLED;
  const RAG = AUTOCONDUCK_RAG_ENABLED;
  const BASE_URL = "http://127.0.0.1:PORT/";

  function postEvent(body) {
    if (!ENABLED) return;
    fetch(BASE_URL + "plugin/events", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(10),
    }).catch(() => {});
  }

  return {
    // Tool lifecycle hooks
    "tool.execute.before": async (input) => {
      postEvent({ kind: "tool_call", session_id: input.sessionId, data: { tool: input.tool } });
    },
    "tool.execute.after": async (input, output) => {
      postEvent({ kind: "tool_result", session_id: input.sessionId, data: { tool: input.tool, ok: !output.error } });
    },

    // Session / subagent lifecycle
    event: async ({ event }) => {
      if (!SUBAGENT) return;
      if (event.type === "session.start" && event.parentSessionId) {
        postEvent({ kind: "SubagentStart", session_id: event.parentSessionId, subagent_id: event.sessionId });
      }
      if (event.type === "session.end" && event.parentSessionId) {
        postEvent({ kind: "SubagentStop", session_id: event.parentSessionId, subagent_id: event.sessionId, data: { outcome: event.outcome ?? "unknown" } });
      }
    },

    // RAG tool
    ...(RAG ? {
      tool: {
        autoconduck_search: {
          description: "Search the indexed codebase for symbols, functions, and documentation (AutoConduck local knowledge base)",
          args: { query: { type: "string" }, limit: { type: "number", default: 5 } },
          execute: async ({ query, limit = 5 }) => {
            const res = await fetch(BASE_URL + "mcp/tools/call", {
              method: "POST",
              headers: { "content-type": "application/json" },
              body: JSON.stringify({ tool: "autoconduck_search", args: { query, limit } }),
              signal: AbortSignal.timeout(3000),
            });
            return res.ok ? res.json() : { error: "autoconduck search unavailable" };
          },
        },
      },
    } : {}),
  };
};
```

The plugin is registered in `opencode.json` under the `"plugin"` key:
```json
{
  "plugin": ["~/.config/opencode/plugins/autoconduck.js"]
}
```

This file is written and maintained by [`OpenCodeAdapter.patch()`](file:///C:/Users/plum/Documents/Works/AutoConduck/autoconduck/harnesses/opencode.py#L34) and cleaned up by `revert()`.

---

## Part 3 — RAG-as-MCP Tool

### RAG is ON by default when `plugins.enabled = True`

`PluginConfig.rag_enabled` defaults to `True` (not `False` as in v1). Users who want pure stagnation/escalation without the knowledge index can disable it explicitly.

### Changes

#### 3.1 MCP Server Endpoint in FastAPI

New file: `autoconduck/server/mcp_routes.py`

```
GET  /mcp              → MCP manifest: server name, version, tool list
POST /mcp/tools/call   → Tool dispatch: autoconduck_search, autoconduck_index
```

The `KnowledgeVectorStore` singleton is initialized at daemon startup when `rag_enabled=True`, with `db_uri` from `SelectionConfig.rag_db_path` (default `~/.autoconduck/rag_db`).

MCP manifest response (version-pinned at `2025-03-26`):
```json
{
  "protocolVersion": "2025-03-26",
  "serverInfo": { "name": "autoconduck", "version": "0.5.0" },
  "indexed_at": "2026-08-31T...",
  "tools": [
    {
      "name": "autoconduck_search",
      "description": "Search indexed codebase symbols. Uses keyword-vector matching (not semantic embedding). Run autoconduck_index first.",
      "inputSchema": { "type": "object", "properties": { "query": {"type":"string"}, "limit": {"type":"number","default":5} }, "required": ["query"] }
    },
    {
      "name": "autoconduck_index",
      "description": "Index a directory into the AutoConduck knowledge base. Call before autoconduck_search on a new project.",
      "inputSchema": { "type": "object", "properties": { "root_dir": {"type":"string"}, "max_files": {"type":"number","default":50} }, "required": ["root_dir"] }
    }
  ]
}
```

#### 3.2 MCP Registration per Harness

**Claude Code** — `settings.json` `mcpServers` block (gated by `rag_enabled`):
```json
{ "mcpServers": { "autoconduck": { "url": "http://127.0.0.1:PORT/mcp", "type": "http" } } }
```

**OpenCode** — the `autoconduck.js` plugin (Part 2.7) already embeds `autoconduck_search` as a native plugin tool. Additionally, the `mcpServers` block is written into `opencode.json` when `rag_enabled`:
```json
{ "mcp": { "autoconduck": { "type": "http", "url": "http://127.0.0.1:PORT/mcp" } } }
```

**Pi** — `autoconduck_search` is registered as a tool in `autoconduck.ts` (emitted by `PiAdapter`) via `pi.registerTool()` when `rag_enabled AND pi_enabled`:
```typescript
if (AUTOCONDUCK_RAG_ENABLED) {
  pi.registerTool('autoconduck_search', {
    description: 'Search the AutoConduck indexed knowledge base for codebase symbols.',
    inputSchema: { query: { type: 'string' }, limit: { type: 'number', default: 5 } },
    handler: async (args) => {
      const res = await fetch(`http://127.0.0.1:${PORT}/mcp/tools/call`, {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ tool: 'autoconduck_search', args }),
        signal: AbortSignal.timeout(3000),
      });
      return res.ok ? res.json() : { error: 'autoconduck unavailable' };
    }
  });
}
```

**OMP** — same pattern as Pi (same API surface), registered in `autoconduck.ts` via `pi.registerTool()`.

#### 3.3 Embedding Quality — Honest Disclosure

The current [`_embed_text()`](file:///C:/Users/plum/Documents/Works/AutoConduck/autoconduck/knowledge/extractor.py#L29) uses a 16-dimensional MD5 hash vector — fast keyword matching, not semantic search. This is explicitly documented in the MCP manifest description, the TUI onboarding description, and in `docs/design/rag-subsystem.md`.

Upgrade path (gated, off by default): when `SelectionConfig.rag_embedding_model` is set to a valid ONNX model path, the `_compat/onnx_fallback.py` runtime loads it for real sentence embeddings. No code path change required in the MCP layer — only `_embed_text()` changes.

---

## Part 4 — Wiring, Onboarding & Harness Visibility

### 4.1 `PluginConfig` Changes

```python
class PluginConfig(BaseModel):
    enabled: bool = False
    claude_enabled: bool = False
    pi_enabled: bool = False
    opencode_enabled: bool = False
    omp_enabled: bool = False          # NEW — was missing; OMP now fully supported
    ledger_retention_days: int = 30
    escalation_ttl_turns: int = 10
    escalation_floor_bump: float = 0.15
    llm_synthesis_enabled: bool = False
    execute_enabled: bool = False
    subagent_enabled: bool = False     # gates subagent hooks + tier routing
    rag_enabled: bool = True           # ON by default when plugin is enabled
```

### 4.2 `SelectionConfig` Changes

```python
class SelectionConfig(BaseModel):
    # ... existing fields unchanged ...
    rag_embedding_model: str = ""      # empty = 16-dim hash fallback; path = ONNX model
```

Note: `subagent_budget_cap_mtok` is **removed** from v1. Tier routing handles this without a dollar cap.

### 4.3 Onboarding Flow — `PluginSetupScreen` Updates

```
(•) Enable Plugin Runtime — Full Integration (Recommended)
    ├── [x] HTTP Hooks + Subagent Tracking (tool events, SubagentStart/Stop)
    ├── [x] Subagent Tier Routing (leaf agents auto-route to budget tier)
    ├── [x] Codebase Search Tool (local RAG via MCP — keyword-vector)
    └── [x] Stagnation Detection & Escalation Bias

( ) Enable Plugin Runtime — Stagnation & Escalation Only (No Hooks, No RAG)
( ) Disable Plugin (Pure Router Mode)
```

The `PluginSetupScreen` saves `subagent_enabled` and `rag_enabled` when "Full Integration" is selected.

### 4.4 `configure_selected_agents()` Pipeline

```python
def configure_selected_agents(agents, port=None):
    cfg = get_config()
    for aid in sorted(set(agents or ())):
        adapter = adapters.get(aid)
        adapter.patch(cfg, port=effective_port)         # provider, hooks, MCP, plugin file
        adapter.install_features()                      # extension files, manifests
        adapter.install_plugin_visibility(cfg)          # NEW: verify/write visible marker
    launcher.install_shims(configured)
```

### 4.5 Harness Visibility — Complete Map

---

#### Claude Code — `/hooks` + `/mcp`

**User sees:**
- `/hooks` → `PreToolUse`, `PostToolUse`, `Stop`, `SubagentStart`, `SubagentStop` each show `AutoConduck Monitor` / `AutoConduck Subagent Tracker`
- `/mcp` → `autoconduck` listed as a connected HTTP MCP server

**Written into `~/.claude/settings.json`:**
```json
{
  "hooks": {
    "PreToolUse":    [{"matcher":"","hooks":[{"type":"http","url":"http://127.0.0.1:PORT/plugin/events","timeoutMs":10,"_name":"AutoConduck Monitor"}]}],
    "PostToolUse":   [{"matcher":"","hooks":[{"type":"http","url":"http://127.0.0.1:PORT/plugin/events","timeoutMs":10,"_name":"AutoConduck Monitor"}]}],
    "Stop":          [{"matcher":"","hooks":[{"type":"http","url":"http://127.0.0.1:PORT/plugin/events","timeoutMs":10,"_name":"AutoConduck Monitor"}]}],
    "SubagentStart": [{"matcher":"","hooks":[{"type":"http","url":"http://127.0.0.1:PORT/plugin/events","timeoutMs":10,"_name":"AutoConduck Subagent Tracker"}]}],
    "SubagentStop":  [{"matcher":"","hooks":[{"type":"http","url":"http://127.0.0.1:PORT/plugin/events","timeoutMs":10,"_name":"AutoConduck Subagent Tracker"}]}]
  },
  "mcpServers": {
    "autoconduck": { "url": "http://127.0.0.1:PORT/mcp", "type": "http" }
  }
}
```

**Gates:** Hooks → `plugins.enabled AND plugins.claude_enabled`. MCP block → additionally `plugins.rag_enabled`.  
**Fallback:** `"type": "command"` with `autoconduck hook claude <event>` for older Claude Code.  
**Revert:** All hooks and `mcpServers.autoconduck` stripped by `revert()`.  
**Managed by:** [`ClaudeCodeAdapter`](file:///C:/Users/plum/Documents/Works/AutoConduck/autoconduck/harnesses/claude_code.py)

---

#### Pi — Extension File + `/tools`

**User sees:**
- `~/.pi/agent/extensions/autoconduck.ts` is listed in Pi's extension directory
- `/provider` shows `AutoConduck Monitor & Router` with pseudo-models
- `/tools` shows `autoconduck_search` (when `rag_enabled`)

**Written by `PiAdapter.patch()`:**
- `~/.pi/agent/extensions/autoconduck.ts` — provider registration, subagent event listeners, `autoconduck_search` tool
- `~/.pi/agent/settings.json` — `defaultProvider`, `defaultModel`

**Extension file header:**
```typescript
// AutoConduck Monitor & Router — managed by autoconduck v0.5.0
// Provides: provider routing, subagent tracking, codebase search
// Reinstall: autoconduck install pi
// Remove:    autoconduck uninstall pi
```

**Gates:** Subagent hooks → `plugins.pi_enabled AND plugins.subagent_enabled`. RAG tool → `plugins.pi_enabled AND plugins.rag_enabled`.  
**Revert:** Delete `autoconduck.ts`. Strip `defaultProvider`/`defaultModel` from `settings.json`.  
**Managed by:** [`PiAdapter`](file:///C:/Users/plum/Documents/Works/AutoConduck/autoconduck/harnesses/pi.py)

---

#### OpenCode — Plugin File + `/mcp` + Provider List

**User sees:**
- `/plugins` or `~/.config/opencode/plugins/` → `autoconduck.js` visible
- Provider picker shows `AutoConduck Monitor & Router`
- `/mcp` shows `autoconduck` MCP server
- `/tools` shows `autoconduck_search` tool (from the plugin, not MCP)

**Written by `OpenCodeAdapter.patch()`:**
- `~/.config/opencode/plugins/autoconduck.js` — full plugin file (hooks + subagent events + RAG tool)
- `opencode.json` — `provider.autoconduck`, `plugin: ["~/.config/opencode/plugins/autoconduck.js"]`, `mcp.autoconduck` (when `rag_enabled`)

**Plugin file header:**
```javascript
// AutoConduck Monitor & Router — managed by autoconduck v0.5.0
// Provides: tool monitoring hooks, subagent tracking, codebase search (autoconduck_search)
// Reinstall: autoconduck install opencode
// Remove:    autoconduck uninstall opencode
```

**Gates:** Plugin file always emitted when `opencode_enabled`. Subagent section active when `subagent_enabled`. RAG tool active when `rag_enabled`.  
**Revert:** Delete `autoconduck.js`. Strip `provider.autoconduck`, `plugin` entry, `mcp.autoconduck` from `opencode.json`.  
**New methods on `OpenCodeAdapter`:** `_plugin_path()`, `_render_plugin_js(cfg, port)`, `install_plugin_visibility(cfg)`.  
**Managed by:** [`OpenCodeAdapter`](file:///C:/Users/plum/Documents/Works/AutoConduck/autoconduck/harnesses/opencode.py)

---

#### OMP — Extension File + `omp models list` + `/extensions` + `/tools`

**User sees:**
- `/extensions` inside OMP terminal shows `autoconduck` extension loaded
- `omp models list` shows `autoconduck` provider with `fast`, `balanced`, `frontier` models
- `omp plugin list` shows `autoconduck` (if installed via `omp plugin install`)
- `/tools` shows `autoconduck_search` (when `rag_enabled`)

**Written by `OmpAdapter.patch()`:**
- `~/.omp/agent/extensions/autoconduck.ts` — provider registration, subagent event listeners (`agent_start`/`agent_end` with `agentKind === 'sub'`), `autoconduck_search` tool
- `~/.omp/agent/models.yml` — `providers.autoconduck` with YAML comment block
- `~/.omp/agent/config.yml` — `modelRoles.default: autoconduck/balanced`

**Extension file header:**
```typescript
// AutoConduck Monitor & Router — managed by autoconduck v0.5.0
// Provides: provider routing, subagent tracking (agent_start/agent_end), codebase search
// Reinstall: autoconduck install omp
// Remove:    autoconduck uninstall omp
// Check loaded: run /extensions in OMP terminal
import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";
```

**Extension structure (OMP uses same Pi fork API):**
```typescript
export default function(pi: ExtensionAPI) {
  pi.registerProvider("autoconduck", { ... });

  const HOOKS_ENABLED = AUTOCONDUCK_HOOKS_ENABLED;
  const SUBAGENT_ENABLED = AUTOCONDUCK_SUBAGENT_ENABLED;
  const RAG_ENABLED = AUTOCONDUCK_RAG_ENABLED;

  if (HOOKS_ENABLED) {
    pi.on('tool_call', (event) => { _appendSpool({ event: 'PreToolUse', ... }); });
    pi.on('tool_result', (event) => { _appendSpool({ event: 'PostToolUse', ... }); });
  }

  if (SUBAGENT_ENABLED) {
    pi.on('agent_start', (event) => {
      if (event.agentKind === 'sub' && event.parentSessionId) {
        _appendSpool({ event: 'SubagentStart', session_id: event.parentSessionId, subagent_id: event.sessionId });
      }
    });
    pi.on('agent_end', (event) => {
      if (event.agentKind === 'sub' && event.parentSessionId) {
        _appendSpool({ event: 'SubagentStop', session_id: event.parentSessionId, subagent_id: event.sessionId });
      }
    });
  }

  if (RAG_ENABLED) {
    pi.registerTool('autoconduck_search', { ... });
  }
}
```

**Gates:** `plugins.omp_enabled AND plugins.enabled`. Subagent → `plugins.subagent_enabled`. RAG → `plugins.rag_enabled`.  
**Revert:** Delete `autoconduck.ts`, strip `providers.autoconduck` from YAML, strip `modelRoles.default` if it starts with `autoconduck/`.  
**New methods on `OmpAdapter`:** `_extension_path()`, `_render_extension(cfg, port)`, `install_plugin_visibility(cfg)`.  
**Managed by:** [`OmpAdapter`](file:///C:/Users/plum/Documents/Works/AutoConduck/autoconduck/harnesses/omp.py)

---

### 4.6 Base Adapter Changes

```python
# autoconduck/harnesses/base.py
class BaseAdapter(ABC):
    # ... existing ...
    def install_plugin_visibility(self, config) -> None:
        """Write any harness-visible plugin/extension markers. Default no-op. Override per harness."""
        pass
```

Each harness that emits an extension file (`Pi`, `OMP`, `OpenCode`) implements this to verify the file was written and is syntactically valid (basic JSON/TS check). Fail-soft: log a warning, do not raise.

---

## Part 5 — Skeptical Cross-Cut Review (Revised)

### Tier routing vs. dollar cap

Tier routing is fundamentally cleaner. The routing engine already has `_tier_from_pseudo()` and the entire budget/balanced/frontier concept. Overriding the effective pseudo-model to `autoconduck-budget` for child sessions is a one-line change in `_select_planned()` that reuses all existing SLA gating, capability floors, and price selection logic. A numeric dollar cap would have been a parallel mechanism competing with existing logic and requiring ongoing maintenance as pricing changes. ✅

### OMP extension system is real

OMP is a Pi fork with the same `pi.on()` EventBus API plus `agent_start`/`agent_end` events that expose `agentKind`. The `agentKind === 'sub'` guard makes subagent detection deterministic. The `_appendSpool()` pattern is identical to Pi — proven safe. The only risk is that `agentKind` exposure in OMP events is noted as "under active development" — the guard handles this gracefully (no-op if field absent). ✅

### OpenCode plugin system is real

The `@opencode-ai/plugin` SDK is the official extension mechanism. Plugins are auto-discovered from `~/.config/opencode/plugins/`. The `tool.execute.before`/`tool.execute.after` interceptors and `event` hooks give us full observability. Using JS (not TS) avoids requiring a compile step. Using `fetch()` with `AbortSignal.timeout(10)` for event reporting is the exact same fail-soft pattern as Claude Code's HTTP hooks. ✅

### What could still go wrong

1. **OpenCode plugin path is global, not project-scoped.** We write to `~/.config/opencode/plugins/` which applies to all OpenCode sessions. This is correct for a routing tool (we want it always active), but users who run OpenCode against multiple projects with different needs should be aware. Document this.

2. **OMP `agentKind` field not yet stable.** Subagent detection degrades silently to no-op if the field is absent. This is acceptable — all other features (provider routing, RAG search, tool monitoring) are unaffected.

3. **`omp_enabled` was missing from `PluginConfig` in v1.** Fixed in v2. OMP was being silently skipped in `PluginSetupScreen` because there was no flag to gate on.

4. **RAG on by default means the MCP server initializes even if the user never calls `autoconduck_index`.** The server starts but searches return empty results until indexed. The MCP manifest includes `"indexed_at": null` to signal this state clearly. Agents that call `autoconduck_search` before indexing get an empty result set — not an error.

5. **OpenCode plugin registration in `opencode.json` needs to be idempotent.** The `plugin` key is an array. `OpenCodeAdapter.patch()` must check for an existing `autoconduck.js` entry and not duplicate it. Use the same marker-check pattern as hook deduplication in `ClaudeCodeAdapter`.

---

## Implementation Order

```
Phase A — Config + core data structures (no breaking changes):
  A1. PluginConfig: add subagent_enabled, rag_enabled (default True), omp_enabled
  A2. SelectionConfig: add rag_embedding_model; remove subagent_budget_cap_mtok
  A3. SessionBiasStore: add _children dict, register_child_session(), is_child_session()
  A4. PluginLedger: add parent_session_id column, schema migration, enqueue() param
  A5. dispatcher._select_planned(): add is_child_session() → effective_pseudo override

Phase B — Event ingestion + transport:
  B1. ClaudeCodeAdapter: HTTP hooks + SubagentStart/Stop, _build_mcp_block()
  B2. plugin_routes.py: SubagentStart/Stop payload parsing, register_child_session() call
  B3. PiAdapter: subagent event listeners in _render_extension(), _appendSpool helper
  B4. OmpAdapter: _extension_path(), _render_extension() — full TS extension file
  B5. OpenCodeAdapter: _plugin_path(), _render_plugin_js() — full JS plugin file

Phase C — MCP server:
  C1. server/mcp_routes.py: GET /mcp, POST /mcp/tools/call, KnowledgeVectorStore singleton
  C2. server_routes.py: mount install_mcp_routes()
  C3. ClaudeCodeAdapter + OpenCodeAdapter: MCP block in patch() and revert()
  C4. PiAdapter + OmpAdapter: autoconduck_search tool in extension file

Phase D — Onboarding + visibility:
  D1. PluginSetupScreen: new full integration options with subagent + RAG toggles
  D2. BaseAdapter: install_plugin_visibility() stub
  D3. Per-harness install_plugin_visibility() implementations
  D4. configure_selected_agents(): call install_plugin_visibility()
  D5. OmpAdapter.patch() and revert(): write + clean extension file, YAML comment

Phase E — Tests + smoke + graph:
  E1. All tests listed in §4.7
  E2. end_to_end_smoke.py assertions
  E3. graphify update .
  E4. pytest green; smoke mode B passes
```

---

## Tests Required

| Test File | Coverage |
|---|---|
| `tests/test_plugin_shims.py` | HTTP hook type in Claude Code settings; fallback command type |
| `tests/test_plugin_shims.py` | SubagentStart/Stop present when `subagent_enabled=True` |
| `tests/test_plugin_shims.py` | MCP block in Claude Code settings when `rag_enabled=True` |
| `tests/test_plugin_shims.py` | OMP extension file written by `OmpAdapter.patch()` |
| `tests/test_plugin_shims.py` | OpenCode plugin JS file written by `OpenCodeAdapter.patch()` |
| `tests/test_plugin_runtime.py` | `is_child_session()` True after `register_child_session()` |
| `tests/test_plugin_runtime.py` | Dispatcher uses `autoconduck-budget` tier for child sessions |
| `tests/test_plugin_runtime.py` | Escalation bump applies to child session only, not parent |
| `tests/test_rag_node.py` | `GET /mcp` returns valid manifest with `indexed_at` field |
| `tests/test_rag_node.py` | `POST /mcp/tools/call` with `autoconduck_search` returns results |
| `tests/test_rag_node.py` | `POST /mcp/tools/call` with `autoconduck_index` runs and reports count |
| `tests/test_rag_node.py` | Empty index returns empty results (not error) |
| `tests/test_agent_adapters.py` | `revert()` removes MCP block from Claude Code + OpenCode |
| `tests/test_agent_adapters.py` | `revert()` removes SubagentStart/Stop hooks from Claude Code |
| `tests/test_agent_adapters.py` | `revert()` deletes OMP extension file |
| `tests/test_agent_adapters.py` | `revert()` deletes OpenCode plugin JS file + strips plugin entry from opencode.json |
| `tests/test_tui_components.py` | `PluginSetupScreen` mounts with new options without markup errors |

---

## Files Touched (Predicted)

| File | Change |
|---|---|
| `autoconduck/config/models.py` | +`omp_enabled`, +`subagent_enabled`, +`rag_enabled` to PluginConfig; +`rag_embedding_model` to SelectionConfig; remove `subagent_budget_cap_mtok` |
| `autoconduck/harnesses/base.py` | `install_plugin_visibility()` default no-op |
| `autoconduck/harnesses/claude_code.py` | HTTP hooks, SubagentStart/Stop events, `_build_mcp_block()`, MCP in `patch()`/`revert()` |
| `autoconduck/harnesses/pi.py` | Subagent listeners + RAG tool in `_render_extension()`, updated header |
| `autoconduck/harnesses/omp.py` | `_extension_path()`, `_render_extension()`, emit TS file in `patch()`, delete in `revert()`, YAML comment, `install_plugin_visibility()` |
| `autoconduck/harnesses/opencode.py` | `_plugin_path()`, `_render_plugin_js()`, emit JS file in `patch()`, delete in `revert()`, plugin entry in opencode.json, `install_plugin_visibility()` |
| `autoconduck/plugin/bias.py` | `_children` dict, `register_child_session()`, `is_child_session()`, `reset_session()` clears child entry |
| `autoconduck/plugin/ledger.py` | `parent_session_id` column, schema migration, `enqueue()` optional param |
| `autoconduck/server/plugin_routes.py` | SubagentStart/Stop payload parsing + `register_child_session()` call |
| `autoconduck/server/mcp_routes.py` | **NEW** — `GET /mcp`, `POST /mcp/tools/call`, KnowledgeVectorStore singleton |
| `autoconduck/server/server_routes.py` | Mount `install_mcp_routes()` |
| `autoconduck/routing/dispatcher.py` | `is_child_session()` check → `effective_pseudo = "autoconduck-budget"` in `_select_planned()` |
| `autoconduck/tui/onboarding/screens_plugin.py` | New full-integration options, subagent + RAG toggles |
| `autoconduck/tui/onboarding/helpers.py` | `install_plugin_visibility()` call in `configure_selected_agents()` |
| `tests/test_plugin_shims.py` | HTTP hooks, SubagentStart/Stop, MCP block, OMP extension, OpenCode plugin |
| `tests/test_plugin_runtime.py` | Child session tier routing, isolated escalation |
| `tests/test_rag_node.py` | MCP endpoints, empty index, indexed_at |
| `tests/test_agent_adapters.py` | Revert removes all managed artifacts per harness |
| `tests/test_tui_components.py` | PluginSetupScreen new options |
| `scripts/end_to_end_smoke.py` | New plugin-mode assertions |
