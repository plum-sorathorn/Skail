# Phase 2 — Daemon-Side Plugin Runtime

## Summary

Implemented the daemon-side plugin runtime per `TWO_PLANE_PLAN.md` Phase 2. All ledger I/O is off the routing hot path (bounded deque + batched WAL flush). No prompt content stored by default. Escalation is deterministic-trigger-only (trigger matrix), raising the dispatcher capability floor for the session with a TTL. Plugin endpoints are fail-soft (never 5xx, no-op when `plugins.enabled=false`). Internal executor proof path (`runtime.py`) wraps the salvaged `executor_loop`+`tools` with deterministic stagnation detection (Turn Guard thresholds 3× identical / 2× consecutive errors → bias + ledger escalation) and a templated synthesis report. No SLM call in v1 (Brain Ladder: deterministic baseline is primary).

## Files Created / Changed

### Created
- `autoconduck/plugin/ledger.py` — SQLite WAL (`run_dir()/plugin_ledger.db`) via `sqlite3`, bounded `deque(maxlen=1000)` + background flusher (batch `size>=25` or every `2s`), durable kinds ONLY `{task_start,escalation,terminal_result,error}`, schema `(id, ts, session_id, task_id, kind, data)` correlation IDs `session_id+task_id` (uuid4 hex short), retention prune on startup (`ledger_retention_days`), no prompt content (`prompt/content/raw_prompt` stripped, values truncated), fail-soft (sqlite errors → log warning, drop batch, never raise), `shutdown_sync()`/`stop()` flush on shutdown, `query_events`/`get_counts` helpers.
- `autoconduck/plugin/bias.py` — `SessionBiasStore` (threshold tables in-memory): `session_id → {bump, expires_at_turn, ts}` with `threading.Lock`, APIs `apply_escalation(session_id,bump,ttl_turns)`, `get_bump(session_id)` (0.0 if expired/missing), `increment_turn(session_id)`, `reset_session(session_id)`, `clear_all()`, `snapshot()`. Hard cap `0.75` for bias-adjusted floor. No awaits inside lock; errors → `0.0` (fail-soft).
- `autoconduck/plugin/runtime.py` — `start_task(session_id,goal,checks,workspace_root,allowed_scope,cfg,client,model,…)` → `task_start` → run `run_executor_tool_loop` (tools gated by config, bash off by default) capturing `LoopState`-like signatures/errors via capturing `execute_tool` shim → deterministic stagnation (3× identical consecutive calls OR 2× consecutive errors ≡ Turn Guard) → `escalation` event + `bias.apply_escalation` → `terminal_result` → `synthesis.render_report` (markdown from ledger facts: rounds, tools, files, errors, outcome). Honest `llm_synthesis_enabled` annotation pass-through. Never calls SLM.
- `autoconduck/plugin/synthesis.py` — `render_report(…)` deterministic template; `llm_synthesis_stub(facts)` appendix `"llm-synthesis-not-wired"` when `plugins.llm_synthesis_enabled=True`.
- `autoconduck/server/plugin_routes.py` — Control plane mounted in `server_routes.install_routes`: `POST /plugin/events`, `GET /plugin/contract`, `POST /plugin/escalate`, `POST /plugin/execute` (guarded by `plugins.enabled` + `plugins.execute_enabled` — default `{"status":"disabled"}`). All handlers wrapped, return `JSONResponse` `{status:ok|ignored|rejected|disabled}`, never 5xx. `/events` validates `kind ∈ {tool_call,tool_result,task_start,task_progress,task_done}`; only `task_start` durable-enqueued, others `count_in_memory`; increments bias turn counter off hot path. `/escalate` validates `reason ∈ {consecutive_errors,repeated_calls,requested_review,acceptance_failed}`; unknown → `{"status":"rejected","reason":"unknown_trigger"}`.
- `tests/test_plugin_runtime.py` — 16 tests covering WAL+batching+retention+queue-pressure, bias TTL/reset, endpoints disabled/validation/escalation/execute-disabled, synthesis stub, never-500, dispatcher bias floor bump, runtime trivial + stagnation paths.

