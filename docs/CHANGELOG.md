# AutoConduck Changelog

## [0.5.2] - 2026-08-31

### Dynamic Task Capability Floors & Tool Loop Floor Inheritance
- **Dynamic Task-Type Base Floors (`routing/dispatcher.py`)**: Added `TASK_BASE_FLOORS` defining capability baselines per task type (`debug: 0.35`, `refactor: 0.40`, `full_workflow: 0.45`, `multi_edit: 0.25`, etc.) scaled by `complexity_score`. Low confidence dynamically elevates the floor (`floor = min(base + 0.15*(1-confidence), 0.60)`).
- **Tool Loop Session Floor Inheritance (`plugin/bias.py`, `routing/dispatcher.py`)**: Turns on `TurnAction.DIRECT_ACTIVE_TIER` inherit the session's active capability floor via `SessionBiasStore.get_session_floor`, preventing multi-turn debugging and refactoring loops from down-tiering to inadequate models mid-session.
- **Deterministic Stagnation Escalation**: Turn Guard `TurnAction.ESCALATE_SLM` immediately applies an escalation bump (+0.15 additive floor, TTL = 10 turns) to the active session.
- **Equal-Cost Capability Tiebreaker (`routing/model_pool.py`)**: When multiple qualifying models have identical or zero cost, `ModelPool._select` uses `-capability_fit` as the secondary sort key, guaranteeing the highest-capability candidate is chosen rather than alphabetical default.

### Automated Multi-Provider Preset Synchronization
- **Dynamic Upstream Ingestion (`scripts/sync_all_presets.py`)**: Ingests all active chat models directly from LiteLLM (2,800+ models), DevPass (317 models), and LLMGateway (205 models), automatically categorizing tiers and updating token pricing.
- **Direct Atomic File Persistence**: Automatically writes synced presets directly to `autoconduck/presets/presets_data.py`, refreshes `presets_fallback.py`, and regenerates `docs/model_catalog.md` (1,024 preset models across 11 providers).
- **Fallback Clobber Fix**: Fixed an issue where `PRESETS.update(FALLBACK_PRESETS)` in `presets_data.py` clobbered live scraped provider lists with hardcoded fallbacks.

### OMP Harness & Session Extraction
- **ESM Template Fixes (`harnesses/omp.py`)**: Replaced CommonJS `require` calls with ESM `import * as fs` and `import * as path` for Oh My Pi extension runtime compatibility.
- **Client-Side Stagnation & Auto-Escalation**: Added client-side repeated call / error tracking in the OMP extension dispatching `POST /plugin/escalate`.
- **Session Header & Hash Propagation (`server/server_router.py`)**: Extracted session headers (`x-autoconduck-session-id`, `x-session-id`, `x-conversation-id`) with fallback conversation-hash derivation for clients that omit explicit session headers.

## [0.5.1] - 2026-08-30

### Stability & Consolidation
- Cleaned up obsolete DAG remnants and synchronized package wheels.
- Finalized two-plane proxy runtime and test suites.

## [0.5.0] - 2026-08-29

