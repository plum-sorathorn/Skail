# AutoConduck — AGENTS.md

AutoConduck is a local zero-overhead model router + optional deterministic plugin orchestrator for coding agents (Claude Code, OpenCode, Pi). Python runtime; end users install via npm (`npm install -g autoconduck`). Current version: 0.5.0.

## Commands
- Dev install: `pip install -r requirements.txt` then `pip install -e .`
- Test: `python -m pytest` (pytest `asyncio_mode=auto`; tests under `tests/`, integration under `tests/integration/`)
- Single file: `python -m pytest tests/test_model_pool.py -q`
- Smoke: `python scripts/end_to_end_smoke.py` (mode A, router-only) and `python scripts/end_to_end_smoke.py --plugin` (mode B, router+plugin — offline-safe, no models required)
- Run: TUI `autoconduck`; headless `autoconduck start --headless [--port] [--host]` (default `127.0.0.1:11434`); daemon `--daemon`; stop `autoconduck stop [--port]`; `conduck` is an alias console command for `autoconduck` (both map to `main.py`).
- Hook: `autoconduck hook claude <Event>` — observe-only shim entrypoint, appends JSON to spool file, exit-0-always (see Gotchas)
- Version bump: `python scripts/bump_version.py --patch` (syncs pyproject.toml, `__init__.py`, npm package.json, README/AGENTS) — **pending Phase 6**, do not bump in Phase 5
- Graph: after editing code run `graphify update .`
- NPM wheels: `python npm-packaging/build.py` (`--check` to verify without rebuild)

## Non-negotiable invariants
- **Fail-soft**: any SLM/tool/config exception degrades to direct dispatch — NEVER surface a 500 to the client. Optional native deps (Outlines, LanceDB, ONNX) are wrapped in `autoconduck/_compat/` so missing binaries still boot.
- **Turn Guard** (`server/turn_guard.py`) MUST stay synchronous, I/O-free, regex-only, <2ms. Do not add async/LLM/tool calls there.
- **Selection is O(models), synchronous, in-memory, sub-ms** — this is the routing hot path; do not add I/O or model calls inside it. Ledger I/O is off the hot path (async bounded queue, batched WAL).
- **Agent config edits are bounded** by `# BEGIN AUTOCONDUCK` / `# END AUTOCONDUCK` markers, with backups in `~/.autoconduck/backups/`. Never write outside those markers. Claude Code hooks in `settings.json` are marker-bounded and revertable (installed only when `plugins.enabled` AND `plugins.claude_enabled`).
- `requirements.txt` is strictly mirrored with `pyproject.toml` runtime deps.
- Session Guard (`server/session_guard.py`) keeps the prompt prefix byte-identical across turns (upstream cache hits) and compacts at the 80% context ceiling. Relocated from `orchestrator/` to `server/` in the two-plane transformation.
- **Plugin endpoints never 5xx; no-op when `plugins.enabled=false`**: `POST /plugin/events`, `GET /plugin/contract`, `POST /plugin/escalate`, `POST /plugin/execute` always return 2xx (`ignored`/`rejected` on disabled/unknown) and never affect routing.
- **SLM is never an authority: escalation / stagnation / completion / safety are deterministic-trigger-only (Brain Ladder).** The local SLM is an optional non-binding signal; every plugin duty has a deterministic baseline; routed LLM judgment goes through the router (deferred wiring).
- **Ledger I/O off the routing hot path**: SQLite WAL, async bounded queue, batched transactions, drop/coalesce non-critical telemetry under pressure; durable-only events (task start, escalation, terminal result, errors).

## Model selection (`routing/model_pool.py` + `routing/dispatcher.py`) — read before touching routing
The router is a **fast-only, per-turn "fit-gate then cheapest"** selector, not a spend meter. There is no slow-path branching, no task-graph, no sub-task/phase planning structures. `select_by_sla()` + dispatcher `_select_planned` do:
1. Filter: enabled/undegraded/excluded → tools → reasoning → context → capability floor → cost.
2. **Capability floor** uses 4-dim `capability_vector` (reasoning, tool_reliability, code_quality, latency_class) scored by `capability_fit()` = min-over-dominant-dims (weight>0.25) + 0.1*weighted_sum, weighted per SLM `task_type` via `TASK_TYPE_WEIGHTS`. Legacy models without a vector fall back to scalar `capability_score`.
3. **Per-turn confidence floor (every classified turn):** `floor = min(base + 0.15*(1-confidence), 0.6)`. Low confidence → higher (more capable) floor; never overrides the price cap.
4. **Optional session escalation bias (additive, cap 0.75, TTL in turns):** When the plugin runtime fires a deterministic trigger (e.g., 3-identical calls / 2 consecutive errors → `POST /plugin/escalate`), `SessionBiasStore` applies an additive bump to the floor for subsequent turns in that session. Semantics: additive, capped at 0.75, TTL = `plugins.escalation_ttl_turns` (default 10), precedence/reset as implemented in `autoconduck/plugin/bias.py`. No bias when plugins disabled.
5. Sort remaining by **absolute cost ascending**, pick cheapest (unless pseudo_model contains "expensive").
6. **`max_price_usd_per_mtok` is an OPT-IN per-selection price cap** (USD per 1M tokens), NOT per-minute and NOT a time-based meter. Disabled by default (`selection.path_price_cap_usd_per_mtok` = `{}`). If it empties the pool it falls back to cheapest available with `fallback_reason="price_cap_emptied_pool"`.
- Explainability flows through `SelectionInfo`/`RoutingDecision` into `/stats`: candidates_considered, candidates_excluded_by, binding_constraint, capability_fit_applied, binding_capability_dim, spend_cap_engaged, fallback_reason.