### Changed
- `autoconduck/config/models.py` — Added `PluginConfig` (`enabled, claude_enabled, pi_enabled, opencode_enabled, ledger_retention_days=30, escalation_ttl_turns=10, escalation_floor_bump=0.15, llm_synthesis_enabled=False, execute_enabled=False`) and `Config.plugins: PluginConfig`. Defaults ensure tolerant loader (absent keys → defaults, no crash).
- `autoconduck/config/__init__.py` — Export `PluginConfig`.
- `autoconduck/routing/dispatcher.py` — `route(…,session_id=None)` and `_select_planned(…,session_id=None)`; after confidence-floor math (`min(base+K*(1-conf),0.60)`) applies bias `floor=min(floor+bump,0.75)` via `SessionBiasStore.get_bump(session_id)` (dict lookup only, fail-soft → no bump). Bias cap is additive above confidence cap.
- `autoconduck/server/server_router.py` — `route_target` now reads `x-autoconduck-session-id` header, calls `get_bias_store().increment_turn(session_id)` (per-turn TTL tick) before `dispatcher.route(…,session_id=session_id)`. Hot path stays sync/in-memory dict ops; errors swallowed.
- `autoconduck/server/server_routes.py` — Fail-soft mount of `install_plugin_routes(app,BaseModel,Field)` after core routes.
- `autoconduck/plugin/__init__.py` — Docstring updated to "Plugin runtime (Phase 2)".

## Pytest Tail

```
python -m pytest -q --tb=short
# 244 passed, 4 skipped, 1 warning (StarletteDeprecationWarning fastapi.testclient pre-existing)
# New plugin suite: 16 passed
# Regression: 0 failures — ledger/bias/runtime hot-path changes are off-path and fail-soft

Full tail (latest run):
244 passed, 4 skipped, 1 warning in 14.99s
Subset:
tests/test_plugin_runtime.py      16 passed
tests/test_phase1a_router.py       5 passed
tests/test_plugin_executor.py      5 passed
tests/test_turn_guard.py           all passed (unchanged)
```

## Endpoint Behavior Transcript (from `tests/test_plugin_runtime.py`)

```
POST /plugin/events  (plugins.enabled=false)        → {"status":"ignored"}                        [200]
POST /plugin/events  kind=weird                     → {"status":"ignored","reason":"unknown_kind"}[200]
POST /plugin/events  kind=tool_call                 → {"status":"ok"}  (counted, not durable)     [200]
POST /plugin/events  kind=task_start                → {"status":"ok"}  (durable enqueued)         [200]
GET  /plugin/contract?session=s2                    → {schema_version:"0.5", session_id:"s2", execution_authority:"plugin-deterministic", brain:"deterministic-first (SLM optional, LLM via router)", acceptance_checks:[], notes:"events=1 counts={…}"} [200]
POST /plugin/escalate reason=unknown_trigger_xyz    → {"status":"rejected","reason":"unknown_trigger"} [200]
POST /plugin/escalate reason=consecutive_errors     → {"status":"ok","floor_bump":0.15,"ttl_turns":3,"session_id":"s"} [200]
POST /plugin/execute (execute_enabled=false)        → {"status":"disabled"}                       [200]
POST /plugin/execute (enabled+execute_enabled=true) → {"status":"ok","result":{task_id,…,report,…}} [200]
Malformed bodies ({} / null / non-dict)             → {"status":"ignored"|"rejected"} never 5xx  [200]
GET  /plugin/contract (no session)                  → {schema_version:"0.5", notes:"no session"}   [200]
```

## Ledger Design Notes

- **WAL + batching:** `PRAGMA journal_mode=WAL` on every `_ensure_db`/`flush_sync` connection; deque → `executemany(INSERT)` under `batch>=25` or `2s` flusher window. `drop-oldest` semantics via `deque(maxlen=1000)` for non-critical telemetry pressure (spec: non-critical telemetry drop under pressure; durable events are the only ones queued, but deque bound still bounds memory).
- **Correlations:** `session_id`+`task_id` (8-hex uuid4 short) indexed (`idx_events_session`, `idx_events_ts`); `run_dir()` from `config/paths.py`.
- **Privacy:** no prompt content by default — `prompt/content/raw_prompt` stripped, strings truncated at 2000 chars; JSON payload via `json.dumps(...,default=str)`.
- **Fail-soft:** every `enqueue`/`flush_sync`/`query_events`/`prune` wrapped; sqlite error → `logger.warning`, drop batch, return 0/`[]`, never raise to callers. Graceful stop: `flush_sync()` on `shutdown_sync()`/`stop()`.
- **Retention:** `DELETE FROM events WHERE ts < cutoff` on startup (and on explicit `prune()`), driven by `plugins.ledger_retention_days`.