### Transformation — Two-Plane Architecture (Proxy = pure router, Plugin = optional deterministic orchestrator)
- **Proxy strip-down (Phase 1):** Removed SLOW path, dynamic DAG machinery, subtask/phase planning, DAG handoff/response-rewriting, heartbeat, plan mutation (`orchestrator/dynamic_factory.py`, `handoff.py`, `fan_out.py`, `subagents.py`, `scripts/simulate_slow_path.py`), and SLOW-path tests. SLM planner trimmed to `TaskClassification` (`task_type`/`confidence`/`complexity_score`) with 2000 ms circuit-breaker and deterministic fallback; `SubTaskSpec`/`Phase`/`to_phase`, `create_escalation_plan`, `evaluate_session_trajectory`, and route-decision logic deleted. Dispatcher wired to `TASK_TYPE_WEIGHTS` + per-turn confidence floor `min(base + 0.15*(1-conf), 0.60)` on every classified turn. 6 dead config keys removed (`ambiguous_low`, `ambiguous_high`, `escalation_threshold`, `slow_threshold`, `min_orchestrator_complexity`, `deescalation_threshold`) — tolerated with startup warning, never a crash. `SessionGuard` relocated `orchestrator/session_guard.py` → `server/session_guard.py` (prefix immutability + 80% compaction). `orchestrator/` retained as transitional re-exports + stub (slated for Phase 7 cleanup).
- **Plugin runtime — daemon-side Python (Phase 2):** `autoconduck/plugin/{ledger.py (SQLite WAL, async bounded queue, batched, durable-only events: task start / escalation / terminal result / errors), bias.py (SessionBiasStore — additive floor bump cap 0.75, TTL turns), runtime.py (salvaged executor_loop + tools proof path, deterministic stagnation 3-identical/2-errors → bias), synthesis.py (templated, LLM stub off behind plugins.llm_synthesis_enabled)}`, `server/plugin_routes.py` (`/plugin/events`, `/plugin/contract`, `/plugin/escalate`, `/plugin/execute` — never 5xx, no-op when `plugins.enabled=false`), ledger I/O off the routing hot path.
- **Per-harness shims (Phase 3):** Hook protocol is non-blocking (<10 ms, spool-file append, drop on failure). `autoconduck hook claude <Event>` observe-only, exit-0-always; spool file `~/.autoconduck/run/hooks.spool` with `autoconduck/plugin/spool.py` tailer. Claude Code hooks in `settings.json` installed only when `plugins.enabled` AND `plugins.claude_enabled` (marker-bounded, revertable). Pi extension gated constant (inert, `plugins.pi_enabled=false`); OpenCode doc-only stub (`plugins.opencode_enabled=false`).
- **Brain Ladder (binding):** Deterministic-first — SLM is optional non-binding signal, never authority for escalation / stagnation / completion / safety; routed LLM judgment goes through the router (deferred wiring).
- **Tests, smoke, tooling (Phase 4):** Smoke modes — mode A `python scripts/end_to_end_smoke.py` (router-only) + mode B `python scripts/end_to_end_smoke.py --plugin` (router+plugin, offline-safe, no models required, 5 plugin-endpoint assertions); 263 passed (up from 262) + new hermetic bias-flow e2e; wheels rebuilt to include `autoconduck/plugin/*` + `autoconduck/cli/hook.py`; `graphify update .` green.
- **Documentation alignment (Phase 5):** README, AGENTS, and `docs/` aligned to the shipped two-plane reality; historical spec docs carry superseded banners; this CHANGELOG entry added. Version remains 0.4.1 — bump to 0.5.0 gated on Phase 6 acceptance gates.
- **Batch 2a consolidation (Phase 7C):** Deleted `autoconduck/orchestrator/` residual package (`__init__.py`, `planner.py`, `roles.py`, `skeletons.py`, `runner.py`, `session_guard.py` — byte-identical MD5 080F09C8 verified); `autoconduck/server/server_chat.py` + `server_messages.py` repointed to `autoconduck.server.session_guard` (fallback chains removed); `tests/test_session_guard.py` unskipped (12 tests now run). Purged 30 dead `SelectionConfig`/`Config` keys (see `docs/phase-reports/PHASE7C2A.md`) and converted `config/manager.py` deprecated strip list to plain strings. Wired `selection.session_guard_compaction_ratio` into `SessionGuard` (default 0.80, `compaction_ratio` param on `guard_context`/`__init__`). Removed DAG-era pseudo-variant `smart-dag` from `_AUTOCONDUCK_VARIANTS`/`PSEUDO_MODELS` and `harnesses/omp.py`; requests using it now route as `autoconduck` (warn-once compat via `normalize_pseudo_model()`/`is_pseudo_model()`).

## [0.4.1] - 2026-08-28