## Turn Guard — do not regress
Healthy tool loops (even touching many files / many turns) route to `DIRECT_ACTIVE_TIER` — the client drives its own loop, **no replanning and no task graph**. Genuine stagnation is ONLY: 3+ IDENTICAL consecutive calls OR 2+ consecutive errors → deterministic trigger to **re-classify** via the SLM classifier (non-binding signal). A prior "complexity drift" escalation (>10 files / >30 turns) was **removed** because it caused runaway replanning cost (the grok-4.6 incident). Do NOT re-add file-count / turn-count escalation for healthy loops. Do NOT add plan-mutation / task graph recompilation on stagnation.

## C6 empirical scoring is deferred
Do NOT build `model_scores.json` / empirical success-weighted scoring yet. It is gated on real usage data and must stay inert/off until then. Routing must remain purely static + the live per-turn SLM signal (`plan.confidence`).

## Structure / entrypoints
- `autoconduck/` runtime package; `main.py` entry; `stats.py` = **write-only** usage accounting for `/stats` (NOT consumed by routing).
- `routing/`: `dispatcher.py` (route + `_select_planned` with per-turn floor + session bias), `slm_planner.py` (`TaskClassification` + `ExecutionPlan` stub — classifier-only, no task-graph structures), `model_pool.py` (`CapabilitySLA` + selection), `pricing.py`, `slm_downloader.py`.
- `server/`: `server_routes.py` (routes), `server_streaming.py`, `turn_guard.py`, `messages_api.py` (Anthropic shim), `sse_streamer.py`, `session_guard.py` (relocated from `orchestrator/`), `plugin_routes.py` (`/plugin/events`, `/plugin/contract`, `/plugin/escalate`, `/plugin/execute` — fail-soft, never 5xx).
- `autoconduck/plugin/` (daemon-side, Python — active only when `plugins.enabled=true`): `ledger.py` (SQLite WAL, async bounded queue, batched, durable-only events), `bias.py` (`SessionBiasStore`, TTL turns, additive cap 0.75), `runtime.py` (salvaged `executor_loop` + `tools` proof path, deterministic stagnation 3-identical/2-errors → bias), `synthesis.py` (templated, LLM stub off behind `plugins.llm_synthesis_enabled`), `spool.py` (spool file tailer), `shims/` (per-harness docs; Claude Code hooks via `cli/hook.py`).
- `autoconduck/cli/hook.py`: `autoconduck hook claude <Event>` — observe-only, appends JSON to `~/.autoconduck/run/hooks.spool` with short timeout, exit-0-always.
- `orchestrator/`: **residual / transitional** — `__init__.py` re-exports + `runner.py` stub kept for import compatibility; all active orchestration graph machinery (dynamic task graphs, hand-off, subagents, heart-beat, plan mutation) was removed in Phase 1 and salvaged into `autoconduck/plugin/`. Do not add new code here. Slated for full removal / relocation in Phase 7.
- `config/`: `models.py` (`Config`/`SelectionConfig`/`PluginConfig` pydantic), `manager.py`, `resolver.py`, `paths.py`.
- `knowledge/` (LanceDB RAG); `auth/`, `launcher/`, `cli/`, `presets/`, `tui/`, `_compat/`.
- `harnesses/` (`base.py`, `omp.py`, `claude_code.py`, `opencode.py`, `pi.py`): Thin translation layer. Pi extension is a gated constant (inert) behind `plugins.pi_enabled=false`; OpenCode shim is doc-only stub behind `plugins.opencode_enabled=false`. Claude Code hooks are the one shipped shim (gated by `plugins.enabled` AND `plugins.claude_enabled`).

## Gotchas
- TUI quit chord is **Ctrl+C** (Textual default Ctrl+Q is disabled); keymap in `tui/keymap.py`.
- User data lives under `~/.autoconduck/` (auth.yaml, backups, catalogs, `run/` with ledger DB `~/.autoconduck/run/ledger.db` and spool file `~/.autoconduck/run/hooks.spool`).
- `autoconduck hook claude <Event>` is observe-only and **exit-0-always**, even on spool/write failure or when the daemon is down — it never blocks the harness. Local overhead budget <10ms per hook.
- Smoke has two modes: `python scripts/end_to_end_smoke.py` (mode A, router-only) and `python scripts/end_to_end_smoke.py --plugin` (mode B, router+plugin — offline-safe via TestClient fallback, no models required).
- Deprecated config keys (6 dead keys removed in the two-plane transformation) are **tolerated with a startup warning, never a crash** — they are ignored. Do not reintroduce them. See `docs/phase-reports/PHASE1A.md` for the exact names.
- Version is 0.4.1 — version bump (`python scripts/bump_version.py --minor` → 0.5.0) happens in **Phase 6 only**, NOT in Phase 5.
- Tests are pure async unit tests (`asyncio_mode=auto`); no ruff/black config in-repo — match neighboring module style and keep edits surgical (don't reformat unrelated lines).