## Bias & Dispatcher Coupling

- `SessionBiasStore` is synchronous, `threading.Lock`-only, zero I/O; `get_bump` is O(1) dict lookup on the hot path. `increment_turn` is called from `server_router.route_target` (per request) and from `/plugin/events` (per event), advancing the TTL window. Expiry is lazy: `get_bump` evicts if `cur >= expires_at`.
- Dispatcher floor math: `base_floor = min(base + K*(1-conf), 0.60)` (confidence cap), then `effective = min(base_floor + bias_bump, 0.75)` — bias is a **separate additive term** with its own cap, per spec.

## Runtime & Synthesis (Brain Ladder)

- `runtime.start_task` never calls SLM. Stagnation uses the **same thresholds as Turn Guard**: `3+ identical consecutive calls OR 2+ consecutive errors`. Detection is double-checked: lightweight signature/error-streak scan plus a `TurnGuard().classify_turn(pseudo_messages)` fallback on the captured trace.
- Synthesis is templated markdown from ledger facts; `llm_synthesis_enabled` only appends an honest `"llm-synthesis-not-wired"` note — no fake LLM call.

## Design Notes for Phase 3 Shims

- **Hook protocol (Phase 3 binding):** shims are **NON-BLOCKING** — localhost append to bounded queue with 5–10 ms timeout then drop; never `await` planning/ledger/LLM; overhead budget `<10ms` per hook invocation (Phase 3 to enforce via `asyncio.wait_for(…,timeout=0.01)` + transport-level `httpx` timeout in shim).
- **Daemon contract for shims (Phase 3):**
  - `POST /plugin/events {session_id,task_id?,kind,data?}` — fire-and-forget ingestion; shims send `tool_call/tool_result/task_start/task_progress/task_done`; daemon counts or durably queues; always `{status:ok|ignored}`.
  - `POST /plugin/escalate {session_id,reason}` — shims are the **ONLY** escalation authority; deterministic trigger matrix validated server-side; SLM never calls it.
  - `GET /plugin/contract?session=` — deterministic JSON task contract (`schema_version:"0.5"`) for shim-side acceptance checks; no SLM invention.
  - `POST /plugin/execute` — `execute_enabled` off by default; Phase 3 shims will not use it directly; it remains an internal proof path / test seam.
- **Session correlation:** `x-autoconduck-session-id` header threads bias across `dispatcher.route` calls. Shim must propagate the same `session_id` on every hook and every routed LLM call for the escalated floor to apply to the next request (next-request bias for harness-native loops; true in-loop escalation only for the internal executor).
- **Claude Code shipped shim (Phase 3.2):** `hooks` block added by existing `patch()` → `autoconduck hook claude <event>` invoking `PreToolUse/PostToolUse/Stop` fire-and-forget `POST /plugin/events` with `5–10ms` timeout, observe-only in v1 (no blocking decisions). Pi/OpenCode flags (`plugins.pi_enabled / opencode_enabled`) remain inert stubs; OMP deferred.
- **Daemon lifecycle (Phase 2 §2.6):** lockfile + crash recovery (ledger authoritative) + port/socket collision handling are deferred to Phase 3/4 daemon-lifecycle work; ledger WAL already survives crashes, and plugin endpoints degrade to no-op when disabled or on I/O error.

## Graph

`graphify update .` run at close: **succeeded** — `2059 nodes, 4164 edges, 129 communities; graph.json/graph.html/GRAPH_REPORT.md updated in graphify-out` (initial run reported binary unavailable; re-run after Phase 2 succeeded).

## Commit

Not committed (per task: orchestrator commits). Branch `two-plane`, HEAD `b490a4f`, working tree contains the Phase 2 diff above. Verify with `git status` / `git diff --stat`.