### Native Async DAG & Zero-Overhead Orchestration
- **LangGraph Removal & Native Async DAG (`orchestrator/dynamic_factory.py`)**: Replaced LangGraph with a lightweight, native `asyncio.gather` execution engine (`DynamicGraphRunner`). Eliminates 50–200ms of graph compilation overhead per turn and removes the `langgraph` and `langgraph-checkpoint-sqlite` dependencies completely.
- **Orphan Subagent Bug Fix**: Fixed an issue where the orchestrator synthesizer could complete early while background child subtasks were still in flight. All dependency trees are now strictly awaited.
- **Cycle-Resilient DAG Builder**: Implemented topological DFS cycle detection in `build_dynamic_graph()` to safely detect cyclical task definitions and degrade to fallback runners without deadlocks.

### Hot-Path Latency & Concurrency Optimizations
- **Fast-Path Config Resolution (`config/manager.py`)**: Added an `st_mtime_ns` timestamp check in `get_config()`, bypassing disk read and SHA256 hashing when `config.yaml` has not changed.
- **Immediate Progress Streaming (`server/server_chat.py`)**: Replaced the 100ms `asyncio.sleep` polling loop with an instantaneous `asyncio.Event` (`done_event`) for subagent node progress events.
- **Normalization Deduplication (`server/server_router.py`)**: Removed redundant message normalization passes in the routing pipeline.
- **Turn Guard Bounded Scope (`server/turn_guard.py`)**: Truncated message history evaluation to the latest 20 messages, guaranteeing sub-2ms classification regardless of session length.
- **Async Usage Stats I/O (`stats.py`)**: Migrated synchronous file append operations to a dedicated background worker thread and queue.
- **SLM Heartbeat Stampede Protection (`server/server_router.py`)**: Added a 60-second TTL lock on background SLM trajectory evaluation tasks.
- **Cleanup of Obsolete Compat Shims**: Removed `autoconduck/_compat/sqlite_checkpointer.py` and decoupled tests from SQLite checkpointer persistence.

## [0.3.5] - 2026-08-25

### Model Selection Overhaul
- **Turn Guard false-positive fix (`server/turn_guard.py`)**: Removed the "complexity drift" escalation (>10 distinct files / >30 tool turns) that misclassified healthy multi-file tool loops as stagnant, causing runaway replanning and Dynamic-DAG recompilation (the grok-4.6 cost incident). Healthy tool loops now stay on DIRECT_ACTIVE_TIER; only 3+ identical calls or 2+ consecutive errors escalate.
- **Capability-vector scoring (`routing/model_pool.py`)**: Replaced the 1D `capability_score` gate with a 4-dim `capability_vector` (reasoning, tool_reliability, code_quality, latency_class) scored by `capability_fit()` (min-with-bonus), weighted per SLM `task_type` via `TASK_TYPE_WEIGHTS`. Selection is now Capability Floor Routing; legacy scalar entries fall back compatibly.
- **Confidence-tightened floor (`routing/dispatcher.py:_select_planned`)**: Low SLM `plan.confidence` raises the capability floor (`min(base + 0.15*(1-conf), 0.6)`).
- **Opt-in per-selection price cap (`CapabilitySLA.max_price_usd_per_mtok`, config `selection.path_price_cap_usd_per_mtok`)**: Reframed the earlier "USD/min" ceiling into an honest per-1M-token price cap, DISABLED by default ({}). Not a spend meter; falls back to cheapest available with `fallback_reason="price_cap_emptied_pool"`.
- **Explainability (`SelectionInfo`/`RoutingDecision` → `/stats`)**: candidates_considered, candidates_excluded_by, binding_constraint, capability_fit_applied, binding_capability_dim, spend_cap_engaged, fallback_reason.

### Notes
- Version bumps now via `python scripts/bump_version.py --patch`.

## [0.3.4] - 2026-08-25

### Fixes & Reliability Enhancements
- **Configuration Resilience & In-Memory Preservation (`config/manager.py`)**: Fixed an issue where transient file locks, missing/empty reads, or background atomic file replaces could cause `get_config()` to evict loaded models and fall back to hardcoded defaults. The in-memory configuration is now preserved with fail-soft guarantees when the config file is temporarily unavailable.
- **Thread-Safe Atomic Config I/O**: Added thread locking (`threading.RLock`) around config load and save operations, collision-proof temporary filenames, and Windows-specific retry backoff for atomic replacements.
- **Automatic Backup Recovery**: `load_config()` automatically recovers active configurations from timestamped backups under `~/.autoconduck/backups/config/` on cold starts if `config.yaml` is missing or corrupted.
- **Provider-Aware Fallback Resolution (`config/resolver.py`, `routing/model_pool.py`, `routing/pricing.py`)**: Enhanced `resolve_orchestrator_model()` to discover provider credentials from environment variables (`LLMGATEWAY_API_KEY`, `ANTHROPIC_API_KEY`, etc.) and fallback presets before defaulting to `gpt-4o`.

## [0.3.2] - 2026-08-24

### Enhancements & Dynamic Model Tiering
- **Dynamic Pool-Relative Model Tiering (`routing/model_pool.py`)**: Replaced fixed static price cutoffs with pool-relative dynamic quantile partitioning. Automatically tiers models across `cheap_fast`, `balanced`, and `frontier_reasoning` based on the user's active/selected models (whether 1, 2, 3, 6, or 20+ models).
- **VCS & Git Fast-Path Intent Routing**: Explicit fast-path classification in `slm_planner.py` for git commits, diffs, status, and routine tasks, preventing runaway costs on expensive models.
- **Emoji Removal Across Logs & TUI**: Purged all emojis from logs, TUI dashboard, onboarding screens, SSE streamers, progress formatters, and CLI outputs in favor of clean bracketed ASCII markers (`[OK]`, `[WARN]`, `[ERR]`, `[..]`, `[>>]`).

## [0.3.0] - 2026-08-24

### Major Features & Architectural Overhaul
- **Embedded SLM Task Architect**: Replaced static 10-factor regex heuristics with local Qwen 2.5 Coder 0.5B Instruct (Q4_K_M GGUF), generating typed Pydantic \ExecutionPlan\ specifications with sub-100ms inference.
- **Turn Guard Subsystem (\server/turn_guard.py\)**: Sub-2ms regex classifier providing instantaneous bypass for active tool loops and stagnation detection for automated SLM re-planning.
- **Dynamic DAG Factory (\orchestrator/dynamic_factory.py\)**: Replaced static 6-phase orchestrator with runtime compilation of tailored \StateGraph\ topologies based on plan dependency DAGs and SQLite checkpointer state persistence.
- **Knowledge Vector Store & RAG Subsystem (\knowledge/vector_store.py\)**: Embedded LanceDB vector database with fast hybrid code search and automated context distillation for complex workflows.
- **Session Lifecycle & Context Guard (\orchestrator/session_guard.py\)**: Preserves immutable prefix contract (turns 0 & 1) for maximum upstream prompt caching across 40+ turns, enforcing intelligent compaction at the 80% context window ceiling.
- **Real-Time Reasoning SSE Streamer (\server/sse_streamer.py\)**: Unified SSE streaming translating internal SLM reasoning deltas into client-compatible formats (\	hinking_delta\ for Claude Code, \delta.reasoning_content\ for OpenAI clients).
- **Autonomous 3-Tier Model Pool (outing/model_pool.py\)**: Dynamic classification into \cheap_fast\ (< .50/1M), \alanced\ (.50–.00/1M), and \rontier_reasoning\ (> .00/1M) with spend guard and degraded provider protections.

### Removed
- Deleted obsolete 0.2.x heuristics: outing/complexity.py\, outing/complexity_helpers.py\, outing/evaluator.py\, outing/semantic_router.py\, outing/fast_graph.py\.
- Deleted static orchestrator files: \orchestrator/graph.py\, \orchestrator/compactor.py\, \orchestrator/complexity_helpers.py\, \orchestrator/recon.py\.
- Deleted deprecated test suites: \	est_routing_fast_path.py\, \	est_complexity_and_tuning.py\, \	est_empirical_tuning.py\.

### Quality & Testing
- Pure async pytest test suite passing at 100% (218 passed, 2 skipped, 0 failed).
- Comprehensive adversarial stress tests for SLM circuit breaker, thread-safe SQLite checkpointing, and fan-out reducer concurrency.
